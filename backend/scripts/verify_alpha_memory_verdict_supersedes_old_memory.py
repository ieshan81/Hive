"""Verdict changes must supersede prior alpha memories — no stale ranking influence."""

from __future__ import annotations

from sqlmodel import select

from _alpha_factory_verify_common import seed_scorecard, session_with_config

from app.database import LessonNode
from app.services.memory_evidence_consolidator_v2 import MemoryEvidenceConsolidatorV2


def main() -> None:
    session, cfg = session_with_config()
    sc = seed_scorecard(session, symbol="SOL/USD", strategy_id="crypto_push_pull_baseline", verdict="paper_candidate")
    consolidator = MemoryEvidenceConsolidatorV2(session, cfg)

    # Simulate legacy verdict-specific memory from older consolidator version.
    session.add(
        LessonNode(
            category="research_memory",
            memory_type="validated_alpha_candidate",
            title="Legacy positive alpha",
            summary="Stale positive memory",
            detailed_lesson="Legacy",
            pattern_key=f"alpha_v2|{sc.normalized_symbol}|{sc.strategy_id}|paper_candidate",
            related_entity_type="alpha_scorecard",
            related_entity_id=str(sc.id),
            visible_to_ai=True,
            can_influence_ranking=True,
            is_consolidated=True,
            memory_level="consolidated_lesson",
        )
    )
    session.commit()

    consolidator.consolidate_scorecards(limit=10)
    session.commit()

    stable_key = consolidator._stable_pattern_key(sc)
    active_after_first = list(
        session.exec(
            select(LessonNode).where(
                LessonNode.related_entity_type == "alpha_scorecard",
                LessonNode.related_entity_id == str(sc.id),
                LessonNode.status == "active",
            )
        ).all()
    )
    assert len(active_after_first) == 1, [(r.pattern_key, r.memory_type) for r in active_after_first]
    assert active_after_first[0].pattern_key == stable_key
    assert active_after_first[0].memory_type == "validated_alpha_candidate"
    assert active_after_first[0].can_influence_ranking is True

    sc.verdict = "rejected"
    sc.promotion_reason = "Rejected after walk-forward overfit."
    session.add(sc)
    session.commit()

    consolidator.consolidate_scorecards(limit=10)
    session.commit()

    active = list(
        session.exec(
            select(LessonNode).where(
                LessonNode.related_entity_type == "alpha_scorecard",
                LessonNode.related_entity_id == str(sc.id),
                LessonNode.status == "active",
            )
        ).all()
    )
    archived = list(
        session.exec(
            select(LessonNode).where(
                LessonNode.related_entity_type == "alpha_scorecard",
                LessonNode.related_entity_id == str(sc.id),
                LessonNode.status == "archived",
            )
        ).all()
    )
    assert len(active) == 1, [(r.status, r.pattern_key, r.memory_type) for r in active]
    canonical = active[0]
    assert canonical.pattern_key == stable_key
    assert canonical.memory_type == "rejected_alpha_candidate"
    assert canonical.can_influence_ranking is False
    assert not any(
        r.memory_type == "validated_alpha_candidate" and r.can_influence_ranking and r.status == "active"
        for r in active
    )
    assert archived, "expected legacy verdict memory archived"
    assert all(r.archive_reason == "verdict_superseded" for r in archived)
    assert all(r.can_influence_ranking is False for r in archived)
    assert all(r.visible_to_ai is False for r in archived)

    print("verify_alpha_memory_verdict_supersedes_old_memory: PASS")
    print({"active_type": canonical.memory_type, "archived_count": len(archived)})


if __name__ == "__main__":
    main()
