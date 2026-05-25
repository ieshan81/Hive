"""Wave E2 — meme spike v2."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.config_manager import ConfigManager
from app.services.meme_volatility_spike_detector import MemeVolatilitySpikeDetector


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        st = MemeVolatilitySpikeDetector(session, cfg).status()
        assert st.get("detector_version") == "v2"
        assert "15Min" in st.get("timeframes", [])
        ev = MemeVolatilitySpikeDetector(session, cfg).evaluate_symbol("DOGE/USD")
        assert "detector_version" in ev
        assert "timeframes_used" in ev
        assert ev["metrics"]["price_change_15m"] is not None or ev["metrics"]["price_change_5m"] is not None
    print("ALL_WAVE_E2_CHECKS_PASSED")


if __name__ == "__main__":
    main()
