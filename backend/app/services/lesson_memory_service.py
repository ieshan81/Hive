"""Evidence-based Hive memory — lessons, graph, patterns."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, MemoryEdge, MemoryEvidence
from app.services.engine_config import cfg_get


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
    ) -> LessonNode:
        if not self.enabled:
            raise RuntimeError("memory disabled")

        pk = pattern_key or self._pattern_key(memory_type, symbol, extra=related_entity_id or "")
        existing: Optional[LessonNode] = None
        if aggregate:
            existing = self.session.exec(
                select(LessonNode).where(LessonNode.pattern_key == pk)
            ).first()

        now = datetime.utcnow()
        if existing:
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
            "type": "lesson",
            "title": row.title,
            "summary": row.summary,
            "detailed_lesson": row.detailed_lesson,
            "what_happened": row.summary,
            "bot_learned": row.detailed_lesson,
            "severity": row.severity,
            "confidence": row.confidence,
            "source": row.source,
            "action_status": row.action_status,
            "proposed_action": row.proposed_action,
            "proposed_prevention": row.proposed_action,
            "symbol": row.symbol,
            "strategy_name": row.strategy_name,
            "cycle_run_id": row.cycle_run_id,
            "signal_id": row.signal_id,
            "broker_order_id": row.broker_order_id,
            "order_id": row.order_id,
            "occurrence_count": row.occurrence_count,
            "evidence_human": self._human_evidence(row.evidence_json or {}),
            "evidence_json": row.evidence_json,
            "evidence_attachments": [{"type": r.evidence_type, "payload": r.payload} for r in evidence_rows],
            "linked_nodes": linked,
            "tags": row.tags or [],
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

    def build_graph(self, limit: int = 80) -> dict[str, Any]:
        lessons = list(
            self.session.exec(
                select(LessonNode).order_by(LessonNode.last_seen_at.desc()).limit(limit)
            ).all()
        )
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
            }
        ]
        edges_out: list[dict] = []
        positions = self._layout_positions(len(lessons))

        for i, lesson in enumerate(lessons):
            nid = f"lesson-{lesson.id}"
            x, y = positions[i] if i < len(positions) else (50, 50)
            nodes.append(
                {
                    "id": nid,
                    "label": lesson.title[:28] + ("…" if len(lesson.title) > 28 else ""),
                    "type": "lesson",
                    "severity": lesson.severity,
                    "confidence": lesson.confidence,
                    "status": lesson.action_status,
                    "count": lesson.occurrence_count,
                    "symbol": lesson.symbol,
                    "strategy_name": lesson.strategy_name,
                    "memory_type": lesson.memory_type,
                    "color": SEVERITY_COLORS.get(lesson.severity, "#64748b"),
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
        for e in db_edges:
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
        symbol: Optional[str] = None,
        severity: Optional[str] = None,
        memory_type: Optional[str] = None,
        cycle_run_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        action_status: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        q = select(LessonNode).order_by(LessonNode.last_seen_at.desc()).limit(limit)
        rows = list(self.session.exec(q).all())
        if symbol:
            rows = [r for r in rows if r.symbol == symbol]
        if severity:
            rows = [r for r in rows if r.severity == severity]
        if memory_type:
            rows = [r for r in rows if r.memory_type == memory_type]
        if cycle_run_id:
            rows = [r for r in rows if r.cycle_run_id == cycle_run_id]
        if strategy_name:
            rows = [r for r in rows if r.strategy_name == strategy_name]
        if action_status:
            rows = [r for r in rows if r.action_status == action_status]
        return [self._lesson_detail(r) for r in rows]

    def symbol_memory_penalty(self, symbol: str) -> float:
        max_pen = float(cfg_get(self.config, "memory.max_memory_penalty", 0.15))
        rows = self.session.exec(
            select(LessonNode).where(
                LessonNode.symbol == symbol,
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
            row.updated_at = datetime.utcnow()
            self.session.add(row)
        return row

    def reject(self, lesson_id: int) -> Optional[LessonNode]:
        row = self.session.get(LessonNode, lesson_id)
        if row:
            row.action_status = "rejected"
            row.updated_at = datetime.utcnow()
            self.session.add(row)
        return row
