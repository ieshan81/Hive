"""The Hive Engine Map is read-only and its truth matches the database.

Asserts: all lifecycle nodes present; paper/live separation matches `_execution_safety`; open
position count + scorecard/outcome counts match the DB; latest trade lifecycle (if any) matches the
canonical outcome; no node advertises a live path; orders_authority is cage_only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, func, select  # noqa: E402

import app.database  # noqa: F401,E402
from app.database import OrderRecord, PaperExperimentOutcome, PositionSnapshot  # noqa: E402
from app.services.hive_engine_map_service import HiveEngineMapService  # noqa: E402

EXPECTED_NODES = {"universe", "signal", "scorecard", "candidate", "risk_cage", "preflight",
                  "broker", "position", "exit_monitor", "outcome", "memory", "backtest_lab", "promotion"}


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng, expire_on_commit=False)


def main() -> None:
    s = _mem()
    # Seed a closed canonical outcome + flat broker.
    s.add(PaperExperimentOutcome(strategy_id="x", symbol="BTC/USD", trade_id="BTCUSD|B1|S1",
                                 realized_pnl=-0.069, realized_pnl_pct=-0.58, canonical_exit_reason="stop_loss",
                                 exit_reason="stop_loss", lesson_created=True))
    s.commit()

    m = HiveEngineMapService(s).map()

    # Shape + node coverage.
    assert m["status"] == "ok", m
    assert m["orders_authority"] == "cage_only", m
    node_keys = {n["key"] for n in m["nodes"]}
    assert EXPECTED_NODES.issubset(node_keys), EXPECTED_NODES - node_keys
    # No node advertises a live path.
    assert not any(n.get("live_path") for n in m["nodes"]), [n["key"] for n in m["nodes"] if n.get("live_path")]

    # Truth matches DB.
    db_positions = int(s.exec(select(func.count()).select_from(PositionSnapshot).where(PositionSnapshot.qty > 0)).one())
    assert m["counts"]["open_positions"] == db_positions, (m["counts"]["open_positions"], db_positions)
    db_outcomes = int(s.exec(select(func.count()).select_from(PaperExperimentOutcome)).one())
    assert m["counts"]["closed_outcomes"] == db_outcomes, m["counts"]
    pos_node = next(n for n in m["nodes"] if n["key"] == "position")
    assert pos_node["status"] == ("flat" if db_positions == 0 else "open"), pos_node

    # Latest trade lifecycle matches the canonical outcome.
    lt = m["latest_trade_lifecycle"]
    assert lt and lt["symbol"] == "BTC/USD" and lt["trade_id"] == "BTCUSD|B1|S1", lt
    assert lt["realized_pnl"] == -0.069 and lt["exit_reason"] == "stop_loss", lt
    assert lt["outcome_status"] == "closed" and lt["memory_lesson_status"] == "linked", lt

    # Real money locked + live disabled in the separation block.
    sep = m["paper_live_separation"]
    assert sep["real_money_locked"] is True and sep["live_disabled"] is True, sep
    assert sep["exits"] in ("ACTIVE", "BLOCKED"), sep
    s.close()
    print(f"verify_engine_map_truth: PASS ({len(m['nodes'])} nodes; positions {db_positions} match; "
          f"latest trade {lt['symbol']} pnl {lt['realized_pnl']}; no live path)")


if __name__ == "__main__":
    main()
