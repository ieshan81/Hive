"""Worker entry — sync Alpaca, run strategies, optional AI review."""

import logging
import time

from app.config import settings
from app.database import Session, engine, init_db
from app.services.ai_fund_manager import AIFundManager
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.config_manager import ConfigManager
from app.services.dashboard_service import build_dashboard
from app.services.strategy_engine import StrategyEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hive.worker")


def run_sync_cycle():
    init_db()
    with Session(engine) as session:
        adapter = AlpacaAdapter(session)
        if adapter.configured:
            adapter.sync_account()
            adapter.sync_positions()
            logger.info("Alpaca sync complete")
        else:
            logger.warning("Alpaca not configured — skipping sync")

        config = ConfigManager(session).get_current()
        engine_strat = StrategyEngine(session, config)
        for sym in ["NVDA", "AAPL"]:
            engine_strat.run_momentum_orb(sym)

        if settings.gemini_configured:
            dashboard = build_dashboard(session)
            ai = AIFundManager(session)
            review = ai.review("worker_cycle", {"cycle": "sync", "dashboard": dashboard})
            if review:
                logger.info("AI review: %s", review.decision)


if __name__ == "__main__":
    logger.info("Hive worker starting")
    while True:
        try:
            run_sync_cycle()
        except Exception as exc:
            logger.exception("Worker cycle failed: %s", exc)
        time.sleep(300)
