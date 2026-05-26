"""Fetch and store fresh Alpaca bars for push-pull universe symbols."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.account_pair_eligibility_service import AccountPairEligibilityService
from app.services.activity_logger import log_activity
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.bar_freshness_service import MAX_BAR_STALENESS_HOURS, BarFreshnessService
from app.services.config_manager import ConfigManager
from app.services.historical_data_service import HistoricalDataService
from app.services.universe_builder import build_merged_universe


PUSH_PULL_TIMEFRAME = "5Min"


class MarketDataRefreshService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.hist = HistoricalDataService(session, self.config)
        self.alpaca = AlpacaAdapter(session)
        self.freshness = BarFreshnessService(session, self.config)

    def refresh_bars(
        self,
        *,
        asset_type: str = "crypto",
        timeframe: str = PUSH_PULL_TIMEFRAME,
        symbols: Optional[list[str]] = None,
        lookback_hours: int = 48,
        operator: str = "operator",
    ) -> dict[str, Any]:
        log_activity(
            self.session,
            "market_data_refresh_started",
            f"Market data refresh started — {asset_type} {timeframe}",
            {"operator": operator, "lookback_hours": lookback_hours},
            commit=False,
        )

        if not self.alpaca.configured:
            out = {
                "status": "error",
                "reason": "alpaca_not_configured",
                "message": "Alpaca not configured — cannot refresh bars",
                "refreshed_count": 0,
                "stale_count": 0,
                "failed_symbols": [],
                "provider_errors": ["Alpaca API keys missing"],
            }
            self._log_refresh_done(out, operator)
            return out

        target = self._resolve_symbols(asset_type, symbols)
        lookback_days = max(1, min(7, (lookback_hours + 23) // 24))
        bar_limit = min(1000, max(100, lookback_hours * 12))  # ~12 bars/hour on 5Min

        refreshed: list[dict] = []
        failed: list[dict] = []
        provider_errors: list[str] = []

        for idx, sym in enumerate(target):
            if idx > 0:
                time.sleep(0.35)  # Alpaca rate-limit spacing
            try:
                asset = "crypto" if "/" in sym else "stock"
                fetch = self.hist.fetch_and_store(
                    sym,
                    timeframe=timeframe,
                    limit=bar_limit,
                    asset_class=asset,
                    lookback_days=lookback_days,
                )
                if fetch.get("status") != "ok":
                    failed.append(
                        {
                            "symbol": sym,
                            "reason": fetch.get("message") or "fetch_failed",
                        }
                    )
                    if fetch.get("message"):
                        provider_errors.append(f"{sym}: {fetch['message'][:120]}")
                    continue
                chk = self.freshness.check_db_only(sym, timeframe=timeframe)
                refreshed.append(
                    {
                        "symbol": sym,
                        "rows_stored": fetch.get("rows_stored", 0),
                        "latest_bar_time": chk.get("last_bar_at"),
                        "fresh": chk.get("fresh"),
                        "staleness_hours": chk.get("staleness_hours"),
                    }
                )
            except Exception as exc:
                try:
                    self.session.rollback()
                except Exception:
                    pass
                failed.append({"symbol": sym, "reason": str(exc)[:200]})
                provider_errors.append(f"{sym}: {str(exc)[:120]}")

        try:
            self.session.flush()
        except Exception:
            self.session.rollback()
        fresh_n = sum(1 for r in refreshed if r.get("fresh"))
        stale_n = sum(1 for r in refreshed if not r.get("fresh")) + len(
            [s for s in target if s not in [r["symbol"] for r in refreshed]]
        )

        latest_times = [r.get("latest_bar_time") for r in refreshed if r.get("latest_bar_time")]
        out = {
            "status": "ok" if refreshed else "partial",
            "refreshed_count": len(refreshed),
            "fresh_count": fresh_n,
            "stale_count": stale_n,
            "failed_symbols": failed,
            "refreshed_symbols": refreshed,
            "latest_bar_time": max(latest_times) if latest_times else None,
            "provider_errors": provider_errors[:20],
            "timeframe": timeframe,
            "lookback_hours": lookback_hours,
            "symbols_requested": len(target),
        }
        self._log_refresh_done(out, operator)
        return out

    def freshness_report(
        self,
        *,
        asset_type: str = "crypto",
        timeframe: str = PUSH_PULL_TIMEFRAME,
        symbols: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        target = self._resolve_symbols(asset_type, symbols, fast=True)
        rows: list[dict] = []
        for sym in target:
            chk = self.freshness.check_db_only(sym, timeframe=timeframe)
            age_min = None
            if chk.get("staleness_hours") is not None:
                age_min = round(float(chk["staleness_hours"]) * 60, 1)
            rows.append(
                {
                    "symbol": sym,
                    "latest_bar_time": chk.get("last_bar_at"),
                    "age_minutes": age_min,
                    "freshness_status": chk.get("bar_freshness"),
                    "provider": (chk.get("meta") or {}).get("source", "database"),
                    "executable_for_push_pull": bool(chk.get("executable")),
                    "plain": chk.get("plain"),
                }
            )
        fresh_n = sum(1 for r in rows if r.get("executable_for_push_pull"))
        return {
            "status": "ok",
            "timeframe": timeframe,
            "symbols": rows,
            "fresh_count": fresh_n,
            "stale_count": len(rows) - fresh_n,
            "count": len(rows),
        }

    def _resolve_symbols(self, asset_type: str, symbols: Optional[list[str]], *, fast: bool = False) -> list[str]:
        if symbols:
            return [normalize_crypto_symbol(s) if "/" in s else s for s in symbols if s]

        priority = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD", "LINK/USD"]
        if fast or asset_type == "crypto":
            elig = AccountPairEligibilityService(self.session, self.config)
            out: list[str] = []
            for p in priority:
                row = elig.classify_symbol(p, asset_class="crypto")
                if row.get("status") == "eligible":
                    out.append(p)
            if fast:
                return out

        universe = build_merged_universe(self.session, self.config, limit=50, lightweight=True)
        elig = AccountPairEligibilityService(self.session, self.config)

        out: list[str] = []
        priority = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD", "LINK/USD"]
        for p in priority:
            if p not in out:
                row = elig.classify_symbol(p, asset_class="crypto")
                if row.get("status") == "eligible":
                    out.append(p)

        for u in universe:
            sym = u.get("symbol")
            if not sym or sym in out:
                continue
            ac = (u.get("asset_type") or "").lower()
            if asset_type == "crypto" and ac != "crypto":
                continue
            if asset_type == "stock" and ac != "stock":
                continue
            if asset_type == "all" or ac in ("crypto", "stock"):
                if u.get("quote_currency") in ("USDC", "USDT") and not u.get("quote_funded"):
                    continue
                if u.get("broker_eligible") is False and u.get("status") == "Blocked":
                    continue
                out.append(sym)

        return out[:25]

    def _log_refresh_done(self, out: dict, operator: str) -> None:
        msg = (
            f"Bars refreshed for {out.get('refreshed_count', 0)} symbols — "
            f"{out.get('fresh_count', 0)} fresh, {out.get('stale_count', 0)} still stale."
        )
        if out.get("provider_errors"):
            msg += f" Provider errors: {len(out['provider_errors'])}."
        log_activity(
            self.session,
            "market_data_refresh_done",
            msg,
            {**out, "operator": operator},
            commit=False,
        )
