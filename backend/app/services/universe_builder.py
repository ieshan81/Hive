"""Build merged operator universe from radar, discovery, registry, and eligibility."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PaperExperimentDecision, StrategyRegistry, SymbolCandidate
from app.services.account_pair_eligibility_service import AccountPairEligibilityService
from app.services.attention_radar_service import AttentionRadarService
from app.services.bar_freshness_service import BarFreshnessService
from app.services.quote_freshness_service import QuoteFreshnessService
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import get_latest_reset_epoch, record_created_after
from app.services.session_engine import SessionEngine
from app.services.symbol_discovery_service import SymbolDiscoveryService


def build_merged_universe(
    session: Session,
    config: Optional[dict] = None,
    *,
    limit: int = 80,
    lightweight: bool = False,
) -> list[dict[str, Any]]:
    cfg = config or ConfigManager(session).get_current()
    sess = SessionEngine().detect()
    by_sym: dict[str, dict[str, Any]] = {}

    priority_crypto = [
        "BTC/USD",
        "ETH/USD",
        "SOL/USD",
        "DOGE/USD",
        "AVAX/USD",
        "LINK/USD",
        "LTC/USD",
        "UNI/USD",
    ]
    starter_stocks = ["NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "GOOGL", "SPY", "QQQ"]
    for sym in priority_crypto:
        by_sym[sym] = {
            "symbol": sym,
            "asset_type": "Crypto",
            "source": "priority_universe",
            "broker_supported": True,
            "push_pull_enabled": True,
        }
    for sym in starter_stocks:
        by_sym[sym] = {
            "symbol": sym,
            "asset_type": "Stock",
            "source": "curated_starter_universe",
            "broker_supported": True,
            "push_pull_enabled": sess.stock_trading_allowed,
            "quote_currency": "USD",
        }

    def upsert(row: dict[str, Any]) -> None:
        sym = row.get("symbol")
        if not sym:
            return
        prev = by_sym.get(sym)
        if not prev:
            by_sym[sym] = row
            return
        for k, v in row.items():
            if v is not None and v != "" and (prev.get(k) in (None, "", "unknown")):
                prev[k] = v

    # Attention radar + discovery (skipped on lightweight paths — avoids Alpaca rate limits)
    if not lightweight:
        try:
            radar = AttentionRadarService(session).scan(limit=min(limit, 50))
            for item in radar.get("items") or []:
                sym = item.get("symbol")
                ac = "crypto" if "/" in sym else "stock"
                upsert(
                    {
                        "symbol": sym,
                        "asset_type": "Crypto" if ac == "crypto" else "Stock",
                        "source": item.get("source") or "attention_radar",
                        "price": item.get("price"),
                        "spread_pct": item.get("spread_pct"),
                        "spread": item.get("spread_display"),
                        "liquidity_score": item.get("liquidity_score"),
                        "broker_supported": item.get("broker_supported", True),
                        "push_pull_enabled": bool(item.get("broker_supported")),
                    }
                )
        except Exception:
            pass

        disc = SymbolDiscoveryService(session)
        modes = ["crypto_night"]
        if sess.stock_trading_allowed:
            modes.append("us_stock_open")
        for mode in modes:
            ac = "crypto" if "crypto" in mode else "stock"
            try:
                found = disc.discover(asset_class=ac, limit=40, session_mode=mode, refresh=False)
                for item in found.get("symbols") or []:
                    sym = item.get("symbol") or item.get("display_symbol")
                    upsert(
                        {
                            "symbol": sym,
                            "asset_type": "Crypto" if ac == "crypto" else "Stock",
                            "source": "symbol_discovery",
                            "price": item.get("price"),
                            "spread_pct": item.get("spread_pct"),
                            "spread": item.get("spread_display"),
                            "liquidity_score": item.get("liquidity_score"),
                            "broker_supported": item.get("tradable", True),
                            "push_pull_enabled": True,
                        }
                    )
            except Exception:
                pass

    # Strategy registry symbols
    for reg in session.exec(select(StrategyRegistry)).all():
        syms = reg.symbols if isinstance(reg.symbols, list) else []
        for sym in syms:
            if sym:
                upsert(
                    {
                        "symbol": sym,
                        "asset_type": "Crypto" if "/" in sym else "Stock",
                        "source": "strategy_registry",
                        "strategy_enabled": reg.current_stage not in ("retired", "rejected"),
                        "push_pull_enabled": reg.current_stage in (
                            "paper_experiment",
                            "paper_active",
                            "paper_candidate",
                            "watchlist",
                        ),
                    }
                )

    # Persisted candidates
    for c in session.exec(select(SymbolCandidate).order_by(SymbolCandidate.scanned_at.desc()).limit(100)).all():
        upsert(
            {
                "symbol": c.symbol,
                "asset_type": "Crypto" if (c.asset_class or "").lower() == "crypto" else "Stock",
                "source": c.source or "symbol_candidates",
                "spread_pct": c.spread_pct,
                "spread": c.spread_display,
                "liquidity_score": c.liquidity_score,
                "last_scan_at": c.scanned_at.isoformat() + "Z" if c.scanned_at else None,
            }
        )

    # Eligibility overlay
    elig = AccountPairEligibilityService(session, cfg)
    elig_sum = elig.summary(symbols=list(by_sym.keys())[:limit])
    pair_map: dict[str, dict] = {}
    for row in (elig_sum.get("eligible") or []) + (elig_sum.get("blocked") or []):
        pair_map[row.get("symbol", "")] = row

    epoch = get_latest_reset_epoch(session)
    decisions = list(
        session.exec(
            select(PaperExperimentDecision).order_by(PaperExperimentDecision.created_at.desc()).limit(150)
        ).all()
    )
    if epoch:
        cutoff = epoch.get("nuke_completed_at")
        decisions = [d for d in decisions if record_created_after(d, cutoff)]

    last_dec: dict[str, PaperExperimentDecision] = {}
    for d in decisions:
        if d.symbol not in last_dec:
            last_dec[d.symbol] = d

    bar_svc = BarFreshnessService(session, cfg)
    quote_svc = QuoteFreshnessService(session, cfg)
    out: list[dict[str, Any]] = []
    for sym, base in list(by_sym.items())[:limit]:
        pair = pair_map.get(sym, {})
        eligible = pair.get("status") == "eligible"
        pair_reason = pair.get("reason")
        fresh = (
            bar_svc.check_db_only(sym)
            if "/" in sym or sym.endswith("USD")
            else {"fresh": True, "executable": True, "bar_freshness": "unknown", "plain": ""}
        )
        qfresh = (
            quote_svc.check(sym)
            if "/" in sym and lightweight
            else {"quote_freshness": "unknown", "executable": True, "plain": ""}
        )
        bar_ok = bool(fresh.get("executable"))
        quote_ok = bool(qfresh.get("executable", True))
        broker_ok = bool(base.get("broker_supported", True)) and eligible

        blocked_reason: Optional[str] = None
        if base.get("asset_type") == "Stock" and not sess.stock_trading_allowed:
            status = "Blocked"
            blocked_reason = sess.us_stock_close_reason or "U.S. stock market is closed"
        elif not broker_ok:
            status = "Blocked"
            blocked_reason = pair_reason or "Not broker eligible"
        elif not bar_ok:
            status = "Blocked"
            blocked_reason = fresh.get("plain") or "Stale or missing bars"
        elif not quote_ok:
            status = "Blocked"
            blocked_reason = qfresh.get("plain") or "Stale quote"
        elif base.get("push_pull_enabled") and broker_ok and bar_ok:
            status = "Active"
        else:
            status = "Watch-only"
            blocked_reason = "Strategy or session not enabled for entries"

        dec = last_dec.get(sym)
        out.append(
            {
                **base,
                "symbol": sym,
                "status": status,
                "tradable_now": status == "Active",
                "quote_currency": pair.get("quote_currency"),
                "quote_funded": eligible and pair.get("category") == "ok",
                "funding_status": "funded" if eligible and pair.get("category") == "ok" else "blocked",
                "broker_eligible": eligible,
                "broker_supported": base.get("broker_supported", True),
                "blocked_reason": blocked_reason,
                "quote_freshness": qfresh.get("quote_freshness", "unknown"),
                "quote_age_seconds": qfresh.get("quote_age_seconds"),
                "last_quote_at": qfresh.get("last_quote_at"),
                "bar_freshness": fresh.get("bar_freshness", "unknown"),
                "last_bar_at": fresh.get("last_bar_at"),
                "last_scan_at": base.get("last_scan_at") or datetime.utcnow().isoformat() + "Z",
                "last_decision": dec.decision if dec else None,
                "last_decision_reason": dec.reason_code if dec else None,
                "strategy_enabled": base.get("strategy_enabled", True),
                "push_pull_enabled": base.get("push_pull_enabled", True),
            }
        )

    return out
