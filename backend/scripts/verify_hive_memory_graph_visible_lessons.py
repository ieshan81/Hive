"""Hive Mind surfaces visible learned memories (no more 'fresh brain').

Proves:
- the new visible categories (spread_widened_pattern, fee_negative_churn, weak_entry_pattern,
  backtest_research_lesson, exit_loop_risk) classify into surfaced categories
- a stale persisted policy (100/25/10) no longer starves consolidation — effective
  thresholds are clamped, so modest raw volume still produces visible learned memories
- diagnostics expose learned_memory_count + latest_visible_memory_titles
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401
from app.database import LessonNode, MemoryPolicyConfig
from app.services.memory_categories import (
    CATEGORY_SYSTEM,
    GRAPH_INTELLIGENCE_CATEGORIES,
    classify_memory_type,
)
from app.services.memory_consolidation_service import MemoryConsolidationService


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _seed(session: Session, n: int, mtype: str = "spread_widened_pattern") -> None:
    for i in range(n):
        session.add(
            LessonNode(
                memory_type=mtype,
                title=f"{mtype} {i}",
                summary="repeated spread block on SOL/USD",
                detailed_lesson="x",
                strategy_name="crypto_push_pull",
                symbol="SOL/USD",
                pattern_key="spread|SOLUSD|cluster",
                memory_level="raw_experience",
                status="active",
            )
        )
    session.commit()


def test_new_categories_visible() -> None:
    for mt in ("spread_widened_pattern", "fee_negative_churn", "weak_entry_pattern", "symbol_cooldown_lesson", "backtest_research_lesson"):
        assert classify_memory_type(mt) in GRAPH_INTELLIGENCE_CATEGORIES, (mt, classify_memory_type(mt))
    assert classify_memory_type("exit_loop_risk") == CATEGORY_SYSTEM
    print("memory: new visible categories classify into surfaced categories — PASS")


def test_stale_policy_still_consolidates() -> None:
    session = _mem()
    # Simulate the stale prod policy row that was starving consolidation (10k raw / 0 learned).
    session.add(
        MemoryPolicyConfig(
            id=1,
            policy_json={
                "consolidation_threshold_total_raw_memories": 100,
                "consolidation_threshold_per_strategy": 25,
                "consolidation_threshold_same_type": 10,
            },
        )
    )
    session.commit()
    _seed(session, 6)  # 6 < old 25/strategy, but >= clamped effective 6
    svc = MemoryConsolidationService(session, {})
    st = svc.status()
    assert st["should_consolidate"] is True, st  # clamp defeats the stale policy
    out = svc.run()
    session.commit()
    assert out["consolidated_created"] >= 1, out
    post = svc.status()
    assert post["learned_memory_count"] >= 1, post
    assert post["latest_visible_memory_titles"], post
    session.close()
    print(f"memory: stale 100/25/10 clamped -> 6 raw -> {out['consolidated_created']} visible learned — PASS")


def test_diagnostics_shape() -> None:
    session = _mem()
    st = MemoryConsolidationService(session, {}).status()
    for k in (
        "raw_memory_count",
        "learned_memory_count",
        "nudge_count",
        "pattern_count",
        "system_issue_count",
        "last_consolidation_at",
        "why_consolidation_skipped",
        "latest_visible_memory_titles",
    ):
        assert k in st, (k, list(st.keys()))
    session.close()
    print("memory: diagnostics expose learned_memory_count + latest_visible_memory_titles — PASS")


if __name__ == "__main__":
    test_new_categories_visible()
    test_stale_policy_still_consolidates()
    test_diagnostics_shape()
    print("ALL PASS: verify_hive_memory_graph_visible_lessons")
