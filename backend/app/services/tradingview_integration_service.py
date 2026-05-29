"""TradingView display-only integration.

Webhook events can create overlays and audit records. They cannot submit
orders, cancel orders, or bypass the Alpaca execution cage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.database import TradingViewEvent, TradingViewIntegration


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

