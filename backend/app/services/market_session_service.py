"""Market-session classification and research features.

This service is research-only. It classifies candle timestamps into broad
liquidity windows so Alpha Factory can measure where a setup works best. The
session label is never a direct trade permission and never bypasses the cage.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo


UTC = timezone.utc
NY = ZoneInfo("America/New_York")


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        raw = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
    else:
        dt = value
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _between(t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= t < end
    return t >= start or t < end


class MarketSessionService:
    """Classify candles into exchange/session windows and summarize edge."""

    def classify_timestamp(self, value: datetime | str, *, asset_class: str = "crypto") -> dict[str, Any]:
        dt_utc = _as_utc(value)
        t_utc = dt_utc.time()
        dt_et = dt_utc.astimezone(NY)
        t_et = dt_et.time()
        is_weekend = dt_utc.weekday() >= 5

        asia = _between(t_utc, time(0, 0), time(8, 0))
        london = _between(t_utc, time(7, 0), time(16, 0))
        new_york = _between(t_utc, time(13, 0), time(22, 0))
        overlap = _between(t_utc, time(13, 0), time(16, 0))
        low_liq = _between(t_utc, time(22, 0), time(0, 0)) or _between(t_utc, time(0, 0), time(1, 0))

        us_regular = (not is_weekend) and _between(t_et, time(9, 30), time(16, 0))
        us_pre = (not is_weekend) and _between(t_et, time(4, 0), time(9, 30))
        us_after = (not is_weekend) and _between(t_et, time(16, 0), time(20, 0))

        if asset_class == "stock":
            if us_regular:
                session_name = "us_regular_market_hours"
                liquidity = 0.9
                spread_risk = "low"
            elif us_pre:
                session_name = "us_premarket"
                liquidity = 0.45
                spread_risk = "high"
            elif us_after:
                session_name = "us_afterhours"
                liquidity = 0.4
                spread_risk = "high"
            else:
                session_name = "low_liquidity_window"
                liquidity = 0.2
                spread_risk = "high"
        elif overlap:
            session_name = "london_new_york_overlap"
            liquidity = 0.92
            spread_risk = "low"
        elif london:
            session_name = "london_session"
            liquidity = 0.78
            spread_risk = "medium"
        elif new_york:
            session_name = "new_york_session"
            liquidity = 0.82
            spread_risk = "medium"
        elif asia:
            session_name = "asia_session"
            liquidity = 0.58
            spread_risk = "medium"
        else:
            session_name = "low_liquidity_window"
            liquidity = 0.35
            spread_risk = "high"

        if asset_class == "crypto" and is_weekend:
            liquidity = min(liquidity, 0.5)
            spread_risk = "high" if spread_risk != "low" else "medium"

        avoid_reason = None
        if session_name == "low_liquidity_window":
            avoid_reason = "low_liquidity_window"
        elif asset_class == "stock" and session_name in {"us_premarket", "us_afterhours"}:
            avoid_reason = f"{session_name}_spread_risk"
        elif asset_class == "crypto" and is_weekend and liquidity < 0.55:
            avoid_reason = "crypto_weekend_low_liquidity"

        return {
            "timestamp_utc": dt_utc.isoformat().replace("+00:00", "Z"),
            "session_name": session_name,
            "session_liquidity_score": round(liquidity, 3),
            "expected_spread_risk": spread_risk,
            "avoid_reason": avoid_reason,
            "asia_session": asia,
            "london_session": london,
            "new_york_session": new_york,
            "london_new_york_overlap": overlap,
            "us_regular_market_hours": us_regular,
            "us_premarket": us_pre,
            "us_afterhours": us_after,
            "crypto_weekend": asset_class == "crypto" and is_weekend,
            "low_liquidity_window": session_name == "low_liquidity_window",
        }

    def summarize_candles(
        self,
        candles: Iterable[Any],
        *,
        asset_class: str = "crypto",
        cost_bps: float | None = None,
    ) -> dict[str, Any]:
        buckets: dict[str, list[float]] = defaultdict(list)
        low_liq_count = 0
        for candle in candles:
            if isinstance(candle, dict):
                ts = candle.get("timestamp")
                open_px = candle.get("open")
                close_px = candle.get("close")
            else:
                ts = getattr(candle, "timestamp", None)
                open_px = getattr(candle, "open", None)
                close_px = getattr(candle, "close", None)
            if ts is None:
                continue
            try:
                op = float(open_px)
                cl = float(close_px)
            except (TypeError, ValueError):
                continue
            if op <= 0:
                continue
            state = self.classify_timestamp(ts, asset_class=asset_class)
            session_name = state["session_name"]
            if state.get("avoid_reason"):
                low_liq_count += 1
            buckets[session_name].append((cl - op) / op)

        metrics = {name: self._metrics(returns, cost_bps=cost_bps) for name, returns in buckets.items()}
        ranked = sorted(metrics.items(), key=lambda item: item[1].get("edge_after_cost_bps") or -999999.0, reverse=True)
        best = ranked[0][0] if ranked else None
        worst = ranked[-1][0] if ranked else None
        best_metrics = metrics.get(best or "", {})
        return {
            "status": "ok",
            "source": "historical_bar_session_proxy",
            "best_session": best,
            "worst_session": worst,
            "session_sample_size": int(best_metrics.get("sample_size") or 0),
            "session_win_rate": best_metrics.get("win_rate"),
            "session_expectancy": best_metrics.get("expectancy"),
            "session_profit_factor": best_metrics.get("profit_factor"),
            "session_edge_after_cost_bps": best_metrics.get("edge_after_cost_bps"),
            "sessions": metrics,
            "low_liquidity_session_warning": (
                f"{low_liq_count} candle(s) fell in low-liquidity/spread-risk windows." if low_liq_count else None
            ),
        }

    @staticmethod
    def _metrics(returns: list[float], *, cost_bps: float | None = None) -> dict[str, Any]:
        n = len(returns)
        if n == 0:
            return {
                "sample_size": 0,
                "win_rate": None,
                "expectancy": None,
                "profit_factor": None,
                "edge_after_cost_bps": None,
            }
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        expectancy = sum(returns) / n
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = None if gross_loss == 0 else gross_win / gross_loss
        edge_after_cost = expectancy * 10000.0 - float(cost_bps or 0.0)
        return {
            "sample_size": n,
            "win_rate": round(len(wins) / n, 4),
            "expectancy": round(expectancy, 8),
            "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "edge_after_cost_bps": round(edge_after_cost, 4),
        }
