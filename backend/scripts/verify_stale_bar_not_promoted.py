"""Paper exploration must not promote stale-bar candidates."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.push_pull_scoring_service import _paper_probe_eligible, _promote_paper_row


def main() -> None:
    row = {
        "symbol": "UNI/USD",
        "entry_allowed": False,
        "no_trade_reason": "STALE_BAR",
        "bar_freshness": "stale",
        "quote_freshness": "fresh",
        "gate_results": {"bar_fresh": False, "quote_fresh": True, "spread_ok": True},
        "bars_count": 180,
        "dynamic_exit_levels": {
            "stop_loss": 9.5,
            "take_profit": 10.5,
            "trailing_stop": 9.7,
            "invalidation_price": 9.3,
        },
    }
    assert _paper_probe_eligible(row, {"exploration": {"enabled": True}, "universe": {"trade_all_eligible": True}}) is False
    promoted = _promote_paper_row(row) if _paper_probe_eligible(row, {}) else row
    assert promoted.get("entry_allowed") is False, promoted
    assert promoted.get("paper_exploration_probe") is not True, promoted
    print("verify_stale_bar_not_promoted: PASS")
    print({"entry_allowed": promoted.get("entry_allowed"), "no_trade_reason": promoted.get("no_trade_reason")})


if __name__ == "__main__":
    main()
