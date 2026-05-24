"""Evidence-based Hive memory — lessons, graph, patterns."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, MemoryEdge, MemoryEvidence
from app.services.engine_config import cfg_get
from app.services.memory_categories import (
    CATEGORY_SYSTEM,
    CATEGORY_TRADING,
    CATEGORY_COLORS,
    GRAPH_FILTER_CATEGORIES,
    classify_memory_type,
    default_visibility,
    drawer_title,
    normalize_memory_type,
    node_badge,
    system_impact,
    trading_impact,
)


SEVERITY_COLORS = {
    "LOW": "#64748b",
    "MEDIUM": "#3b82f6",
    "HIGH": "#f97316",
    "CRITICAL": "#ef4444",
}


class LessonMemoryService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.enabled = bool(cfg_get(config, "memory.enabled", True))

    def _pattern_key(self, memory_type: str, symbol: Optional[str], extra: str = "") -> str:
        base = f"{memory_type}|{symbol or ''}|{extra}"
        return hashlib.sha256(base.encode()).hexdigest()[:24]

    def upsert_lesson(
        self,
        *,
        memory_type: str,
        title: str,
        summary: str,
        detailed_lesson: str,
        category: Optional[str] = None,
        severity: str = "MEDIUM",
        confidence: float = 0.9,
        source: str = "deterministic",
        cycle_run_id: Optional[str] = None,
        signal_id: Optional[int] = None,
        order_id: Optional[int] = None,
        broker_order_id: Optional[str] = None,
        symbol: Optional[str] = None,
        strategy_name: Optional[str] = None,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[str] = None,
        evidence: Optional[dict] = None,
        proposed_action: Optional[str] = None,
        action_status: str = "none",
        pattern_key: Optional[str] = None,
        tags: Optional[list[str]] = None,
        aggregate: bool = False,
        unsupported_claim: bool = False,
        visible_in_graph: Optional[bool] = None,
        visible_to_ai: Optional[bool] = None,
        can_influence_ranking: Optional[bool] = None,
    ) -> LessonNode:
        if not self.enabled:
            raise RuntimeError("memory disabled")

        memory_type = normalize_memory_type(memory_type)
        cat = category or classify_memory_type(memory_type)
        vis = default_visibility(cat, memory_type, severity)

        pk = pattern_key or self._pattern_key(memory_type, symbol, extra=related_entity_id or "")
        existing: Optional[LessonNode] = None
        if aggregate:
            existing = self.session.exec(
                select(LessonNode).where(LessonNode.pattern_key == pk)
            ).first()

        now = datetime.utcnow()
        if existing:
            existing.memory_type = memory_type
            existing.category = cat
            vis = default_visibility(cat, memory_type, severity)
            existing.visible_to_ai = visible_to_ai if visible_to_ai is not None else vis["visible_to_ai"]
            existing.can_influence_ranking = (
                can_influence_ranking if can_influence_ranking is not None else vis["can_influence_ranking"]
            )
            existing.occurrence_count += 1
            existing.last_seen_at = now
            existing.updated_at = now
            existing.cycle_run_id = cycle_run_id or existing.cycle_run_id
            if evidence:
                ev = dict(existing.evidence_json or {})
                ev.update(evidence)
                ev["occurrence_count"] = existing.occurrence_count
                existing.evidence_json = ev
            self.session.add(existing)
            self._ensure_edges(existing)
            return existing

        lesson = LessonNode(
            category=cat,
            memory_type=memory_type,
            title=title,
            summary=summary,
            detailed_lesson=detailed_lesson,
            severity=severity,
            confidence=confidence,
            source=source,
            cycle_run_id=cycle_run_id,
            signal_id=signal_id,
            order_id=order_id,
            broker_order_id=broker_order_id,
            symbol=symbol,
            strategy_name=strategy_name,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            evidence_json=evidence or {},
            proposed_action=proposed_action,
            action_status=action_status,
            status="active",
            visible_in_graph=visible_in_graph if visible_in_graph is not None else vis["visible_in_graph"],
            visible_to_ai=visible_to_ai if visible_to_ai is not None else vis["visible_to_ai"],
            can_influence_ranking=can_influence_ranking
            if can_influence_ranking is not None
            else vis["can_influence_ranking"],
            human_review_status="pending",
            pattern_key=pk,
            occurrence_count=1,
            first_seen_at=now,
            last_seen_at=now,
            tags=tags or [],
            unsupported_claim=unsupported_claim,
            created_at=now,
            updated_at=now,
        )
        self.session.add(lesson)
        self.session.flush()
        if evidence:
            self.session.add(
                MemoryEvidence(
                    lesson_id=lesson.id,
                    evidence_type=memory_type,
                    payload=evidence,
                )
            )
        self._ensure_edges(lesson)
        return lesson

    def _ensure_edges(self, lesson: LessonNode) -> None:
        if lesson.status in ("deleted",) or not lesson.visible_in_graph:
            return
        hive_id = "hive"
        lesson_nid = f"lesson-{lesson.id}"
        self._add_edge(hive_id, lesson_nid, "learned_from", lesson.id)
        if lesson.symbol:
            sym_id = f"symbol-{lesson.symbol.replace('/', '')}"
            self._add_edge(lesson_nid, sym_id, "related_symbol", lesson.id)
            self._add_edge(sym_id, lesson_nid, "learned_from", lesson.id)
        if lesson.strategy_name:
            st_id = f"strategy-{lesson.strategy_name}"
            self._add_edge(lesson_nid, st_id, "traded_by", lesson.id)
        if lesson.broker_order_id:
            oid = f"order-{lesson.broker_order_id}"
            self._add_edge(lesson_nid, oid, "learned_from", lesson.id)
        if lesson.memory_type in ("fee_lesson", "broker_behavior"):
            self._add_edge(lesson_nid, "broker-alpaca", "broker_behavior", lesson.id)
        if lesson.category == CATEGORY_SYSTEM:
            self._add_edge(lesson_nid, "system-issues", "related_bug", lesson.id)

    def _add_edge(self, source: str, target: str, relation: str, lesson_id: int) -> None:
        exists = self.session.exec(
            select(MemoryEdge).where(
                MemoryEdge.source_id == source,
                MemoryEdge.target_id == target,
                MemoryEdge.relation == relation,
            )
        ).first()
        if exists:
            exists.evidence_count += 1
            self.session.add(exists)
            return
        self.session.add(
            MemoryEdge(
                source_id=source,
                target_id=target,
                relation=relation,
                weight=1.0,
                evidence_count=1,
                lesson_id=lesson_id,
            )
        )

    def propose_ai_lesson(
        self,
        *,
        title: str,
        summary: str,
        detailed_lesson: str,
        evidence_refs: list[dict],
        cycle_run_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> LessonNode:
        if not evidence_refs:
            return self.upsert_lesson(
                memory_type="ai_review_issue",
                title=title,
                summary=summary,
                detailed_lesson=detailed_lesson,
                severity="LOW",
                confidence=0.2,
                source="ai_review",
                cycle_run_id=cycle_run_id,
                symbol=symbol,
                evidence={"refs": evidence_refs, "unsupported": True},
                action_status="rejected",
                unsupported_claim=True,
                visible_to_ai=False,
            )
        return self.upsert_lesson(
            memory_type="ai_review_issue",
            title=title,
            summary=summary,
            detailed_lesson=detailed_lesson,
            severity="MEDIUM",
            confidence=0.6,
            source="ai_review",
            cycle_run_id=cycle_run_id,
            symbol=symbol,
            evidence={"refs": evidence_refs},
            action_status="pending_human_review",
        )

    def _filter_rows(
        self,
        rows: list[LessonNode],
        *,
        category: Optional[str] = None,
        memory_type: Optional[str] = None,
        symbol: Optional[str] = None,
        severity: Optional[str] = None,
        cycle_run_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        action_status: Optional[str] = None,
        include_archived: bool = False,
        graph_default: bool = False,
    ) -> list[LessonNode]:
        out = []
        for r in rows:
            if not include_archived and r.status in ("archived", "deleted"):
                continue
            if graph_default:
                if not r.visible_in_graph:
                    continue
                if r.category == CATEGORY_SYSTEM:
                    continue
                if r.category not in (CATEGORY_TRADING,):
                    continue
            if category and r.category != category:
                continue
            if memory_type and r.memory_type != memory_type:
                continue
            if symbol and r.symbol != symbol:
                continue
            if severity and r.severity != severity:
                continue
            if cycle_run_id and r.cycle_run_id != cycle_run_id:
                continue
            if strategy_name and r.strategy_name != strategy_name:
                continue
            if action_status and r.action_status != action_status:
                continue
            out.append(r)
        return out

    def get_lesson(self, node_id: str) -> Optional[dict[str, Any]]:
        if node_id.startswith("lesson-"):
            lid = int(node_id.replace("lesson-", ""))
            row = self.session.get(LessonNode, lid)
            if row:
                return self._lesson_detail(row)
        return None

    def _lesson_detail(self, row: LessonNode) -> dict[str, Any]:
        evidence_rows = self.session.exec(
            select(MemoryEvidence).where(MemoryEvidence.lesson_id == row.id)
        ).all()
        edges = self.session.exec(
            select(MemoryEdge).where(
                (MemoryEdge.source_id == f"lesson-{row.id}")
                | (MemoryEdge.target_id == f"lesson-{row.id}")
            )
        ).all()
        linked = []
        for e in edges:
            other = e.target_id if e.source_id == f"lesson-{row.id}" else e.source_id
            linked.append({"node_id": other, "relation": e.relation})

        return {
            "node_id": f"lesson-{row.id}",
            "lesson_id": row.id,
            "type": "lesson",
            "category": row.category,
            "memory_type": row.memory_type,
            "drawer_title": drawer_title(row.category),
            "title": row.title,
            "summary": row.summary,
            "detailed_lesson": row.detailed_lesson,
            "what_happened": row.summary,
            "why_it_matters": row.detailed_lesson,
            "bot_learned": row.detailed_lesson if row.category == CATEGORY_TRADING else None,
            "trading_impact": trading_impact(row.category),
            "system_impact": system_impact(row.category),
            "severity": row.severity,
            "confidence": row.confidence,
            "source": row.source,
            "action_status": row.action_status,
            "status": row.status,
            "human_review_status": row.human_review_status,
            "visible_to_ai": row.visible_to_ai,
            "visible_in_graph": row.visible_in_graph,
            "can_influence_ranking": row.can_influence_ranking,
            "proposed_action": row.proposed_action,
            "proposed_prevention": row.proposed_action,
            "symbol": row.symbol,
            "strategy_name": row.strategy_name,
            "cycle_run_id": row.cycle_run_id,
            "signal_id": row.signal_id,
            "broker_order_id": row.broker_order_id,
            "order_id": row.order_id,
            "occurrence_count": row.occurrence_count,
            "badge": node_badge(row),
            "evidence_human": self._human_evidence(row.evidence_json or {}),
            "evidence_json": row.evidence_json,
            "evidence_attachments": [
                {"type": r.evidence_type, "payload": r.payload} for r in evidence_rows
            ],
            "linked_nodes": linked,
            "tags": row.tags or [],
            "archive_reason": row.archive_reason,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
            "last_seen_at": row.last_seen_at.isoformat() + "Z" if row.last_seen_at else None,
        }

    def _human_evidence(self, ev: dict) -> list[dict[str, str]]:
        out = []
        skip = {"refs", "unsupported"}
        for k, v in ev.items():
            if k in skip or v is None:
                continue
            out.append({"label": k.replace("_", " ").title(), "value": str(v)})
        return out

    def build_graph(
        self,
        limit: int = 80,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        include_archived: bool = False,
        graph_default: bool = True,
    ) -> dict[str, Any]:
        all_rows = list(
            self.session.exec(
                select(LessonNode).order_by(LessonNode.last_seen_at.desc()).limit(limit * 3)
            ).all()
        )
        lessons = self._filter_rows(
            all_rows,
            category=category,
            severity=severity,
            include_archived=include_archived,
            graph_default=graph_default and not category and not include_archived,
        )[:limit]

        nodes: list[dict] = [
            {
                "id": "hive",
                "label": "HIVE",
                "type": "hive",
                "severity": "LOW",
                "confidence": 1.0,
                "status": "active",
                "count": len(lessons),
                "x": 50,
                "y": 50,
                "color": "#00d1ff",
            }
        ]
        edges_out: list[dict] = []
        positions = self._layout_positions(len(lessons))

        for i, lesson in enumerate(lessons):
            nid = f"lesson-{lesson.id}"
            x, y = positions[i] if i < len(positions) else (50, 50)
            cat_color = CATEGORY_COLORS.get(lesson.category, SEVERITY_COLORS.get(lesson.severity, "#64748b"))
            nodes.append(
                {
                    "id": nid,
                    "label": lesson.title[:28] + ("…" if len(lesson.title) > 28 else ""),
                    "type": "lesson",
                    "category": lesson.category,
                    "severity": lesson.severity,
                    "confidence": lesson.confidence,
                    "status": lesson.status,
                    "badge": node_badge(lesson),
                    "count": lesson.occurrence_count,
                    "symbol": lesson.symbol,
                    "strategy_name": lesson.strategy_name,
                    "memory_type": lesson.memory_type,
                    "color": cat_color,
                    "x": x,
                    "y": y,
                    "created_at": lesson.created_at.isoformat() + "Z" if lesson.created_at else None,
                    "last_seen_at": lesson.last_seen_at.isoformat() + "Z" if lesson.last_seen_at else None,
                }
            )
            edges_out.append(
                {
                    "id": f"e-hive-{lesson.id}",
                    "source": "hive",
                    "target": nid,
                    "relation": "learned_from",
                    "weight": lesson.confidence,
                    "evidence_count": lesson.occurrence_count,
                }
            )
            if lesson.symbol:
                sid = f"symbol-{lesson.symbol.replace('/', '')}"
                if not any(n["id"] == sid for n in nodes):
                    nodes.append(
                        {
                            "id": sid,
                            "label": lesson.symbol,
                            "type": "symbol",
                            "severity": "LOW",
                            "confidence": 0.8,
                            "status": "active",
                            "count": 1,
                            "symbol": lesson.symbol,
                            "x": x + 8,
                            "y": y,
                            "color": "#06b6d4",
                        }
                    )
                edges_out.append(
                    {
                        "id": f"e-{nid}-{sid}",
                        "source": nid,
                        "target": sid,
                        "relation": "related_symbol",
                        "weight": 1.0,
                        "evidence_count": 1,
                    }
                )

        db_edges = self.session.exec(select(MemoryEdge).limit(200)).all()
        node_ids = {n["id"] for n in nodes}
        for e in db_edges:
            if e.source_id in node_ids and e.target_id in node_ids:
                if not any(x["id"] == f"ge-{e.id}" for x in edges_out):
                    edges_out.append(
                        {
                            "id": f"ge-{e.id}",
                            "source": e.source_id,
                            "target": e.target_id,
                            "relation": e.relation,
                            "weight": e.weight,
                            "evidence_count": e.evidence_count,
                        }
                    )

        return {"nodes": nodes, "edges": edges_out}

    def _layout_positions(self, n: int) -> list[tuple[float, float]]:
        if n <= 0:
            return []
        import math

        out = []
        for i in range(n):
            angle = (2 * math.pi * i) / max(n, 1)
            r = 32
            out.append((50 + r * math.cos(angle), 50 + r * math.sin(angle)))
        return out

    def list_lessons(
        self,
        *,
        category: Optional[str] = None,
        symbol: Optional[str] = None,
        severity: Optional[str] = None,
        memory_type: Optional[str] = None,
        cycle_run_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        action_status: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        rows = list(
            self.session.exec(
                select(LessonNode).order_by(LessonNode.last_seen_at.desc()).limit(limit * 2)
            ).all()
        )
        filtered = self._filter_rows(
            rows,
            category=category,
            memory_type=memory_type,
            symbol=symbol,
            severity=severity,
            cycle_run_id=cycle_run_id,
            strategy_name=strategy_name,
            action_status=action_status,
            include_archived=include_archived,
            graph_default=False,
        )[:limit]
        return [self._lesson_detail(r) for r in filtered]

    def symbol_memory_penalty(self, symbol: str) -> float:
        max_pen = float(cfg_get(self.config, "memory.max_memory_penalty", 0.15))
        rows = self.session.exec(
            select(LessonNode).where(
                LessonNode.symbol == symbol,
                LessonNode.category == CATEGORY_TRADING,
                LessonNode.can_influence_ranking == True,  # noqa: E712
                LessonNode.status == "active",
                LessonNode.severity.in_(["HIGH", "CRITICAL"]),
            )
        ).all()
        if not rows:
            return 0.0
        return min(max_pen, 0.03 * sum(r.occurrence_count for r in rows))

    def approve(self, lesson_id: int) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if row:
            row.action_status = "approved"
            row.human_review_status = "approved"
            row.updated_at = datetime.utcnow()
            self.session.add(row)
        return row

    def reject(self, lesson_id: int) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if row:
            row.action_status = "rejected"
            row.human_review_status = "rejected"
            row.updated_at = datetime.utcnow()
            self.session.add(row)
        return row

    def archive(
        self,
        lesson_id: int,
        *,
        reason: str = "",
        hide_from_ai: bool = True,
        hide_from_graph: bool = True,
        by: str = "operator",
    ) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if not row:
            return None
        row.status = "archived"
        row.archive_reason = reason or "archived by operator"
        row.visible_in_graph = not hide_from_graph if hide_from_graph is False else False
        row.visible_to_ai = not hide_from_ai if hide_from_ai is False else False
        row.can_influence_ranking = False
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        return row

    def restore(self, lesson_id: int) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if not row:
            return None
        row.status = "active"
        vis = default_visibility(row.category, row.memory_type, row.severity)
        row.visible_in_graph = vis["visible_in_graph"]
        row.visible_to_ai = vis["visible_to_ai"]
        row.can_influence_ranking = vis["can_influence_ranking"]
        row.archive_reason = None
        row.deleted_at = None
        row.deleted_by = None
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        return row

    def soft_delete(
        self,
        lesson_id: int,
        *,
        reason: str = "",
        by: str = "operator",
    ) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if not row:
            return None
        row.status = "deleted"
        row.visible_in_graph = False
        row.visible_to_ai = False
        row.can_influence_ranking = False
        row.deleted_at = datetime.utcnow()
        row.deleted_by = by
        row.archive_reason = reason or "deleted by operator"
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        return row

    def mark_resolved(self, lesson_id: int) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if row:
            row.status = "resolved"
            row.can_influence_ranking = False
            row.updated_at = datetime.utcnow()
            self.session.add(row)
        return row

    def set_visibility(
        self,
        lesson_id: int,
        *,
        visible_to_ai: Optional[bool] = None,
        visible_in_graph: Optional[bool] = None,
        can_influence_ranking: Optional[bool] = None,
    ) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if not row:
            return None
        if visible_to_ai is not None:
            row.visible_to_ai = visible_to_ai
        if visible_in_graph is not None:
            row.visible_in_graph = visible_in_graph
        if can_influence_ranking is not None:
            row.can_influence_ranking = can_influence_ranking
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        return row

    def bulk_archive(
        self,
        lesson_ids: list[int],
        *,
        reason: str = "",
        hide_from_ai: bool = True,
        hide_from_graph: bool = True,
    ) -> int:
        n = 0
        for lid in lesson_ids:
            if self.archive(lid, reason=reason, hide_from_ai=hide_from_ai, hide_from_graph=hide_from_graph):
                n += 1
        return n

    def bulk_restore(self, lesson_ids: list[int]) -> int:
        return sum(1 for lid in lesson_ids if self.restore(lid))

    def bulk_soft_delete(self, lesson_ids: list[int], *, reason: str = "") -> int:
        return sum(1 for lid in lesson_ids if self.soft_delete(lid, reason=reason))

    def bulk_hide_from_ai(self, lesson_ids: list[int]) -> int:
        n = 0
        for lid in lesson_ids:
            if self.set_visibility(lid, visible_to_ai=False, can_influence_ranking=False):
                n += 1
        return n

    def set_category(self, lesson_id: int, category: str, memory_type: Optional[str] = None) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if not row:
            return None
        row.category = category
        if memory_type:
            row.memory_type = normalize_memory_type(memory_type)
        vis = default_visibility(category, row.memory_type, row.severity)
        if category == CATEGORY_SYSTEM:
            row.visible_in_graph = vis["visible_in_graph"]
            row.visible_to_ai = False
            row.can_influence_ranking = False
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        return row

    def bulk_set_category(self, lesson_ids: list[int], category: str) -> int:
        return sum(1 for lid in lesson_ids if self.set_category(lid, category))

    def hive_mind_summary(self) -> dict[str, Any]:
        rows = list(self.session.exec(select(LessonNode).order_by(LessonNode.last_seen_at.desc()).limit(200)).all())
        trading = [r for r in rows if r.category == CATEGORY_TRADING and r.status == "active"][:8]
        system = [r for r in rows if r.category == CATEGORY_SYSTEM and r.status == "active"][:5]
        ai_rows = [r for r in rows if r.category == "ai_review_memory"][:5]
        patterns = [r for r in rows if r.occurrence_count >= 2 and r.status == "active"][:8]
        return {
            "trading_recent": [self._lesson_detail(r) for r in trading],
            "system_recent": [self._lesson_detail(r) for r in system],
            "ai_recent": [self._lesson_detail(r) for r in ai_rows],
            "patterns": [
                {
                    "id": r.id,
                    "title": r.title,
                    "memory_type": r.memory_type,
                    "occurrence_count": r.occurrence_count,
                    "symbol": r.symbol,
                }
                for r in patterns
            ],
        }
