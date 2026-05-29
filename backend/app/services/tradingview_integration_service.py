"""TradingView display-only integration.

Webhook events can create overlays and audit records. They cannot submit
orders, cancel orders, or bypass the Alpaca execution cage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, col, select

from app.database import HistoricalBar, TradingViewEvent, TradingViewIntegration


class TradingViewIntegrationService:
    def __init__(self, session: Session):
        self.session = session

    def status(self) -> dict[str, Any]:
        rows = self.session.exec(select(TradingViewIntegration).limit(20)).all()
        latest = self.session.exec(select(TradingViewEvent).order_by(TradingViewEvent.created_at.desc()).limit(1)).first()
        return {
            "status": "ok",
            "mode": "display_only",
            "execution_allowed": False,
            "execution_blocked_reason": "display_only_execution_blocked",
            "integrations": [self._integration_row(r) for r in rows],
            "latest_event": self._event_row(latest) if latest else None,
        }

    def overlays(self, limit: int = 50) -> dict[str, Any]:
        rows = self.session.exec(select(TradingViewEvent).order_by(TradingViewEvent.created_at.desc()).limit(limit)).all()
        return {"status": "ok", "mode": "display_only", "overlays": [self._event_row(r) for r in rows]}

    def chart(self, symbol: str = "BTC/USD", timeframe: str = "5Min", limit: int = 120) -> dict[str, Any]:
        """READ ONLY: return cached bars for local overlay fallback; never fetch providers."""
        clean_symbol = str(symbol or "BTC/USD").upper().replace("-", "/")
        compact_symbol = clean_symbol.replace("/", "")
        symbol_variants = list(dict.fromkeys([clean_symbol, compact_symbol, clean_symbol.replace("/", "-")]))
        tf = str(timeframe or "5Min")
        timeframe_variants = list(dict.fromkeys([tf, tf.lower(), tf.upper()]))
        capped_limit = min(max(int(limit or 120), 20), 300)
        rows = self.session.exec(
            select(HistoricalBar)
            .where(col(HistoricalBar.symbol).in_(symbol_variants))
            .where(col(HistoricalBar.timeframe).in_(timeframe_variants))
            .order_by(HistoricalBar.timestamp.desc())
            .limit(capped_limit)
        ).all()
        bars = list(reversed(rows))
        return {
            "status": "ok" if bars else "empty",
            "mode": "display_only",
            "source": "cached_historical_bars_only",
            "symbol": clean_symbol,
            "timeframe": tf,
            "bar_count": len(bars),
            "last_close": bars[-1].close if bars else None,
            "candles": [self._bar_row(b) for b in bars],
            "message": None if bars else "No cached bars found for local chart fallback.",
        }

    def webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        integration = self.session.exec(select(TradingViewIntegration).limit(1)).first()
        if not integration:
            integration = TradingViewIntegration(name="default_display_only")
            self.session.add(integration)
            self.session.flush()
        integration.last_event_at = datetime.utcnow()
        symbol = str(payload.get("symbol") or payload.get("ticker") or "")
        event = TradingViewEvent(
            integration_id=integration.id,
            event_type=str(payload.get("event_type") or payload.get("type") or "signal"),
            payload_json=payload,
            mapped_signal_json={
                "symbol": symbol,
                "side": payload.get("side"),
                "timeframe": payload.get("timeframe"),
                "display_only": True,
            },
            accepted_for_display=True,
            execution_blocked_reason="display_only_execution_blocked",
        )
        self.session.add(integration)
        self.session.add(event)
        self.session.flush()
        return {
            "status": "ok",
            "accepted_for_display": True,
            "execution_attempted": False,
            "execution_blocked_reason": event.execution_blocked_reason,
            "event": self._event_row(event),
        }

    @staticmethod
    def _integration_row(r: TradingViewIntegration) -> dict[str, Any]:
        return {
            "id": r.id,
            "name": r.name,
            "status": r.status,
            "allowed_actions": r.allowed_actions,
            "last_event_at": r.last_event_at.isoformat() + "Z" if r.last_event_at else None,
        }

    @staticmethod
    def _event_row(r: TradingViewEvent) -> dict[str, Any]:
        return {
            "id": r.id,
            "integration_id": r.integration_id,
            "event_type": r.event_type,
            "mapped_signal": r.mapped_signal_json,
            "accepted_for_display": r.accepted_for_display,
            "execution_blocked_reason": r.execution_blocked_reason,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        }

    @staticmethod
    def _bar_row(r: HistoricalBar) -> dict[str, Any]:
        ts = r.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return {
            "time": int(ts.timestamp()),
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
        }

