"""Paper execution policy — state machine, marketable limit IOC."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.database import ExecutionLog, OrderRecord
from app.services.engine_config import cfg_get
from app.services.portfolio_gate import ApprovedCandidate
from app.services.symbol_tier_service import EngineBoundaryBlocked, SymbolTierService


class ExecutionPolicy:
    def __init__(self, session: Session, config: dict, alpaca, tier_service: SymbolTierService):
        self.session = session
        self.config = config
        self.alpaca = alpaca
        self.tiers = tier_service

    def _buffer_bps(self, tier: str) -> int:
        if "MEME" in tier:
            return int(cfg_get(self.config, "execution.limit_price_buffer_bps_meme", 40))
        if "MAJOR" in tier:
            return int(cfg_get(self.config, "execution.limit_price_buffer_bps_major", 15))
        return int(cfg_get(self.config, "execution.limit_price_buffer_bps_alt", 25))

    def limit_price(self, side: str, bid: float, ask: float, tier: str) -> float:
        bps = self._buffer_bps(tier)
        if side.lower() == "buy":
            return ask * (1 + bps / 10000.0)
        return bid * (1 - bps / 10000.0)

    def process_selected(
        self,
        cycle_run_id: str,
        selected: list[ApprovedCandidate],
        *,
        quote_by_symbol: dict[str, dict],
        portfolio_decision_id: Optional[int] = None,
        code_version_sha: str = "dev",
    ) -> list[ExecutionLog]:
        logs: list[ExecutionLog] = []
        paper_enabled = bool(cfg_get(self.config, "execution.paper_orders_enabled", False))
        live_enabled = bool(cfg_get(self.config, "execution.live_orders_enabled", False))
        max_per_cycle = int(cfg_get(self.config, "execution.max_orders_per_cycle", 1))

        submitted = 0
        for cand in selected[:max_per_cycle]:
            try:
                self.tiers.assert_order_path(cand.symbol)
            except EngineBoundaryBlocked as exc:
                log = self._create_log(
                    cycle_run_id,
                    cand,
                    status="rejected",
                    reject_reason=str(exc),
                    quote=quote_by_symbol.get(cand.symbol),
                    portfolio_decision_id=portfolio_decision_id,
                    code_version_sha=code_version_sha,
                )
                logs.append(log)
                continue

            quote = quote_by_symbol.get(cand.symbol) or {}
            bid = quote.get("bid")
            ask = quote.get("ask")
            limit_px = self.limit_price(cand.side, bid or cand.entry_price, ask or cand.entry_price, cand.tier)

            if not paper_enabled and not live_enabled:
                log = self._create_log(
                    cycle_run_id,
                    cand,
                    status="approved_no_order",
                    reject_reason="PAPER_EXECUTION_DISABLED",
                    limit_price=limit_px,
                    tif="ioc",
                    quote=quote,
                    portfolio_decision_id=portfolio_decision_id,
                    code_version_sha=code_version_sha,
                    gates_passed={"risk": True, "portfolio": True, "execution": False},
                )
                logs.append(log)
                continue

            if live_enabled:
                log = self._create_log(
                    cycle_run_id,
                    cand,
                    status="rejected",
                    reject_reason="LIVE_ORDERS_NOT_ARMED",
                    limit_price=limit_px,
                    tif="ioc",
                    quote=quote,
                    portfolio_decision_id=portfolio_decision_id,
                    code_version_sha=code_version_sha,
                )
                logs.append(log)
                continue

            client_id = f"hive-{cycle_run_id[:8]}-{uuid.uuid4().hex[:8]}"
            result = self.alpaca.submit_marketable_limit_ioc(
                cand.symbol,
                cand.position_qty,
                cand.side,
                limit_price=limit_px,
                client_order_id=client_id,
            )
            status = "paper_order_submitted" if result.get("success") else "paper_order_rejected"
            log = self._create_log(
                cycle_run_id,
                cand,
                status=status,
                reject_reason=result.get("error"),
                limit_price=limit_px,
                tif="ioc",
                quote=quote,
                broker_order_id=result.get("order_id"),
                broker_client_order_id=client_id,
                portfolio_decision_id=portfolio_decision_id,
                code_version_sha=code_version_sha,
                submitted_at=datetime.utcnow() if result.get("success") else None,
            )
            if result.get("success"):
                submitted += 1
                self.session.add(
                    OrderRecord(
                        alpaca_order_id=result.get("order_id"),
                        symbol=cand.symbol,
                        side=cand.side,
                        qty=cand.position_qty,
                        order_type="limit_ioc",
                        status="submitted",
                        stop_loss=cand.stop_loss,
                    )
                )
            logs.append(log)

        return logs

    def _create_log(
        self,
        cycle_run_id: str,
        cand: ApprovedCandidate,
        *,
        status: str,
        reject_reason: Optional[str],
        limit_price: float,
        tif: str,
        quote: dict,
        broker_order_id: Optional[str] = None,
        broker_client_order_id: Optional[str] = None,
        portfolio_decision_id: Optional[int] = None,
        code_version_sha: str = "dev",
        submitted_at: Optional[datetime] = None,
        gates_passed: Optional[dict] = None,
    ) -> ExecutionLog:
        meta = cand.meta or {}
        payload_hash = hashlib.sha256(str(cand.signal_id).encode()).hexdigest()[:16]
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
            tif=tif,
            bid_at_decision=quote.get("bid"),
            ask_at_decision=quote.get("ask"),
            mid_at_decision=quote.get("mid"),
            spread_pct_at_decision=quote.get("spread_pct") or cand.spread_pct,
            atr14_at_decision=cand.atr14,
            expected_move_pct=cand.expected_move_pct or meta.get("expected_move_pct"),
            edge_over_cost=cand.edge_over_cost,
            risk_pct=cand.sizing_evidence.get("risk_pct"),
            gates_passed_json=gates_passed or {"risk": True, "portfolio": True},
            gates_failed_json={"reason": reject_reason} if reject_reason else None,
            broker_order_id=broker_order_id,
            broker_client_order_id=broker_client_order_id,
            submitted_at=submitted_at,
            status=status,
            reject_reason=reject_reason,
            parent_signal_payload_hash=payload_hash,
            code_version_sha=code_version_sha,
        )
        self.session.add(log)
        return log
