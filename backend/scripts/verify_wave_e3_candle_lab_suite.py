"""Wave E3 — Candle Lab."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import engine, init_db
from app.services.config_manager import ConfigManager
from app.services.technical_candle_analysis_service import TechnicalCandleAnalysisService


def main():
    init_db()
    with Session(engine) as session:
        cfg = ConfigManager(session).get_current()
        svc = TechnicalCandleAnalysisService(session, cfg)
        st = svc.status()
        assert st.get("no_fake_lines") is True
        assert "reason" in st.get("annotation_required_fields", [])
        out = svc.analyze("DOGE/USD", timeframe="5Min")
        assert out["status"] in ("ok", "empty")
        if out["status"] == "ok":
            for a in out.get("annotations", []):
                assert a.get("reason")
                assert a.get("timeframe")
                assert "confidence" in a
                assert a.get("invalidation_level") is not None
                assert a.get("source_bars")
    print("ALL_WAVE_E3_CHECKS_PASSED")


if __name__ == "__main__":
    main()
