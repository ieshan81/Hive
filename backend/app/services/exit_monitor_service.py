"""Exit monitor — always-on position watch status."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.alpaca_adapter import AlpacaAdapter
from app.services.config_manager import ConfigManager
from app.services.training_execution_service import TrainingExecutionService


def exit_monitor_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    alpaca = AlpacaAdapter(session)
    positions = alpaca.sync_positions_cached() or []
    training = TrainingExecutionService(session, cfg)
    monitor = training.monitor_exits()

    plans = []
    for pos in positions:
        qty = float(getattr(pos, "qty", 0) or 0)
        if qty <= 0:
            continue
        sym = pos.symbol
        entry = float(getattr(pos, "avg_entry_price", 0) or 0)
        current = float(getattr(pos, "current_price", 0) or 0)
        upl = float(getattr(pos, "unrealized_pl", 0) or 0)
        plans.append(
            {
                "symbol": sym,
                "qty": qty,
                "avg_entry": entry,
                "current_price": current,
                "unrealized_pl": upl,
                "profit_target": "configured in push_pull.profit_target_bps",
                "atr_stop": "configured in push_pull.atr_stop_multiplier",
                "hard_safety_stop": True,
                "timeout": "configured in push_pull.timeout_minutes",
                "next_exit_check": "every training cycle",
            }
        )

    return {
        "status": "ok",
        "schema_version": 1,
        "exit_monitor_enabled": True,
        "require_exit_monitor": bool((cfg.get("paper_learning") or {}).get("require_position_monitor", True)),
        "open_positions_count": len(plans),
        "positions": plans,
        "latest_monitor_run": monitor,
        "plain": (
            f"Watching {len(plans)} open position(s) for exit triggers."
            if plans
            else "No open positions — exit monitor idle."
        ),
    }
