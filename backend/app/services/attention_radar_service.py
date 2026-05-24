"""Attention / meme radar — broker truth first, watch-only for unsupported."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.config_manager import ConfigManager
from app.services.symbol_discovery_service import SymbolDiscoveryService


MEME_HINTS = {"DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF"}
MAJOR = {"BTC", "ETH", "SOL", "AVAX", "LINK", "LTC", "BCH", "UNI", "AAVE"}


def _attention_type(symbol: str) -> str:
    base = symbol.split("/")[0].replace("USD", "").upper()
    if base in MEME_HINTS or "DOGE" in base:
        return "meme_coin"
    if base in MAJOR:
        return "major_crypto"
    return "unknown"


class AttentionRadarService:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)
        self.discovery = SymbolDiscoveryService(session)

    def scan(self, limit: int = 25) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        broker_supported: list[str] = []

        if self.alpaca.configured:
            assets = self.alpaca.get_tradable_assets(asset_class="crypto", limit=200)
            broker_supported = [a["symbol"] for a in assets if a.get("tradable")]

        discovered = self.discovery.discover(
            asset_class="crypto",
            limit=min(limit, 50),
            session_mode="crypto_night",
            refresh=False,
        )
        disc_rows = discovered.get("symbols") or []

        seen: set[str] = set()
        for row in disc_rows:
            sym = row.get("symbol") or row.get("display_symbol")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            norm = normalize_crypto_symbol(sym)
            tradable = row.get("tradable", True) and row.get("broker_supported", True)
            atype = _attention_type(norm)
            items.append(
                {
                    "symbol": norm,
                    "display_symbol": row.get("display_symbol", norm),
                    "attention_type": atype,
                    "broker_supported": tradable,
                    "trade_status": "tradable_now" if tradable else "watch_only_not_broker_supported",
                    "price": row.get("price"),
                    "bid": row.get("bid"),
                    "ask": row.get("ask"),
                    "spread_pct": row.get("spread_pct"),
                    "spread_display": row.get("spread_display", "No data"),
                    "volume": row.get("volume"),
                    "liquidity_score": row.get("liquidity_score"),
                    "liquidity_display": row.get("liquidity_display", "No data"),
                    "volatility_score": row.get("volatility_score"),
                    "volatility_display": row.get("volatility_display", "No data"),
                    "eligibility": row.get("eligibility", "UNKNOWN"),
                    "caution_reason": row.get("caution_reason"),
                    "rejection_reason": row.get("rejection_reason"),
                    "reason": f"{atype} on Alpaca radar",
                    "source": "alpaca",
                }
            )

        # Watch-only placeholders for known meme names not on broker (no fake tradable)
        for meme in ("PEPE/USD", "FLOKI/USD", "BONK/USD"):
            if meme not in seen and len(items) < limit:
                norm = normalize_crypto_symbol(meme)
                on_broker = any(norm.replace("/", "") in b.replace("/", "") for b in broker_supported)
                if not on_broker:
                    items.append(
                        {
                            "symbol": norm,
                            "display_symbol": norm,
                            "attention_type": "meme_coin",
                            "broker_supported": False,
                            "trade_status": "watch_only_not_broker_supported",
                            "price": None,
                            "bid": None,
                            "ask": None,
                            "spread_pct": None,
                            "spread_display": "No data",
                            "volume": None,
                            "liquidity_score": None,
                            "liquidity_display": "No data",
                            "volatility_score": None,
                            "volatility_display": "No data",
                            "eligibility": "BLOCKED",
                            "rejection_reason": "Not supported on Alpaca paper crypto",
                            "reason": "Watch-only — not broker supported",
                            "source": "attention_radar",
                        }
                    )

        return {
            "status": "ok",
            "count": len(items[:limit]),
            "items": items[:limit],
            "scanned_at": datetime.utcnow().isoformat() + "Z",
            "paper_trading_only": True,
        }
