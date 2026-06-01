"""Deterministic strategy-candidate generator for the Alpha Factory.

This is research-only. Gemini may suggest hypotheses elsewhere, but this module
does not call an LLM and never approves or submits trades.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ResearchBacktestRun, SymbolCandidate
from app.services.engine_config import cfg_get


def _norm(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").strip()


STRATEGY_FAMILIES: list[dict[str, Any]] = [
    {
        "strategy_family": "momentum_continuation",
        "strategy_id": "crypto_push_pull_baseline",
        "candidate_name": "Momentum Continuation",
        "parameter_ranges": {
            "lookback_bars": [1, 3, 6],
            "momentum_threshold_1h": [0.0025, 0.004, 0.006],
            "atr_stop_multiplier": [0.8, 1.0, 1.4],
            "take_profit_r_multiple": [1.2, 1.6, 2.0],
        },
        "hypothesis": "Fresh momentum with volume confirmation can continue if costs are small.",
        "expected_behavior": "Small paper entries only after positive after-cost evidence.",
        "invalidation_rules": ["stale_quote", "stale_bar", "spread_expansion", "momentum_reversal"],
        "required_data": ["bars_1m", "bars_5m", "quote", "spread"],
        "risk_notes": "ATR stop and take-profit levels required before any paper entry.",
    },
    {
        "strategy_family": "breakout_retest",
        "strategy_id": "crypto_push_pull_baseline",
        "candidate_name": "Breakout Retest",
        "parameter_ranges": {
            "lookback_bars": [12, 24, 48],
            "retest_tolerance_pct": [0.001, 0.0025],
            "atr_stop_multiplier": [1.0, 1.5],
        },
        "hypothesis": "Range breakout followed by retest may produce cleaner entries than chasing.",
        "expected_behavior": "Waits for retest confirmation and exits on failed breakout.",
        "invalidation_rules": ["failed_breakout", "range_reentry", "volume_fade"],
        "required_data": ["bars_5m", "bars_15m", "volume", "quote"],
        "risk_notes": "Reject when retest level is too close to round-trip cost.",
    },
    {
        "strategy_family": "mean_reversion_snapback",
        "strategy_id": "crypto_mean_reversion",
        "candidate_name": "Mean Reversion Snapback",
        "parameter_ranges": {
            "lookback": [12, 24, 48],
            "z_entry": [1.5, 2.0, 2.5],
            "atr_stop_multiplier": [0.8, 1.2],
        },
        "hypothesis": "Overextended liquid symbols can snap back toward mean/VWAP.",
        "expected_behavior": "Trades only liquid symbols with strict stop and cost filter.",
        "invalidation_rules": ["trend_acceleration", "spread_expansion", "liquidity_weak"],
        "required_data": ["bars_5m", "volatility", "spread"],
        "risk_notes": "Avoid meme/tiny liquidity unless spread is exceptionally tight.",
    },
    {
        "strategy_family": "volatility_compression_breakout",
        "strategy_id": "crypto_volatility_breakout",
        "candidate_name": "Volatility Compression Breakout",
        "parameter_ranges": {
            "range_lookback": [10, 14, 24],
            "atr_expansion_mult": [1.25, 1.5, 2.0],
            "volume_spike_threshold": [1.3, 1.8],
        },
        "hypothesis": "Compression plus sudden expansion can create a short-lived edge.",
        "expected_behavior": "Fires only when volatility expansion direction is confirmed.",
        "invalidation_rules": ["false_breakout", "quote_stale", "spread_shock"],
        "required_data": ["bars_1m", "bars_5m", "volume", "spread"],
        "risk_notes": "High turnover is penalized in promotion.",
    },
    {
        "strategy_family": "sentiment_assisted_momentum",
        "strategy_id": "crypto_push_pull_baseline",
        "candidate_name": "Sentiment-Assisted Momentum",
        "parameter_ranges": {
            "lookback_bars": [1, 3, 6],
            "sentiment_adjustment_cap": [0.05, 0.1],
            "momentum_threshold_1h": [0.003, 0.005],
        },
        "hypothesis": "Public sentiment can rank price/volume setups but cannot create permission alone.",
        "expected_behavior": "Sentiment adjusts ranking only after price/volume gates pass.",
        "invalidation_rules": ["pump_dump_risk", "sentiment_price_divergence", "stale_quote"],
        "required_data": ["bars_5m", "quote", "public_sentiment"],
        "risk_notes": "Never trades from sentiment alone.",
    },
    {
        # Longer-horizon experiment: higher timeframe momentum has a larger move budget
        # relative to round-trip cost, so the corrected cost model can leave net edge.
        "strategy_family": "higher_timeframe_momentum",
        "strategy_id": "crypto_push_pull_baseline",
        "candidate_name": "Higher-Timeframe Momentum (1h/4h)",
        "timeframe": "1h",
        "parameter_ranges": {
            "timeframe": ["1h", "4h"],
            "lookback_bars": [6, 12, 24],
            "momentum_threshold": [0.01, 0.02, 0.035],
            "atr_stop_multiplier": [1.2, 1.6, 2.0],
            "take_profit_r_multiple": [1.5, 2.0, 3.0],
        },
        "hypothesis": "On 1h/4h bars the expected move is large vs round-trip cost, so a small after-cost edge can survive.",
        "expected_behavior": "Fewer, larger paper entries; only after positive after-cost evidence on the higher timeframe.",
        "invalidation_rules": ["stale_bar", "spread_expansion", "momentum_reversal", "trend_exhaustion"],
        "required_data": ["bars_1h", "bars_4h", "quote", "spread"],
        "risk_notes": "Longer holds; promotion still requires sufficient sample and positive edge after the corrected cost model.",
        "longer_horizon": True,
        "majors_only": ["BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "LINK/USD", "AVAX/USD", "DOGE/USD", "UNI/USD"],
    },
]


class AutonomousStrategyGenerator:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def generate(self, *, symbols: Optional[list[str]] = None, limit: int = 12) -> list[dict[str, Any]]:
        universe = self._symbols(symbols, limit=limit)
        out: list[dict[str, Any]] = []
        for sym in universe:
            asset_class = "crypto" if "/" in sym else "stock"
            for family in STRATEGY_FAMILIES:
                if asset_class == "stock" and str(family["strategy_id"]).startswith("crypto_"):
                    continue
                # Longer-horizon experiments are limited to the approved majors only.
                majors = family.get("majors_only")
                if majors and sym not in majors:
                    continue
                out.append({**family, "symbol": sym, "asset_class": asset_class, "autonomous_generated": True})
        return out

    def _symbols(self, symbols: Optional[list[str]], *, limit: int) -> list[str]:
        if symbols:
            return list(dict.fromkeys([str(s).strip().upper() for s in symbols if str(s).strip()]))[:limit]
        # Build a de-duplicated pool from scanned candidates, then recent research targets.
        pool: list[str] = []
        for row in self.session.exec(
            select(SymbolCandidate).order_by(SymbolCandidate.scanned_at.desc()).limit(limit * 3)
        ).all():
            sym = str(row.symbol or "").upper()
            if sym and sym not in pool:
                pool.append(sym)
        for run in self.session.exec(
            select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.desc()).limit(30)
        ).all():
            for sym in run.symbols or []:
                s = str(sym).upper()
                if s and s not in pool:
                    pool.append(s)
        if not pool:
            pool = ["BTC/USD", "ETH/USD", "SOL/USD"]
        # Rotation: push symbols whose recent research keeps coming back insufficient-sample to
        # the back so fresh setups are researched first instead of re-churning the same thin one.
        thin = self._repeatedly_thin_symbols()
        pool.sort(key=lambda s: 1 if _norm(s) in thin else 0)  # stable: thin symbols last
        return pool[:limit]

    def _repeatedly_thin_symbols(self, *, window: int = 3, min_repeats: int = 2) -> set[str]:
        """Symbols with >= min_repeats insufficient-sample runs among their last `window` runs."""
        min_sample = int(cfg_get(self.config, "alpha_factory.min_sample_size", 5) or 5)
        runs = list(
            self.session.exec(
                select(ResearchBacktestRun).order_by(ResearchBacktestRun.created_at.desc()).limit(200)
            ).all()
        )
        seen: Counter = Counter()
        thin_hits: Counter = Counter()
        for run in runs:  # newest first
            sample = int(run.sample_size or run.num_trades or 0)
            for sym in run.symbols or []:
                key = _norm(sym)
                if seen[key] >= window:
                    continue
                seen[key] += 1
                if sample < min_sample:
                    thin_hits[key] += 1
        return {k for k, hits in thin_hits.items() if hits >= min_repeats}
