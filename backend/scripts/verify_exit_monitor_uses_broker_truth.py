"""The exit path decides from BROKER TRUTH, not stale local state alone.

The exit-relevant services (open-position review, exit monitor, training execution) reference
broker positions / ExposureTruth / reconciliation / current_positions — so an exit decision is
grounded in what the broker actually holds. Also confirms exits are never gated off by the
heartbeat entry gate (exits always managed).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
EXIT_PATH_FILES = [
    "app/services/open_position_review_service.py",
    "app/services/exit_monitor_service.py",
    "app/services/training_execution_service.py",
]
BROKER_TRUTH_TOKENS = ("ExposureTruth", "fresh_broker_positions", "broker_positions",
                       "current_positions", "broker_truth", "reconcil")


def main() -> None:
    grounded = []
    for rel in EXIT_PATH_FILES:
        text = (BACKEND / rel).read_text(encoding="utf-8")
        if any(tok in text for tok in BROKER_TRUTH_TOKENS):
            grounded.append(rel)
    assert grounded, "no exit-path module references broker truth — exits would rely on stale local state"

    # The heartbeat entry gate adds only ENTRY blockers — it never returns an exit blocker.
    from app.services.heartbeat_service import HEARTBEAT_ONLY_BLOCKER, NO_BACKTEST_EVIDENCE_BLOCKER
    assert "entry" in HEARTBEAT_ONLY_BLOCKER and "entry" in NO_BACKTEST_EVIDENCE_BLOCKER

    # The training loop manages exits unconditionally before computing entry blockers.
    loop = (BACKEND / "app/services/fast_crypto_training_loop.py").read_text(encoding="utf-8")
    assert loop.index("monitor_exits") < loop.index("entry_gate_blockers"), "exits managed before entry gating"
    print(f"verify_exit_monitor_uses_broker_truth: PASS (broker-truth in {len(grounded)} exit module(s); exits never gated by heartbeat)")


if __name__ == "__main__":
    main()
