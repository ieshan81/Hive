"""Training entries remain disabled without operator enable."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.config_manager import ConfigManager
from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop


def main():
    init_db()
    with Session(engine) as session:
        st = FastCryptoTrainingLoop(session, ConfigManager(session).get_current()).status()
        assert st.get("can_submit_orders") is False
        assert "training_mode_disabled" in (st.get("blockers") or [])
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
