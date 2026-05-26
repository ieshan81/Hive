"""Alpaca crypto order precision — Decimal quantization, no float artifacts."""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Optional


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_qty(qty: float, increment: Optional[float]) -> tuple[float, dict[str, Any]]:
    raw = _dec(qty)
    inc = _dec(increment) if increment and float(increment) > 0 else Decimal("0.000000001")
    if inc <= 0:
        inc = Decimal("0.000000001")
    steps = (raw / inc).to_integral_value(rounding=ROUND_DOWN)
    normalized = steps * inc
    return float(normalized), {
        "raw_qty": float(raw),
        "normalized_qty": float(normalized),
        "min_trade_increment": float(inc),
        "qty_rounding": "ROUND_DOWN",
    }


def quantize_limit_price(
    price: float,
    increment: Optional[float],
    *,
    max_decimal_places: int = 9,
) -> tuple[float, dict[str, Any]]:
    raw = _dec(price)
    inc = _dec(increment) if increment and float(increment) > 0 else Decimal("0.000000001")
    if inc <= 0:
        inc = Decimal("0.000000001")
    steps = (raw / inc).to_integral_value(rounding=ROUND_HALF_UP)
    normalized = steps * inc
    # Hard cap decimal places for Alpaca (e.g. BTC/USD max 9)
    fmt = f"{{0:.{max_decimal_places}f}}"
    capped = Decimal(fmt.format(normalized))
    return float(capped), {
        "raw_limit_price": float(raw),
        "normalized_limit_price": float(capped),
        "price_increment": float(inc),
        "max_decimal_places": max_decimal_places,
        "precision_valid": True,
    }


def normalize_order_fields(
    *,
    qty: Optional[float] = None,
    limit_price: Optional[float] = None,
    min_trade_increment: Optional[float] = None,
    price_increment: Optional[float] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"precision_valid": True}
    if qty is not None:
        nqty, qmeta = quantize_qty(qty, min_trade_increment)
        out["normalized_qty"] = nqty
        out.update({f"qty_{k}": v for k, v in qmeta.items() if k != "normalized_qty"})
    if limit_price is not None:
        npx, pxmeta = quantize_limit_price(limit_price, price_increment)
        out["normalized_limit_price"] = npx
        out.update({f"limit_{k}": v for k, v in pxmeta.items() if k != "normalized_limit_price"})
    return out
