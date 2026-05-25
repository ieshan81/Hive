"""Phase 21 diagnostic bundle — required E–G export keys."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REQUIRED = [
    "fast_training_exit_only_status.json",
    "fast_training_exit_decisions.json",
    "fast_training_exit_orders.json",
    "preflight_decisions.json",
    "meme_spike_v2_status.json",
    "candle_lab_status.json",
    "candle_lab_analysis.json",
    "strategy_import_status.json",
    "imported_strategies.json",
    "hive_brain_graph.json",
    "true_hold_time_audit.json",
    "live_lock_tripwire_status.json",
]


def main():
    from sqlmodel import Session

    from app.database import engine, init_db
    from app.services.diagnostic_export import export_diagnostic_bundle

    init_db()
    with Session(engine) as session:
        bundle = export_diagnostic_bundle(session)
        files = bundle.get("files") or bundle
    missing = [k for k in REQUIRED if k not in files]
    if missing:
        print(f"MISSING_KEYS: {missing}")
        sys.exit(1)
    print("ALL_PHASE21_BUNDLE_KEYS_PRESENT")


if __name__ == "__main__":
    main()
