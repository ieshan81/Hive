"""Pre-submit quote refresh — fetch fresh quote before paper order handoff."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.config_manager import ConfigManager
from app.services.quote_freshness_service import QuoteFreshnessService, attach_quote_age


class PreSubmitQuoteService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.quotes = QuoteFreshnessService(session, self.config)

    def refresh_for_submit(
        self,
        symbol: str,
        *,
        asset_class: str = "crypto",
        initial_quote: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        1. Check initial quote age (if provided).
        2. If stale, fetch fresh quote from Alpaca.
        3. Return quote ready for preflight or block reason.
        """
        first = self.quotes.check(symbol, asset_class=asset_class, quote=initial_quote)
        attempts = [
            {
                "attempt": 1,
                "source": "initial",
                "fresh": first.get("fresh"),
                "quote_age_seconds": first.get("quote_age_seconds"),
            }
        ]
        if first.get("fresh"):
            return {
                "status": "ok",
                "quote": first.get("quote") or {},
                "quote_refreshed": False,
                "quote_refresh_result": "already_fresh",
                "quote_age_seconds_at_submit": first.get("quote_age_seconds"),
                "attempts": attempts,
                "plain": "Quote already fresh at submit",
            }

        refreshed = self.quotes.fetch_fresh(symbol, asset_class=asset_class, force=True)
        attempts.append(
            {
                "attempt": 2,
                "source": "alpaca_refresh",
                "fresh": refreshed.get("fresh"),
                "quote_age_seconds": refreshed.get("quote_age_seconds"),
                "result": refreshed.get("quote_refresh_result"),
            }
        )
        if refreshed.get("fresh"):
            return {
                "status": "ok",
                "quote": refreshed.get("quote") or {},
                "quote_refreshed": True,
                "quote_refresh_result": "refreshed_ok",
                "quote_age_seconds_at_submit": refreshed.get("quote_age_seconds"),
                "attempts": attempts,
                "plain": "Quote refreshed before submit",
            }

        return {
            "status": "blocked",
            "quote": refreshed.get("quote") or first.get("quote") or {},
            "quote_refreshed": True,
            "quote_refresh_result": refreshed.get("quote_refresh_result", "still_stale"),
            "quote_age_seconds_at_submit": refreshed.get("quote_age_seconds"),
            "block_reason_code": "STALE_QUOTE",
            "human_reason": refreshed.get("plain") or first.get("plain"),
            "attempts": attempts,
            "plain": "Blocked before broker: quote still stale after refresh",
        }
