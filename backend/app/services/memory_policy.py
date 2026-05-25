"""Memory policy defaults — consolidation, retention, graph display."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.database import MemoryPolicyConfig

DEFAULT_MEMORY_POLICY = {
    "consolidation_threshold_total_raw_memories": 100,
    "consolidation_threshold_per_strategy": 25,
    "consolidation_threshold_same_type": 10,
    "archive_raw_after_consolidation": True,
    "raw_memory_retention_days": 30,
    "keep_audit_evidence_forever": True,
    "keep_trade_evidence_forever": True,
    "keep_risk_incidents_forever": True,
    "graph_default_show_raw_memories": False,
    "graph_default_show_consolidated_memories": True,
    "max_default_graph_nodes": 50,
    "max_ai_context_memories": 25,
}


def load_memory_policy(session: Session, config: dict) -> dict[str, Any]:
    row = session.get(MemoryPolicyConfig, 1)
    base = dict(DEFAULT_MEMORY_POLICY)
    base.update(config.get("memory_policy") or {})
    if row and row.policy_json:
        base.update(row.policy_json)
    return base


def ensure_memory_policy_row(session: Session, config: dict) -> dict[str, Any]:
    policy = load_memory_policy(session, config)
    row = session.get(MemoryPolicyConfig, 1)
    if not row:
        session.add(MemoryPolicyConfig(id=1, policy_json=policy))
        session.flush()
    return policy
