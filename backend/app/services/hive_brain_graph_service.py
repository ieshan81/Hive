"""Clean Hive Brain graph — clusters + top lessons, max nodes, no spaghetti."""

from __future__ import annotations

import math
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, MemoryEdge, PositionSnapshot, StrategyRegistry
from app.services.memory_categories import (
    AI_LEARNING_TYPES,
    CLUSTER_LABELS,
    HIVE_BRAIN_CLUSTERS,
    MEMORY_LEVEL_CONSOLIDATED,
    MEMORY_LEVEL_CORE,
    MEMORY_LEVEL_RAW,
    TRAINING_MEMORY_TYPES,
    memory_graph_cluster,
)
from app.services.memory_consolidation_service import MemoryConsolidationService
from app.services.memory_policy import load_memory_policy


def _cluster_for_lesson(lesson: LessonNode) -> str:
    mt = lesson.memory_type or ""
    if mt in TRAINING_MEMORY_TYPES:
        return "cluster-experiments"
    if mt in AI_LEARNING_TYPES or lesson.memory_level in (MEMORY_LEVEL_CORE, MEMORY_LEVEL_CONSOLIDATED):
        return "cluster-ai-core"
    if mt == "stale_position_memory":
        return "cluster-staleness"
    if "exit" in mt:
        return "cluster-exit-lessons"
    return memory_graph_cluster(mt)


class HiveBrainGraphService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.policy = load_memory_policy(session, config)

    def build(
        self,
        *,
        show_raw: bool = False,
        expand_cluster: Optional[str] = None,
        max_nodes: Optional[int] = None,
    ) -> dict[str, Any]:
        max_n = max_nodes or int(self.policy.get("max_default_graph_nodes", 50))
        nodes: list[dict] = [
            {
                "id": "hive",
                "label": "HIVE BRAIN",
                "type": "hive",
                "severity": "LOW",
                "confidence": 1.0,
                "status": "active",
                "count": 0,
                "x": 50,
                "y": 50,
                "color": "#00d1ff",
                "stability": "core",
            }
        ]
        edges: list[dict] = []
        cluster_stats: dict[str, dict] = {}

        lessons = self._select_lessons(show_raw, expand_cluster)
        raw_total = len(
            list(
                self.session.exec(
                    select(LessonNode).where(
                        LessonNode.status == "active",
                        LessonNode.memory_level == MEMORY_LEVEL_RAW,
                    )
                ).all()
            )
        )
        consolidated = len(
            list(
                self.session.exec(
                    select(LessonNode).where(
                        LessonNode.memory_level.in_(("consolidated_lesson", "core_ai_lesson")),
                        LessonNode.status == "active",
                    )
                ).all()
            )
        )

        ci = 0
        for cid, label in HIVE_BRAIN_CLUSTERS.items():
            angle = (2 * math.pi * ci) / max(len(HIVE_BRAIN_CLUSTERS), 1)
            nodes.append(
                {
                    "id": cid,
                    "label": label,
                    "type": "cluster",
                    "severity": "LOW",
                    "confidence": 0.9,
                    "status": "active",
                    "count": 0,
                    "x": 50 + 28 * math.cos(angle),
                    "y": 50 + 28 * math.sin(angle),
                    "color": "#8b5cf6",
                    "stability": "hub",
                    "evidence_strength": "medium",
                }
            )
            edges.append(
                {
                    "id": f"e-hive-{cid}",
                    "source": "hive",
                    "target": cid,
                    "relation": "cluster",
                    "weight": 1.0,
                    "weight_tier": "core",
                }
            )
            cluster_stats[cid] = {"count": 0, "confidence": 0.0, "latest": None}
            ci += 1

        lesson_slots = max(0, max_n - len(nodes) - 3)
        placed = 0
        for lesson in lessons[: lesson_slots * 2]:
            if placed >= lesson_slots:
                break
            if not show_raw and lesson.memory_level == MEMORY_LEVEL_RAW and not expand_cluster:
                continue
            cid = _cluster_for_lesson(lesson)
            if expand_cluster and cid != expand_cluster:
                continue
            nid = f"lesson-{lesson.id}"
            if any(n["id"] == nid for n in nodes):
                continue
            cs = cluster_stats.get(cid, {"count": 0, "confidence": 0.0})
            cs["count"] = cs.get("count", 0) + 1
            cs["confidence"] = max(cs.get("confidence", 0), lesson.confidence)
            cs["latest"] = lesson.title[:40]
            cluster_stats[cid] = cs
            hub = next((n for n in nodes if n["id"] == cid), None)
            hx, hy = (hub["x"], hub["y"]) if hub else (50, 50)
            nodes.append(
                {
                    "id": nid,
                    "label": lesson.title[:24] + ("…" if len(lesson.title) > 24 else ""),
                    "type": "lesson",
                    "memory_level": lesson.memory_level,
                    "memory_type": lesson.memory_type,
                    "severity": lesson.severity,
                    "confidence": lesson.confidence,
                    "strength": getattr(lesson, "strength", 0.5),
                    "status": lesson.status,
                    "symbol": lesson.symbol,
                    "strategy_name": lesson.strategy_name,
                    "x": hx + (placed % 3) * 4 - 4,
                    "y": hy + (placed // 3) * 4 - 4,
                    "color": "#22d3ee" if lesson.memory_level == MEMORY_LEVEL_CORE else "#a78bfa",
                    "evidence_count": lesson.occurrence_count,
                }
            )
            wt = "strong" if lesson.memory_level == MEMORY_LEVEL_CORE else "medium"
            edges.append(
                {
                    "id": f"e-{cid}-{lesson.id}",
                    "source": cid,
                    "target": nid,
                    "relation": "learned_from",
                    "weight": lesson.confidence,
                    "weight_tier": wt,
                    "evidence_count": lesson.occurrence_count,
                }
            )
            placed += 1

        for cid, stats in cluster_stats.items():
            for n in nodes:
                if n["id"] == cid:
                    n["count"] = stats.get("count", 0)
                    n["latest_lesson"] = stats.get("latest")
                    n["confidence"] = stats.get("confidence", 0.9)

        self._append_positions(nodes, edges)
        self._append_strategies(nodes, edges, max_n)

        if len(nodes) > max_n:
            keep = {n["id"] for n in nodes if n["type"] in ("hive", "cluster", "position", "strategy")}
            ranked = sorted(
                [n for n in nodes if n["id"] not in keep],
                key=lambda x: (x.get("strength", 0), x.get("confidence", 0)),
                reverse=True,
            )
            for n in ranked[: max(0, max_n - len(keep))]:
                keep.add(n["id"])
            nodes = [n for n in nodes if n["id"] in keep]
            edges = [e for e in edges if e["source"] in keep and e["target"] in keep]

        cons_status = MemoryConsolidationService(self.session, self.config).status()
        hidden_raw = raw_total if not show_raw else 0
        return {
            "status": "ok",
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "graph_mode": "hive_brain",
                "total_raw_memories": raw_total,
                "consolidated_memories": consolidated,
                "core_ai_memories": sum(1 for l in lessons if l.memory_level == MEMORY_LEVEL_CORE),
                "archived_raw_memories": cons_status.get("archived_raw_memories", 0),
                "compression_ratio": cons_status.get("compression_ratio", 0),
                "hidden_raw_memories": hidden_raw,
                "visible_nodes": len(nodes),
                "max_default_nodes": max_n,
                "ai_learning_memory_count": sum(
                    1 for l in lessons if l.memory_type in AI_LEARNING_TYPES or l.category == "ai_learning_memory"
                ),
                "active_training_lessons": sum(1 for l in lessons if l.memory_type in TRAINING_MEMORY_TYPES),
                "stale_position_lessons": sum(1 for l in lessons if l.memory_type == "stale_position_memory"),
                "show_raw": show_raw,
                "expand_cluster": expand_cluster,
                "cluster_count": len(HIVE_BRAIN_CLUSTERS),
                "synaptic_density": round(len(edges) / max(len(nodes), 1), 2),
            },
        }

    def _select_lessons(self, show_raw: bool, expand_cluster: Optional[str]) -> list[LessonNode]:
        q = select(LessonNode).where(LessonNode.status == "active", LessonNode.visible_in_graph == True)  # noqa: E712
        if not show_raw:
            q = q.where(
                LessonNode.memory_level.in_(
                    ("consolidated_lesson", "core_ai_lesson", "pattern_memory", "raw_experience")
                )
            )
        rows = list(self.session.exec(q.order_by(LessonNode.importance_score.desc()).limit(120)).all())
        if not show_raw:
            prioritized = [r for r in rows if r.memory_level != MEMORY_LEVEL_RAW]
            raw_sample = [r for r in rows if r.memory_level == MEMORY_LEVEL_RAW][:5]
            return prioritized + raw_sample
        return rows

    def _append_positions(self, nodes: list[dict], edges: list[dict]) -> None:
        cid = "cluster-active-positions"
        for pos in self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all():
            pid = f"position-{pos.symbol.replace('/', '')}"
            nodes.append(
                {
                    "id": pid,
                    "label": f"{pos.symbol} open",
                    "type": "position",
                    "severity": "MEDIUM",
                    "confidence": 0.95,
                    "status": "active",
                    "x": 62,
                    "y": 48,
                    "color": "#22c55e",
                }
            )
            edges.append(
                {
                    "id": f"e-{cid}-{pid}",
                    "source": cid,
                    "target": pid,
                    "relation": "open_position",
                    "weight": 1.0,
                    "weight_tier": "strong",
                }
            )

    def _append_strategies(self, nodes: list[dict], edges: list[dict], max_n: int) -> None:
        for reg in self.session.exec(select(StrategyRegistry)).all()[:6]:
            if reg.current_stage not in ("rejected", "paper_active", "paper_experiment"):
                continue
            sid = f"strategy-{reg.strategy_id}"
            cid = "cluster-rejected" if reg.current_stage == "rejected" else "cluster-experiments"
            nodes.append(
                {
                    "id": sid,
                    "label": reg.name[:20],
                    "type": "strategy",
                    "stage": reg.current_stage,
                    "x": 70,
                    "y": 35,
                    "color": "#ef4444" if reg.current_stage == "rejected" else "#fbbf24",
                }
            )
            edges.append(
                {
                    "id": f"e-{cid}-{reg.strategy_id}",
                    "source": cid,
                    "target": sid,
                    "relation": "strategy_stage",
                    "weight": 0.9,
                    "weight_tier": "medium",
                }
            )

    def rebuild(self) -> dict[str, Any]:
        return self.build(show_raw=False)
