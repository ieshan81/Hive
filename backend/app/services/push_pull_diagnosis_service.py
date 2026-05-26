"""Auto-diagnose why no paper order submitted after ticks."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler
from app.services.config_manager import ConfigManager
from app.services.market_data_refresh_service import MarketDataRefreshService
from app.services.paper_order_proof_service import PaperOrderProofService
from app.services.push_pull_engine_service import PushPullEngineService
from app.services.universe_service import universe_status


class PushPullDiagnosisService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()

    def why_no_order(self) -> dict[str, Any]:
        uni = universe_status(self.session, self.config)
        syms = uni.get("symbols") or []
        fresh_bars = sum(1 for s in syms if s.get("bar_freshness") == "fresh")
        stale_bars = sum(1 for s in syms if s.get("bar_freshness") == "stale")
        fresh_quotes = sum(1 for s in syms if s.get("quote_freshness") == "fresh")
        stale_quotes = sum(1 for s in syms if s.get("quote_freshness") == "stale")

        elig = AggressivePaperLearningService(self.session).scan_experiment_eligibility()
        eligible_n = len(elig.get("eligible") or [])

        tick = PushPullEngineService(self.session, self.config).latest_tick()
        rb = tick.get("reason_breakdown") or {}

        proof = PaperOrderProofService(self.session, self.config).summary()
        sched = AutonomousPaperScheduler(self.session, self.config).status()

        try:
            fresh_report = MarketDataRefreshService(self.session, self.config).freshness_report(
                asset_type="crypto"
            )
        except Exception as exc:
            fresh_report = {"error": str(exc)[:200]}

        lines = [
            f"Universe: {uni.get('total_symbols', 0)} symbols ({fresh_bars} fresh bars, {stale_bars} stale bars).",
            f"Quotes: {fresh_quotes} fresh, {stale_quotes} stale.",
            f"Eligible paper strategies: {eligible_n}.",
            f"Latest tick: {tick.get('plain', 'no tick yet')}.",
            f"Broker submits this epoch: {proof['counts'].get('submitted_to_broker', 0)}.",
        ]
        if rb:
            parts = [f"{v} {k.replace('_', ' ')}" for k, v in rb.items()]
            lines.append("Tick breakdown: " + ", ".join(parts[:8]) + ".")

        return {
            "status": "ok",
            "why_no_order": " ".join(lines),
            "universe_total": uni.get("total_symbols"),
            "fresh_bar_count": fresh_bars,
            "stale_bar_count": stale_bars,
            "fresh_quote_count": fresh_quotes,
            "stale_quote_count": stale_quotes,
            "eligible_strategy_count": eligible_n,
            "push_signals_found": tick.get("push_signals_found"),
            "approved_count": tick.get("approved_count"),
            "order_count": tick.get("order_count"),
            "reason_breakdown": rb,
            "quote_refresh_attempts": tick.get("quote_refresh_attempts"),
            "paper_order_proof": proof.get("counts"),
            "scheduler": sched,
            "market_data_freshness": {
                "fresh_count": fresh_report.get("fresh_count"),
                "stale_count": fresh_report.get("stale_count"),
            },
            "operator_next_action": self._next_action(proof, fresh_bars, fresh_quotes, eligible_n),
        }

    def _next_action(self, proof: dict, fresh_bars: int, fresh_quotes: int, eligible_n: int) -> str:
        if proof.get("counts", {}).get("submitted_to_broker", 0) > 0:
            return "Monitor fill and exit monitor — order reached broker."
        if fresh_bars == 0:
            return "Run POST /api/market-data/refresh-bars for priority crypto pairs."
        if eligible_n == 0:
            return "Ensure Crypto Push-Pull Baseline is paper_experiment and has stop-loss params."
        if fresh_quotes == 0:
            return "Quotes may be rate-limited — wait 1–2 min and run another tick."
        return "Run another tick or wait for scheduler — push signals may need spread/edge alignment."
