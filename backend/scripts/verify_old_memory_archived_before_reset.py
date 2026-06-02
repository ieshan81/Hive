"""Memory reset archives noisy (unlinked) active lessons while PRESERVING every evidence-linked
lesson. Never hard-deletes. Idempotent."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, func, select  # noqa: E402

import app.database  # noqa: F401,E402
from app.database import LessonNode  # noqa: E402
from app.services.memory_governance_service import MemoryGovernanceService  # noqa: E402


def _mem() -> Session:
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return Session(eng, expire_on_commit=False)


def main() -> None:
    s = _mem()
    # Evidence-linked (preserve): scorecard-linked + outcome-linked + evidence_json trade_id.
    s.add(LessonNode(memory_type="validated_alpha_candidate", title="a", summary="s", detailed_lesson="d",
                     related_entity_type="alpha_scorecard", related_entity_id="42", status="active"))
    s.add(LessonNode(memory_type="paper_outcome_lesson", title="b", summary="s", detailed_lesson="d",
                     evidence_json={"trade_id": "BTCUSD|B1|S1"}, status="active"))
    # Noisy (archive): no evidence link.
    s.add(LessonNode(memory_type="ai_chatter", title="c", summary="s", detailed_lesson="d", status="active"))
    s.add(LessonNode(memory_type="status_noise", title="d", summary="s", detailed_lesson="d", evidence_json={}, status="active"))
    s.add(LessonNode(memory_type="hypothesis_idea", title="e", summary="s", detailed_lesson="d", status="active"))  # unlinked hypothesis = noise
    s.commit()

    gov = MemoryGovernanceService(s)

    # Dry-run first: reports without mutating.
    dry = gov.archive_noisy_active_memory(dry_run=True)
    assert dry["archived"] == 0 and dry["would_archive"] == 3, dry
    assert int(s.exec(select(func.count()).select_from(LessonNode).where(LessonNode.status == "active")).one()) == 5

    # Real archive.
    out = gov.archive_noisy_active_memory()
    s.commit()
    assert out["archived"] == 3, out
    assert out["evidence_linked_preserved"] == 2, out

    active = list(s.exec(select(LessonNode).where(LessonNode.status == "active")).all())
    archived = list(s.exec(select(LessonNode).where(LessonNode.status == "archived")).all())
    assert len(active) == 2, [l.memory_type for l in active]      # evidence-linked preserved
    assert len(archived) == 3, [l.memory_type for l in archived]  # noise archived (not deleted)
    # Nothing hard-deleted.
    assert int(s.exec(select(func.count()).select_from(LessonNode)).one()) == 5
    # Archived lessons can no longer influence ranking / AI.
    assert all((not a.can_influence_ranking) and (not a.visible_to_ai) for a in archived)
    # Evidence-linked survivors are intact.
    assert all(MemoryGovernanceService.is_evidence_linked(a) for a in active)

    # Idempotent: re-run archives nothing more.
    out2 = gov.archive_noisy_active_memory()
    s.commit()
    assert out2["archived"] == 0, out2
    s.close()
    print("verify_old_memory_archived_before_reset: PASS (3 noisy archived, 2 evidence-linked preserved, no deletes, idempotent)")


if __name__ == "__main__":
    main()
