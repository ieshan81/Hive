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


class HistoricalDataService:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config
        self.alpaca = AlpacaAdapter(session)

    def list_coverage(self) -> list[dict[str, Any]]:
        rows = self.session.exec(
            select(HistoricalDataCoverage).order_by(HistoricalDataCoverage.symbol)
        ).all()
        return [
            {
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "rows_count": r.rows_count,
                "source": r.source,
                "gaps_detected": r.gaps_detected,
                "gap_notes": r.gap_notes,
                "last_updated": r.last_updated.isoformat() + "Z" if r.last_updated else None,
            }
            for r in rows
        ]

    def fetch_and_store(
        self,
        symbol: str,
        *,
        timeframe: str = "1Hour",
        limit: int = 500,
        asset_class: str = "crypto",
    ) -> dict[str, Any]:
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
                bars = self.alpaca.get_crypto_bars(quote_sym, timeframe=timeframe, limit=limit)
            else:
                bars = self.alpaca.get_bars(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            req.status = "error"
            req.error_message = str(e)[:300]
            self._log_error(symbol, timeframe, "fetch", req.error_message)
            return {"status": "error", "message": req.error_message, "rows": 0}

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
        start = str(bars[0].get("timestamp", ""))[:10] if bars else None
        end = str(bars[-1].get("timestamp", ""))[:10] if bars else None
        cov = self.session.exec(
            select(HistoricalDataCoverage).where(
                HistoricalDataCoverage.symbol == symbol,
                HistoricalDataCoverage.timeframe == timeframe,
            )
        ).first()
        if not cov:
            cov = HistoricalDataCoverage(symbol=symbol, timeframe=timeframe)
        cov.start_date = start
        cov.end_date = end
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
            "start_date": start,
            "end_date": end,
        }

    def get_bars(
        self,
        symbol: str,
        *,
        timeframe: str = "1Hour",
        min_rows: int = 30,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Load from DB or fetch from Alpaca if insufficient."""
        rows = list(
            self.session.exec(
                select(HistoricalBar)
                .where(HistoricalBar.symbol == symbol, HistoricalBar.timeframe == timeframe)
                .order_by(HistoricalBar.timestamp)
            ).all()
        )
        meta = {"source": "database", "synthetic": False, "gaps_detected": False}
        if len(rows) < min_rows:
            fetch = self.fetch_and_store(symbol, timeframe=timeframe, limit=500)
            if fetch.get("status") != "ok":
                return [], {"error": fetch.get("message"), "confidence": "none"}
            rows = list(
                self.session.exec(
                    select(HistoricalBar)
                    .where(HistoricalBar.symbol == symbol, HistoricalBar.timeframe == timeframe)
                    .order_by(HistoricalBar.timestamp)
                ).all()
            )
            meta["source"] = "alpaca_fresh"
        if len(rows) < min_rows:
            return [], {
                "error": f"Only {len(rows)} bars — insufficient for research",
                "confidence": "low",
            }
        cov = self.session.exec(
            select(HistoricalDataCoverage).where(
                HistoricalDataCoverage.symbol == symbol,
                HistoricalDataCoverage.timeframe == timeframe,
            )
        ).first()
        if cov and cov.gaps_detected:
            meta["gaps_detected"] = True
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
