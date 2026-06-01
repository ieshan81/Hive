"""Read-only business-state summary for paper autopilot decisions."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PaperExperimentOutcome, PositionSnapshot, SettingsActionAudit
from app.services.autopilot_decision_classifier import classify_block_reason
from app.services.exposure_truth_service import ExposureTruthService
from app.services.order_ledger_service import build_trade_ledger, display_symbol


def _latest(session: Session, model, *order_cols):
    order = order_cols or (model.id.desc(),)
    return session.exec(select(model).order_by(*order).limit(1)).first()


class AutopilotDecisionStateService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def state(self) -> dict[str, Any]:
        exposure_svc = ExposureTruthService(self.session, self.config)
        broker_positions, broker_truth_available, broker_truth_evidence = exposure_svc.fresh_broker_positions()
        exposure = exposure_svc.stale_local_summary(
            broker_positions=broker_positions if broker_truth_available else None,
            broker_truth_available=True if broker_truth_available else None,
        )
        positions = (
            list(broker_positions or [])
            if broker_truth_available
            else list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
        )
        latest_tick = self.session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == "autonomous_run_one_cycle")
            .order_by(SettingsActionAudit.created_at.desc())
            .limit(1)
        ).first()
        tick = dict(latest_tick.details_json or {}) if latest_tick and latest_tick.details_json else {}
        latest_order = _latest(self.session, OrderRecord, OrderRecord.submitted_at.desc(), OrderRecord.id.desc())
        latest_exec = _latest(self.session, ExecutionLog, ExecutionLog.created_at.desc(), ExecutionLog.id.desc())
        latest_outcome = _latest(self.session, PaperExperimentOutcome, PaperExperimentOutcome.created_at.desc(), PaperExperimentOutcome.id.desc())
        try:
            ledger_summary = (build_trade_ledger(self.session, limit=200).get("summary") or {})
        except Exception:
            ledger_summary = {"gross_pnl": None, "win_rate_pct": None, "biggest_loser": None}
        outcomes = list(self.session.exec(select(PaperExperimentOutcome)).all())
        losers = [o for o in outcomes if o.realized_pnl is not None]
        biggest = min(losers, key=lambda o: float(o.realized_pnl or 0), default=None)
        reason = (
            tick.get("reason")
            or tick.get("plain_summary")
            or getattr(latest_exec, "reject_reason", None)
            or "no_recent_cycle"
        )
        cls = classify_block_reason(str(reason))
        hard_ok = not bool(cls.get("should_freeze")) and not positions
        selected = tick.get("selected_candidate")
        rejected = tick.get("rejected_candidates") or tick.get("no_trade_reason_breakdown") or {}
        tick_orders_created = int(tick.get("orders_created") or tick.get("new_orders") or 0)
        final_decision = self._final_trade_decision(tick_orders_created, selected)
        plain = self._plain_summary(exposure, positions, selected, rejected, final_decision, reason, tick)
        win_rate_pct = ledger_summary.get("win_rate_pct")
        try:
            from app.services.paper_exploration_service import PaperExplorationService

            exploration = PaperExplorationService(self.session, self.config).decision_state()
        except Exception:
            exploration = {
                "standard_entries_allowed": None,
                "paper_exploration_allowed": None,
                "selected_exploration_candidate": None,
                "exploration_order_submitted": False,
                "exploration_block_reason": "exploration_state_unavailable",
            }
        return {
            "status": "ok",
            "are_we_trading": final_decision == "submitted",
            # Paper-exploration lane (real money always locked; standard entries follow the cage).
            **exploration,
            "why_not_trading": None if final_decision == "submitted" else reason,
            "hard_safety_ok": hard_ok,
            "broker_positions": [
                {
                    "symbol": display_symbol(self._position_symbol(p)),
                    "qty": self._position_qty(p),
                    "market_value": self._position_market_value(p),
                }
                for p in positions
            ],
            "broker_truth": {
                "available": broker_truth_available,
                **(broker_truth_evidence or {}),
            },
            "stale_local_state": exposure,
            "repaired_this_tick": tick.get("trade_state_repair"),
            "last_tick_at": latest_tick.created_at.isoformat() + "Z" if latest_tick and latest_tick.created_at else None,
            "last_tick_id": latest_tick.id if latest_tick else None,
            "tick_status": tick.get("status") or tick.get("action") or ("no_recent_tick" if not latest_tick else "completed"),
            "tick_reason": reason,
            "tick_orders_created": tick_orders_created,
            "tick_selected_candidate": selected,
            "tick_trade_state_repair": tick.get("trade_state_repair"),
            "tick_market_data_refresh": tick.get("market_data_refresh"),
            "candidates_seen": tick.get("candidates_created") or tick.get("symbols_scanned_count") or 0,
            "candidates_rejected": rejected,
            "candidates_rotated": cls.get("should_rotate"),
            "selected_candidate": selected,
            "final_trade_decision": final_decision,
            "expected_edge_after_cost": (selected or {}).get("edge_after_cost_bps") if isinstance(selected, dict) else None,
            "last_order": self._order_row(latest_order),
            "last_exit": self._outcome_row(latest_outcome),
            "last_realized_pnl": getattr(latest_outcome, "realized_pnl", None) if latest_outcome else None,
            "gross_pnl_since_reset": ledger_summary.get("gross_pnl"),
            "gross_pnl_source": "trades_ledger_summary" if ledger_summary.get("gross_pnl") is not None else "unavailable",
            "win_rate_since_reset": round(float(win_rate_pct) / 100.0, 4) if win_rate_pct is not None else None,
            "trades_ledger_summary": ledger_summary,
            "biggest_loser_since_reset": self._outcome_row(biggest),
            "current_mode": "paper",
            "blocked_reason_class": cls.get("blocked_reason_class"),
            "should_rotate": cls.get("should_rotate"),
            "should_freeze": cls.get("should_freeze"),
            "human_plain_english_summary": plain,
        }

    @staticmethod
    def _final_trade_decision(tick_orders_created: int, selected: Any) -> str:
        if tick_orders_created > 0:
            return "submitted"
        if isinstance(selected, dict) and selected:
            return "approved_pending_or_blocked"
        return "no_trade_no_edge"

    @staticmethod
    def _position_symbol(pos: Any) -> str:
        if isinstance(pos, dict):
            return str(pos.get("symbol") or pos.get("sym") or "")
        return str(getattr(pos, "symbol", "") or "")

    @staticmethod
    def _position_qty(pos: Any) -> float:
        try:
            if isinstance(pos, dict):
                return float(pos.get("qty") or 0)
            return float(getattr(pos, "qty", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _position_market_value(pos: Any) -> float:
        try:
            if isinstance(pos, dict):
                return float(pos.get("market_value") or pos.get("marketValue") or 0)
            return float(getattr(pos, "market_value", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _order_row(row: Optional[OrderRecord]) -> Optional[dict[str, Any]]:
        if not row:
            return None
        return {
            "id": row.id,
            "symbol": display_symbol(row.symbol),
            "side": row.side,
            "status": row.status,
            "submitted_at": row.submitted_at.isoformat() + "Z" if row.submitted_at else None,
        }

    @staticmethod
    def _outcome_row(row: Optional[PaperExperimentOutcome]) -> Optional[dict[str, Any]]:
        if not row:
            return None
        return {
            "id": row.id,
            "symbol": display_symbol(row.symbol),
            "realized_pnl": row.realized_pnl,
            "exit_reason": row.exit_reason,
        }

    @staticmethod
    def _plain_summary(
        exposure: dict,
        positions: list,
        selected: Any,
        rejected: Any,
        decision: str,
        reason: str,
        tick: dict,
    ) -> str:
        stale = exposure.get("broker_flat_stale_symbols") or []
        if positions:
            syms = ", ".join(display_symbol(AutopilotDecisionStateService._position_symbol(p)) for p in positions[:3])
            return f"Holding {syms}. Exit monitor controls exits; entries wait for cage approval."
        prefix = "Broker is flat."
        if stale:
            repair = tick.get("trade_state_repair") or {}
            affected = int(repair.get("affected_count") or 0) if isinstance(repair, dict) else 0
            if affected > 0:
                prefix += f" Broker-flat repair updated {affected} stale local row(s)."
            else:
                prefix += f" Local stale {', '.join(stale[:4])} rows still need broker-flat repair."
        if decision == "submitted":
            sym = selected.get("symbol") if isinstance(selected, dict) else "candidate"
            return f"{prefix} {sym} passed edge/cage and a paper order was submitted in the latest tick."
        if decision == "approved_pending_or_blocked":
            sym = selected.get("symbol") if isinstance(selected, dict) else "candidate"
            return f"{prefix} Latest tick selected {sym}, but no order was created in that tick: {reason}."
        if rejected:
            return f"{prefix} No paper order submitted: {reason}."
        return f"{prefix} No candidate passed edge-after-cost yet."
