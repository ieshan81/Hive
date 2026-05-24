"""Symbol discovery — real Alpaca data, extensible for future providers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.config_manager import ConfigManager
from app.services.quote_utils import (
    eligibility_from_spread,
    liquidity_from_volume,
    spread_from_bid_ask,
    spread_score,
    volatility_score_from_bars,
)
from app.services.session_engine import SessionEngine, SessionState


def _display_symbol(symbol: str, asset_class: str) -> str:
    if asset_class == "crypto":
        return normalize_crypto_symbol(symbol)
    return symbol


def _rejection_reason(
    tradable: bool,
    spread_display: str,
    spread_pct: float | None,
    max_spread: float,
    has_price: bool,
) -> str | None:
    if not tradable:
        return "Symbol not tradable"
    if spread_display == "No quote":
        return "No quote"
    if spread_display == "Invalid quote":
        return "Invalid quote"
    if spread_pct is not None and spread_pct > max_spread:
        return f"Spread too wide ({spread_display})"
    if not has_price:
        return "Missing price"
    return None


class SymbolDiscoveryService:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)
        self.max_spread = float(self.config.get("max_spread_pct", 0.005))

    def discover(
        self,
        asset_class: str = "all",
        limit: int = 25,
        session_mode: str = "auto",
        refresh: bool = False,
    ) -> dict[str, Any]:
        session_state = self._resolve_session(session_mode)
        if refresh:
            from app.services.market_radar_service import MarketRadarService

            MarketRadarService(self.session, self.config).refresh(session_state)

        raw_items = self._fetch_raw(asset_class, limit, session_state)
        symbols = [self._enrich(item, session_state) for item in raw_items[:limit]]

        return {
            "status": "ok" if self.alpaca.configured else "not_configured",
            "session_mode": session_state.mode,
            "asset_class": asset_class,
            "count": len(symbols),
            "symbols": symbols,
            "message": None if self.alpaca.configured else "Alpaca not configured",
        }

    def _resolve_session(self, session_mode: str) -> SessionState:
        if session_mode in ("stock_day", "crypto_night", "closed"):
            engine = SessionEngine()
            now_state = engine.detect()
            return SessionState(
                us_stock_session=now_state.us_stock_session,
                crypto_session=now_state.crypto_session,
                is_weekend=now_state.is_weekend,
                is_night_mode=now_state.is_night_mode,
                stock_trading_allowed=session_mode == "stock_day",
                crypto_trading_allowed=session_mode in ("crypto_night", "stock_day"),
                mode=session_mode,
            )
        return SessionEngine().detect()

    def _fetch_raw(self, asset_class: str, limit: int, session_state: SessionState) -> list[dict]:
        if not self.alpaca.configured:
            return []

        items: list[dict] = []

        if asset_class in ("stock", "all"):
            if asset_class == "stock" or session_state.mode == "stock_day":
                for item in self.alpaca.get_most_actives(limit=limit):
                    items.append({**item, "asset_class": "stock", "source": "alpaca_screener"})
                if not any(i.get("asset_class") == "stock" for i in items):
                    for item in self.alpaca.get_tradable_assets(asset_class="stock", limit=limit):
                        items.append({**item, "source": "alpaca_assets"})

        if asset_class in ("crypto", "all"):
            if asset_class == "crypto" or session_state.mode in ("crypto_night", "stock_day"):
                for item in self.alpaca.get_crypto_assets(limit=limit):
                    items.append({**item, "asset_class": "crypto", "source": "alpaca_crypto"})

        if asset_class == "all" and session_state.mode == "crypto_night":
            items = [i for i in items if i.get("asset_class") == "crypto"]

        seen: set[str] = set()
        unique: list[dict] = []
        for c in items:
            key = f"{c['symbol']}:{c.get('asset_class', 'stock')}"
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return unique

    def _enrich(self, item: dict, session_state: SessionState) -> dict[str, Any]:
        symbol = item["symbol"]
        asset_class = item.get("asset_class", "stock")
        display = _display_symbol(symbol, asset_class)

        ref_price = None
        tf = "1Hour" if asset_class == "crypto" else "1Day"
        bars = self.alpaca.get_bars(symbol, timeframe=tf, limit=20, asset_class=asset_class)
        if bars:
            ref_price = bars[-1]["close"]

        quote = self.alpaca.get_quote(symbol, asset_class, reference_price=ref_price)
        bid = quote.get("bid") if quote else None
        ask = quote.get("ask") if quote else None
        spread_pct, spread_display = spread_from_bid_ask(bid, ask)
        price = quote.get("mid") if quote else (ref_price if ref_price else None)

        volume = item.get("volume")
        if volume is None and bars:
            volume = bars[-1].get("volume")
        if volume is not None and volume <= 0:
            volume = None

        liquidity = None
        if volume is not None and volume > 0:
            if asset_class == "stock":
                liquidity = liquidity_from_volume(volume)
            elif bars:
                avg_vol = sum(b.get("volume", 0) for b in bars[-5:]) / min(len(bars), 5)
                liquidity = liquidity_from_volume(avg_vol if avg_vol > 0 else None)

        volatility = volatility_score_from_bars(bars)
        spread_qual = spread_score(spread_pct, self.max_spread)
        eligibility = eligibility_from_spread(
            spread_pct, self.max_spread, item.get("tradable", True), spread_display
        )
        rejection = _rejection_reason(
            item.get("tradable", True), spread_display, spread_pct, self.max_spread, price is not None
        )
        caution = None
        if eligibility == "caution":
            if spread_pct is not None and spread_pct > self.max_spread * 0.6:
                caution = f"Spread elevated ({spread_display})"
            elif liquidity is not None and liquidity < self.config.get("min_liquidity_score", 40):
                caution = f"Liquidity below preferred minimum ({liquidity:.0f})"
            else:
                caution = "Borderline eligibility"

        def _disp(val):
            return val if val is not None else "No data"

        return {
            "symbol": symbol,
            "display_symbol": display,
            "asset_class": asset_class,
            "source": item.get("source", "alpaca"),
            "tradable": item.get("tradable", True),
            "fractionable": item.get("fractionable") if asset_class == "stock" else None,
            "broker_supported": True,
            "price": price,
            "bid": bid,
            "ask": ask,
            "spread_pct": spread_pct,
            "spread_display": spread_display,
            "volume": volume,
            "liquidity_score": liquidity,
            "liquidity_display": _disp(liquidity),
            "volatility_score": volatility,
            "volatility_display": _disp(volatility),
            "sentiment_score": None,
            "sentiment_display": "No data",
            "spread_score": spread_qual,
            "spread_score_display": _disp(spread_qual),
            "eligibility": eligibility.upper(),
            "rejection_reason": rejection,
            "caution_reason": caution,
            "last_updated": datetime.utcnow().isoformat() + "Z",
        }
