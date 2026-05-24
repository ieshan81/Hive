import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, engine, LessonNode
from sqlmodel import Session, select
from app.services.research_lab_service import ResearchLabService


def main():
    init_db()
    with Session(engine) as session:
        out = ResearchLabService(session).import_legacy_bundle({})
        session.commit()
        assert out["imported"] >= 6
        legacy = session.exec(
            select(LessonNode).where(LessonNode.source == "legacy_bot")
        ).all()
        assert all(r.status == "archived" for r in legacy)
        assert all(r.visible_to_ai is False for r in legacy)
        print("verify_legacy_ai_bundle_import_archived: OK", out["imported"])


if __name__ == "__main__":
    main()
