"""Verify Alpaca paper env + a read-only connection through the SAME client Hive uses.

Asserts (always): API key + secret present, broker base URL is PAPER, live trading disabled.
Then (when keys are configured) calls the read-only account/positions/orders via the alpaca-py
TradingClient(paper=True) and asserts the account is reachable + paper + not auth-blocked.

NEVER prints keys/secrets. Read-only — never submits an order. On a network-unavailable
environment it soft-skips the live call (so CI without egress still passes the env assertions);
a real 401/403 is a HARD failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402


def _classify(exc) -> str:
    msg = str(exc).lower()
    code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if "401" in msg or code == 401 or "unauthorized" in msg:
        return "AUTH_401_INVALID_KEY_OR_SECRET"
    if "403" in msg or code == 403 or "forbidden" in msg:
        return "AUTH_403_PERMISSION_OR_ACCOUNT"
    if "timeout" in msg or "timed out" in msg or "getaddrinfo" in msg or "name or service" in msg or "connection" in msg:
        return "NETWORK_UNAVAILABLE"
    return "UNKNOWN"


def main() -> None:
    # --- env assertions (always) ---
    api = settings.alpaca_api_key or ""
    sec = settings.alpaca_secret_key or ""
    base = (getattr(settings, "alpaca_base_url", "") or "").lower()

    assert api and sec, "ALPACA_API_KEY / ALPACA_SECRET_KEY missing or empty"
    assert '"' not in api and "'" not in api and '"' not in sec, "key/secret contains a quote char (bad .env quoting)"
    assert "paper-api.alpaca.markets" in base, f"broker base URL is not PAPER: {base!r}"

    from app.services.broker_safety import is_paper_broker_url
    assert is_paper_broker_url() is True, "is_paper_broker_url() is False — broker not in paper mode"

    live = bool(getattr(settings, "live_orders_enabled", False)) or bool(getattr(settings, "live_trading_enabled", False))
    assert not live, "live trading is enabled at the settings layer — must be disabled"

    if not getattr(settings, "alpaca_configured", False):
        print("verify_alpaca_paper_env_and_connection: PASS (env asserts ok; keys not configured here — connection skipped)")
        return

    # --- read-only connection (no orders) ---
    try:
        from alpaca.trading.client import TradingClient

        c = TradingClient(settings.alpaca_api_key, settings.alpaca_secret_key, paper=True)
        acct = c.get_account()
        status = str(getattr(acct, "status", ""))
        c.get_all_positions()
        c.get_orders()
        assert "ACTIVE" in status.upper(), f"account status not ACTIVE: {status}"
        assert getattr(acct, "trading_blocked", False) is False, "account trading_blocked"
        # equity/buying_power are account financials (not secrets) — safe to surface.
        print(f"verify_alpaca_paper_env_and_connection: PASS (paper account ACTIVE, equity={acct.equity}, "
              f"buying_power={acct.buying_power}; read-only account/positions/orders reachable)")
    except Exception as exc:
        cls = _classify(exc)
        if cls == "NETWORK_UNAVAILABLE":
            print("verify_alpaca_paper_env_and_connection: PASS (env asserts ok; live call skipped — NETWORK_UNAVAILABLE)")
            return
        raise AssertionError(f"Alpaca read-only connection FAILED: {cls} (no secrets shown)") from exc


if __name__ == "__main__":
    main()
