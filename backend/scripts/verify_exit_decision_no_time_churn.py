"""Fee-negative max-hold extension is classified as hold, not forced churn exit."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.exit_decision_service import classify_exit_decision


def main() -> None:
    out = classify_exit_decision({"action": "hold", "reason": "MAX_HOLD_EXTENDED_FEE_NEGATIVE"})
    assert out["exit_decision"] == "no_exit_hold", out
    assert out["time_alone_forced_loss_exit"] is False, out
    print("verify_exit_decision_no_time_churn: PASS")
    print(out)


if __name__ == "__main__":
    main()
