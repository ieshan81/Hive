"""Quote freshness — separate from bar freshness; gates paper submit."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session

from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get


def _quote_age_seconds(quote: dict) -> Optional[float]:
    qts = quote.get("quote_timestamp")
    if not qts:
        return None
    try:
        ts = datetime.fromisoformat(str(qts).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
    except (TypeError, ValueError):
        return None


def attach_quote_age(quote: dict, config: dict) -> dict:
    """Mutate quote dict with quote_age_seconds and freshness flags."""
    out = dict(quote)
    age = _quote_age_seconds(out)
    out["quote_age_seconds"] = age
    max_age = int(cfg_get(config, "execution.quote_max_age_seconds", 30))
    if age is None:
        out["quote_age_status"] = "quote_age_unknown"
        out["quote_freshness"] = "stale"
        out["executable"] = False
    elif age <= max_age:
        out["quote_age_status"] = "fresh"
        out["quote_freshness"] = "fresh"
        out["executable"] = True
    else:
        out["quote_age_status"] = "stale"
        out["quote_freshness"] = "stale"
        out["executable"] = False
    out["quote_max_age_seconds"] = max_age
    return out


class QuoteFreshnessService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)

    def check(self, symbol: str, *, asset_class: str = "crypto", quote: Optional[dict] = None) -> dict[str, Any]:
        sym = normalize_crypto_symbol(symbol) if "/" in symbol else symbol
        raw = quote if quote is not None else (self.alpaca.get_quote(sym, asset_class) or {})
        q = attach_quote_age(raw, self.config)
        fresh = bool(q.get("executable"))
        age = q.get("quote_age_seconds")
        plain = "Quote fresh" if fresh else (
            f"Quote stale — {round(age or 0)}s old (max {q.get('quote_max_age_seconds')}s)"
            if age is not None
            else "Quote stale — no timestamp"
        )
        return {
            "symbol": symbol,
            "fresh": fresh,
            "executable": fresh,
            "quote_freshness": q.get("quote_freshness", "stale"),
            "quote_age_seconds": age,
            "last_quote_at": q.get("quote_timestamp"),
            "bid": q.get("bid"),
            "ask": q.get("ask"),
            "mid": q.get("mid"),
            "spread_pct": q.get("spread_pct"),
            "plain": plain,
            "quote": q,
        }

    def fetch_fresh(self, symbol: str, *, asset_class: str = "crypto", force: bool = True) -> dict[str, Any]:
        """Fetch latest quote from Alpaca and return freshness check."""
        sym = normalize_crypto_symbol(symbol) if "/" in symbol else symbol
        if not self.alpaca.configured:
            return {
                "status": "error",
                "reason": "alpaca_not_configured",
                "fresh": False,
                "quote_refresh_result": "provider_not_configured",
                "plain": "Alpaca not configured — cannot refresh quote",
            }
        if getattr(self.alpaca, "broker_sync_rate_limited", False) and not force:
            return {
                "status": "rate_limited",
                "fresh": False,
                "quote_refresh_result": "rate_limited",
                "plain": "Broker rate limited — quote refresh skipped",
            }
        raw = self.alpaca.get_quote(sym, asset_class) or {}
        chk = self.check(symbol, asset_class=asset_class, quote=raw)
        return {
            "status": "ok" if chk.get("fresh") else "stale",
            "quote_refreshed": True,
            "quote_refresh_result": "fresh" if chk.get("fresh") else "still_stale",
            **chk,
        }
