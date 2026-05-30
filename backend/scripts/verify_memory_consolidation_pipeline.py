"""Hive Mind consolidation: raw memories become learned memories + diagnostics.

Proves:
- consolidation diagnostics expose raw / candidate / consolidated / nudge / pattern /
  system_issue counts + last_consolidation_at + why_consolidation_skipped
- a cluster of raw memories consolidates into a learned (consolidated) memory once the
  (now-sane) thresholds are met, and the source raw rows are archived
- when below threshold, why_consolidation_skipped explains exactly why
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.database  # noqa: F401  (register models on SQLModel.metadata)
from app.database import LessonNode
from app.services.memory_consolidation_service import MemoryConsolidationService

DIAG_KEYS = (
    "raw_memory_count",
    "candidate_memory_count",
    "consolidated_memory_count",
    "nudge_count",
    "pattern_count",
    "system_issue_count",
    "last_consolidation_at",
    "why_consolidation_skipped",
)


def _mem_session() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng)


def _seed_raw(session: Session, n: int) -> None:
    for i in range(n):
        session.add(
            LessonNode(
                memory_type="paper_trade_outcome",  # not a PROTECTED type
                title=f"raw outcome {i}",
                summary=f"Paper outcome sample {i}",
                detailed_lesson="raw experience",
                strategy_name="crypto_push_pull",
                symbol="SOL/USD",
                pattern_key="loss_band|SOLUSD|cluster",  # identical -> one group
                memory_level="raw_experience",
                status="active",
            )
        )
    session.commit()


def test_diagnostics_counts_present() -> None:
    session = _mem_session()
    st = MemoryConsolidationService(session, {}).status()
    for k in DIAG_KEYS:
        assert k in st, (k, list(st.keys()))
    assert st["raw_memory_count"] == 0
    assert st["why_consolidation_skipped"], st  # nothing to consolidate -> reason present
    session.close()
    print("memory: diagnostics counts exposed (raw/candidate/consolidated/nudge/pattern/system) — PASS")


def test_raw_consolidates_into_learned() -> None:
    session = _mem_session()
    _seed_raw(session, 6)  # 6 in one strategy crosses per-strategy threshold; group >= same_type
    svc = MemoryConsolidationService(session, {})
    pre = svc.status()
    assert pre["raw_memory_count"] == 6 and pre["candidate_memory_count"] == 6, pre
    assert pre["should_consolidate"] is True, pre
    out = svc.run()
    session.commit()
    assert out["consolidated_created"] >= 1, out
    post = svc.status()
    assert post["consolidated_memory_count"] >= 1, post
    assert post["raw_memory_count"] < 6, post  # sources archived
    print(
        f"memory: 6 raw -> {out['consolidated_created']} learned memory(ies), "
        f"raw archived={out['raw_archived']} — PASS"
    )


def test_why_skipped_below_threshold() -> None:
    session = _mem_session()
    _seed_raw(session, 2)  # below thresholds
    st = MemoryConsolidationService(session, {}).status()
    assert st["should_consolidate"] is False, st
    assert "below consolidation thresholds" in (st["why_consolidation_skipped"] or ""), st
    session.close()
    print("memory: why_consolidation_skipped explains sub-threshold state — PASS")


if __name__ == "__main__":
    test_diagnostics_counts_present()
    test_raw_consolidates_into_learned()
    test_why_skipped_below_threshold()
    print("ALL PASS: verify_memory_consolidation_pipeline")
