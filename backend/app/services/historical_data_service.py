"""Historical bar storage — Alpaca first, honest gaps, no fake candles."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import HistoricalBar, HistoricalDataCoverage, HistoricalDataError, HistoricalDataRequest
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol


def _parse_ts(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val
    s = str(val).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s.replace("+00:00", ""))
    except ValueError:
        return datetime.utcnow()


def _date_str(val: Any) -> Optional[str]:
    if not val:
        return None
    return str(val)[:10]


class HistoricalDataService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.alpaca = AlpacaAdapter(session)

    def list_coverage(self) -> list[dict[str, Any]]:
        rows = self.session.exec(
            select(HistoricalDataCoverage).order_by(HistoricalDataCoverage.symbol)
        ).all()
        return [self._coverage_dict(r) for r in rows]

    def _coverage_dict(self, r: HistoricalDataCoverage) -> dict[str, Any]:
        return {
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "requested_start_date": r.requested_start_date,
            "requested_end_date": r.requested_end_date,
            "actual_start_date": r.actual_start_date or r.start_date,
            "actual_end_date": r.actual_end_date or r.end_date,
            "data_is_recent": r.data_is_recent,
            "data_staleness_days": r.data_staleness_days,
            "date_warning": r.date_warning,
            "rows_count": r.rows_count,
            "source": r.source,
            "gaps_detected": r.gaps_detected,
            "gap_notes": r.gap_notes,
            "last_updated": r.last_updated.isoformat() + "Z" if r.last_updated else None,
        }

    def _compute_date_meta(
        self, bars: list[dict], lookback_days: int
    ) -> dict[str, Any]:
        now = datetime.utcnow()
        requested_end = now.date().isoformat()
        requested_start = (now - timedelta(days=lookback_days)).date().isoformat()
        if not bars:
            return {
                "requested_start_date": requested_start,
                "requested_end_date": requested_end,
                "actual_start_date": None,
                "actual_end_date": None,
                "data_is_recent": False,
                "data_staleness_days": 9999,
                "date_warning": f"No bars returned for requested {lookback_days}-day window",
            }
        last_ts = _parse_ts(bars[-1]["timestamp"])
        first_ts = _parse_ts(bars[0]["timestamp"])
        actual_end = last_ts.date().isoformat()
        actual_start = first_ts.date().isoformat()
        staleness = (now.date() - last_ts.date()).days
        data_is_recent = staleness <= max(3, lookback_days // 10)
        warning = None
        if staleness > 7:
            warning = (
                f"Requested {lookback_days} days of recent data "
                f"({requested_start} to {requested_end}) but actual range is "
                f"{actual_start} to {actual_end} ({staleness} days stale)."
            )
        return {
            "requested_start_date": requested_start,
            "requested_end_date": requested_end,
            "actual_start_date": actual_start,
            "actual_end_date": actual_end,
            "data_is_recent": data_is_recent,
            "data_staleness_days": staleness,
            "date_warning": warning,
        }

    def _trim_to_lookback(self, bars: list[dict], lookback_days: int) -> list[dict]:
        if not bars or lookback_days <= 0:
            return bars
        sorted_bars = sorted(bars, key=lambda b: _parse_ts(b["timestamp"]))
        end = _parse_ts(sorted_bars[-1]["timestamp"])
        cutoff = end - timedelta(days=lookback_days)
        trimmed = [b for b in sorted_bars if _parse_ts(b["timestamp"]) >= cutoff]
        if len(trimmed) < 10 and len(sorted_bars) >= 10:
            trimmed = sorted_bars[-min(len(sorted_bars), lookback_days * 24) :]
        return trimmed

    def fetch_and_store(
        self,
        symbol: str,
        *,
        timeframe: str = "1Hour",
        limit: int = 500,
        asset_class: str = "crypto",
        lookback_days: Optional[int] = None,
    ) -> dict[str, Any]:
        lb = lookback_days or max(30, limit // 24)
        req = HistoricalDataRequest(
            symbol=symbol,
            timeframe=timeframe,
            status="pending",
            created_at=datetime.utcnow(),
        )
        self.session.add(req)
        self.session.flush()

        if not self.alpaca.configured:
            req.status = "error"
            req.error_message = "Alpaca not configured"
            self._log_error(symbol, timeframe, "fetch", req.error_message)
            return {"status": "error", "message": req.error_message, "rows": 0}

        try:
            if asset_class == "crypto":
                quote_sym = normalize_crypto_symbol(symbol)
                bars = self.alpaca.get_crypto_bars(
                    quote_sym,
                    timeframe=timeframe,
                    limit=limit,
                    lookback_days=lb,
                )
            else:
                bars = self.alpaca.get_bars(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            req.status = "error"
            req.error_message = str(e)[:300]
            self._log_error(symbol, timeframe, "fetch", req.error_message)
            return {"status": "error", "message": req.error_message, "rows": 0}

        bars = sorted(bars, key=lambda b: _parse_ts(b["timestamp"]))
        bars = self._trim_to_lookback(bars, lb)
        bars = bars[-limit:] if len(bars) > limit else bars

        if len(bars) < 2:
            req.status = "error"
            req.error_message = f"Insufficient bars ({len(bars)})"
            self._log_error(symbol, timeframe, "fetch", req.error_message)
            return {"status": "error", "message": req.error_message, "rows": len(bars)}

        stored = 0
        for b in bars:
            ts = _parse_ts(b.get("timestamp"))
            exists = self.session.exec(
                select(HistoricalBar).where(
                    HistoricalBar.symbol == symbol,
                    HistoricalBar.timeframe == timeframe,
                    HistoricalBar.timestamp == ts,
                )
            ).first()
            if exists:
                continue
            self.session.add(
                HistoricalBar(
                    symbol=symbol,
                    asset_class=asset_class,
                    timeframe=timeframe,
                    timestamp=ts,
                    open=float(b["open"]),
                    high=float(b["high"]),
                    low=float(b["low"]),
                    close=float(b["close"]),
                    volume=float(b.get("volume") or 0),
                    source="alpaca",
                    synthetic=False,
                )
            )
            stored += 1

        gaps = self._detect_gaps(bars, timeframe)
        date_meta = self._compute_date_meta(bars, lb)
        cov = self.session.exec(
            select(HistoricalDataCoverage).where(
                HistoricalDataCoverage.symbol == symbol,
                HistoricalDataCoverage.timeframe == timeframe,
            )
        ).first()
        if not cov:
            cov = HistoricalDataCoverage(symbol=symbol, timeframe=timeframe)
        cov.start_date = date_meta["actual_start_date"]
        cov.end_date = date_meta["actual_end_date"]
        cov.requested_start_date = date_meta["requested_start_date"]
        cov.requested_end_date = date_meta["requested_end_date"]
        cov.actual_start_date = date_meta["actual_start_date"]
        cov.actual_end_date = date_meta["actual_end_date"]
        cov.data_is_recent = date_meta["data_is_recent"]
        cov.data_staleness_days = date_meta["data_staleness_days"]
        cov.date_warning = date_meta["date_warning"]
        cov.rows_count = len(
            self.session.exec(
                select(HistoricalBar).where(
                    HistoricalBar.symbol == symbol, HistoricalBar.timeframe == timeframe
                )
            ).all()
        )
        cov.source = "alpaca"
        cov.gaps_detected = gaps
        cov.gap_notes = "gap detected in bar sequence" if gaps else None
        cov.last_updated = datetime.utcnow()
        self.session.add(cov)

        req.status = "ok"
        req.rows_fetched = stored
        self.session.add(req)
        return {
            "status": "ok",
            "symbol": symbol,
            "timeframe": timeframe,
            "rows_stored": stored,
            "total_bars": len(bars),
            "gaps_detected": gaps,
            **date_meta,
        }

    def get_bars(
        self,
        symbol: str,
        *,
        timeframe: str = "1Hour",
        min_rows: int = 30,
        lookback_days: Optional[int] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Load from DB or fetch from Alpaca if insufficient; trim to lookback window."""
        lb = lookback_days or 90
        rows = list(
            self.session.exec(
                select(HistoricalBar)
                .where(HistoricalBar.symbol == symbol, HistoricalBar.timeframe == timeframe)
                .order_by(HistoricalBar.timestamp)
            ).all()
        )
        meta: dict[str, Any] = {"source": "database", "synthetic": False, "gaps_detected": False}
        if len(rows) < min_rows:
            fetch = self.fetch_and_store(
                symbol, timeframe=timeframe, limit=min(500, lb * 24), lookback_days=lb
            )
            if fetch.get("status") != "ok":
                return [], {"error": fetch.get("message"), "confidence": "none", **fetch}
            rows = list(
                self.session.exec(
                    select(HistoricalBar)
                    .where(HistoricalBar.symbol == symbol, HistoricalBar.timeframe == timeframe)
                    .order_by(HistoricalBar.timestamp)
                ).all()
            )
            meta["source"] = "alpaca_fresh"
            for k in (
                "requested_start_date",
                "requested_end_date",
                "actual_start_date",
                "actual_end_date",
                "data_is_recent",
                "data_staleness_days",
                "date_warning",
            ):
                if fetch.get(k) is not None:
                    meta[k] = fetch[k]
        if len(rows) < min_rows:
            return [], {
                "error": f"Only {len(rows)} bars — insufficient for research",
                "confidence": "low",
            }
        bars = [
            {
                "timestamp": r.timestamp.isoformat() + "Z",
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
        bars = self._trim_to_lookback(bars, lb)
        date_meta = self._compute_date_meta(bars, lb)
        meta.update(date_meta)
        cov = self.session.exec(
            select(HistoricalDataCoverage).where(
                HistoricalDataCoverage.symbol == symbol,
                HistoricalDataCoverage.timeframe == timeframe,
            )
        ).first()
        if cov and cov.gaps_detected:
            meta["gaps_detected"] = True
        meta["rows"] = len(bars)
        meta["confidence"] = "medium" if len(bars) >= 120 else "low"
        return bars, meta

    def _detect_gaps(self, bars: list[dict], timeframe: str) -> bool:
        if len(bars) < 3:
            return False
        step = timedelta(hours=1) if "Hour" in timeframe else timedelta(minutes=5)
        prev = _parse_ts(bars[0].get("timestamp"))
        for b in bars[1:]:
            cur = _parse_ts(b.get("timestamp"))
            if cur - prev > step * 2.5:
                return True
            prev = cur
        return False

    def _log_error(self, symbol: str, timeframe: str, op: str, msg: str) -> None:
        self.session.add(
            HistoricalDataError(
                symbol=symbol,
                timeframe=timeframe,
                operation=op,
                message=msg[:500],
            )
        )
