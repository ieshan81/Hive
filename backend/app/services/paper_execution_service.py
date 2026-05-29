"""Safe Alpaca paper order execution — preflight, submit, reconcile."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PortfolioDecision, StrategySignal
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.alpaca_broker_error import broker_rejection_detail, classify_reject_reason, parse_alpaca_exception
from app.services.broker_safety import (
    broker_base_url,
    is_paper_broker_url,
    live_lock_status,
    paper_execution_blockers,
)
from app.services.config_manager import ConfigManager
from app.services.cooldown_service import CooldownService
from app.services.engine_config import cfg_get
from app.services.execution_preflight import build_client_order_id
from app.services.order_reconciliation import reconcile_order
from app.services.portfolio_gate import ApprovedCandidate
from app.services.symbol_tier_service import EngineBoundaryBlocked, SymbolTierService


CODE_VERSION_SHA = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "dev")[:12]


def _map_broker_rejection_code(error: str, broker_error: Optional[dict] = None) -> str:
    if broker_error:
        return classify_reject_reason(broker_error)
    err = (error or "").lower()
    if "notional" in err or "minimum" in err or "min order" in err:
        return "BROKER_REJECTED_MIN_NOTIONAL"
    if "insufficient" in err and "balance" in err:
        return "BROKER_INSUFFICIENT_BALANCE"
    if "increment" in err or "precision" in err or "subtick" in err:
        if "price" in err or "limit" in err:
            return "BROKER_LIMIT_PRICE_PRECISION"
        return "BROKER_QTY_PRECISION"
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
            expected_move_pct=meta.get("expected_move_pct")
            or (float(meta.get("take_profit_pct", 0.03)) * 100 if meta.get("take_profit_pct") else None),
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
        from app.services.account_pair_eligibility_service import AccountPairEligibilityService

        strategy_id = ""
        if signal_row and getattr(signal_row, "strategy", None):
            strategy_id = str(signal_row.strategy)
        elif cand.meta.get("strategy_id"):
            strategy_id = str(cand.meta["strategy_id"])
        preflight_side = cand.side or ("sell" if cand.signal_type == "exit" else "buy")
        elig = AccountPairEligibilityService(self.session, self.config).preflight_block(
            cand.symbol, preflight_side, strategy_id
        )
        if elig:
            return self._log(
                cycle_run_id,
                cand,
                status="preflight_blocked",
                reject_reason=elig[0],
                limit_price=None,
                quote={},
                portfolio_decision_id=portfolio_decision.id if portfolio_decision else None,
                gates_failed={
                    "category": elig[0],
                    "reason": elig[1],
                    "preflight_stage": "account_pair_eligibility_block",
                },
            )

        from app.services.pre_submit_quote_service import PreSubmitQuoteService
        from app.services.activity_logger import log_activity

        quote_sym = normalize_crypto_symbol(cand.symbol)
        initial = self.alpaca.get_quote(quote_sym, "crypto") or {}
        if initial and not initial.get("quote_timestamp"):
            initial["quote_timestamp"] = datetime.now(timezone.utc).isoformat()
        refresh = PreSubmitQuoteService(self.session, self.config).refresh_for_submit(
            cand.symbol, asset_class="crypto", initial_quote=initial
        )
        quote = refresh.get("quote") or {}
        quote_meta = {
            "quote_refreshed": bool(refresh.get("quote_refreshed")),
            "quote_refresh_result": refresh.get("quote_refresh_result"),
            "quote_age_seconds_at_submit": refresh.get("quote_age_seconds_at_submit"),
            "quote_refresh_attempts": refresh.get("attempts"),
        }

        if refresh.get("status") == "blocked":
            log_activity(
                self.session,
                "quote_refresh_blocked",
                f"{cand.symbol}: {refresh.get('plain', 'quote still stale')}",
                {"symbol": cand.symbol, **quote_meta},
                commit=False,
            )
            return self._log(
                cycle_run_id,
                cand,
                status="preflight_blocked",
                reject_reason="STALE_QUOTE",
                limit_price=None,
                quote=quote,
                portfolio_decision_id=portfolio_decision.id if portfolio_decision else None,
                gates_failed={
                    "code": "STALE_QUOTE",
                    "reason": refresh.get("human_reason") or refresh.get("plain"),
                    "preflight_stage": "pre_submit_quote_refresh",
                    "outcome_bucket": "preflight_blocked",
                    "blocked_before_broker": True,
                    **quote_meta,
                },
            )

        if refresh.get("quote_refreshed"):
            log_activity(
                self.session,
                "quote_refreshed",
                f"{cand.symbol}: quote refreshed before submit ({refresh.get('quote_refresh_result')})",
                {"symbol": cand.symbol, **quote_meta},
                commit=False,
            )
            mid = float(quote.get("mid") or quote.get("ask") or 0)
            if mid > 0 and cand.position_qty > 0:
                cand.entry_price = mid
                cand.spread_pct = quote.get("spread_pct") or cand.spread_pct

        from app.trading_cage.execution_cage import ExecutionCage

        cage = ExecutionCage(self.session, self.config).validate_submit(
            cand=cand,
            cycle_run_id=cycle_run_id,
            portfolio_decision=portfolio_decision,
            account=account,
            positions=positions,
            open_order_symbols=open_order_symbols or set(),
            quote=quote,
            signal_row=signal_row,
        )

        if not cage.passed:
            return self._log(
                cycle_run_id,
                cand,
                status="preflight_blocked",
                reject_reason=cage.block_reason_code,
                limit_price=cage.preflight.limit_price if cage.preflight else None,
                quote=quote,
                portfolio_decision_id=portfolio_decision.id if portfolio_decision else None,
                gates_failed={
                    "code": cage.block_reason_code,
                    "reason": cage.human_reason,
                    "cage_stage": cage.stage,
                    "cost_model": cage.cost_model,
                    "allocation": cage.allocation,
                    "crypto_validation": cage.crypto_validation,
                    "preflight_stage": f"execution_cage_{cage.stage}",
                    "outcome_bucket": "preflight_blocked",
                    "blocked_before_broker": True,
                    **quote_meta,
                },
            )

        pf = cage.preflight
        assert pf is not None

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

        crypto_val = cage.crypto_validation or {}
        norm = crypto_val.get("normalized_payload") or {}
        recipe = crypto_val.get("recipe") or str(
            cfg_get(self.config, "execution.crypto_paper_recipe", "limit_ioc_qty")
        )
        submit_qty = norm.get("qty", cand.position_qty)
        submit_limit = norm.get("limit_price", pf.limit_price or cand.entry_price)
        submit_notional = norm.get("notional")
        if submit_qty and submit_qty != cand.position_qty:
            cand.position_qty = float(submit_qty)

        pending = self._log(
            cycle_run_id,
            cand,
            status="paper_order_pending",
            reject_reason=None,
            limit_price=submit_limit,
            quote=quote,
            portfolio_decision_id=portfolio_decision.id if portfolio_decision else None,
            broker_client_order_id=pf.client_order_id,
            gates_passed={
                "preflight": True,
                "risk": True,
                "portfolio": True,
                "evidence": pf.evidence,
                "outcome_bucket": "submitted_to_broker",
                "crypto_validator": crypto_val,
                "execution_cage": True,
                "cost_model": cage.cost_model,
                "allocation": cage.allocation,
                **quote_meta,
            },
        )
        self.session.flush()

        if recipe == "market_notional" and submit_notional:
            result = self.alpaca.submit_crypto_market_notional(
                cand.symbol,
                float(submit_notional),
                cand.side,
                client_order_id=pf.client_order_id,
                time_in_force=norm.get("time_in_force", "gtc"),
            )
        else:
            result = self.alpaca.submit_marketable_limit_ioc(
                cand.symbol,
                float(submit_qty),
                cand.side,
                limit_price=float(submit_limit),
                client_order_id=pf.client_order_id,
            )

        if not result.get("success"):
            broker_err = result.get("broker_error") or parse_alpaca_exception(
                Exception(result.get("error", "broker rejected"))
            )
            req_payload = result.get("request_payload") or norm
            detail = broker_rejection_detail(
                parsed=broker_err,
                request_payload=req_payload,
                symbol=cand.symbol,
            )
            pending.status = "paper_order_rejected"
            pending.reject_reason = _map_broker_rejection_code(result.get("error", ""), broker_err)
            pending.gates_failed_json = {
                **detail,
                "preflight_stage": "broker_rejection",
                "outcome_bucket": "broker_rejected",
                "broker": result.get("error"),
                "broker_message": detail.get("plain"),
                **quote_meta,
            }
            self.session.add(pending)
            from app.services.activity_logger import log_activity

            log_activity(
                self.session,
                "broker_rejected",
                f"{cand.symbol}: Broker rejected after submit — {detail.get('plain', pending.reject_reason)}",
                detail,
                commit=False,
            )
            CooldownService(self.session, self.config).apply_symbol(
                cand.symbol, "BROKER_REJECTION", details={"error": pending.reject_reason, **detail}
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

    def validate_order_dry_run(self, body: dict[str, Any]) -> dict[str, Any]:
        """Dry-run crypto order validation — does not submit to Alpaca."""
        symbol = str(body.get("symbol") or "")
        side = str(body.get("side") or "buy")
        order_type = str(body.get("type") or body.get("order_type") or "limit")
        tif = str(body.get("time_in_force") or "ioc")
        qty = body.get("qty")
        notional = body.get("notional")
        limit_price = body.get("limit_price")
        if qty is not None:
            qty = float(qty)
        if notional is not None:
            notional = float(notional)
        if limit_price is not None:
            limit_price = float(limit_price)

        account = self.alpaca.sync_account_cached()
        open_syms = {o.get("symbol") for o in self.alpaca.get_open_orders()}
        v = AlpacaCryptoOrderValidator(self.session, self.alpaca, self.config).validate_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            time_in_force=tif,
            qty=qty,
            notional=notional,
            limit_price=limit_price,
            client_order_id=body.get("client_order_id") or f"dry-{uuid.uuid4().hex[:8]}",
            account=account,
            open_order_symbols=open_syms,
            dry_run=True,
        )
        return {
            "status": "ok",
            "valid": v.valid,
            "normalized_payload": v.normalized_payload,
            "asset_metadata": v.asset_metadata,
            "buying_power_check": v.buying_power_check,
            "quote_currency_check": v.quote_currency_check,
            "precision_adjustments": v.precision_adjustments,
            "validator_reasons": v.validator_reasons,
            "reject_code": v.reject_code,
            "would_submit_to_broker": False,
        }

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

        account = self.alpaca.sync_account_cached()
        positions = self.alpaca.sync_positions_cached()
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
