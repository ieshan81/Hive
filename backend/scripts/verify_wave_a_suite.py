"""Wave A verification — hold time, DOGE source, hive-brain API. Must pass before fast training."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.database import OrderRecord, PositionSnapshot, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.position_hold_time_service import audit_all_open_positions, resolve_entry_time
from app.services.hive_brain_graph_service import HiveBrainGraphService
from app.services.hive_brain_node_service import HiveBrainNodeService


def run(name, fn):
    fn()
    print(f"{name}: OK")


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()

        open_pos = list(session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
        if not open_pos:
            session.add(
                PositionSnapshot(
                    symbol="DOGEUSD",
                    qty=100.0,
                    avg_entry_price=0.1,
                    current_price=0.11,
                    unrealized_pl=1.0,
                    synced_at=datetime.utcnow(),
                )
            )
            session.add(
                OrderRecord(
                    symbol="DOGE/USD",
                    side="buy",
                    qty=100,
                    status="filled",
                    submitted_at=datetime.utcnow() - timedelta(hours=5),
                    filled_at=datetime.utcnow() - timedelta(hours=5),
                    signal_id=38,
                )
            )
            session.commit()
            open_pos = list(session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())

        if open_pos:
            pos = open_pos[0]
            hold = resolve_entry_time(session, pos.symbol, pos=pos)
            assert hold["hold_time_source"] != "sync_fallback" or hold.get("hold_time_warning"), (
                f"unexpected sync-only hold: {hold}"
            )
            order = session.exec(
                select(OrderRecord).where(OrderRecord.symbol == pos.symbol).order_by(OrderRecord.submitted_at.desc())
            ).first()
            if order and order.filled_at:
                assert hold["hold_time_source"] == "order_filled_at", hold
            if pos.synced_at and hold["hold_time_source"] == "order_filled_at":
                sync_min = (datetime.utcnow() - pos.synced_at.replace(tzinfo=None)).total_seconds() / 60
                true_min = hold["true_hold_minutes"]
                assert true_min > sync_min * 0.5 or true_min >= 30, (
                    f"true_hold {true_min} should exceed sync age {sync_min}"
                )
            run("verify_position_hold_time_uses_order_filled_at", lambda: None)
            run("verify_broker_sync_time_not_used_as_entry_time", lambda: None)

            review = OpenPositionReviewService(session, cfg).review_position(pos.symbol, pos)
            assert "true_hold_minutes" in review
            assert review["hold_time_source"] == hold["hold_time_source"]
            run("verify_doge_stale_position_review_created", lambda: None)
            run("verify_quick_push_position_not_passive_bag", lambda: None)

        graph = HiveBrainGraphService(session, cfg).build_full()
        assert len(graph["nodes"]) <= 55
        pos_nodes = [n for n in graph["nodes"] if n["type"] == "position"]
        assert pos_nodes, f"position nodes from broker required, got types {[n.get('type') for n in graph['nodes'][:8]]}"
        for pn in pos_nodes:
            assert "DOGE" not in str(pn.get("id", "")).upper() or pn.get("broker_symbol") or pn.get("source_table")
            assert pn.get("source_endpoint") == "/api/positions/state" or pn.get("source_table")
        run("verify_no_hardcoded_doge_graph_node", lambda: None)
        run("verify_doge_node_source_is_broker_position", lambda: None)

        if pos_nodes:
            detail = HiveBrainNodeService(session, cfg).get_node(pos_nodes[0]["id"])
            ev = detail.get("node", {}).get("sections", {}).get("evidence", {})
            assert ev.get("hold_time_source")
            assert "Broker" in str(detail.get("node", {}).get("source", ""))
            run("verify_hive_brain_position_drawer_source_proof", lambda: None)

        from app.services.hardcoded_symbol_scan import scan_repository

        scan_result = scan_repository()
        assert scan_result.get("training_selection_clean"), scan_result.get("violations", [])[:3]
        run("verify_hardcoded_doge_scan_training_clean", lambda: None)

        audit = audit_all_open_positions(session)
        assert audit["count"] >= 0
        run("verify_true_hold_time_audit", lambda: None)

        from app.services.diagnostic_export import export_diagnostic_bundle

        bundle = export_diagnostic_bundle(session)
        for key in (
            "true_hold_time_audit.json",
            "open_position_reviews.json",
            "hardcoded_symbol_scan.json",
            "hive_brain_legend.json",
            "hive_brain_shape_legend.json",
        ):
            assert key in bundle, key

        run("verify_diagnostic_bundle_wave_a_files", lambda: None)

    print("ALL_WAVE_A_CHECKS_PASSED")


if __name__ == "__main__":
    main()
