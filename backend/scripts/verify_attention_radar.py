"""Verify attention radar broker truth."""

from __future__ import annotations

from app.database import engine, Session, init_db
from app.services.attention_radar_service import AttentionRadarService
from app.services.startup import bootstrap_database


def main() -> None:
    init_db()
    bootstrap_database()
    session = Session(engine)
    radar = AttentionRadarService(session).scan(limit=25)
    assert radar["status"] == "ok"
    for item in radar["items"]:
        assert "trade_status" in item
        assert "broker_supported" in item
        if not item["broker_supported"]:
            assert item["trade_status"] == "watch_only_not_broker_supported"
    print("OK attention radar:", radar["count"], "items")


if __name__ == "__main__":
    main()
