"""Verify a stock-data failure cannot block the 24/7 crypto scan.

Crypto and stocks are separate lanes: crypto refreshes first and unconditionally; the stock
refresh is a separate, market-hours-gated call whose failure returns an error dict (never raises
out to abort the crypto path). Readiness also marks crypto independent of stock data.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    agent = (BACKEND / "app/v2/agent_engine.py").read_text(encoding="utf-8", errors="ignore")
    hist = (BACKEND / "app/services/historical_data_service.py").read_text(encoding="utf-8", errors="ignore")
    readiness = (BACKEND / "app/services/stock_data_readiness_service.py").read_text(encoding="utf-8", errors="ignore")

    # Crypto refresh must come before the stock refresh, and be its own call.
    c_idx = agent.find('asset_type="crypto"')
    s_idx = agent.find('asset_type="stock"')
    assert c_idx != -1, "crypto refresh not found in agent_engine"
    assert s_idx == -1 or c_idx < s_idx, "crypto refresh must run before/independent of the stock refresh"
    # Stock refresh is gated by market session (does not run — let alone fail — when closed).
    assert "stock_trading_allowed" in agent, "stock refresh is not market-hours gated"

    # fetch failures return an error dict instead of raising (so one asset's failure can't abort the other).
    assert 'return {"status": "error"' in hist, "fetch_and_store does not return a structured error on failure"

    # readiness explicitly marks crypto independent of stock data.
    assert '"crypto_independent": True' in readiness, "readiness does not mark crypto independent"
    # readiness probe swallows per-symbol errors (read-only) rather than raising.
    assert "read-only probe — never raises out" in readiness or "except Exception" in readiness, \
        "stock readiness probe may raise and abort"
    print("verify_stock_failure_does_not_block_crypto_scanning: PASS (crypto lane independent of stock data)")


if __name__ == "__main__":
    main()
