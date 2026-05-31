"""Live push-pull scoring — score_push_pull_setup on every scan symbol."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PositionSnapshot, StrategyRegistry
from app.services.bar_freshness_service import BarFreshnessService
from app.services.candlestick_pattern_engine import top_pattern
from app.services.config_manager import ConfigManager
from app.services.dynamic_exit_levels_service import compute_dynamic_exit_levels
from app.services.engine_config import cfg_get
from app.services.ratchet_exit_service import apply_paper_ratchet_entry, entry_min_bars, paper_ratchet_enabled
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


def _paper_exploration_on(config: dict) -> bool:
    exp = config.get("exploration") or {}
    promotion = (config.get("promotion") or {}).get("current_stage", "PAPER")
    execution = config.get("execution") or {}
    live_orders = bool(execution.get("live_orders_enabled", False)) or bool(config.get("live_trading_enabled", False))
    return promotion == "PAPER" and bool(exp.get("enabled", True)) and not live_orders


def _trade_all_eligible_on(config: dict) -> bool:
    explicit = cfg_get(config, "universe.trade_all_eligible", None)
    if explicit is not None:
        return bool(explicit)
    from app.services.scan_limits import zero_means_unlimited

    return zero_means_unlimited(cfg_get(config, "universe.max_execution_shortlist", 0))


def _has_complete_exit_levels(row: dict[str, Any]) -> bool:
    levels = row.get("dynamic_exit_levels") or {}
    if levels.get("status") == "unavailable":
        return False
    required = ("stop_loss", "take_profit", "trailing_stop", "invalidation_price")
    return all(levels.get(k) is not None for k in required)


def _promote_paper_row(row: dict[str, Any]) -> dict[str, Any]:
    original_reason = row.get("no_trade_reason") or "strict_gate_failed"
    probe = dict(row)
    probe["entry_allowed"] = True
    probe["paper_exploration_probe"] = True
    probe["paper_probe_original_reason"] = original_reason
    probe["no_trade_reason"] = None
    probe["soft_concerns"] = list(dict.fromkeys((probe.get("soft_concerns") or []) + [original_reason]))
    evidence = dict(probe.get("score_components") or {})
    evidence["paper_exploration_probe"] = True
    evidence["paper_probe_original_reason"] = original_reason
    probe["score_components"] = evidence
    probe["thesis"] = (
        f"Paper entry with pattern TP/SL bands despite {original_reason}; "
        "dynamic stop, target, trailing, and invalidation define the experiment."
    )
    return probe


def _paper_probe_eligible(row: dict[str, Any], config: Optional[dict] = None) -> bool:
    cfg = config or {}
    levels = row.get("dynamic_exit_levels") or {}
    gates = row.get("gate_results") or {}
    if not _has_complete_exit_levels(row):
        return False
    if row.get("entry_allowed") is True:
        return False
    reason = str(row.get("no_trade_reason") or "").upper()
    if "SCORE_ERROR" in reason or "INSUFFICIENT" in reason:
        return False

    bar_ok = row.get("bar_freshness") == "fresh" or bool(gates.get("bar_fresh"))
    if not bar_ok and not (paper_ratchet_enabled(cfg) and int(row.get("bars_count") or 0) >= entry_min_bars(cfg)):
        return False

    if _trade_all_eligible_on(cfg):
        # Full-universe paper mode: pattern SL/TP bands define risk; structure/edge are soft.
        return int(row.get("bars_count") or 0) >= 10

    if gates.get("long_structure_ok") is False:
        return False
    data_ready = (
        row.get("quote_freshness") == "fresh"
        and bool(gates.get("quote_fresh", True))
        and bool(gates.get("spread_ok", True))
    )
    return bool(data_ready)


def _metrics_from_bars(bars: list[dict], quote: dict) -> dict[str, Any]:
    if len(bars) < 3:
        return {}
    last = bars[-1]
    prev = bars[-2]
    c0 = float(last.get("close") or 0)
    c1 = float(prev.get("close") or 0)
    o0 = float(last.get("open") or c0)
    hi = float(last.get("high") or c0)
    lo = float(last.get("low") or c0)
    vols = [float(b.get("volume") or 0) for b in bars[-20:]]
    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1) if len(vols) > 1 else 1.0
    last_vol = vols[-1] if vols else 0.0
    body_pct = abs(c0 - float(last.get("open") or c0)) / max(hi - lo, 1e-9) if hi > lo else 0.0
    mom_1h = (c0 - c1) / c1 if c1 > 0 else 0.0
    three_bar_return = 0.0
    if len(bars) >= 4:
        c3 = float(bars[-4].get("close") or 0)
        if c3 > 0:
            three_bar_return = (c0 - c3) / c3
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
        "last_candle_return": (c0 - o0) / o0 if o0 > 0 else 0.0,
        "three_bar_return": three_bar_return,
        "last_candle_green": c0 >= o0,
        "body_pct": min(1.0, body_pct),
        "volume_spike": last_vol / max(avg_vol, 1e-9),
        "spread_pct": spread_pct,
        "expected_move_pct": abs(mom_1h) * 100.0,
        "current_price": mid or c0,
    }


def _long_structure_decision(config: dict, pattern: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    """Require a real bullish/reversal structure before a long paper entry.

    Paper mode is allowed to explore weak volume, weak trend confirmation, and
    other soft concerns. It should not treat a large red candle as a long setup
    just because absolute movement creates a high expected-move estimate.
    """

    pp = config.get("push_pull") or {}
    structure_cfg = pp.get("long_structure") or {}
    if structure_cfg.get("enabled", True) is False or _trade_all_eligible_on(config):
        return {"long_structure_ok": True, "reason": "structure_filter_disabled"}

    pattern_name = str(pattern.get("pattern") or "none")
    pattern_direction = str(pattern.get("direction") or "neutral")
    pattern_conf = float(pattern.get("confidence") or 0.0)
    min_pattern_conf = float(structure_cfg.get("min_bullish_pattern_confidence", 0.45))
    max_negative_momentum = float(structure_cfg.get("max_negative_momentum_without_pattern", -0.0005))

    bullish_pattern = pattern_direction == "long" and pattern_name != "none" and pattern_conf >= min_pattern_conf
    bearish_pattern = pattern_direction == "short" and pattern_conf >= min_pattern_conf

    last_green = bool(metrics.get("last_candle_green"))
    momentum = float(metrics.get("momentum_1h") or 0.0)
    three_bar = float(metrics.get("three_bar_return") or 0.0)
    last_return = float(metrics.get("last_candle_return") or 0.0)

    bullish_continuation = last_green and (momentum >= max_negative_momentum or three_bar >= 0)
    bearish_tape = bearish_pattern or ((not last_green) and momentum < 0 and three_bar <= 0)

    if bullish_pattern or bullish_continuation:
        return {
            "long_structure_ok": True,
            "reason": "bullish_pattern" if bullish_pattern else "bullish_continuation",
            "pattern": pattern_name,
            "pattern_direction": pattern_direction,
            "pattern_confidence": round(pattern_conf, 4),
            "last_candle_green": last_green,
            "last_candle_return": round(last_return, 6),
            "momentum_1h": round(momentum, 6),
            "three_bar_return": round(three_bar, 6),
        }

    return {
        "long_structure_ok": False,
        "reason": "BEARISH_STRUCTURE_NO_LONG_ENTRY" if bearish_tape else "NO_BULLISH_LONG_STRUCTURE",
        "pattern": pattern_name,
        "pattern_direction": pattern_direction,
        "pattern_confidence": round(pattern_conf, 4),
        "last_candle_green": last_green,
        "last_candle_return": round(last_return, 6),
        "momentum_1h": round(momentum, 6),
        "three_bar_return": round(three_bar, 6),
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
    allow_bar_fetch = _trade_all_eligible_on(config) or _paper_exploration_on(config)
    bar_chk = bar_svc.check(symbol, timeframe="5Min", allow_fetch=allow_bar_fetch)
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
    if not bar_chk.get("fresh") and bars and len(bars) >= 10:
        from app.services.historical_data_service import _parse_ts
        from datetime import datetime

        last_ts = _parse_ts(bars[-1]["timestamp"])
        age_h = (datetime.utcnow() - last_ts).total_seconds() / 3600.0
        max_h = float(cfg_get(config, "universe.max_bar_staleness_hours", 96))
        if age_h <= max_h:
            bar_chk = {
                **bar_chk,
                "fresh": True,
                "executable": True,
                "bar_freshness": "fresh",
                "staleness_hours": round(age_h, 1),
            }
    pattern = top_pattern(bars)
    pattern_direction = str(pattern.get("direction") or "long")
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
        pattern_confidence=float(pattern.get("confidence") or 0.0),
        pullback_quality_score=float(pattern.get("pullback_quality_score") or 0.45),
        reversal_risk_score=float(pattern.get("reversal_risk_score") or 0.35),
        continuation_score=float(pattern.get("continuation_score") or 0.45),
    )
    structure = _long_structure_decision(config, pattern, metrics)
    gate_results = dict(scored.gate_results)
    gate_results["long_structure_ok"] = bool(structure.get("long_structure_ok"))
    score_components = dict(scored.evidence)
    score_components["long_structure"] = structure
    entry_allowed = bool(scored.entry_allowed) and bool(structure.get("long_structure_ok"))
    no_trade_reason = scored.no_trade_reason
    base_trade_quality = float(scored.trade_quality_score or 0.0)
    trade_quality = base_trade_quality
    sentiment_ctx: dict[str, Any] = {}
    try:
        from app.services.sentiment_service import (
            apply_sentiment_ranking_modifier,
            resolve_sentiment_for_ranking,
        )

        sentiment_ctx = resolve_sentiment_for_ranking(config, symbol, side="buy")
        if sentiment_ctx.get("used_in_ranking"):
            trade_quality = apply_sentiment_ranking_modifier(
                base_trade_quality, float(sentiment_ctx.get("sentiment_alignment") or 0.0)
            )
    except Exception:
        sentiment_ctx = {"used_in_ranking": False, "sentiment_alignment": 0.0}
    if scored.entry_allowed and not structure.get("long_structure_ok"):
        no_trade_reason = str(structure.get("reason") or "NO_BULLISH_LONG_STRUCTURE")
        trade_quality = min(float(trade_quality or 0.0), 0.34)
        score_components["bearish_structure_filter"] = True
    pull_exit = scored.pull_exit_score if has_position else None
    version = _strategy_version(session)
    th = _thresholds(config)
    dynamic_levels = None
    entry_price = float(metrics.get("current_price") or quote.get("mid") or 0)
    if entry_price > 0:
        try:
            dynamic_levels = compute_dynamic_exit_levels(
                config,
                symbol=symbol,
                side="buy",
                entry_price=entry_price,
                current_price=entry_price,
                bars=bars,
                quote=quote,
                signal_meta={
                    "push_score": scored.push_score,
                    "trade_quality_score": base_trade_quality,
                    "edge_after_cost_bps": scored.edge_after_cost_bps,
                    "pattern_confidence": pattern.get("confidence"),
                    "reversal_risk_score": pattern.get("reversal_risk_score"),
                    "score_components": scored.evidence,
                },
                tier=tier,
            ).to_dict()
        except Exception as exc:
            dynamic_levels = {"status": "unavailable", "error": type(exc).__name__}
    row = {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "asset_class": asset_class,
        "strategy_version": version,
        "scoring_model": SCORING_MODEL,
        "push_score": scored.push_score,
        "pull_exit_score": pull_exit,
        "trade_quality_score": round(float(trade_quality or 0.0), 4),
        "base_trade_quality_score": round(base_trade_quality, 4),
        "sentiment_score": sentiment_ctx.get("sentiment_score"),
        "sentiment_alignment": sentiment_ctx.get("sentiment_alignment"),
        "sentiment_used_in_ranking": bool(sentiment_ctx.get("used_in_ranking")),
        "sentiment_model_used": sentiment_ctx.get("model_used"),
        "edge_after_cost_bps": scored.edge_after_cost_bps,
        "entry_allowed": entry_allowed,
        "no_trade_reason": no_trade_reason,
        "gate_results": gate_results,
        "score_components": score_components,
        "pattern": pattern,
        "pattern_name": pattern.get("pattern"),
        "pattern_confidence": pattern.get("confidence"),
        "pullback_quality_score": pattern.get("pullback_quality_score"),
        "reversal_risk_score": pattern.get("reversal_risk_score"),
        "continuation_score": pattern.get("continuation_score"),
        "paper_exploration": scored.evidence.get("paper_exploration"),
        "soft_concerns": scored.evidence.get("soft_concerns") or [],
        "dynamic_exit_levels": dynamic_levels,
        "stop_loss": (dynamic_levels or {}).get("stop_loss"),
        "take_profit": (dynamic_levels or {}).get("take_profit"),
        "trailing_stop": (dynamic_levels or {}).get("trailing_stop"),
        "invalidation_price": (dynamic_levels or {}).get("invalidation_price"),
        "risk_reward": (dynamic_levels or {}).get("risk_reward"),
        "threshold_values": th,
        "bar_freshness": bar_chk.get("bar_freshness"),
        "quote_freshness": quote_chk.get("quote_freshness"),
        "bars_count": len(bars),
        "universe_status": (universe_row or {}).get("status"),
        "blocked_reason": (universe_row or {}).get("blocked_reason"),
        "thesis": _thesis_for(pattern, entry_allowed, no_trade_reason, pattern_direction),
    }
    row = apply_paper_ratchet_entry(row, config, bars=bars)
    return row


def _thesis_for(pattern: dict[str, Any], entry_allowed: bool, reason: Optional[str], direction: str) -> str:
    name = str(pattern.get("pattern") or "none").replace("_", " ")
    if entry_allowed:
        return f"Paper exploration can test {name} {direction} setup; dynamic exit bars define the risk."
    if reason:
        return f"{name.title()} observed, but hard execution gate reports {reason}."
    return f"{name.title()} context is being monitored for a controlled pullback."


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
        from app.services.scan_limits import scan_limit, slice_limit

        universe_limit = scan_limit(cfg, "universe.max_scanned_symbols_per_cycle", 0)
        universe = build_merged_universe(session, cfg, limit=universe_limit, lightweight=True)

    eval_limit = limit
    if limit <= 0:
        from app.services.scan_limits import scan_limit

        eval_limit = scan_limit(cfg, "universe.max_scanned_symbols_per_cycle", 0)

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
    ]
    from app.services.scan_limits import slice_limit

    active_assets = slice_limit(active_assets, eval_limit)

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
    if _paper_exploration_on(cfg):
        if _trade_all_eligible_on(cfg):
            for idx, row in enumerate(ranked):
                if row.get("entry_allowed") or not _paper_probe_eligible(row, cfg):
                    continue
                ranked[idx] = _promote_paper_row(row)
            selected = next((r for r in ranked if r.get("entry_allowed")), None)
        elif selected is None:
            for idx, row in enumerate(ranked):
                if not _paper_probe_eligible(row, cfg):
                    continue
                ranked[idx] = _promote_paper_row(row)
                selected = ranked[idx]
                break
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
        reason = str(r.get("no_trade_reason") or "unknown")
        if reason.upper() in ("DATA_STALE", "STALE_BAR", "NO_BARS"):
            reason = "stale_bar"
        breakdown[reason] += 1

    fresh_count = sum(1 for r in ranked if r.get("bar_freshness") == "fresh")
    eligible_count = sum(1 for r in ranked if r.get("entry_allowed"))

    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "scoring_model": SCORING_MODEL,
        "strategy_version": _strategy_version(session),
        "symbols_scored": len(ranked),
        "fresh_count": fresh_count,
        "eligible_count": eligible_count,
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
