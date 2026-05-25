"""Multi-strategy conflict detection — evaluate only, no orders."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import PositionSnapshot, StrategyConflict, StrategyRegistry


class StrategyConflictService:
    MAX_OPEN_POSITIONS = 3
    MAX_MEME_POSITIONS = 1
    MEME_SYMBOLS = frozenset({"DOGE/USD", "DOGEUSD", "SHIB/USD", "PEPE/USD"})

    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config

    def evaluate(self) -> dict[str, Any]:
        active = list(
            self.session.exec(
                select(StrategyRegistry).where(
                    StrategyRegistry.current_stage.in_(["paper_active", "live_candidate", "tiny_live"])
                )
            ).all()
        )
        open_pos = list(
            self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()
        )
        conflicts: list[StrategyConflict] = []

        if len(open_pos) > self.MAX_OPEN_POSITIONS:
            conflicts.append(
                StrategyConflict(
                    symbol="*",
                    side="*",
                    resolution="block_new_entries",
                    evidence_json={"reason": "max_open_positions", "count": len(open_pos)},
                )
            )

        meme_count = sum(1 for p in open_pos if self._is_meme(p.symbol))
        if meme_count > self.MAX_MEME_POSITIONS:
            conflicts.append(
                StrategyConflict(
                    symbol="DOGE",
                    side="long",
                    resolution="block_meme_duplicate",
                    evidence_json={"meme_positions": meme_count},
                )
            )

        by_symbol: dict[str, list] = {}
        for reg in active:
            for sym in reg.symbols or []:
                by_symbol.setdefault(sym, []).append(reg)

        for sym, regs in by_symbol.items():
            if len(regs) > 1:
                winner = max(regs, key=lambda r: r.current_score or 0)
                for loser in regs:
                    if loser.strategy_id != winner.strategy_id:
                        conflicts.append(
                            StrategyConflict(
                                winner_strategy_id=winner.strategy_id,
                                loser_strategy_id=loser.strategy_id,
                                symbol=sym,
                                side="long",
                                signal_timestamp=datetime.utcnow(),
                                resolution="highest_score_wins",
                                evidence_json={
                                    "winner_score": winner.current_score,
                                    "loser_score": loser.current_score,
                                },
                            )
                        )

        for c in conflicts:
            self.session.add(c)
        return {"status": "ok", "conflicts_recorded": len(conflicts), "active_strategies": len(active)}

    def list_conflicts(self, limit: int = 50) -> list[dict]:
        rows = self.session.exec(
            select(StrategyConflict).order_by(StrategyConflict.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "id": r.id,
                "winner_strategy_id": r.winner_strategy_id,
                "loser_strategy_id": r.loser_strategy_id,
                "symbol": r.symbol,
                "side": r.side,
                "resolution": r.resolution,
                "evidence": r.evidence_json,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ]

    def _is_meme(self, symbol: str) -> bool:
        s = symbol.upper().replace("-", "")
        return "DOGE" in s or "SHIB" in s or "PEPE" in s
