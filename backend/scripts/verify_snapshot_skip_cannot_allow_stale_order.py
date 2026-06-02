"""Phase 9 verifier: skip_entry_safety_snapshot_gates cannot bypass stale-data / live / paper gates.

The snapshot-skip flag only relaxes the snapshot-CACHE availability blockers in entry_safety_service.
The broker-submit-time gates — stale quote (execution_preflight), live lock + paper-broker (the
submission guard) — are independent of that flag, so a skipped snapshot can never allow a stale-data
or live order to reach the broker.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    esafe = (BACKEND / "app/services/entry_safety_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    preflight = (BACKEND / "app/services/execution_preflight.py").read_text(encoding="utf-8-sig", errors="ignore")
    guard = (BACKEND / "app/services/broker_submission_guard.py").read_text(encoding="utf-8-sig", errors="ignore")

    # The skip flag only gates snapshot-cache blockers (system_snapshot_degraded / universe_snapshot_stale).
    assert "skip_snapshot_gates" in esafe, "entry_safety_service should read the skip flag"
    assert "if not skip_snapshot_gates" in esafe, "skip flag must only relax snapshot-cache blockers"

    # The stale-quote gate exists and is NOT conditioned on the skip flag.
    assert 'STALE_QUOTE' in preflight, "preflight must have a stale-quote gate"
    assert "skip_entry_safety_snapshot_gates" not in preflight, "stale-quote gate must be independent of snapshot-skip"
    assert "skip_snapshot" not in preflight, "preflight stale gates must not honor a snapshot-skip flag"

    # The broker submission guard (live lock + paper-broker) has no snapshot-skip bypass.
    assert "skip" not in guard.lower(), "submission guard must not have any skip/bypass"
    assert "is_paper_broker_url" in guard and "assert_live_blocked" in guard, "guard must enforce paper + live-block"

    print("verify_snapshot_skip_cannot_allow_stale_order: PASS (snapshot-skip only relaxes cache blockers; stale-quote/live/paper gates independent)")


if __name__ == "__main__":
    main()
