"""Position sizing for small paper accounts — reserve cash aware."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.capital_buckets import BucketAllocation, bucket_for_asset_class
from app.services import quant_math


@dataclass
class SizeResult:
    quantity: float
    notional: float
    size_by_risk: float
    size_by_bucket: float
    size_by_position_cap: float
    size_by_buying_power: float
    usable_cash: float
    block_reason: Optional[str] = None
    block_code: Optional[str] = None


def usable_cash_after_reserve(cash: float, buckets: BucketAllocation) -> float:
    reserved = buckets.reserve_cash_bucket + buckets.emergency_cash_bucket
    return max(0.0, cash - reserved)


def compute_safe_position_size(
    *,
    account_equity: float,
    cash: float,
    buying_power: float,
    entry_price: float,
    stop_loss: Optional[float],
    asset_class: str,
    buckets: BucketAllocation,
    config: dict,
    broker_position_qty: float = 0.0,
    is_exit: bool = False,
) -> SizeResult:
    max_risk_pct = config.get("max_risk_per_trade", 0.01)
    max_pos_pct = config.get("max_position_size_pct", 0.25)
    min_notional = config.get("min_order_notional_usd", 1.0)

    usable = usable_cash_after_reserve(cash, buckets)
    bucket_cap = bucket_for_asset_class(asset_class, buckets)

    if entry_price is None or entry_price <= 0:
        return SizeResult(0, 0, 0, 0, 0, 0, usable, "Missing or invalid entry price", "DATA_MISSING")

    if is_exit:
        qty = broker_position_qty
        notional = qty * entry_price
        return SizeResult(qty, notional, 0, 0, 0, 0, usable)

    if stop_loss is None:
        return SizeResult(0, 0, 0, 0, 0, 0, usable, "Stop-loss required", "MISSING_STOP_LOSS")

    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        return SizeResult(0, 0, 0, 0, 0, 0, usable, "Invalid stop distance", "INVALID_STOP_DISTANCE")

    risk_dollars = account_equity * max_risk_pct
    size_by_risk = quant_math.position_quantity(risk_dollars, entry_price, stop_loss)
    size_by_bucket = bucket_cap / entry_price if bucket_cap > 0 else 0
    size_by_position_cap = (account_equity * max_pos_pct) / entry_price if account_equity > 0 else 0
    size_by_bp = min(buying_power, usable) / entry_price if entry_price > 0 else 0

    qty = max(0.0, min(size_by_risk, size_by_bucket, size_by_position_cap, size_by_bp))
    notional = qty * entry_price

    if usable < min_notional and notional > 0:
        return SizeResult(
            0,
            0,
            size_by_risk,
            size_by_bucket,
            size_by_position_cap,
            size_by_bp,
            usable,
            f"Usable cash ${usable:.2f} below reserve after buckets",
            "INSUFFICIENT_BUYING_POWER",
        )

    if notional > 0 and notional < min_notional:
        return SizeResult(
            0,
            notional,
            size_by_risk,
            size_by_bucket,
            size_by_position_cap,
            size_by_bp,
            usable,
            f"Notional ${notional:.2f} below minimum ${min_notional:.2f}",
            "NOTIONAL_TOO_SMALL",
        )

    return SizeResult(
        qty,
        notional,
        size_by_risk,
        size_by_bucket,
        size_by_position_cap,
        size_by_bp,
        usable,
    )
