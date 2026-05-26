"""Evidence-based Hive memory — lessons, graph, patterns."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, MemoryEdge, MemoryEvidence
from app.services.engine_config import cfg_get
from app.services.memory_categories import (
    CATEGORY_BACKTEST,
    CATEGORY_RESEARCH,
    CATEGORY_SYSTEM,
    CATEGORY_TRADING,
    CATEGORY_WALK_FORWARD,
    CATEGORY_COLORS,
    CLUSTER_LABELS,
    GRAPH_FILTER_CATEGORIES,
    GRAPH_INTELLIGENCE_CATEGORIES,
    RESEARCH_MEMORY_TYPES,
    classify_memory_type,
    default_visibility,
    drawer_title,
    memory_graph_cluster,
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
            system_validation_status="pending",
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
                if r.category not in GRAPH_INTELLIGENCE_CATEGORIES:
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
            "system_validation_status": getattr(row, "system_validation_status", "pending"),
            "system_validated_at": row.system_validated_at.isoformat() + "Z" if getattr(row, "system_validated_at", None) else None,
            "system_validator_rule": getattr(row, "system_validator_rule", None),
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
        graph_filter: Optional[str] = None,
        severity: Optional[str] = None,
        include_archived: bool = False,
        graph_default: bool = True,
    ) -> dict[str, Any]:
        all_rows = list(
            self.session.exec(
                select(LessonNode).order_by(LessonNode.last_seen_at.desc()).limit(limit * 3)
            ).all()
        )
        intelligence_mode = graph_default and not category and not include_archived
        lessons = self._filter_rows(
            all_rows,
            category=category,
            severity=severity,
            include_archived=include_archived,
            graph_default=intelligence_mode,
        )[: limit * 2 if intelligence_mode else limit]

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
        cluster_ids: set[str] = set()
        positions = self._layout_positions(len(lessons))

        def _ensure_cluster(cid: str) -> None:
            if cid in cluster_ids:
                return
            cluster_ids.add(cid)
            idx = len(cluster_ids)
            import math

            angle = (2 * math.pi * idx) / max(len(CLUSTER_LABELS), 8)
            nodes.append(
                {
                    "id": cid,
                    "label": CLUSTER_LABELS.get(cid, cid),
                    "type": "cluster",
                    "severity": "LOW",
                    "confidence": 0.9,
                    "status": "active",
                    "count": 0,
                    "x": 50 + 22 * math.cos(angle),
                    "y": 50 + 22 * math.sin(angle),
                    "color": "#8b5cf6",
                }
            )
            edges_out.append(
                {
                    "id": f"e-hive-{cid}",
                    "source": "hive",
                    "target": cid,
                    "relation": "cluster",
                    "weight": 1.0,
                    "evidence_count": 1,
                }
            )

        for i, lesson in enumerate(lessons):
            nid = f"lesson-{lesson.id}"
            x, y = positions[i] if i < len(positions) else (50, 50)
            cat_color = CATEGORY_COLORS.get(lesson.category, SEVERITY_COLORS.get(lesson.severity, "#64748b"))
            cid = memory_graph_cluster(lesson.memory_type or "")
            if intelligence_mode:
                _ensure_cluster(cid)
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
                    "system_validation_status": getattr(lesson, "system_validation_status", "pending"),
                    "color": cat_color,
                    "x": x,
                    "y": y,
                    "created_at": lesson.created_at.isoformat() + "Z" if lesson.created_at else None,
                    "last_seen_at": lesson.last_seen_at.isoformat() + "Z" if lesson.last_seen_at else None,
                }
            )
            if intelligence_mode:
                edges_out.append(
                    {
                        "id": f"e-{cid}-{lesson.id}",
                        "source": cid,
                        "target": nid,
                        "relation": "evidence",
                        "weight": lesson.confidence,
                        "evidence_count": lesson.occurrence_count,
                    }
                )
            else:
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

        if intelligence_mode:
            self._append_registry_graph_nodes(nodes, edges_out, cluster_ids)

        if graph_filter:
            nodes, edges_out = self._apply_graph_filter(nodes, edges_out, graph_filter)

        active_trading = sum(
            1 for r in all_rows if r.category == CATEGORY_TRADING and r.status == "active" and r.visible_in_graph
        )
        active_research = sum(
            1
            for r in all_rows
            if r.category in (CATEGORY_RESEARCH, CATEGORY_BACKTEST, CATEGORY_WALK_FORWARD)
            or (r.memory_type in RESEARCH_MEMORY_TYPES)
            and r.status == "active"
        )
        validated_research = sum(
            1
            for r in all_rows
            if (r.memory_type in RESEARCH_MEMORY_TYPES or r.category in (CATEGORY_RESEARCH, CATEGORY_BACKTEST))
            and getattr(r, "system_validation_status", "pending") == "validated"
        )
        active_system = sum(
            1 for r in all_rows if r.category == CATEGORY_SYSTEM and r.status == "active"
        )
        archived_or_deleted = sum(1 for r in all_rows if r.status in ("archived", "deleted"))
        hidden_by_filter = max(0, len(all_rows) - len(lessons) - archived_or_deleted)
        empty_reason = None
        if not lessons and len(nodes) <= 1:
            if archived_or_deleted:
                empty_reason = f"No active memories in this filter. {archived_or_deleted} archived/deleted hidden."
            elif active_trading == 0 and active_research == 0:
                empty_reason = "No active trading or research memories. Run Research Lab or complete paper cycles."
            else:
                empty_reason = "No memories match current filter."
        elif category and active_research > 0 and len(lessons) == 0:
            empty_reason = "Research memories exist but are hidden by filter."

        return {
            "status": "ok",
            "nodes": nodes,
            "edges": edges_out,
            "meta": {
                "active_trading_memories": active_trading,
                "active_research_memories": active_research,
                "validated_research_memories": validated_research,
                "rejected_strategies": sum(1 for n in nodes if n.get("type") == "strategy" and "rejected" in str(n.get("stage", ""))),
                "active_paper_strategies": sum(1 for n in nodes if n.get("type") == "strategy" and n.get("stage") == "paper_active"),
                "experiment_eligible_strategies": 0,
                "active_system_issues": active_system,
                "archived_or_deleted": archived_or_deleted,
                "hidden_by_filter": hidden_by_filter,
                "filters_applied": category or ("intelligence_default" if intelligence_mode else "all"),
                "empty_reason": empty_reason,
                "cluster_count": len(cluster_ids),
            },
        }

    def _apply_graph_filter(
        self, nodes: list[dict], edges_out: list[dict], graph_filter: str
    ) -> tuple[list[dict], list[dict]]:
        gf = graph_filter.lower().replace("-", "_")
        keep_ids = {"hive"}

        def _keep_node(n: dict) -> bool:
            if n.get("id") == "hive":
                return True
            if gf == "rejected":
                return (
                    n.get("id", "").startswith("cluster-rejected")
                    or n.get("stage") == "rejected"
                    or n.get("memory_type") == "rejected_strategy_memory"
                )
            if gf == "active_paper":
                return (
                    n.get("id", "").startswith("cluster-active-paper")
                    or n.get("stage") == "paper_active"
                    or n.get("type") == "position"
                )
            if gf == "experiments":
                return (
                    n.get("id", "").startswith("cluster-experiment")
                    or n.get("stage") == "paper_experiment"
                    or (n.get("memory_type") or "").startswith("experiment_")
                )
            if gf == "strategy":
                return n.get("type") in ("strategy", "cluster") and "strategy" in str(n.get("id", ""))
            return True

        for n in nodes:
            if _keep_node(n):
                keep_ids.add(n["id"])
        for e in edges_out:
            if e.get("source") in keep_ids or e.get("target") in keep_ids:
                keep_ids.add(e.get("source", ""))
                keep_ids.add(e.get("target", ""))
        filtered_nodes = [n for n in nodes if n["id"] in keep_ids]
        filtered_edges = [
            e for e in edges_out if e.get("source") in keep_ids and e.get("target") in keep_ids
        ]
        return filtered_nodes, filtered_edges

    def _append_registry_graph_nodes(
        self, nodes: list[dict], edges_out: list[dict], cluster_ids: set[str]
    ) -> None:
        try:
            from app.database import PositionEnrichedState, PositionSnapshot, StrategyRegistry

            regs = list(self.session.exec(select(StrategyRegistry)).all())
            for reg in regs[:12]:
                sid = f"strategy-{reg.strategy_id}"
                if any(n["id"] == sid for n in nodes):
                    continue
                nodes.append(
                    {
                        "id": sid,
                        "label": reg.name[:24],
                        "type": "strategy",
                        "stage": reg.current_stage,
                        "strategy_id": reg.strategy_id,
                        "severity": "HIGH" if reg.current_stage == "rejected" else "MEDIUM",
                        "confidence": 0.8,
                        "status": "active",
                        "count": reg.memory_count,
                        "color": "#ef4444" if reg.current_stage == "rejected" else "#22c55e",
                        "x": 72,
                        "y": 30 + (hash(reg.strategy_id) % 40),
                    }
                )
                cid = "cluster-rejected" if reg.current_stage == "rejected" else "cluster-active-paper"
                if reg.current_stage == "paper_experiment":
                    cid = "cluster-experiments"
                if cid not in cluster_ids:
                    cluster_ids.add(cid)
                    nodes.append(
                        {
                            "id": cid,
                            "label": CLUSTER_LABELS.get(cid, cid),
                            "type": "cluster",
                            "severity": "LOW",
                            "confidence": 0.9,
                            "status": "active",
                            "count": 0,
                            "x": 78,
                            "y": 50,
                            "color": "#8b5cf6",
                        }
                    )
                    edges_out.append(
                        {"id": f"e-hive-{cid}", "source": "hive", "target": cid, "relation": "cluster", "weight": 1.0, "evidence_count": 1}
                    )
                edges_out.append(
                    {
                        "id": f"e-{cid}-{reg.strategy_id}",
                        "source": cid,
                        "target": sid,
                        "relation": "strategy_stage",
                        "weight": 1.0,
                        "evidence_count": 1,
                    }
                )
            open_pos = list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
            for p in open_pos:
                st = self.session.exec(
                    select(PositionEnrichedState).where(PositionEnrichedState.broker_symbol == p.symbol)
                ).first()
                state = (st.state_json if st else {}) or {}
                psid = f"position-{p.symbol}"
                nodes.append(
                    {
                        "id": psid,
                        "label": f"{p.symbol} open",
                        "type": "position",
                        "severity": "MEDIUM",
                        "confidence": 0.9,
                        "status": "active",
                        "symbol": p.symbol,
                        "strategy_name": state.get("strategy_name"),
                        "x": 28,
                        "y": 62,
                        "color": "#06b6d4",
                    }
                )
                cid = "cluster-active-paper"
                edges_out.append(
                    {"id": f"e-{psid}-paper", "source": psid, "target": cid, "relation": "open_position", "weight": 1.0, "evidence_count": 1}
                )
        except Exception:
            pass

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
        from app.services.nuke_epoch_service import filter_lessons_post_nuke, get_latest_nuke_epoch

        rows = list(self.session.exec(select(LessonNode).order_by(LessonNode.last_seen_at.desc()).limit(200)).all())
        rows = filter_lessons_post_nuke(self.session, rows)
        nuke = get_latest_nuke_epoch(self.session)
        trading = [r for r in rows if r.category == CATEGORY_TRADING and r.status == "active"][:8]
        system = [r for r in rows if r.category == CATEGORY_SYSTEM and r.status == "active"][:5]
        ai_rows = [r for r in rows if r.category == "ai_review_memory"][:5]
        patterns = [r for r in rows if r.occurrence_count >= 2 and r.status == "active"][:8]
        return {
            "fresh_brain": bool(nuke and not rows),
            "nuke_epoch": nuke,
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
