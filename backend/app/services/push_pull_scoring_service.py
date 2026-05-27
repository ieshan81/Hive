"""Live push-pull scoring — score_push_pull_setup on every scan symbol."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PositionSnapshot, StrategyRegistry
from app.services.bar_freshness_service import BarFreshnessService
from app.services.config_manager import ConfigManager
from app.services.historical_data_service import HistoricalDataService
from app.services.quote_freshness_service import QuoteFreshnessService
from app.trading_cage.push_pull_engine import score_push_pull_setup

STRATEGY_VERSION_DEFAULT = "baseline"
SCORING_MODEL = "score_push_pull_setup"


def _strategy_version(session: Session) -> str:
    reg = session.exec(
        select(StrategyRegistry).where(StrategyRegistry.strategy_id == "crypto_push_pull_baseline")
    ).first()
    if reg and getattr(reg, "version", None):
        return str(reg.version)
    params = (reg.active_parameters_json or {}) if reg else {}
    return str(params.get("version") or STRATEGY_VERSION_DEFAULT)


def _asset_class_for(symbol: str, row: Optional[dict] = None) -> str:
    asset = str((row or {}).get("asset_type") or "").lower()
    if asset in ("crypto", "stock"):
        return asset
    return "crypto" if "/" in symbol else "stock"


def _thresholds(config: dict) -> dict[str, float]:
    pp = config.get("push_pull") or {}
    return {
        "push_strength_min": float(pp.get("push_strength_min", 0.004)),
        "body_pct_min": float(pp.get("body_pct_min", 0.35)),
        "volume_spike_min": float(pp.get("volume_spike_min", 1.5)),
        "max_spread_bps": float(pp.get("max_spread_bps", 50.0)),
        "max_quote_age_seconds": float(pp.get("max_quote_age_seconds", 30.0)),
        "max_bar_age_minutes": float(pp.get("max_bar_age_minutes", 120.0)),
    }


def _metrics_from_bars(bars: list[dict], quote: dict) -> dict[str, Any]:
    if len(bars) < 3:
        return {}
    last = bars[-1]
    prev = bars[-2]
    c0 = float(last.get("close") or 0)
    c1 = float(prev.get("close") or 0)
    hi = float(last.get("high") or c0)
    lo = float(last.get("low") or c0)
    vols = [float(b.get("volume") or 0) for b in bars[-20:]]
    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1) if len(vols) > 1 else 1.0
    last_vol = vols[-1] if vols else 0.0
    body_pct = abs(c0 - float(last.get("open") or c0)) / max(hi - lo, 1e-9) if hi > lo else 0.0
    mom_1h = (c0 - c1) / c1 if c1 > 0 else 0.0
    if len(bars) >= 13:
        c12 = float(bars[-13].get("close") or 0)
        if c12 > 0:
            mom_1h = (c0 - c12) / c12
    mid = quote.get("mid") or ((quote.get("bid") or 0) + (quote.get("ask") or 0)) / 2
    spread_pct = quote.get("spread_pct")
    if spread_pct is None and quote.get("bid") and quote.get("ask") and mid:
        spread_pct = (float(quote["ask"]) - float(quote["bid"])) / float(mid)
    return {
        "momentum_1h": mom_1h,
        "body_pct": min(1.0, body_pct),
        "volume_spike": last_vol / max(avg_vol, 1e-9),
        "spread_pct": spread_pct,
        "expected_move_pct": abs(mom_1h) * 100.0,
        "current_price": mid or c0,
    }


def score_symbol(
    session: Session,
    config: dict,
    symbol: str,
    *,
    universe_row: Optional[dict] = None,
    has_position: bool = False,
) -> dict[str, Any]:
    """Score one symbol with research model score_push_pull_setup."""
    asset_class = _asset_class_for(symbol, universe_row)
    strategy_id = "crypto_push_pull_baseline" if asset_class == "crypto" else "stock_push_pull_baseline"
    bar_svc = BarFreshnessService(session, config)
    quote_svc = QuoteFreshnessService(session, config)
    bar_chk = bar_svc.check(symbol, timeframe="5Min", allow_fetch=False)
    quote_chk = quote_svc.check(symbol, asset_class=asset_class)
    quote = {
        "bid": quote_chk.get("bid"),
        "ask": quote_chk.get("ask"),
        "spread_pct": quote_chk.get("spread_pct"),
        "quote_timestamp": quote_chk.get("last_quote_at"),
        "mid": None,
    }
    if quote.get("bid") and quote.get("ask"):
        quote["mid"] = (float(quote["bid"]) + float(quote["ask"])) / 2

    hist = HistoricalDataService(session, config)
    bars, _meta = hist.get_bars(symbol, timeframe="5Min", min_rows=14, lookback_days=14)
    metrics = _metrics_from_bars(bars, quote)
    bar_age_min = None
    if bar_chk.get("staleness_hours") is not None:
        bar_age_min = float(bar_chk["staleness_hours"]) * 60.0

    tier = "TIER_MAJOR" if symbol in ("BTC/USD", "ETH/USD", "SPY", "QQQ", "AAPL", "MSFT", "NVDA") else "TIER_ALT"
    scored = score_push_pull_setup(
        config,
        symbol=symbol,
        momentum_1h=metrics.get("momentum_1h"),
        body_pct=metrics.get("body_pct"),
        volume_spike=metrics.get("volume_spike"),
        spread_pct=metrics.get("spread_pct"),
        quote_age_seconds=quote_chk.get("quote_age_seconds"),
        bar_age_minutes=bar_age_min,
        expected_move_pct=metrics.get("expected_move_pct"),
        tier=tier,
        vwap_confirm=bool(metrics.get("body_pct", 0) >= _thresholds(config)["body_pct_min"]),
        ema_confirm=bool(metrics.get("momentum_1h", 0) >= _thresholds(config)["push_strength_min"]),
        atr_valid=bar_chk.get("fresh", False),
    )
    pull_exit = scored.pull_exit_score if has_position else None
    version = _strategy_version(session)
    th = _thresholds(config)
    return {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "asset_class": asset_class,
        "strategy_version": version,
        "scoring_model": SCORING_MODEL,
        "push_score": scored.push_score,
        "pull_exit_score": pull_exit,
        "trade_quality_score": scored.trade_quality_score,
        "edge_after_cost_bps": scored.edge_after_cost_bps,
        "entry_allowed": scored.entry_allowed,
        "no_trade_reason": scored.no_trade_reason,
        "gate_results": scored.gate_results,
        "score_components": scored.evidence,
        "threshold_values": th,
        "bar_freshness": bar_chk.get("bar_freshness"),
        "quote_freshness": quote_chk.get("quote_freshness"),
        "bars_count": len(bars),
        "universe_status": (universe_row or {}).get("status"),
        "blocked_reason": (universe_row or {}).get("blocked_reason"),
    }


def score_active_universe(
    session: Session,
    config: Optional[dict] = None,
    *,
    universe: Optional[list[dict]] = None,
    limit: int = 24,
) -> dict[str, Any]:
    """Score active paper symbols; rank by trade_quality_score."""
    cfg = config or ConfigManager(session).get_current()
    from app.services.alpaca_adapter import AlpacaAdapter

    adapter = AlpacaAdapter(session)
    if getattr(adapter, "broker_sync_rate_limited", False):
        return {
            "status": "degraded",
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "reason": "alpaca_rate_limited",
            "scoring_model": SCORING_MODEL,
            "strategy_version": _strategy_version(session),
            "scores": [],
            "selected_candidate": None,
            "rejected_candidates": [],
            "no_trade_reason_breakdown": {"alpaca_rate_limited": 1},
        }
    if universe is None:
        from app.services.universe_builder import build_merged_universe

        universe = build_merged_universe(session, cfg, limit=60, lightweight=True)

    positions = session.exec(select(PositionSnapshot)).all()
    open_syms = {
        p.symbol.upper().replace("/", "")
        for p in positions
        if (p.qty or 0) > 0
    }

    active_assets = [
        u
        for u in universe
        if u.get("status") == "Active" and u.get("asset_type") in ("Crypto", "Stock")
    ][:limit]

    scored_rows: list[dict[str, Any]] = []
    for row in active_assets:
        sym = row.get("symbol") or ""
        norm = sym.upper().replace("/", "")
        has_pos = norm in open_syms
        try:
            scored_rows.append(
                score_symbol(session, cfg, sym, universe_row=row, has_position=has_pos)
            )
        except Exception as exc:
            scored_rows.append(
                {
                    "symbol": sym,
                    "scoring_model": SCORING_MODEL,
                    "entry_allowed": False,
                    "no_trade_reason": f"SCORE_ERROR:{type(exc).__name__}",
                    "trade_quality_score": 0.0,
                }
            )

    ranked = sorted(scored_rows, key=lambda x: float(x.get("trade_quality_score") or 0), reverse=True)
    selected = next((r for r in ranked if r.get("entry_allowed")), None)
    rejected = [
        {
            "symbol": r.get("symbol"),
            "trade_quality_score": r.get("trade_quality_score"),
            "no_trade_reason": r.get("no_trade_reason"),
            "push_score": r.get("push_score"),
        }
        for r in ranked
        if r.get("symbol") != (selected or {}).get("symbol")
    ]

    breakdown: Counter[str] = Counter()
    for r in ranked:
        reason = r.get("no_trade_reason") or "unknown"
        breakdown[str(reason)] += 1

    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "scoring_model": SCORING_MODEL,
        "strategy_version": _strategy_version(session),
        "symbols_scored": len(ranked),
        "scores": ranked,
        "selected_candidate": selected,
        "rejected_candidates": rejected[:20],
        "no_trade_reason_breakdown": dict(breakdown),
        "threshold_values": _thresholds(cfg),
    }


def push_pull_scores_export(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    return score_active_universe(session, config)


def no_trade_reason_breakdown_export(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    scored = score_active_universe(session, config)
    return {
        "status": "ok",
        "generated_at_utc": scored.get("generated_at_utc"),
        "breakdown": scored.get("no_trade_reason_breakdown"),
        "selected_candidate": scored.get("selected_candidate"),
        "top_rejected": scored.get("rejected_candidates", [])[:10],
    }
