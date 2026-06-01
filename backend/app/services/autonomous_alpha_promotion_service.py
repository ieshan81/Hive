"""Autonomous promotion and quarantine for Alpha Factory scorecards.

This service updates research-stage verdicts only. It cannot approve live
trading and cannot submit paper orders.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AlphaScorecard, StrategyRegistry
from app.services.engine_config import cfg_get

PAPER_ALLOWED_VERDICTS = {"paper_candidate", "paper_active"}


class AutonomousAlphaPromotionService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def evaluate(self, scorecard: AlphaScorecard) -> AlphaScorecard:
        blockers: list[str] = list(scorecard.blocker_reasons_json or [])
        min_sample = int(cfg_get(self.config, "alpha_factory.min_sample_size", 5) or 5)
        min_pf = float(cfg_get(self.config, "alpha_factory.min_profit_factor", 1.05) or 1.05)
        max_dd = float(cfg_get(self.config, "alpha_factory.max_drawdown_pct", 35.0) or 35.0)
        min_edge = float(cfg_get(self.config, "alpha_factory.min_edge_after_cost_bps", 0.0) or 0.0)

        if scorecard.sample_size < min_sample:
            blockers.append("insufficient_sample")
        if scorecard.expectancy is None or float(scorecard.expectancy) <= 0:
            blockers.append("negative_or_missing_expectancy")
        if scorecard.profit_factor is None or float(scorecard.profit_factor) < min_pf:
            blockers.append("profit_factor_below_threshold")
        if scorecard.max_drawdown_pct is not None and float(scorecard.max_drawdown_pct) > max_dd:
            blockers.append("drawdown_too_high")
        if scorecard.edge_after_cost_bps is None or float(scorecard.edge_after_cost_bps) <= min_edge:
            blockers.append("edge_after_cost_not_positive")
        if scorecard.data_freshness_status not in ("fresh", "cached_ok", "unknown"):
            blockers.append("data_not_fresh")
        if scorecard.recent_loss_cooldown_until and scorecard.recent_loss_cooldown_until > datetime.utcnow():
            blockers.append("recent_negative_expectancy_cooldown")

        blockers = sorted(set(blockers))
        only_sample_blocked = blockers == ["insufficient_sample"]
        has_positive_core = (
            scorecard.expectancy is not None
            and float(scorecard.expectancy) > 0
            and scorecard.profit_factor is not None
            and float(scorecard.profit_factor) >= min_pf
            and scorecard.edge_after_cost_bps is not None
            and float(scorecard.edge_after_cost_bps) > min_edge
        )
        if "recent_negative_expectancy_cooldown" in blockers:
            verdict = "paper_quarantined"
            reason = "Quarantined after recent negative paper expectancy."
        elif only_sample_blocked and has_positive_core:
            verdict = "promising"
            reason = "Promising but still below autonomous sample-size requirement."
        elif blockers:
            verdict = "unproven" if "insufficient_sample" in blockers else "rejected"
            reason = f"Rejected by deterministic evidence gate: {', '.join(blockers[:5])}."
        else:
            verdict = "paper_candidate"
            reason = (
                f"{scorecard.symbol} {scorecard.strategy_family} has positive after-cost evidence "
                f"(PF {scorecard.profit_factor}, sample {scorecard.sample_size})."
            )
        scorecard.verdict = verdict
        scorecard.current_stage = verdict
        scorecard.blocker_reasons_json = blockers
        scorecard.promotion_reason = reason
        scorecard.updated_at = datetime.utcnow()
        self.session.add(scorecard)
        self._sync_registry(scorecard)
        return scorecard

    def quarantine_recent_losses(self, *, symbol: str, strategy_id: str, reason: str = "recent_losses") -> dict[str, Any]:
        norm = self._norm(symbol)
        rows = list(
            self.session.exec(
                select(AlphaScorecard).where(
                    AlphaScorecard.normalized_symbol == norm,
                    AlphaScorecard.strategy_id == strategy_id,
                )
            ).all()
        )
        cooldown = datetime.utcnow() + timedelta(
            minutes=int(cfg_get(self.config, "alpha_factory.quarantine_cooldown_minutes", 120) or 120)
        )
        for row in rows:
            row.verdict = "paper_quarantined"
            row.current_stage = "paper_quarantined"
            row.recent_loss_cooldown_until = cooldown
            row.blocker_reasons_json = sorted(set((row.blocker_reasons_json or []) + [reason]))
            row.promotion_reason = f"Autonomous quarantine: {reason}."
            row.updated_at = datetime.utcnow()
            self.session.add(row)
            self._sync_registry(row)
        return {"status": "ok", "quarantined": len(rows), "cooldown_until": cooldown.isoformat() + "Z"}

    def _sync_registry(self, sc: AlphaScorecard) -> None:
        reg = self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == sc.strategy_id)
        ).first()
        if not reg:
            reg = StrategyRegistry(
                strategy_id=sc.strategy_id,
                name=sc.strategy_family.replace("_", " ").title(),
                family=sc.strategy_family,
                asset_class=sc.asset_class,
                symbols=[sc.symbol],
                timeframe=sc.timeframe,
                current_stage=sc.current_stage,
                can_trade_paper=sc.verdict in PAPER_ALLOWED_VERDICTS,
                can_trade_live=False,
                live_locked=True,
            )
        else:
            symbols = list(reg.symbols or [])
            if sc.symbol not in symbols:
                symbols.append(sc.symbol)
                reg.symbols = symbols
            reg.current_stage = sc.current_stage
            reg.can_trade_paper = sc.verdict in PAPER_ALLOWED_VERDICTS
            reg.can_trade_live = False
            reg.live_locked = True
            reg.latest_backtest_run_id = sc.last_backtest_run_id
            reg.latest_walk_forward_id = sc.last_walk_forward_run_id
        reg.current_score = sc.scorecard_json.get("composite_score") if isinstance(sc.scorecard_json, dict) else None
        reg.quarantine_status = "active" if sc.verdict == "paper_quarantined" else None
        reg.updated_at = datetime.utcnow()
        self.session.add(reg)

    @staticmethod
    def _norm(symbol: str) -> str:
        return str(symbol or "").upper().replace("/", "").replace("-", "").strip()
