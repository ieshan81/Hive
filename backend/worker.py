"""Worker entry — runs strategy cycle on interval."""

import logging
import time

from app.config import settings
from app.database import Session, engine, init_db
from app.services.cycle_engine import CycleEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hive.worker")


def run_sync_cycle():
    init_db()
    with Session(engine) as session:
        result = CycleEngine(session).run()
        logger.info("Cycle result: %s", result.get("status"))


if __name__ == "__main__":
    logger.info("Hive worker starting — paper trading only")
    while True:
        try:
            run_sync_cycle()
        except Exception as exc:
            logger.exception("Worker cycle failed: %s", exc)
        time.sleep(300)
