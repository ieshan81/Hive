"""Dynamic market radar — real Alpaca discovery, no hardcoded symbols."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, delete, select

from app.database import SymbolCandidate
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.activity_logger import log_activity


def _spread_from_quote(quote: dict | None) -> tuple[float | None, str]:
    if quote is None:
        return None, "No quote"
    bid = quote.get("bid")
    ask = quote.get("ask")
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None, "No quote"
    mid = (bid + ask) / 2
    if mid <= 0:
        return None, "No quote"
    spread_pct = (ask - bid) / mid
    return spread_pct, f"{spread_pct * 100:.3f}%"


def _eligibility(spread_pct: float | None, max_spread: float, tradable: bool, has_quote: bool) -> str:
    if not tradable:
        return "blocked"
    if not has_quote or spread_pct is None:
        return "unknown"
    if spread_pct > max_spread:
        return "blocked"
    if spread_pct > max_spread * 0.6:
        return "caution"
    return "eligible"


def _liquidity_from_volume(volume: float | None) -> float | None:
    if volume is None:
        return None
    # Normalize volume to 0-100 score (log scale heuristic)
    import math

    if volume <= 0:
        return 0.0
    return min(100.0, math.log10(volume + 1) * 20)


class MarketRadarService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.alpaca = AlpacaAdapter(session)
        self.max_spread = config.get("max_spread_pct", 0.005)

    def refresh(self) -> list[SymbolCandidate]:
        if not self.alpaca.configured:
            log_activity(self.session, "market_radar", "Alpaca not configured — radar skipped")
            return []

        candidates: list[dict] = []

        # Stocks: screener most actives + tradable filter
        for item in self.alpaca.get_most_actives(limit=15):
            candidates.append({**item, "asset_class": "stock", "source": "screener"})

        # Crypto: tradable pairs
        for item in self.alpaca.get_crypto_assets(limit=10):
            candidates.append({**item, "asset_class": "crypto", "source": "alpaca_crypto"})

        # Dedupe by symbol
        seen: set[str] = set()
        unique: list[dict] = []
        for c in candidates:
            sym = c["symbol"]
            if sym not in seen:
                seen.add(sym)
                unique.append(c)

        # Clear old candidates and insert fresh scan
        self.session.exec(delete(SymbolCandidate))
        self.session.commit()

        results: list[SymbolCandidate] = []
        for c in unique:
            symbol = c["symbol"]
            asset_class = c.get("asset_class", "stock")
            quote = self.alpaca.get_quote(symbol, asset_class)
            spread_pct, spread_display = _spread_from_quote(quote)

            # Volume-based liquidity for stocks
            liquidity = None
            if asset_class == "stock":
                bars = self.alpaca.get_bars(symbol, timeframe="1Day", limit=5)
                if bars:
                    avg_vol = sum(b["volume"] for b in bars) / len(bars)
                    liquidity = _liquidity_from_volume(avg_vol)

            has_quote = spread_pct is not None
            eligibility = _eligibility(
                spread_pct, self.max_spread, c.get("tradable", True), has_quote
            )

            row = SymbolCandidate(
                symbol=symbol,
                name=c.get("name"),
                asset_class=asset_class,
                liquidity_score=liquidity,
                sentiment_score=None,
                volatility_score=None,
                spread_pct=spread_pct * 100 if spread_pct is not None else None,
                spread_display=spread_display,
                eligibility=eligibility,
                source=c.get("source", "alpaca"),
                scanned_at=datetime.utcnow(),
            )
            self.session.add(row)
            results.append(row)

        self.session.commit()
        for r in results:
            self.session.refresh(r)

        log_activity(
            self.session,
            "market_radar",
            f"Refreshed {len(results)} symbol candidates",
            {"count": len(results), "stocks": sum(1 for r in results if r.asset_class == "stock"), "crypto": sum(1 for r in results if r.asset_class == "crypto")},
        )
        return results
