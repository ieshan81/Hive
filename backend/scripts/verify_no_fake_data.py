"""Ensure dashboard does not inject fake demo trading records."""

from __future__ import annotations

from app.database import engine, Session, init_db
from app.services.dashboard_service import build_dashboard
from app.services.startup import bootstrap_database


def main() -> None:
    init_db()
    bootstrap_database()
    session = Session(engine)
    dash = build_dashboard(session)
    assert dash["systemStatus"]["paperTradingOnly"] is True
    assert dash["systemStatus"]["liveTradingEnabled"] is False
    mc = dash.get("monteCarlo", {})
    if mc.get("status") == "ok":
        assert mc.get("warning") is None or "simulation" in str(mc.get("warning", "")).lower()
    print("OK no fake data flags:", dash["systemStatus"])


if __name__ == "__main__":
    main()
