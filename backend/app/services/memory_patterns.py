"""Pattern aggregator — update pattern memories each cycle."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.database import AIReview, BlockedTrade, ExecutionLog, StrategySignal
from app.services.engine_config import cfg_get
from app.services.lesson_memory_service import LessonMemoryService
from app.services.memory_triggers import on_repeated_risk_block


def run_pattern_scan(session: Session, config: dict, cycle_run_id: str) -> list[int]:
    if not cfg_get(config, "memory.enabled", True):
        return []
    min_occ = int(cfg_get(config, "memory.min_occurrences_for_pattern", 3))
    window_hours = int(cfg_get(config, "memory.pattern_window_cycles", 20)) * 2
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    created: list[int] = []

    blocks = session.exec(
        select(BlockedTrade).where(BlockedTrade.created_at >= cutoff)
    ).all()
    by_sym_reason: Counter[tuple[str, str]] = Counter()
    for b in blocks:
        code = b.block_reason_code or "UNKNOWN"
        by_sym_reason[(b.symbol, code)] += 1
    for (sym, code), count in by_sym_reason.items():
        if count >= min_occ:
            row = on_repeated_risk_block(
                session,
                config,
                symbol=sym,
                block_reason_code=code,
                count=count,
                strategy_name=blocks[0].strategy if blocks else None,
                cycle_run_id=cycle_run_id,
            )
            created.append(row.id)

    deferred = session.exec(
        select(StrategySignal).where(
            StrategySignal.cycle_run_id == cycle_run_id,
            StrategySignal.status == "portfolio_deferred",
        )
    ).all()
    if len(deferred) >= 3:
        svc = LessonMemoryService(session, config)
        row = svc.upsert_lesson(
            memory_type="strategy_pattern",
            title="Portfolio gate deferring many entries",
            summary=f"{len(deferred)} signals deferred this cycle (often TOP_N_LIMIT)",
            detailed_lesson="Strategy may be generating more entries than Top-N allows; rank quality matters.",
            severity="LOW",
            source="deterministic",
            cycle_run_id=cycle_run_id,
            evidence={"deferred_count": len(deferred)},
            pattern_key="portfolio_deferred_spike",
            aggregate=True,
        )
        created.append(row.id)

    fails = session.exec(
        select(ExecutionLog).where(
            ExecutionLog.created_at >= cutoff,
            ExecutionLog.status.in_(["paper_order_rejected", "paper_order_cancelled", "paper_order_unfilled"]),
        )
    ).all()
    if len(fails) >= min_occ:
        svc = LessonMemoryService(session, config)
        row = svc.upsert_lesson(
            memory_type="execution_lesson",
            title="Repeated paper execution failures",
            summary=f"{len(fails)} unfilled/rejected orders in window",
            detailed_lesson="Review spread buffers, IOC limits, and symbol liquidity.",
            severity="MEDIUM",
            source="deterministic",
            cycle_run_id=cycle_run_id,
            evidence={"failure_count": len(fails)},
            pattern_key="paper_exec_failures",
            aggregate=True,
        )
        created.append(row.id)

    reviews = list(session.exec(select(AIReview).order_by(AIReview.created_at.desc()).limit(5)).all())
    skipped = sum(1 for _ in reviews if False)
    return created
