"""Safe Alpaca paper order execution — preflight, submit, reconcile."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PortfolioDecision, StrategySignal
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.broker_safety import (
    broker_base_url,
    is_paper_broker_url,
    live_lock_status,
    paper_execution_blockers,
)
from app.services.config_manager import ConfigManager
from app.services.cooldown_service import CooldownService
from app.services.engine_config import cfg_get
from app.services.execution_preflight import build_client_order_id, run_preflight
from app.services.order_reconciliation import reconcile_order
from app.services.portfolio_gate import ApprovedCandidate
from app.services.symbol_tier_service import EngineBoundaryBlocked, SymbolTierService


CODE_VERSION_SHA = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "dev")[:12]


def _map_broker_rejection_code(error: str) -> str:
    err = (error or "").lower()
    if "notional" in err or "minimum" in err or "min order" in err:
        return "BROKER_REJECTED_MIN_NOTIONAL"
    return "BROKER_REJECTED"


class PaperExecutionService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config if config is not None else ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)
        self.tiers = SymbolTierService(self.config)

    def status(self) -> dict[str, Any]:
        blockers = paper_execution_blockers(self.config, alpaca_configured=self.alpaca.configured)
        paper_on = bool(cfg_get(self.config, "execution.paper_orders_enabled", False))
        return {
            "status": "ok",
            "paper_orders_enabled": paper_on,
            "live_orders_enabled": bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
            "broker_base_url": broker_base_url(),
            "broker_mode_detected": "paper" if is_paper_broker_url() else "live_or_unknown",
            "paper_execution_ready": paper_on and not blockers,
            "paper_execution_blockers": blockers,
            **live_lock_status(self.config),
        }

    def enable(self, *, operator: str = "operator") -> dict[str, Any]:
        if not is_paper_broker_url():
            return {"status": "error", "code": "BROKER_NOT_PAPER", "message": "Alpaca must use paper-api.alpaca.markets"}
        cfg = ConfigManager(self.session).get_current()
        cfg.setdefault("execution", {})["paper_orders_enabled"] = True
        cfg["execution"]["live_orders_enabled"] = False
        cfg["live_trading_enabled"] = False
        ConfigManager(self.session)._activate(cfg, changed_by=operator, reason="Paper execution enabled")
        self.config = cfg
        return self.status()

    def disable(self, *, operator: str = "operator") -> dict[str, Any]:
        cfg = ConfigManager(self.session).get_current()
        cfg.setdefault("execution", {})["paper_orders_enabled"] = False
        ConfigManager(self.session)._activate(cfg, changed_by=operator, reason="Paper execution disabled")
        self.config = cfg
        return self.status()

    def candidate_from_signal(self, sig: StrategySignal, dec: Optional[PortfolioDecision] = None) -> ApprovedCandidate:
        meta = dict(sig.signal_metadata or {})
        return ApprovedCandidate(
            signal_id=sig.id,
            symbol=sig.symbol,
            side="buy" if "buy" in (sig.side or "") else "sell",
            signal_type=sig.signal_type or "entry",
            meta=meta,
            strength=sig.strength,
            confidence=sig.confidence,
            spread_pct=meta.get("spread_pct"),
            liquidity_score=meta.get("liquidity_score"),
            edge_over_cost=meta.get("edge_over_cost"),
            expected_move_pct=meta.get("expected_move_pct"),
            position_qty=float(meta.get("position_qty") or 0),
            entry_price=float(meta.get("current_price") or 0),
            stop_loss=sig.stop_loss,
            atr14=meta.get("atr14"),
            tier=meta.get("tier", "TIER_ALT"),
            cost_evidence=meta.get("cost_edge", {}),
            sizing_evidence=meta.get("sizing", meta.get("gates", {})),
        )

    def submit_candidate(
        self,
        cand: ApprovedCandidate,
        *,
        cycle_run_id: str,
        portfolio_decision: Optional[PortfolioDecision],
        account,
        positions: list,
        open_order_symbols: Optional[set[str]] = None,
        signal_row: Optional[StrategySignal] = None,
    ) -> ExecutionLog:
        quote_sym = normalize_crypto_symbol(cand.symbol)
        quote = self.alpaca.get_quote(quote_sym, "crypto") or {}
        quote["quote_age_seconds"] = 0

        pf = run_preflight(
            self.session,
            self.config,
            cand=cand,
            cycle_run_id=cycle_run_id,
            portfolio_decision=portfolio_decision,
            account=account,
            positions=positions,
            open_order_symbols=open_order_symbols or set(),
            alpaca=self.alpaca,
            quote=quote,
            signal_row=signal_row,
        )

        if not pf.passed:
            return self._log(
                cycle_run_id,
                cand,
                status="preflight_blocked",
                reject_reason=pf.block_reason_code,
                limit_price=pf.limit_price,
                quote=pf.quote or quote,
                portfolio_decision_id=portfolio_decision.id if portfolio_decision else None,
                gates_failed={
                    "code": pf.block_reason_code,
                    "reason": pf.human_reason,
                    "evidence": pf.evidence,
                    "preflight_stage": pf.evidence.get("preflight_stage", "internal_preflight_block"),
                },
            )

        try:
            self.tiers.assert_order_path(cand.symbol)
        except EngineBoundaryBlocked as exc:
            return self._log(
                cycle_run_id,
                cand,
                status="preflight_blocked",
                reject_reason="ENGINE_BOUNDARY_BLOCKED",
                limit_price=pf.limit_price,
                quote=quote,
                portfolio_decision_id=portfolio_decision.id if portfolio_decision else None,
                gates_failed={"reason": str(exc)},
            )

        pending = self._log(
            cycle_run_id,
            cand,
            status="paper_order_pending",
            reject_reason=None,
            limit_price=pf.limit_price,
            quote=quote,
            portfolio_decision_id=portfolio_decision.id if portfolio_decision else None,
            broker_client_order_id=pf.client_order_id,
            gates_passed={"preflight": True, "risk": True, "portfolio": True},
        )
        self.session.flush()

        result = self.alpaca.submit_marketable_limit_ioc(
            cand.symbol,
            cand.position_qty,
            cand.side,
            limit_price=pf.limit_price or cand.entry_price,
            client_order_id=pf.client_order_id,
        )

        if not result.get("success"):
            pending.status = "paper_order_rejected"
            pending.reject_reason = _map_broker_rejection_code(result.get("error", ""))
            pending.gates_failed_json = {
                "broker": result.get("error"),
                "preflight_stage": "broker_rejection",
            }
            self.session.add(pending)
            CooldownService(self.session, self.config).apply_symbol(
                cand.symbol, "BROKER_REJECTION", details={"error": pending.reject_reason}
            )
            return pending

        pending.status = "paper_order_submitted"
        pending.broker_order_id = result.get("order_id")
        pending.submitted_at = datetime.utcnow()
        self.session.add(pending)

        self.session.add(
            OrderRecord(
                alpaca_order_id=result.get("order_id"),
                broker_client_order_id=pf.client_order_id,
                symbol=cand.symbol,
                side=cand.side,
                qty=cand.position_qty,
                order_type="limit_ioc",
                status="submitted",
                stop_loss=cand.stop_loss,
                take_profit=signal_row.take_profit if signal_row else None,
                cycle_run_id=cycle_run_id,
                signal_id=cand.signal_id,
                raw_payload=result,
            )
        )
        self.session.flush()

        broker_detail = self.alpaca.get_order_by_id(result.get("order_id"))
        if broker_detail:
            reconcile_order(
                self.session,
                execution_log=pending,
                broker_order=broker_detail,
                alpaca=self.alpaca,
                strategy=signal_row.strategy if signal_row else None,
            )
        return pending

    def run_selected_for_cycle(self, cycle_run_id: str) -> dict[str, Any]:
        dec = self.session.exec(
            select(PortfolioDecision).where(
                PortfolioDecision.cycle_run_id == cycle_run_id,
                PortfolioDecision.selected_for_execution == True,  # noqa: E712
                PortfolioDecision.portfolio_rank == 1,
            )
        ).first()
        if not dec:
            return {"status": "error", "message": "No Top-1 selected signal for cycle"}

        sig = self.session.get(StrategySignal, dec.signal_id)
        if not sig:
            return {"status": "error", "message": "Signal not found"}

        account = self.alpaca.sync_account()
        positions = self.alpaca.sync_positions()
        open_syms = {o.get("symbol") for o in self.alpaca.get_open_orders()}

        cand = self.candidate_from_signal(sig, dec)
        log = self.submit_candidate(
            cand,
            cycle_run_id=cycle_run_id,
            portfolio_decision=dec,
            account=account,
            positions=positions,
            open_order_symbols=open_syms,
            signal_row=sig,
        )
        self.session.commit()

        return {
            "status": "ok",
            "cycle_run_id": cycle_run_id,
            "signal_id": sig.id,
            "symbol": sig.symbol,
            "execution_status": log.status,
            "block_reason_code": log.reject_reason,
            "broker_order_id": log.broker_order_id,
            "client_order_id": log.broker_client_order_id,
            "submitted": log.status in ("paper_order_submitted", "paper_order_filled", "paper_order_partially_filled"),
        }

    def _log(
        self,
        cycle_run_id: str,
        cand: ApprovedCandidate,
        *,
        status: str,
        reject_reason: Optional[str],
        limit_price: Optional[float],
        quote: dict,
        portfolio_decision_id: Optional[int],
        broker_order_id: Optional[str] = None,
        broker_client_order_id: Optional[str] = None,
        submitted_at: Optional[datetime] = None,
        gates_passed: Optional[dict] = None,
        gates_failed: Optional[dict] = None,
    ) -> ExecutionLog:
        meta = cand.meta or {}
        log = ExecutionLog(
            event_id=str(uuid.uuid4()),
            cycle_run_id=cycle_run_id,
            signal_id=cand.signal_id,
            portfolio_decision_id=portfolio_decision_id,
            symbol=cand.symbol,
            side=cand.side,
            signal_type=cand.signal_type,
            requested_qty=cand.position_qty,
            requested_notional=cand.position_qty * cand.entry_price,
            limit_price=limit_price,
            tif="ioc",
            bid_at_decision=quote.get("bid"),
            ask_at_decision=quote.get("ask"),
            mid_at_decision=quote.get("mid"),
            spread_pct_at_decision=quote.get("spread_pct") or cand.spread_pct,
            atr14_at_decision=cand.atr14,
            expected_move_pct=cand.expected_move_pct or meta.get("expected_move_pct"),
            edge_over_cost=cand.edge_over_cost,
            risk_pct=(cand.sizing_evidence or {}).get("risk_pct"),
            gates_passed_json=gates_passed,
            gates_failed_json=gates_failed,
            broker_order_id=broker_order_id,
            broker_client_order_id=broker_client_order_id,
            submitted_at=submitted_at,
            status=status,
            reject_reason=reject_reason,
            parent_signal_payload_hash=hashlib.sha256(str(cand.signal_id).encode()).hexdigest()[:16],
            code_version_sha=CODE_VERSION_SHA,
        )
        self.session.add(log)
        return log
