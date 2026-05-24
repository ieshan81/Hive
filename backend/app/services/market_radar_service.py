"""Dynamic market radar — real Alpaca discovery, session-aware, no hardcoded symbols."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, delete

from app.database import SymbolCandidate
from app.services.activity_logger import log_activity
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.quote_utils import eligibility_from_spread, liquidity_from_volume, spread_from_bid_ask, volatility_score_from_bars
from app.services.session_engine import SessionState


class MarketRadarService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.alpaca = AlpacaAdapter(session)
        self.max_spread = float(config.get("max_spread_pct", 0.005))

    def refresh(self, session_state: SessionState | None = None) -> list[SymbolCandidate]:
        from app.services.session_engine import SessionEngine

        session_state = session_state or SessionEngine().detect()

        if not self.alpaca.configured:
            log_activity(self.session, "market_radar", "Alpaca not configured — radar skipped")
            return []

        candidates: list[dict] = []
        crypto_error: str | None = None

        if session_state.mode == "crypto_night":
            crypto_items = self.alpaca.get_crypto_assets(limit=15)
            if not crypto_items:
                crypto_error = "Crypto data unavailable — no tradable crypto assets returned from Alpaca"
                log_activity(self.session, "market_radar", crypto_error)
            else:
                for item in crypto_items:
                    candidates.append({**item, "asset_class": "crypto", "source": "alpaca_crypto"})
        elif session_state.mode == "stock_day":
            for item in self.alpaca.get_most_actives(limit=15):
                candidates.append({**item, "asset_class": "stock", "source": "screener"})
        else:
            log_activity(
                self.session,
                "market_radar",
                f"Session mode {session_state.mode} — no radar scan for closed market",
                session_state.to_dict(),
            )
            return []

        if session_state.mode == "stock_day":
            for item in self.alpaca.get_crypto_assets(limit=5):
                candidates.append({**item, "asset_class": "crypto", "source": "alpaca_crypto"})

        seen: set[str] = set()
        unique: list[dict] = []
        for c in candidates:
            sym = c["symbol"]
            if sym not in seen:
                seen.add(sym)
                unique.append(c)

        self.session.exec(delete(SymbolCandidate))
        self.session.commit()

        results: list[SymbolCandidate] = []
        for c in unique:
            symbol = c["symbol"]
            asset_class = c.get("asset_class", "stock")
            tf = "1Hour" if asset_class == "crypto" else "1Day"

            bars = self.alpaca.get_bars(symbol, timeframe=tf, limit=20, asset_class=asset_class)
            ref_price = bars[-1]["close"] if bars else None

            quote = self.alpaca.get_quote(symbol, asset_class, reference_price=ref_price)
            spread_pct, spread_display = spread_from_bid_ask(
                quote.get("bid") if quote else None,
                quote.get("ask") if quote else None,
            )

            liquidity = None
            if asset_class == "stock" and bars:
                avg_vol = sum(b["volume"] for b in bars) / len(bars)
                liquidity = liquidity_from_volume(avg_vol)
            elif asset_class == "crypto" and bars:
                avg_vol = sum(b.get("volume", 0) for b in bars[-5:]) / min(len(bars), 5)
                liquidity = liquidity_from_volume(avg_vol)

            volatility = volatility_score_from_bars(bars)

            eligibility = eligibility_from_spread(
                spread_pct,
                self.max_spread,
                c.get("tradable", True),
                spread_display,
            )

            row = SymbolCandidate(
                symbol=symbol,
                name=c.get("name"),
                asset_class=asset_class,
                liquidity_score=liquidity,
                sentiment_score=None,
                volatility_score=volatility,
                spread_pct=spread_pct,
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

        details = {
            "count": len(results),
            "mode": session_state.mode,
            "stocks": sum(1 for r in results if r.asset_class == "stock"),
            "crypto": sum(1 for r in results if r.asset_class == "crypto"),
            "crypto_error": crypto_error,
        }
        log_activity(
            self.session,
            "market_radar",
            f"Refreshed {len(results)} symbol candidates ({session_state.mode})",
            details,
        )
        return results
