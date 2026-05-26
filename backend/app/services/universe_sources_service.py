"""Universe source proof — Alpaca API counts vs curated display universe."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import StrategyRegistry
from app.services.account_pair_eligibility_service import AccountPairEligibilityService
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.alpaca_crypto_assets import fetch_crypto_assets
from app.services.bar_freshness_service import BarFreshnessService
from app.services.config_manager import ConfigManager
from app.services.quote_freshness_service import QuoteFreshnessService
from app.services.session_engine import SessionEngine
from app.services.universe_builder import build_merged_universe

CURATED_CRYPTO = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "DOGE/USD",
    "AVAX/USD",
    "LINK/USD",
    "LTC/USD",
    "UNI/USD",
]
CURATED_STOCKS = ["NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "GOOGL", "SPY", "QQQ"]


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def universe_sources(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    sess = SessionEngine().detect()
    errors: list[str] = []

    crypto_err = None
    crypto_assets: dict[str, dict] = {}
    try:
        crypto_assets = fetch_crypto_assets(force=False)
    except Exception as exc:
        crypto_err = type(exc).__name__
        errors.append(f"alpaca_crypto_assets: {exc}")

    stock_err = None
    stock_rows: list[dict] = []
    alpaca = AlpacaAdapter(session)
    try:
        stock_rows = alpaca.get_tradable_assets(asset_class="stock", limit=500) or []
    except Exception as exc:
        stock_err = type(exc).__name__
        errors.append(f"alpaca_stock_assets: {exc}")

    registry_syms: set[str] = set()
    for reg in session.exec(select(StrategyRegistry)).all():
        for sym in reg.symbols if isinstance(reg.symbols, list) else []:
            if sym:
                registry_syms.add(sym)

    display = build_merged_universe(session, cfg, limit=80, lightweight=True)
    crypto_display = [r for r in display if r.get("asset_type") == "Crypto"]
    stock_display = [r for r in display if r.get("asset_type") == "Stock"]

    usd_pairs = [s for s in crypto_assets if s.endswith("/USD")]
    unfunded_quotes = {"USDC", "USDT", "BTC"}
    quote_blocked = [
        s
        for s, m in crypto_assets.items()
        if (m.get("quote_currency") or "").upper() in unfunded_quotes
    ]

    return {
        "status": "ok" if not errors else "degraded",
        "generated_at_utc": _now(),
        "last_refresh_at": _now(),
        "data_source_status": "ok" if not errors else "partial",
        "errors": errors,
        "market_session": sess.to_dict(),
        "source_counts": {
            "alpaca_crypto_assets_api": len(crypto_assets),
            "alpaca_crypto_tradable": sum(1 for a in crypto_assets.values() if a.get("tradable")),
            "alpaca_crypto_usd_pairs": len(usd_pairs),
            "alpaca_stock_assets_api": len(stock_rows),
            "curated_crypto_watchlist": len(CURATED_CRYPTO),
            "curated_stock_watchlist": len(CURATED_STOCKS),
            "strategy_registry_symbols": len(registry_syms),
            "display_universe_total": len(display),
            "display_crypto": len(crypto_display),
            "display_stock": len(stock_display),
        },
        "why_only_8_crypto_displayed": (
            "Operator universe uses curated priority crypto list in lightweight mode "
            f"(8 symbols). Alpaca crypto assets API returned {len(crypto_assets)} active assets / "
            f"{len(usd_pairs)} USD pairs. Full Alpaca fan-out runs when lightweight=False."
        ),
        "non_usd_pairs": {
            "hidden_from_display": True,
            "quote_blocked_unfunded_count": len(quote_blocked),
            "note": "USDC/USDT/BTC quote pairs blocked when quote currency unfunded in paper account.",
        },
        "alpaca_crypto_api_called": bool(crypto_assets) or crypto_err is None,
        "alpaca_stock_api_called": bool(stock_rows) or stock_err is None,
    }


def universe_assets_crypto(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    assets = fetch_crypto_assets(force=False)
    display = {r["symbol"]: r for r in build_merged_universe(session, cfg, lightweight=True) if r.get("asset_type") == "Crypto"}
    rows = []
    for sym in CURATED_CRYPTO:
        meta = assets.get(sym) or {}
        disp = display.get(sym, {})
        rows.append(
            {
                "symbol": sym,
                "in_display_universe": sym in display,
                "tradable": meta.get("tradable"),
                "status": meta.get("status"),
                "min_order_size": meta.get("min_order_size"),
                "min_trade_increment": meta.get("min_trade_increment"),
                "price_increment": meta.get("price_increment"),
                "fractionable": meta.get("fractionable"),
                "quote_currency": meta.get("quote_currency") or "USD",
                "display_status": disp.get("status"),
                "blocked_reason": disp.get("blocked_reason"),
            }
        )
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "alpaca_total_active_crypto": len(assets),
        "display_count": len(rows),
        "assets": rows,
    }


def universe_assets_stocks(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    sess = SessionEngine().detect()
    display = {r["symbol"]: r for r in build_merged_universe(session, cfg, lightweight=True) if r.get("asset_type") == "Stock"}
    rows = []
    for sym in CURATED_STOCKS:
        disp = display.get(sym, {})
        rows.append(
            {
                "symbol": sym,
                "in_display_universe": sym in display,
                "market_open": sess.stock_trading_allowed,
                "display_status": disp.get("status"),
                "tradable_now": disp.get("tradable_now"),
                "blocked_reason": disp.get("blocked_reason") or (
                    sess.us_stock_close_reason if not sess.stock_trading_allowed else None
                ),
                "bar_freshness": disp.get("bar_freshness"),
            }
        )
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "market_session": sess.to_dict(),
        "stock_entries_blocked_while_closed": not sess.stock_trading_allowed,
        "becomes_active_when_market_opens": True,
        "assets": rows,
    }


def universe_eligibility(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    symbols = CURATED_CRYPTO + CURATED_STOCKS
    elig = AccountPairEligibilityService(session, cfg).summary(symbols=symbols)
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        **elig,
    }


def universe_freshness(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    bar_svc = BarFreshnessService(session, cfg)
    quote_svc = QuoteFreshnessService(session, cfg)
    sess = SessionEngine().detect()
    rows = []
    for sym in CURATED_CRYPTO + CURATED_STOCKS:
        is_crypto = "/" in sym
        if is_crypto:
            bf = bar_svc.check_db_only(sym)
            qf = quote_svc.check(sym)
        else:
            bf = bar_svc.check_db_only(sym) if sess.stock_trading_allowed else {
                "bar_freshness": "market_closed_fresh_until_next_session",
                "executable": False,
                "plain": sess.us_stock_close_reason or "U.S. stock market is closed",
                "last_bar_at": None,
            }
            qf = {"quote_freshness": "market_closed", "executable": False, "plain": "Market closed"}
        rows.append(
            {
                "symbol": sym,
                "asset_type": "Crypto" if is_crypto else "Stock",
                "bar_freshness": bf.get("bar_freshness"),
                "bar_age_hours": bf.get("staleness_hours"),
                "last_bar_at": bf.get("last_bar_at"),
                "quote_freshness": qf.get("quote_freshness"),
                "quote_age_seconds": qf.get("quote_age_seconds"),
                "last_quote_at": qf.get("last_quote_at"),
                "freshness_reason": bf.get("plain") or qf.get("plain"),
                "tradable_now": bool(bf.get("executable")) and bool(qf.get("executable", True)),
            }
        )
    return {"status": "ok", "generated_at_utc": _now(), "symbols": rows}


def universe_scan_summary(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    from app.services.universe_service import universe_status

    st = universe_status(session, config)
    src = universe_sources(session, config)
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "total_symbols": st.get("total_symbols"),
        "counts": st.get("counts"),
        "source_proof": src.get("source_counts"),
        "why_only_8_crypto": src.get("why_only_8_crypto_displayed"),
        "market_session": src.get("market_session"),
        "reset_epoch": st.get("reset_epoch"),
    }
