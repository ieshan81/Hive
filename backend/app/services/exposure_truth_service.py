"""Broker-first exposure truth for duplicate-buy and stale local state handling.

Local trade rows are evidence/memory. Broker position truth is the authority when
it is available. This service never places orders and never deletes records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PositionSnapshot, TradeRecord
from app.services.order_ledger_service import display_symbol, normalize_symbol


def _qty(value: Any) -> float:
    try:
        return abs(float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _position_symbol(pos: Any) -> str:
    if isinstance(pos, dict):
        return str(pos.get("symbol") or pos.get("sym") or "")
    return str(getattr(pos, "symbol", "") or "")


def _position_qty(pos: Any) -> float:
    if isinstance(pos, dict):
        return _qty(pos.get("qty"))
    return _qty(getattr(pos, "qty", 0))


def _position_market_value(pos: Any) -> float:
    if isinstance(pos, dict):
        return _qty(pos.get("market_value") or pos.get("marketValue"))
    return _qty(getattr(pos, "market_value", 0))


@dataclass
class ExposureTruth:
    normalized_symbol: str
    display_symbol: str
    broker_qty: float = 0.0
    broker_market_value: float = 0.0
    broker_position_open: bool = False
    local_open_trade_count: int = 0
    local_open_trade_ids: list[int] = field(default_factory=list)
    local_position_qty: float = 0.0
    reconciliation_state: str = "unknown"
    broker_flat: bool = False
    stale_local_open: bool = False
    effective_exposure_state: str = "unknown"
    authority: str = "unknown"
    confidence: str = "low"
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "normalized_symbol": self.normalized_symbol,
            "display_symbol": self.display_symbol,
            "broker_qty": self.broker_qty,
            "broker_market_value": self.broker_market_value,
            "broker_position_open": self.broker_position_open,
            "local_open_trade_count": self.local_open_trade_count,
            "local_open_trade_ids": self.local_open_trade_ids,
            "local_position_qty": self.local_position_qty,
            "reconciliation_state": self.reconciliation_state,
            "broker_flat": self.broker_flat,
            "stale_local_open": self.stale_local_open,
            "effective_exposure_state": self.effective_exposure_state,
            "authority": self.authority,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


class ExposureTruthService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def fresh_broker_positions(self) -> tuple[list[Any], bool, dict[str, Any]]:
        """Fetch authoritative broker positions once.

        Cached PositionSnapshot rows are useful fallback evidence, but they are
        not broker truth for repair/decision-state decisions. A caller that needs
        broker authority should call this once and pass the returned positions
        into get_symbol_exposure/stale_local_summary.
        """
        try:
            from app.services.alpaca_adapter import AlpacaAdapter

            adapter = AlpacaAdapter(self.session)
            if not adapter.configured:
                return [], False, {"source": "fresh_broker_sync", "reason": "alpaca_not_configured"}
            positions = adapter.sync_positions_cached(force=True)
            if getattr(adapter, "broker_sync_rate_limited", False):
                return [], False, {"source": "fresh_broker_sync", "reason": "broker_sync_rate_limited"}
            if getattr(adapter, "broker_sync_failed", False):
                return [], False, {"source": "fresh_broker_sync", "reason": "broker_sync_failed"}
            return list(positions or []), True, {
                "source": "fresh_broker_sync",
                "position_count": len(positions or []),
            }
        except Exception as exc:
            return [], False, {
                "source": "fresh_broker_sync",
                "reason": "broker_sync_failed",
                "error_type": type(exc).__name__,
            }

    def _broker_truth_available(
        self,
        *,
        broker_positions: Optional[list[Any]],
        explicit: Optional[bool],
    ) -> tuple[bool, dict[str, Any]]:
        if explicit is not None:
            return bool(explicit), {"source": "explicit", "broker_truth_available": bool(explicit)}
        if broker_positions is not None:
            return True, {"source": "provided_positions", "position_count": len(broker_positions or [])}
        return False, {
            "source": "local_fallback_only",
            "broker_truth_available": False,
            "reason": "fresh_or_explicit_broker_positions_required",
        }

    def _position_rows(self, broker_positions: Optional[list[Any]]) -> list[Any]:
        if broker_positions is not None:
            return list(broker_positions or [])
        return list(self.session.exec(select(PositionSnapshot)).all())

    def _local_open_trades(self, normalized: str) -> list[TradeRecord]:
        rows = list(
            self.session.exec(select(TradeRecord).where(TradeRecord.status == "open")).all()
        )
        return [r for r in rows if normalize_symbol(r.symbol) == normalized]

    def get_symbol_exposure(
        self,
        symbol: str,
        *,
        broker_positions: Optional[list[Any]] = None,
        broker_truth_available: Optional[bool] = None,
    ) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        disp = display_symbol(symbol)
        available, availability_evidence = self._broker_truth_available(
            broker_positions=broker_positions,
            explicit=broker_truth_available,
        )
        positions = self._position_rows(broker_positions)
        matching_positions = [p for p in positions if normalize_symbol(_position_symbol(p)) == normalized]
        broker_qty = max((_position_qty(p) for p in matching_positions), default=0.0)
        broker_mv = max((_position_market_value(p) for p in matching_positions), default=0.0)
        local_positions = [
            p for p in self.session.exec(select(PositionSnapshot)).all() if normalize_symbol(p.symbol) == normalized
        ]
        local_position_qty = max((_position_qty(p) for p in local_positions), default=0.0)
        local_open = self._local_open_trades(normalized)
        local_ids = [int(r.id) for r in local_open if r.id is not None]
        broker_open = available and broker_qty > 0
        broker_flat = available and broker_qty <= 0
        stale_local = broker_flat and bool(local_open)

        if broker_open:
            state = "broker_open"
            authority = "broker_truth"
            confidence = "high"
            recon = "broker_open"
        elif broker_flat and local_open:
            state = "broker_flat_local_stale"
            authority = "broker_truth"
            confidence = "high"
            recon = "broker_flat_local_stale"
        elif broker_flat:
            state = "broker_flat_local_clean"
            authority = "broker_truth"
            confidence = "high"
            recon = "broker_flat_local_clean"
        elif local_open or local_position_qty > 0:
            state = "broker_unknown_local_open"
            authority = "local_fallback"
            confidence = "medium"
            recon = "broker_unknown_local_open"
        else:
            state = "unknown"
            authority = "unknown"
            confidence = "low"
            recon = "unknown"

        return ExposureTruth(
            normalized_symbol=normalized,
            display_symbol=disp,
            broker_qty=broker_qty,
            broker_market_value=broker_mv,
            broker_position_open=bool(broker_open),
            local_open_trade_count=len(local_open),
            local_open_trade_ids=local_ids,
            local_position_qty=local_position_qty,
            reconciliation_state=recon,
            broker_flat=bool(broker_flat),
            stale_local_open=bool(stale_local),
            effective_exposure_state=state,
            authority=authority,
            confidence=confidence,
            evidence={
                "broker_truth_available": available,
                "availability": availability_evidence,
                "matching_broker_position_count": len(matching_positions),
                "matching_local_position_count": len(local_positions),
                "local_open_trade_ids": local_ids,
            },
        ).as_dict()

    def duplicate_buy_decision(
        self,
        symbol: str,
        *,
        broker_positions: Optional[list[Any]] = None,
        broker_truth_available: Optional[bool] = None,
    ) -> dict[str, Any]:
        exposure = self.get_symbol_exposure(
            symbol,
            broker_positions=broker_positions,
            broker_truth_available=broker_truth_available,
        )
        state = exposure["effective_exposure_state"]
        blocked = state in {"broker_open", "broker_unknown_local_open"}
        reason = None
        if state == "broker_open":
            reason = "broker_position_exists"
        elif state == "broker_unknown_local_open":
            reason = "broker_unknown_local_open_fallback"
        allowed_reason = None
        if state == "broker_flat_local_stale":
            allowed_reason = "broker_flat_overrides_stale_local_open"
        return {
            "blocked": blocked,
            "reason": reason,
            "duplicate_check_source": exposure["authority"],
            "allowed_reason": allowed_reason,
            **exposure,
        }

    def stale_local_summary(
        self,
        *,
        broker_positions: Optional[list[Any]] = None,
        broker_truth_available: Optional[bool] = None,
    ) -> dict[str, Any]:
        rows = list(self.session.exec(select(TradeRecord).where(TradeRecord.status == "open")).all())
        symbols = sorted({display_symbol(r.symbol) for r in rows})
        broker_flat_symbols = []
        for sym in symbols:
            exp = self.get_symbol_exposure(
                sym,
                broker_positions=broker_positions,
                broker_truth_available=broker_truth_available,
            )
            if exp.get("stale_local_open"):
                broker_flat_symbols.append(sym)
        exposure_by_symbol = {
            sym: self.get_symbol_exposure(
                sym,
                broker_positions=broker_positions,
                broker_truth_available=broker_truth_available,
            )
            for sym in broker_flat_symbols
        }
        return {
            "stale_local_open_trade_count": len(rows),
            "stale_local_open_symbols": symbols,
            "broker_flat_stale_trade_count": sum(
                int(exposure_by_symbol[sym].get("local_open_trade_count") or 0)
                for sym in broker_flat_symbols
            ),
            "broker_flat_stale_symbols": broker_flat_symbols,
            "duplicate_buy_source_of_truth": "broker_truth_first_with_local_fallback",
        }
