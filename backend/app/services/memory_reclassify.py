"""One-time / idempotent reclassification of legacy lesson rows."""

from __future__ import annotations

from sqlmodel import Session, select

from app.database import LessonNode
from app.services.memory_categories import (
    CATEGORY_SYSTEM,
    classify_memory_type,
    default_visibility,
    normalize_memory_type,
)


def reclassify_existing_lessons(session: Session) -> int:
    rows = list(session.exec(select(LessonNode)).all())
    updated = 0
    for row in rows:
        new_type = normalize_memory_type(row.memory_type)
        cat = classify_memory_type(new_type)
        changed = False
        if row.memory_type != new_type:
            row.memory_type = new_type
            changed = True
        if not getattr(row, "category", None) or row.category == "trading_memory" and cat == CATEGORY_SYSTEM:
            row.category = cat
            changed = True
        elif not row.category:
            row.category = cat
            changed = True

        # Force system bugs off AI/ranking
        if cat == CATEGORY_SYSTEM:
            vis = default_visibility(cat, new_type, row.severity)
            if row.visible_to_ai is not False:
                row.visible_to_ai = vis["visible_to_ai"]
                changed = True
            if row.can_influence_ranking is not False:
                row.can_influence_ranking = vis["can_influence_ranking"]
                changed = True

        if changed:
            session.add(row)
            updated += 1
    return updated
