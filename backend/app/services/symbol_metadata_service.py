"""Fast per-symbol metadata for hover cards — never runs slow full discovery.

Uses the cached symbol-identity payload (no network) for asset class / venue, plus quick
fail-safe DB reads (open-position mark price, latest paper outcome, latest sentiment). Any
unavailable field is ``null`` and listed in ``missing_fields`` — never invented, never
hardcoded as a primary source.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.services.order_ledger_service import classify_asset, display_symbol, normalize_symbol


def _session_type(asset_class: str) -> Optional[str]:
    if asset_class == "crypto":
        return "24/7"
    if asset_class == "stock":
        return "us_market_hours"
    return None


def _identity(symbol: str) -> dict[str, Any]:
    try:
        from app.services import symbol_identity_service

        return symbol_identity_service.get_identity(symbol, allow_network=False) or {}
    except Exception:
        return {}


def _last_price(session: Session, norm: str) -> Optional[float]:
    """Mark price from an open broker position snapshot (fast DB; no network)."""
    try:
        from app.database import PositionSnapshot

        for p in session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all():
            if normalize_symbol(getattr(p, "symbol", "")) == norm:
                v = getattr(p, "current_price", None)
                return float(v) if v is not None else None
    except Exception:
        return None
    return None


def _latest_outcome(session: Session, norm: str) -> tuple[Optional[float], Optional[str]]:
    """(latest realized P&L, strategy) for the symbol from PaperExperimentOutcome."""
    try:
        from app.database import PaperExperimentOutcome

        rows = session.exec(
            select(PaperExperimentOutcome).order_by(PaperExperimentOutcome.created_at.desc()).limit(60)
        ).all()
        for r in rows:
            if normalize_symbol(getattr(r, "symbol", "")) == norm:
                pnl = getattr(r, "realized_pnl", None)
                return (float(pnl) if pnl is not None else None, getattr(r, "strategy_id", None))
    except Exception:
        return (None, None)
    return (None, None)


def _latest_sentiment(session: Session, norm: str) -> Optional[float]:
    try:
        from app.database import SentimentSnapshot  # type: ignore

        rows = session.exec(
            select(SentimentSnapshot).order_by(SentimentSnapshot.created_at.desc()).limit(60)
        ).all()
        for r in rows:
            if normalize_symbol(getattr(r, "symbol", "")) == norm:
                v = getattr(r, "score", None) or getattr(r, "sentiment_score", None)
                return float(v) if v is not None else None
    except Exception:
        return None
    return None


def metadata_for(session: Session, symbol: str) -> dict[str, Any]:
    raw = str(symbol or "").strip()
    norm = normalize_symbol(raw)
    ident = _identity(raw)
    asset_type = str(ident.get("asset_type") or "").lower()
    asset_class = asset_type if asset_type in ("crypto", "stock") else classify_asset(raw)
    disp = display_symbol(raw, asset_class)
    last_price = _last_price(session, norm)
    pnl, strategy = _latest_outcome(session, norm)
    sentiment = _latest_sentiment(session, norm)

    missing: list[str] = []
    full_name = ident.get("full_name") or ident.get("long_name")  # only present with network enrichment
    if not full_name:
        missing.append("full_name")
    if last_price is None:
        missing.append("last_price")
    missing.append("spread_pct")  # no fast cached spread source
    if sentiment is None:
        missing.append("latest_sentiment")
    if pnl is None:
        missing.append("latest_trade_pnl")

    return {
        "symbol": raw,
        "display_symbol": disp,
        "normalized_symbol": norm,
        "asset_class": asset_class,
        "full_name": full_name,  # null when unavailable (frontend shows "Name unavailable")
        "venue": ident.get("exchange"),
        "exchange": ident.get("exchange"),
        "tradable": True if asset_class in ("crypto", "stock") else None,
        "session_type": _session_type(asset_class),
        "source": "identity_cache" if ident else "fallback_classifier",
        "last_price": last_price,
        "spread_pct": None,
        "latest_sentiment": sentiment,
        "latest_trade_pnl": pnl,
        "latest_strategy": strategy,
        "metadata_stale": not bool(ident),
        "missing_fields": missing,
    }


def metadata_many(session: Session, symbols: list[str]) -> dict[str, Any]:
    items = []
    seen: set[str] = set()
    for s in symbols:
        key = normalize_symbol(s)
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            items.append(metadata_for(session, s))
        except Exception as exc:  # never crash the endpoint on one bad symbol
            items.append({"symbol": s, "error": type(exc).__name__, "asset_class": "unknown", "missing_fields": ["all"]})
    return {"status": "ok", "count": len(items), "symbols": items}
