"""Verify push-pull scoring service exports."""

from __future__ import annotations

from app.database import init_db
from app.services.config_manager import ConfigManager
from app.services.push_pull_scoring_service import SCORING_MODEL, score_active_universe
from app.services.strategy_status_service import strategy_status


def main() -> None:
    init_db()
    from sqlmodel import Session
    from app.database import engine

    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        scored = score_active_universe(session, cfg, limit=3)
        assert scored["scoring_model"] == SCORING_MODEL
        assert "scores" in scored
        st = strategy_status(session, cfg)
        assert st.get("scoring_on_live_path") is True
        assert st.get("live_scoring_model") == "score_push_pull_setup"
    print("OK push_pull_scoring_service")


if __name__ == "__main__":
    main()
