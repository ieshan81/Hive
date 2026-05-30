"""Exit plan self-healing — Paper Autopilot Operations Brain verifier.

Proves:
- signal-linked stop/target is recovered onto the opening signal
- latest entry signal is used when execution log lacks signal_id
- orphan positions get an emergency paper-only plan
- after successful heal, OPEN_POSITION_MISSING_EXIT_PLAN preflight gate clears
- when auto-heal is disabled, unmanaged positions remain blocked
- live trading stays locked; AI cannot submit orders
"""

import sys
from pathlib import Path
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import ExecutionLog, StrategySignal
from app.services.ai_boundaries import AI_CAPABILITIES, assert_actor_not_ai
from app.services.exit_monitor_service import open_positions_missing_exit_plan, resolve_exit_plan
from app.services.exit_plan_self_heal_service import attempt_exit_plan_self_heal

CFG = {
    "live_trading_enabled": False,
    "execution": {"paper_orders_enabled": True, "live_orders_enabled": False},
    "autonomous_paper_learning": {
        "max_unrealized_loss_pct": 1.5,
        "max_unrealized_loss_usd": 4.0,
        "block_new_entry_if_unmanaged_position": True,
        "auto_heal_missing_exit_plans": True,
        "emergency_max_hold_hours": 12,
    },
    "paper_learning": {"require_position_monitor": True, "mode_enabled": True},
    "promotion": {"stage": "PAPER"},
}


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _add_log(session: Session, **kwargs) -> ExecutionLog:
    row = ExecutionLog(
        event_id=kwargs.pop("event_id", str(uuid.uuid4())),
        cycle_run_id=kwargs.pop("cycle_run_id", f"verify-{uuid.uuid4().hex[:8]}"),
        **kwargs,
    )
    session.add(row)
    return row


def _fake_pos(symbol: str, entry: float = 100.0, qty: float = 1.0) -> dict:
    return {
        "symbol": symbol,
        "qty": qty,
        "avg_entry_price": entry,
        "current_price": entry,
        "unrealized_pl": 0.0,
    }


def _run_heal(session: Session, positions: list) -> dict:
    with patch("app.services.exit_plan_self_heal_service.is_paper_broker_url", return_value=True), patch(
        "app.services.exit_plan_self_heal_service.AlpacaAdapter"
    ) as mock_cls:
        mock_cls.return_value.sync_positions_cached.return_value = positions
        return attempt_exit_plan_self_heal(session, CFG, operator="verify")


def test_recover_from_signal_with_stop_target() -> None:
    session = _mem_session()
    sig = StrategySignal(
        strategy="crypto_push_pull_baseline",
        symbol="ETH/USD",
        signal="buy",
        signal_type="entry",
        stop_loss=1900.0,
        take_profit=2100.0,
    )
    session.add(sig)
    session.flush()
    _add_log(
        session,
        symbol="ETH/USD",
        side="buy",
        signal_type="entry",
        status="paper_order_filled",
        signal_id=sig.id,
        filled_avg_price=2000.0,
        requested_qty=0.01,
        filled_qty=0.01,
    )
    session.commit()

    before = resolve_exit_plan(session, CFG, "ETH/USD", avg_entry=2000.0)
    assert before["has_exit_plan"] is True, before

    out = _run_heal(session, [_fake_pos("ETHUSD", 2000.0)])
    assert out["status"] == "ok", out
    assert out["attempted"] == 0, out
    session.close()
    print("self-heal: signal with stop/target already protected — PASS")


def test_recover_latest_entry_signal_without_log_signal_id() -> None:
    session = _mem_session()
    sig = StrategySignal(
        strategy="crypto_push_pull_baseline",
        symbol="LTC/USD",
        signal="buy",
        signal_type="entry",
        stop_loss=90.0,
        take_profit=110.0,
    )
    session.add(sig)
    session.flush()
    _add_log(
        session,
        symbol="LTC/USD",
        side="buy",
        signal_type="entry",
        status="paper_order_filled",
        signal_id=None,
        filled_avg_price=100.0,
        requested_qty=1.0,
        filled_qty=1.0,
    )
    session.commit()

    before = resolve_exit_plan(session, CFG, "LTC/USD", avg_entry=100.0)
    assert before["has_exit_plan"] is True, before
    session.close()
    print("self-heal: latest entry signal resolves plan without log signal_id — PASS")


def test_emergency_plan_for_orphan_position() -> None:
    session = _mem_session()
    _add_log(
        session,
        symbol="DOGE/USD",
        side="buy",
        signal_type="entry",
        status="paper_order_filled",
        signal_id=None,
        filled_avg_price=0.10,
        requested_qty=100.0,
        filled_qty=100.0,
    )
    session.commit()

    before = resolve_exit_plan(session, CFG, "DOGE/USD", avg_entry=0.10)
    assert before["missing_exit_plan"] is True, before

    out = _run_heal(session, [_fake_pos("DOGEUSD", 0.10, 100.0)])
    assert out["attempted"] == 1, out
    pos_result = out["positions"][0]
    assert pos_result.get("emergency_exit_plan_attached") is True, pos_result

    after = resolve_exit_plan(session, CFG, "DOGE/USD", avg_entry=0.10)
    assert after["has_exit_plan"] is True, after
    assert after["exit_plan_source"] == "emergency_backfill", after
    assert after["protection_state"] == "emergency plan", after
    meta = session.get(StrategySignal, after["signal_id"]).signal_metadata or {}
    assert meta.get("counts_as_strategy_success") is False, meta
    session.close()
    print("self-heal: orphan position gets emergency paper plan — PASS")


def test_heal_unblocks_new_entries() -> None:
    session = _mem_session()
    _add_log(
        session,
        symbol="AVAX/USD",
        side="buy",
        signal_type="entry",
        status="paper_order_filled",
        filled_avg_price=30.0,
        requested_qty=1.0,
        filled_qty=1.0,
    )
    session.commit()

    positions = [_fake_pos("AVAXUSD", 30.0)]
    missing_before = open_positions_missing_exit_plan(session, CFG, positions)
    assert missing_before, missing_before

    _run_heal(session, positions)
    missing_after = open_positions_missing_exit_plan(session, CFG, positions)
    assert missing_after == [], missing_after
    session.close()
    print("self-heal: managed position no longer blocks new entries — PASS")


def test_unmanaged_remains_blocked_when_auto_heal_disabled() -> None:
    session = _mem_session()
    cfg = {
        **CFG,
        "autonomous_paper_learning": {
            **CFG["autonomous_paper_learning"],
            "auto_heal_missing_exit_plans": False,
        },
    }
    session.add(
        ExecutionLog(
            event_id=str(uuid.uuid4()),
            cycle_run_id=f"verify-{uuid.uuid4().hex[:8]}",
            symbol="LINK/USD",
            side="buy",
            signal_type="entry",
            status="paper_order_filled",
            filled_avg_price=15.0,
            requested_qty=1.0,
            filled_qty=1.0,
        )
    )
    session.commit()
    positions = [_fake_pos("LINKUSD", 15.0)]

    with patch("app.services.exit_plan_self_heal_service.is_paper_broker_url", return_value=True), patch(
        "app.services.exit_plan_self_heal_service.AlpacaAdapter"
    ) as mock_cls:
        mock_cls.return_value.sync_positions_cached.return_value = positions
        out = attempt_exit_plan_self_heal(session, cfg, operator="verify")
    assert out.get("reason") == "auto_heal_disabled", out

    missing = open_positions_missing_exit_plan(session, cfg, positions)
    assert missing, missing
    session.close()
    print("self-heal: disabled auto-heal leaves position unmanaged — PASS")


def test_live_trading_remains_locked() -> None:
    session = _mem_session()
    out = _run_heal(session, [])
    assert out.get("status") in ("ok", "skipped"), out
    diag = out
    with patch("app.services.exit_plan_self_heal_service.is_paper_broker_url", return_value=True):
        from app.services.exit_plan_self_heal_service import self_heal_diagnostics

        d = self_heal_diagnostics(session, CFG)
    assert d.get("live_lock_status") == "locked", d
    assert CFG["live_trading_enabled"] is False
    session.close()
    print("self-heal: live trading remains locked — PASS")


def test_ai_cannot_submit_orders() -> None:
    assert AI_CAPABILITIES["can_submit_orders"] is False
    try:
        assert_actor_not_ai("ai_advisor", action="submit_order")
        raised = False
    except PermissionError:
        raised = True
    assert raised is True
    print("self-heal: AI actor cannot trigger orders — PASS")


if __name__ == "__main__":
    test_recover_from_signal_with_stop_target()
    test_recover_latest_entry_signal_without_log_signal_id()
    test_emergency_plan_for_orphan_position()
    test_heal_unblocks_new_entries()
    test_unmanaged_remains_blocked_when_auto_heal_disabled()
    test_live_trading_remains_locked()
    test_ai_cannot_submit_orders()
    print("ALL PASS: verify_exit_plan_self_healing")
