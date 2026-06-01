"""Read-only business-state summary for paper autopilot decisions."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PaperExperimentOutcome, PositionSnapshot, SettingsActionAudit
from app.services.autopilot_decision_classifier import classify_block_reason
from app.services.exposure_truth_service import ExposureTruthService
from app.services.order_ledger_service import display_symbol


def _latest(session: Session, model, *order_cols):
    order = order_cols or (model.id.desc(),)
    return session.exec(select(model).order_by(*order).limit(1)).first()


class AutopilotDecisionStateService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def state(self) -> dict[str, Any]:
        exposure = ExposureTruthService(self.session, self.config).stale_local_summary()
        positions = list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
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
        outcomes = list(self.session.exec(select(PaperExperimentOutcome)).all())
        realized = [float(o.realized_pnl or 0) for o in outcomes if o.realized_pnl is not None]
        gross = round(sum(realized), 6) if realized else 0.0
        win_rate = round(len([x for x in realized if x > 0]) / len(realized), 4) if realized else None
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
        final_decision = "submitted" if latest_order and latest_exec and latest_exec.status in (
            "paper_order_submitted",
            "paper_order_filled",
            "paper_order_partially_filled",
        ) else "no_trade"
        plain = self._plain_summary(exposure, positions, selected, rejected, final_decision, reason)
        return {
            "status": "ok",
            "are_we_trading": final_decision == "submitted",
            "why_not_trading": None if final_decision == "submitted" else reason,
            "hard_safety_ok": hard_ok,
            "broker_positions": [
                {"symbol": display_symbol(p.symbol), "qty": p.qty, "market_value": p.market_value}
                for p in positions
            ],
            "stale_local_state": exposure,
            "repaired_this_tick": tick.get("trade_state_repair"),
            "candidates_seen": tick.get("candidates_created") or tick.get("symbols_scanned_count") or 0,
            "candidates_rejected": rejected,
            "candidates_rotated": cls.get("should_rotate"),
            "selected_candidate": selected,
            "final_trade_decision": final_decision,
            "expected_edge_after_cost": (selected or {}).get("edge_after_cost_bps") if isinstance(selected, dict) else None,
            "last_order": self._order_row(latest_order),
            "last_exit": self._outcome_row(latest_outcome),
            "last_realized_pnl": getattr(latest_outcome, "realized_pnl", None) if latest_outcome else None,
            "gross_pnl_since_reset": gross,
            "win_rate_since_reset": win_rate,
            "biggest_loser_since_reset": self._outcome_row(biggest),
            "current_mode": "paper",
            "blocked_reason_class": cls.get("blocked_reason_class"),
            "should_rotate": cls.get("should_rotate"),
            "should_freeze": cls.get("should_freeze"),
            "human_plain_english_summary": plain,
        }

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
    def _plain_summary(exposure: dict, positions: list, selected: Any, rejected: Any, decision: str, reason: str) -> str:
        stale = exposure.get("broker_flat_stale_symbols") or []
        if positions:
            syms = ", ".join(display_symbol(p.symbol) for p in positions[:3])
            return f"Holding {syms}. Exit monitor controls exits; entries wait for cage approval."
        prefix = "Broker is flat."
        if stale:
            prefix += f" Local stale {', '.join(stale[:4])} rows need/received broker-flat repair."
        if decision == "submitted":
            sym = selected.get("symbol") if isinstance(selected, dict) else "candidate"
            return f"{prefix} {sym} passed edge/cage and a paper order was submitted."
        if rejected:
            return f"{prefix} No paper order submitted: {reason}."
        return f"{prefix} No candidate passed edge-after-cost yet."
