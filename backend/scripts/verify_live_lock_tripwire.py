"""LIVE_TRADING_ARMED env makes tripwire unsafe."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.config_manager import ConfigManager
from app.services.live_lock_tripwire import assert_live_blocked, live_lock_tripwire_status
from sqlmodel import Session
from app.database import engine, init_db


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        os.environ["LIVE_TRADING_ARMED"] = "1"
        st = live_lock_tripwire_status(cfg)
        ok, code = assert_live_blocked(cfg)
        os.environ.pop("LIVE_TRADING_ARMED", None)
        assert st.get("LIVE_TRADING_ARMED") == 1
        assert ok is False
        assert code == "LIVE_TRADING_ARMED"
        st2 = live_lock_tripwire_status(cfg)
        assert st2.get("api_key_swap_unlocks_live") is False
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
