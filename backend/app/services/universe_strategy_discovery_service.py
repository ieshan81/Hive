"""Universe-wide strategy discovery — funnel breakdown, multi-symbol backtests, verdict."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import HistoricalBar, SettingsActionAudit
from app.services.account_pair_eligibility_service import AccountPairEligibilityService
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.alpaca_crypto_assets import fetch_crypto_assets
from app.services.bar_freshness_service import BarFreshnessService
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.historical_data_service import HistoricalDataService, _parse_ts
from app.services.quote_freshness_service import QuoteFreshnessService
from app.services.research_backtest_engine import ResearchBacktestEngine
from app.services.research_memory_service import ResearchMemoryService
from app.services.research_performance import evaluate_metrics
from app.services.symbol_normalize import symbol_variants
from app.services import universe_ranking_service as urs

ANCHOR_SYMBOLS = ["BTC/USD", "ETH/USD"]
DEFAULT_TOP_N = 10
DEFAULT_TIMEFRAMES = ("5Min", "1Min")
MIN_BARS_BACKTEST = 50

# In-process cache (also persisted to SettingsActionAudit)
_LATEST_DISCOVERY: dict[str, Any] = {}

# Research-backed sweep grid (capped by ParameterSweepEngine max_combo)
PUSH_PULL_SWEEP_GRID: dict[str, list] = {
    "momentum_threshold_1h": [0.003, 0.004, 0.005, 0.006],
    "edge_multiplier": [0.9, 1.0, 1.1],
    "max_spread_pct": [0.003, 0.005, 0.008],
    "max_hold_hours": [6, 12, 24],
    "atr_multiplier": [1.0, 1.5, 2.0],
}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _load_usd_universe() -> tuple[list[str], dict[str, dict]]:
    assets = fetch_crypto_assets(force=False) or {}
    usd = sorted(s for s in assets.keys() if s.endswith("/USD"))
    return usd, assets


def _db_bars_only(session: Session, symbol: str, timeframe: str, limit: int) -> list[dict[str, Any]]:
    variants = symbol_variants(symbol)
    rows = list(
        session.exec(
            select(HistoricalBar)
            .where(HistoricalBar.symbol.in_(variants), HistoricalBar.timeframe == timeframe)
            .order_by(HistoricalBar.timestamp.desc())
            .limit(limit)
        ).all()
    )
    rows.reverse()
    return [
        {
            "timestamp": r.timestamp.isoformat() + "Z",
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        }
        for r in rows
    ]


def _reconcile_stale_bar_block(blocks: list[str], bars: list, config: dict) -> None:
    """Drop stale_bar when cached bars are within configured staleness window."""
    if "stale_bar" not in blocks or not bars or len(bars) < 10:
        return
    last_ts = _parse_ts(bars[-1]["timestamp"])
    age_h = (datetime.utcnow() - last_ts).total_seconds() / 3600.0
    max_h = float(cfg_get(config, "universe.max_bar_staleness_hours", 96))
    if age_h <= max_h:
        blocks.remove("stale_bar")


def evaluate_symbol_blocks(
    session: Session,
    config: dict,
    symbol: str,
    *,
    assets_meta: Optional[dict] = None,
    fetch_quote: bool = True,
) -> dict[str, Any]:
    """Per-symbol gate breakdown — answers why a symbol is not eligible."""
    blocks: list[str] = []
    meta = (assets_meta or {}).get(symbol) or {}
    bar_svc = BarFreshnessService(session, config)
    quote_svc = QuoteFreshnessService(session, config)
    hist = HistoricalDataService(session, config)

    if not meta.get("tradable", True):
        blocks.append("not_tradable")
    quote_ccy = (meta.get("quote_currency") or "USD").upper()
    if quote_ccy in ("USDC", "USDT", "BTC") and symbol not in ("BTC/USD", "ETH/USD"):
        blocks.append("quote_currency_unfunded")

    elig = AccountPairEligibilityService(session, config).classify_symbol(symbol, asset_class="crypto")
    if elig.get("status") != "eligible":
        cat = elig.get("category") or "account_pair_eligibility"
        if cat == "account_pair_eligibility" or "USDC" in str(elig.get("reason", "")) or "USDT" in str(elig.get("reason", "")):
            blocks.append("quote_currency_unfunded")
        elif cat == "market_session":
            blocks.append("market_closed")
        else:
            blocks.append("account_pair_eligibility")

    bar_5m = bar_svc.check_db_only(symbol, timeframe="5Min")
    if not bar_5m.get("fresh"):
        blocks.append("stale_bar")
    bar_1m = bar_svc.check_db_only(symbol, timeframe="1Min")
    require_1m = bool(cfg_get(config, "universe.require_1m_fresh_for_shortlist", False))
    if require_1m and not bar_1m.get("fresh"):
        blocks.append("stale_bar_1m")

    quote = {}
    if fetch_quote:
        try:
            quote = quote_svc.check(symbol, asset_class="crypto")
            if not quote.get("fresh"):
                blocks.append("stale_quote")
            q = quote.get("quote") or {}
            if q.get("bid") is None and q.get("ask") is None:
                blocks.append("stale_or_missing_quote")
        except Exception:
            blocks.append("stale_or_missing_quote")
            quote = {"fresh": False, "quote": {}}

    if fetch_quote:
        bars_5m, bar_meta = hist.get_bars(symbol, timeframe="5Min", min_rows=14, lookback_days=14)
    else:
        bars_5m = _db_bars_only(session, symbol, "5Min", 80)
        bar_meta = {} if len(bars_5m) >= 14 else {"error": f"Only {len(bars_5m)} cached 5Min bars"}
    if bar_meta.get("error") or len(bars_5m) < 14:
        blocks.append("insufficient_historical_bars")
    else:
        _reconcile_stale_bar_block(blocks, bars_5m, config)

    bars_1m = []
    if not bar_meta.get("error"):
        if fetch_quote:
            bars_1m, _ = hist.get_bars(symbol, timeframe="1Min", min_rows=30, lookback_days=7)
        else:
            bars_1m = _db_bars_only(session, symbol, "1Min", 80)

    metrics = {}
    try:
        quote_for_metrics = quote.get("quote") if fetch_quote and isinstance(quote, dict) else {}
        # Cached/page-state scans must not make every symbol vanish merely
        # because we intentionally skipped live quotes. Use the latest bar as a
        # proxy quote for ranking visibility only. Execution still requires a
        # fresh real quote in PaperExecutionService preflight.
        if not fetch_quote and bars_5m:
            last_close = float((bars_5m[-1] or {}).get("close") or 0)
            if last_close > 0:
                quote_for_metrics = {
                    "bid": last_close * 0.9995,
                    "ask": last_close * 1.0005,
                    "mid": last_close,
                    "spread_pct": 0.001,
                    "cached_proxy_quote": True,
                }
        metrics = urs.extract_symbol_metrics(
            symbol, bars_5m or [], quote_for_metrics
        )
    except Exception:
        metrics = {
            "symbol": symbol,
            "eligible": False,
            "ineligible_reason": "stale_or_missing_quote",
        }
        blocks.append("stale_or_missing_quote")
    if metrics.get("ineligible_reason") == "spread_too_wide":
        blocks.append("spread_too_wide")
    if metrics.get("ineligible_reason") == "bar_stale":
        if "stale_bar" not in blocks:
            blocks.append("stale_bar")
    allow_zero_volume = bool(cfg_get(config, "universe.allow_zero_volume_cached_bars_for_paper", True))
    if metrics.get("dollar_volume", 0) <= 0 and bars_5m and not allow_zero_volume:
        blocks.append("liquidity_too_low")

    edge_note = None
    if bars_1m and quote:
        try:
            from app.services.push_pull_scorer import evaluate_entry, classify_regime

            regime = classify_regime(bars_1m)
            ev = evaluate_entry(
                symbol,
                bars_1m,
                bars_5m or bars_1m,
                quote if isinstance(quote, dict) else {},
                universe_rank_score=metrics.get("universe_rank_score", 0.5) if "universe_rank_score" in metrics else 0.5,
                regime=regime,
            )
            if "EDGE_NEGATIVE" in (ev.get("reasons") or []):
                blocks.append("no_edge_after_cost")
            if ev.get("regime") == "panic":
                blocks.append("volatility_regime_panic")
            edge_note = {
                "push_score": ev.get("push_score"),
                "edge_bps": ev.get("edge_bps"),
                "quality_score": ev.get("quality_score"),
            }
        except Exception:
            pass

    try:
        from app.services.sentiment_service import FinBERTScorer

        if not FinBERTScorer.is_available():
            pass  # informational only — does not block universe rank
    except Exception:
        pass

    eligible = len(blocks) == 0
    primary_block = blocks[0] if blocks else None
    return {
        "symbol": symbol,
        "blocks": blocks,
        "eligible": eligible,
        "primary_block": primary_block,
        "metrics": metrics,
        "edge_preview": edge_note,
        "bar_freshness_5m": bar_5m.get("bar_freshness"),
        "quote_freshness": quote.get("quote_freshness") if fetch_quote else "unknown",
    }


def build_funnel_breakdown(
    session: Session,
    config: Optional[dict] = None,
    *,
    max_evaluate: int = 36,
    fetch_quotes: bool = True,
) -> dict[str, Any]:
    """Full funnel with exact block-reason counts."""
    cfg = config or ConfigManager(session).get_current()
    available, assets = _load_usd_universe()
    adapter = AlpacaAdapter(session)
    rate_limited = bool(getattr(adapter, "broker_sync_rate_limited", False))
    if rate_limited:
        fetch_quotes = False
    if not adapter.configured:
        return {
            "status": "degraded",
            "generated_at_utc": _now(),
            "reason": "alpaca_not_configured",
            "answer": "Alpaca not configured — cannot evaluate universe.",
            "available_symbols": len(available),
            "evaluated_symbols": 0,
            "block_breakdown": {},
            "degraded": True,
        }

    eval_syms = available[:max_evaluate]
    per_symbol: list[dict] = []
    block_counter: Counter[str] = Counter()
    stale_symbols: list[str] = []
    unavailable_symbols: list[str] = []

    for sym in eval_syms:
        try:
            row = evaluate_symbol_blocks(
                session, cfg, sym, assets_meta=assets, fetch_quote=fetch_quotes
            )
        except Exception as exc:
            row = {
                "symbol": sym,
                "blocks": ["evaluation_error"],
                "eligible": False,
                "primary_block": "evaluation_error",
                "metrics": {
                    "symbol": sym,
                    "eligible": False,
                    "ineligible_reason": "stale_or_missing_quote",
                },
                "error": type(exc).__name__,
            }
            unavailable_symbols.append(sym)
        per_symbol.append(row)
        for b in row.get("blocks") or []:
            block_counter[b] += 1
        if "stale_or_missing_quote" in (row.get("blocks") or []):
            stale_symbols.append(sym)
        if row.get("error"):
            unavailable_symbols.append(sym)

    metrics = [r["metrics"] for r in per_symbol if r.get("metrics")]
    ranked = urs.rank_universe(metrics, config=cfg)
    rank_by_sym = {r["symbol"]: r for r in ranked}

    eligible_rows = []
    for r in per_symbol:
        m = rank_by_sym.get(r["symbol"], {})
        rank_score = float(m.get("universe_rank_score") or 0)
        dropped = bool(m.get("dropped", True))
        if r.get("eligible") and not dropped:
            eligible_rows.append({**m, "blocks": r.get("blocks")})

    snapshot = urs.build_pipeline_snapshot(available, metrics, ranked, max_shortlist=0)
    # build_pipeline_snapshot only knows metric-level eligibility. Override
    # the candidate layers with the stricter deterministic gate result from
    # evaluate_symbol_blocks so stale bars, account blocks, and other cage
    # blockers do not leak into execution lists.
    from app.services.scan_limits import scan_limit, slice_limit

    exec_cap = scan_limit(cfg, "universe.max_execution_shortlist", 0)
    snapshot["eligible"] = eligible_rows
    snapshot["shortlist"] = slice_limit(eligible_rows, exec_cap)
    snapshot.setdefault("funnel", {})
    fresh_count = sum(
        1
        for r in per_symbol
        if "stale_bar" not in (r.get("blocks") or [])
        and "stale_bar_1m" not in (r.get("blocks") or [])
        and "insufficient_historical_bars" not in (r.get("blocks") or [])
    )
    snapshot["funnel"]["fresh"] = fresh_count
    snapshot["funnel"]["eligible"] = len(eligible_rows)
    snapshot["funnel"]["ranked"] = len(eligible_rows)
    snapshot["funnel"]["execution_shortlist"] = len(snapshot["shortlist"])

    n_avail = len(available)
    n_eval = len(eval_syms)
    n_eligible = len(eligible_rows)
    n_ranked = n_eligible
    n_short = len(snapshot.get("shortlist") or [])

    top_blocks = block_counter.most_common(12)
    answer_parts = []
    if n_eligible == 0 and n_eval > 0:
        answer_parts.append(
            f"{n_avail} USD pairs available; evaluated {n_eval}; 0 eligible because: "
            + ", ".join(f"{c}×{n}" for c, n in top_blocks[:6])
        )
    else:
        answer_parts.append(
            f"{n_avail} USD pairs → evaluated {n_eval} → {n_eligible} eligible → {n_short} queued for paper entry"
        )

    return {
        "status": "degraded" if rate_limited else "ok",
        "generated_at_utc": _now(),
        "reason": "alpaca_rate_limited" if rate_limited else None,
        "degraded": rate_limited,
        "cached_data_used": rate_limited,
        "retry_after_seconds": 90 if rate_limited else None,
        "stale_symbols": stale_symbols[:20],
        "unavailable_symbols": list(dict.fromkeys(unavailable_symbols))[:20],
        "answer": ". ".join(answer_parts),
        "funnel": snapshot.get("funnel"),
        "available_symbols": n_avail,
        "evaluated_symbols": n_eval,
        "fresh_count": fresh_count,
        "eligible_count": n_eligible,
        "ranked_count": n_ranked,
        "execution_shortlist_count": n_short,
        "block_breakdown": dict(block_counter),
        "block_breakdown_labels": {
            "stale_quote": "stale quote blocks",
            "stale_bar": "stale 5Min bar blocks",
            "stale_bar_1m": "stale 1Min bar blocks",
            "spread_too_wide": "spread too wide",
            "quote_currency_unfunded": "quote currency unfunded",
            "insufficient_historical_bars": "not enough historical bars",
            "no_edge_after_cost": "no edge after cost (live scorer)",
            "volatility_regime_panic": "panic volatility regime",
            "liquidity_too_low": "liquidity too low",
            "account_pair_eligibility": "account eligibility",
            "not_tradable": "not tradable on broker",
        },
        "symbols_blocked_sample": [
            {"symbol": r["symbol"], "blocks": r.get("blocks"), "primary": r.get("primary_block")}
            for r in per_symbol
            if r.get("blocks")
        ][:15],
        "pipeline": snapshot,
        "note": (
            "Rank threshold 0.40 applies after eligibility. "
            "Live quote fetch may mark pairs stale if market data refresh has not run recently."
        ),
    }


def select_backtest_symbols(
    session: Session,
    config: dict,
    *,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """Pick top-N symbols for backtest using DB bar coverage (no live quote storm)."""
    available, assets = _load_usd_universe()
    hist = HistoricalDataService(session, config)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for sym in available:
        ok_tf: list[str] = []
        bars_count = 0
        skip_reason = None
        for tf in DEFAULT_TIMEFRAMES:
            bars, meta = hist.get_bars(sym, timeframe=tf, min_rows=MIN_BARS_BACKTEST, lookback_days=90)
            if meta.get("error") or len(bars) < MIN_BARS_BACKTEST:
                continue
            ok_tf.append(tf)
            bars_count = max(bars_count, len(bars))
        if not ok_tf:
            skipped.append({"symbol": sym, "reason": "insufficient_bars", "bars_count": bars_count})
            continue
        bar_svc = BarFreshnessService(session, config)
        bf = bar_svc.check_db_only(sym, timeframe="5Min")
        candidates.append(
            {
                "symbol": sym,
                "bars_count": bars_count,
                "timeframes_available": ok_tf,
                "bar_freshness": bf.get("bar_freshness"),
                "priority": 100 if sym in ANCHOR_SYMBOLS else 0,
            }
        )

    candidates.sort(key=lambda x: (-x["priority"], -x["bars_count"], x["symbol"]))
    selected: list[str] = []
    for a in ANCHOR_SYMBOLS:
        if a in available and a not in selected:
            selected.append(a)
    for c in candidates:
        if c["symbol"] not in selected and len(selected) < top_n:
            selected.append(c["symbol"])

    return {
        "available_usd_pairs": len(available),
        "eligible_for_backtest": len(candidates),
        "selected_symbols": selected,
        "skipped_symbols": skipped[:30],
        "anchors_included": [s for s in ANCHOR_SYMBOLS if s in selected],
    }


def _verdict_from_results(per_symbol_results: list[dict], sweep_summary: Optional[dict] = None) -> dict[str, Any]:
    tested = [r for r in per_symbol_results if r.get("status") == "ok" and (r.get("num_trades") or 0) > 0]
    total_trades = sum(int(r.get("num_trades") or 0) for r in per_symbol_results)
    low_sample = total_trades < int(
        (sweep_summary or {}).get("low_sample_threshold", 10)
    )

    by_sym: dict[str, list] = {}
    for r in per_symbol_results:
        by_sym.setdefault(r["symbol"], []).append(r)

    sym_scores = []
    for sym, runs in by_sym.items():
        trades = sum(int(x.get("num_trades") or 0) for x in runs)
        if trades == 0:
            continue
        exps = [float(x.get("expectancy") or 0) for x in runs if x.get("expectancy") is not None]
        pfs = [float(x.get("profit_factor") or 0) for x in runs if x.get("profit_factor") is not None]
        sym_scores.append(
            {
                "symbol": sym,
                "runs": len(runs),
                "total_trades": trades,
                "avg_expectancy": sum(exps) / len(exps) if exps else None,
                "avg_profit_factor": sum(pfs) / len(pfs) if pfs else None,
            }
        )

    sym_scores.sort(key=lambda x: float(x.get("avg_expectancy") or -999), reverse=True)
    best = sym_scores[0] if sym_scores else None
    worst = sym_scores[-1] if sym_scores else None

    tf_scores: Counter[str] = Counter()
    for r in per_symbol_results:
        if r.get("num_trades"):
            label = f"{r.get('expectancy', 0):.4f}"
            tf_scores[(r.get("timeframe"), label)] += 1
    best_tf = None
    tf_agg: dict[str, list[float]] = {}
    for r in per_symbol_results:
        tf = r.get("timeframe")
        if r.get("expectancy") is not None and tf:
            tf_agg.setdefault(tf, []).append(float(r["expectancy"]))
    if tf_agg:
        best_tf = max(tf_agg.keys(), key=lambda t: sum(tf_agg[t]) / len(tf_agg[t]))

    global_exp = None
    global_pf = None
    if tested:
        global_exp = sum(float(r.get("expectancy") or 0) for r in tested) / len(tested)
        pfs_valid = [float(r.get("profit_factor") or 0) for r in tested if r.get("profit_factor") is not None]
        global_pf = sum(pfs_valid) / len(pfs_valid) if pfs_valid else None

    main_blockers = []
    if low_sample:
        main_blockers.append("insufficient_sample_size")
    if global_exp is not None and global_exp < 0:
        main_blockers.append("negative_expectancy_after_costs")
    if global_pf is not None and global_pf < 1.0:
        main_blockers.append("cost_model_kills_edge")

    if low_sample:
        status = "unproven"
    elif global_exp is not None and global_exp < 0:
        status = "weak"
    elif global_exp is not None and global_exp > 0 and (global_pf or 0) >= 1.05:
        status = "promising"
    else:
        status = "keep_testing"

    gates_strict = sum(
        1
        for r in per_symbol_results
        if r.get("status") == "empty" and "No trades" in str(r.get("warnings"))
    )
    paper_now = status == "promising" and not low_sample and gates_strict < len(per_symbol_results) // 2

    return {
        "current_status": status,
        "total_trades_tested": total_trades,
        "symbols_tested_count": len({r["symbol"] for r in per_symbol_results}),
        "best_symbol": best,
        "worst_symbol": worst,
        "best_timeframe": best_tf,
        "main_blockers": main_blockers,
        "global_expectancy": global_exp,
        "global_profit_factor": global_pf,
        "should_paper_trade_now": paper_now,
        "gates_too_strict": gates_strict > len(per_symbol_results) // 2 if per_symbol_results else False,
        "cost_model_kills_edge": "cost_model_kills_edge" in main_blockers,
        "next_experiment": (
            "Run parameter sweep on best 2 symbols; refresh market data; widen universe eval with fresh quotes."
            if status in ("weak", "keep_testing", "unproven")
            else "Walk-forward validation on best symbol only."
        ),
        "strategy_weak_globally": status == "weak" and (not best or (best.get("avg_expectancy") or 0) < 0),
        "btc_eth_only_weak": _btc_eth_only_weak(per_symbol_results),
    }


def _btc_eth_only_weak(results: list[dict]) -> Optional[bool]:
    anchor = [r for r in results if r.get("symbol") in ANCHOR_SYMBOLS]
    other = [r for r in results if r.get("symbol") not in ANCHOR_SYMBOLS and r.get("num_trades")]
    if not anchor:
        return None
    anchor_neg = sum(1 for r in anchor if (r.get("expectancy") or 0) < 0)
    other_pos = sum(1 for r in other if (r.get("expectancy") or 0) > 0)
    if anchor_neg == len(anchor) and other_pos > 0:
        return True
    if anchor_neg == len(anchor) and not other:
        return True
    return False


def run_universe_discovery(
    session: Session,
    body: Optional[dict] = None,
    *,
    operator: str = "operator",
) -> dict[str, Any]:
    """Universe-wide per-symbol backtests + optional sweep on top performers."""
    cfg = ConfigManager(session).get_current()
    body = body or {}
    top_n = int(body.get("top_n_backtest_symbols", DEFAULT_TOP_N))
    timeframes = body.get("timeframes") or list(DEFAULT_TIMEFRAMES)
    lookback_days = int(body.get("lookback_days", 90))
    run_sweep = bool(body.get("run_parameter_sweep", True))

    funnel = build_funnel_breakdown(session, cfg, max_evaluate=36, fetch_quotes=False)
    selection = select_backtest_symbols(session, cfg, top_n=top_n)
    symbols = selection["selected_symbols"]

    bt = ResearchBacktestEngine(session, cfg)
    mem = ResearchMemoryService(session, cfg)
    per_symbol_results: list[dict] = []
    skipped = selection.get("skipped_symbols") or []

    for sym in symbols:
        for tf in timeframes:
            bars, meta = HistoricalDataService(session, cfg).get_bars(
                sym, timeframe=tf, min_rows=MIN_BARS_BACKTEST, lookback_days=lookback_days
            )
            if meta.get("error") or len(bars) < MIN_BARS_BACKTEST:
                skipped.append(
                    {
                        "symbol": sym,
                        "timeframe": tf,
                        "reason": meta.get("error") or "insufficient_bars",
                        "bars_count": len(bars),
                    }
                )
                continue
            out = bt.run(
                "crypto_push_pull_baseline",
                [sym],
                lookback_days=lookback_days,
                timeframe=tf,
            )
            metrics = out.get("metrics") or {}
            row = {
                "symbol": sym,
                "timeframe": tf,
                "run_id": out.get("run_id"),
                "status": out.get("status"),
                "bars_count": metrics.get("bars_count") or len(bars),
                "num_trades": metrics.get("num_trades") or out.get("result", {}).get("num_trades"),
                "win_rate": metrics.get("win_rate"),
                "expectancy": metrics.get("expectancy"),
                "profit_factor": metrics.get("profit_factor"),
                "max_drawdown": metrics.get("max_drawdown"),
                "result_label": metrics.get("result_label"),
                "warnings": (out.get("result") or {}).get("warnings"),
            }
            per_symbol_results.append(row)
            if out.get("run_id"):
                mem.from_backtest_run(out["run_id"])

    sweep_summary = None
    sweep_results = []
    if run_sweep and per_symbol_results:
        sym_scores = {}
        for r in per_symbol_results:
            if (r.get("num_trades") or 0) > 0:
                sym_scores.setdefault(r["symbol"], []).append(float(r.get("expectancy") or -1))
        ranked_syms = sorted(
            sym_scores.keys(),
            key=lambda s: sum(sym_scores[s]) / len(sym_scores[s]),
            reverse=True,
        )[:2]
        from app.services.parameter_sweep_engine import ParameterSweepEngine

        sweep_eng = ParameterSweepEngine(session, cfg)
        for sym in ranked_syms:
            for tf in timeframes[:1]:
                sw = sweep_eng.sweep(
                    "crypto_push_pull_baseline",
                    [sym],
                    PUSH_PULL_SWEEP_GRID,
                    lookback_days=lookback_days,
                )
                sweep_results.append({"symbol": sym, "timeframe": tf, **sw})
        if sweep_results:
            all_res = []
            for sw in sweep_results:
                all_res.extend(sw.get("results") or [])
            best = max(
                all_res,
                key=lambda x: float(x.get("expectancy") or -999),
                default={},
            )
            worst = min(
                all_res,
                key=lambda x: float(x.get("expectancy") or 999),
                default={},
            )
            sweep_summary = {
                "combinations_tested": sum(sw.get("combinations", 0) for sw in sweep_results),
                "best_params": best.get("parameters"),
                "best_expectancy": best.get("expectancy"),
                "worst_params": worst.get("parameters"),
                "worst_expectancy": worst.get("expectancy"),
            }

    verdict = _verdict_from_results(per_symbol_results, sweep_summary)
    verdict["backtests_run"] = len(per_symbol_results)

    summary_memory = _write_discovery_memory(session, cfg, funnel, selection, verdict, per_symbol_results)

    payload = {
        "status": "ok",
        "generated_at_utc": _now(),
        "operator": operator,
        "funnel_breakdown": funnel,
        "symbol_selection": selection,
        "per_symbol_results": per_symbol_results,
        "skipped": skipped,
        "parameter_sweep": sweep_summary,
        "parameter_sweep_results": sweep_results,
        "verdict": verdict,
        "memory_created": summary_memory,
    }
    _persist_latest(session, payload, operator)
    _LATEST_DISCOVERY.clear()
    _LATEST_DISCOVERY.update(payload)
    session.commit()
    return payload


def _write_discovery_memory(
    session: Session,
    config: dict,
    funnel: dict,
    selection: dict,
    verdict: dict,
    results: list[dict],
) -> Optional[dict]:
    mem = ResearchMemoryService(session, config)
    syms_tested = sorted({r["symbol"] for r in results})
    status = verdict.get("current_status", "unproven")
    total_trades = verdict.get("total_trades_tested", 0)
    summary = (
        f"Universe discovery backtest on {len(syms_tested)} symbols ({', '.join(syms_tested[:6])}"
        f"{'…' if len(syms_tested) > 6 else ''}): {total_trades} total trades, verdict={status}. "
        f"Funnel: {funnel.get('answer', '')[:200]}. "
    )
    if status == "weak":
        summary += " Do not promote. Parameter sweep and fresh market data required before paper focus."
    elif status == "promising":
        summary += " Promising on subset — walk-forward before paper sizing."
    else:
        summary += " Keep testing — sample or edge insufficient for promotion."

    row = mem.create_typed(
        "strategy_discovery_verdict",
        title=f"Universe discovery: {status}",
        summary=summary[:500],
        strategy_id="crypto_push_pull_baseline",
        evidence={
            "verdict": verdict,
            "symbols_tested": syms_tested,
            "funnel": funnel.get("funnel"),
            "block_breakdown": funnel.get("block_breakdown"),
        },
        action_status="candidate" if status in ("keep_testing", "unproven") else status,
        pattern_key=f"universe_discovery|{status}|{len(syms_tested)}",
        aggregate=True,
    )
    return {"id": row.id, "title": row.title, "memory_type": row.memory_type}


def _persist_latest(session: Session, payload: dict, operator: str) -> None:
    session.add(
        SettingsActionAudit(
            action="universe_discovery_latest",
            actor=operator,
            details_json=payload,
        )
    )
    session.flush()


def discovery_status(session: Session) -> dict[str, Any]:
    latest = discovery_latest(session)
    from sqlmodel import select
    from app.database import ResearchBacktestRun

    run_count = len(session.exec(select(ResearchBacktestRun)).all())
    available, _ = _load_usd_universe()
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "has_latest_discovery": latest.get("status") == "ok" and bool(latest.get("per_symbol_results")),
        "latest_generated_at": latest.get("generated_at_utc"),
        "available_usd_pairs": len(available),
        "backtest_run_count": run_count,
        "latest_verdict_status": (latest.get("verdict") or {}).get("current_status"),
    }


def discovery_latest(session: Session) -> dict[str, Any]:
    if _LATEST_DISCOVERY:
        return _LATEST_DISCOVERY
    row = session.exec(
        select(SettingsActionAudit)
        .where(SettingsActionAudit.action == "universe_discovery_latest")
        .order_by(SettingsActionAudit.created_at.desc())
    ).first()
    if row and row.details_json:
        return row.details_json
    return {"status": "not_run_yet", "message": "POST /api/backtesting/run-universe-discovery to build universe-wide proof."}


def strategy_verdict(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    latest = discovery_latest(session)
    funnel = build_funnel_breakdown(session, cfg, max_evaluate=36, fetch_quotes=True)
    verdict = latest.get("verdict") or _verdict_from_results(latest.get("per_symbol_results") or [])

    per_sym = latest.get("per_symbol_results") or []
    best_symbols = sorted(
        [r for r in per_sym if (r.get("num_trades") or 0) > 0],
        key=lambda x: float(x.get("expectancy") or -999),
        reverse=True,
    )[:5]
    worst_symbols = sorted(
        [r for r in per_sym if (r.get("num_trades") or 0) > 0],
        key=lambda x: float(x.get("expectancy") or 999),
    )[:5]

    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "current_status": verdict.get("current_status", "unproven"),
        "backtests_run": verdict.get("backtests_run", len(per_sym)),
        "total_trades_tested": verdict.get("total_trades_tested", 0),
        "best_symbol": verdict.get("best_symbol"),
        "worst_symbol": verdict.get("worst_symbol"),
        "best_timeframe": verdict.get("best_timeframe"),
        "best_symbols": best_symbols,
        "worst_symbols": worst_symbols,
        "main_blockers": verdict.get("main_blockers", []),
        "funnel_answer": funnel.get("answer"),
        "block_breakdown": funnel.get("block_breakdown"),
        "next_experiment": verdict.get("next_experiment"),
        "should_paper_trade_now": verdict.get("should_paper_trade_now", False),
        "gates_too_strict": verdict.get("gates_too_strict"),
        "cost_model_kills_edge": verdict.get("cost_model_kills_edge"),
        "strategy_weak_globally": verdict.get("strategy_weak_globally"),
        "btc_eth_only_weak": verdict.get("btc_eth_only_weak"),
        "sentiment_plan": sentiment_railway_plan(),
    }


def sentiment_railway_plan() -> dict[str, Any]:
    """Option A recommended for Railway — no boot-time transformers."""
    return {
        "recommended_option": "A",
        "label": "Keep FinBERT off on Railway; headline scoring inactive until optional worker",
        "options": {
            "A": {
                "safe": True,
                "description": "FinBERT stays inactive on Railway. UI shows honest inactive. No transformers in requirements.",
            },
            "B": {
                "safe": False,
                "description": "Separate optional sentiment worker with transformers — risks OOM/build failure if enabled on main service.",
            },
            "C": {
                "safe": True,
                "description": "Cheap headline polarity without FinBERT — still capped ±10%, never permits trades.",
            },
        },
        "finbert_on_railway": False,
        "do_not_break_boot": True,
    }


def export_bundle_sections(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    latest = discovery_latest(session)
    verdict = strategy_verdict(session, config)
    per = latest.get("per_symbol_results") or []
    best = sorted(
        [r for r in per if (r.get("num_trades") or 0) > 0],
        key=lambda x: float(x.get("expectancy") or -999),
        reverse=True,
    )[:10]
    worst = sorted(
        [r for r in per if (r.get("num_trades") or 0) > 0],
        key=lambda x: float(x.get("expectancy") or 999),
    )[:10]
    return {
        "universe_discovery_backtest.json": latest,
        "per_symbol_backtest_results.json": {"results": per, "count": len(per)},
        "strategy_verdict.json": verdict,
        "backtest_skip_reasons.json": {
            "skipped": latest.get("skipped", []),
            "selection": latest.get("symbol_selection", {}),
        },
        "best_symbols.json": {"symbols": best},
        "worst_symbols.json": {"symbols": worst},
        "parameter_sweep_results.json": {
            "summary": latest.get("parameter_sweep"),
            "details": latest.get("parameter_sweep_results"),
        },
    }
