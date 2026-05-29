"""Phase 21 diagnostic bundle key registry check.

The synchronous bundle build is intentionally heavy. This verifier checks that
the required export keys remain registered in diagnostic_export.py; durable async
job behavior is covered by the diagnostic export job/status verifiers.
"""

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


def main() -> None:
    export_source = Path(__file__).resolve().parents[1] / "app" / "services" / "diagnostic_export.py"
    text = export_source.read_text(encoding="utf-8")
    missing = [key for key in REQUIRED if key not in text]
    if missing:
        print(f"MISSING_KEYS: {missing}")
        sys.exit(1)
    print("ALL_PHASE21_BUNDLE_KEYS_PRESENT")


if __name__ == "__main__":
    main()
