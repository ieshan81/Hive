"""Phase 6 verifier: no production direct broker-submit bypass.

Production code must route orders through PaperExecutionService (the caged wrapper). Asserts the
adapter's submit_* methods and the raw client.submit_order are not called from any other production
module.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
sys.path.insert(0, str(BACKEND))

# Files allowed to reference the broker submit methods:
#  - alpaca_adapter.py defines them + calls the raw client
#  - paper_execution_service.py is the single approved caged wrapper
APPROVED = {"alpaca_adapter.py", "paper_execution_service.py"}
SUBMIT_PATTERNS = (".submit_paper_order(", ".submit_marketable_limit_ioc(", ".submit_crypto_market_notional(")


def main() -> None:
    violations: list[str] = []
    raw_client_calls: list[str] = []
    for py in APP.rglob("*.py"):
        text = py.read_text(encoding="utf-8-sig", errors="ignore")
        if py.name not in APPROVED:
            for pat in SUBMIT_PATTERNS:
                if pat in text:
                    violations.append(f"{py.relative_to(APP)} calls {pat}")
        # raw client.submit_order is only allowed inside the adapter
        if "client.submit_order(" in text and py.name != "alpaca_adapter.py":
            raw_client_calls.append(str(py.relative_to(APP)))

    assert not violations, "Direct broker submit bypass found (must go through PaperExecutionService):\n  " + "\n  ".join(violations)
    assert not raw_client_calls, "Raw client.submit_order outside the adapter:\n  " + "\n  ".join(raw_client_calls)
    print("verify_no_direct_broker_submit_bypass: PASS (submit_* only in adapter + PaperExecutionService; raw submit only in adapter)")


if __name__ == "__main__":
    main()
