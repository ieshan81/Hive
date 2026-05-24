"""Database-backed memory engine — no Graphiti in MVP."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.database import AIMemory
from app.services.config_manager import ConfigManager


class MemoryEngine:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()

    def update_strength(
        self,
        memory_id: int,
        confirmed: bool = False,
        failed: bool = False,
    ) -> Optional[AIMemory]:
        mem = self.session.get(AIMemory, memory_id)
        if mem is None:
            return None
        weights = self.config.get("memory_weights", {})
        bonus = weights.get("confirmation_bonus", 0.1)
        penalty = weights.get("failure_penalty", 0.15)
        new_strength = mem.strength * (1 - mem.decay_rate)
        if confirmed:
            new_strength += bonus
            mem.last_confirmed_at = datetime.utcnow()
        if failed:
            new_strength -= penalty
        mem.strength = max(0.0, min(1.0, new_strength))
        self.session.add(mem)
        self.session.commit()
        self.session.refresh(mem)
        return mem

    def create_memory(
        self,
        memory_type: str,
        event: str,
        lesson: str,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        confidence: float = 0.5,
        linked_trade_id: Optional[int] = None,
    ) -> AIMemory:
        mem = AIMemory(
            memory_type=memory_type,
            symbol=symbol,
            strategy=strategy,
            event=event,
            lesson=lesson,
            confidence=confidence,
            strength=confidence,
            linked_trade_id=linked_trade_id,
        )
        self.session.add(mem)
        self.session.commit()
        self.session.refresh(mem)
        return mem

    def list_memories(self, limit: int = 100) -> list[AIMemory]:
        return list(
            self.session.exec(select(AIMemory).order_by(AIMemory.created_at.desc()).limit(limit)).all()
        )

    def memory_graph_nodes(self) -> list[dict]:
        memories = self.list_memories(200)
        type_counts: dict[str, int] = {}
        for m in memories:
            type_counts[m.memory_type] = type_counts.get(m.memory_type, 0) + 1

        colors = {
            "trade": "#3b82f6",
            "strategy": "#8b5cf6",
            "regime": "#06b6d4",
            "correlation": "#14b8a6",
            "blocked": "#f97316",
            "lesson": "#22c55e",
            "mistake": "#ef4444",
        }
        positions = [
            (72, 28), (28, 42), (78, 58), (22, 68), (68, 78), (38, 22), (48, 82),
        ]
        nodes = []
        for i, (label, count) in enumerate(type_counts.items()):
            x, y = positions[i % len(positions)]
            nodes.append(
                {
                    "id": label,
                    "label": label.replace("_", " ").title(),
                    "count": count,
                    "color": colors.get(label, "#64748b"),
                    "x": x,
                    "y": y,
                }
            )
        return nodes
