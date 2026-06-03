"""Worker entry — optional paper scheduler loop or legacy cycle engine."""

import logging
import os
import time

from app.database import Session, engine, init_db
from app.services.config_manager import ConfigManager
from app.services.cycle_engine import CycleEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hive.worker")


def run_sync_cycle():
    init_db()
    with Session(engine) as session:
        result = CycleEngine(session).run()
        logger.info("Cycle result: %s", result.get("status"))


def run_paper_scheduler_tick():
    init_db()
    with Session(engine) as session:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        cfg = ConfigManager(session).get_current()
        interval = max(60, int((cfg.get("autonomous_paper_learning") or {}).get("scheduler_interval_seconds", 600)))
        sched = AutonomousPaperScheduler(session, cfg)
        st = sched.status()
        if not st.get("scheduler_enabled"):
            logger.info("Paper scheduler worker: scheduler disabled — sleeping")
            return interval
        if st.get("paused"):
            logger.info("Paper scheduler worker: paused (%s)", st.get("paused_reason"))
            return interval
        if st.get("tick_in_progress"):
            logger.info("Paper scheduler worker: tick already in progress — skip")
            return max(60, interval // 2)
        out = sched.tick(operator="worker")
        logger.info("Paper scheduler tick: %s", out.get("status", out.get("reason")))
        return interval


if __name__ == "__main__":
    import sys

    if os.environ.get("HIVE_PAPER_SCHEDULER_WORKER") == "1":
        logger.info("Hive paper scheduler worker — local/dev only (not Railway web)")
        while True:
            try:
                sleep_s = run_paper_scheduler_tick()
            except Exception as exc:
                logger.exception("Paper scheduler tick failed: %s", exc)
                sleep_s = 300
            time.sleep(max(60, sleep_s))
        sys.exit(0)

    if os.environ.get("HIVE_WORKER_EXPLICIT_ENABLE") != "1":
        logger.error(
            "Worker refused — set HIVE_WORKER_EXPLICIT_ENABLE=1 (legacy cycle) "
            "or HIVE_PAPER_SCHEDULER_WORKER=1 (paper scheduler loop)"
        )
        sys.exit(1)
    logger.info("Hive worker starting — legacy CycleEngine (explicit enable)")
    while True:
        try:
            run_sync_cycle()
        except Exception as exc:
            logger.exception("Worker cycle failed: %s", exc)
        time.sleep(300)
