"""Capital bucket allocation from config — no hard-coded percentages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BucketAllocation:
    stock_day_bucket: float
    crypto_night_bucket: float
    reserve_cash_bucket: float
    emergency_cash_bucket: float
    account_equity: float

    def to_dict(self) -> dict:
        return {
            "stock_day_bucket": round(self.stock_day_bucket, 2),
            "crypto_night_bucket": round(self.crypto_night_bucket, 2),
            "reserve_cash_bucket": round(self.reserve_cash_bucket, 2),
            "emergency_cash_bucket": round(self.emergency_cash_bucket, 2),
            "account_equity": round(self.account_equity, 2),
        }


def get_bucket_fractions(config: dict) -> dict[str, float]:
    buckets = config.get("capital_buckets", {})
    return {
        "stock_day_bucket": buckets.get("stock_day_bucket_fraction", 0.5),
        "crypto_night_bucket": buckets.get("crypto_night_bucket_fraction", 0.3),
        "reserve_cash_bucket": buckets.get("reserve_cash_bucket_fraction", 0.15),
        "emergency_cash_bucket": buckets.get("emergency_cash_bucket_fraction", 0.05),
    }


def compute_buckets(account_equity: float, config: dict) -> BucketAllocation:
    fr = get_bucket_fractions(config)
    return BucketAllocation(
        stock_day_bucket=account_equity * fr["stock_day_bucket"],
        crypto_night_bucket=account_equity * fr["crypto_night_bucket"],
        reserve_cash_bucket=account_equity * fr["reserve_cash_bucket"],
        emergency_cash_bucket=account_equity * fr["emergency_cash_bucket"],
        account_equity=account_equity,
    )


def bucket_for_asset_class(asset_class: str, buckets: BucketAllocation) -> float:
    if asset_class == "crypto":
        return buckets.crypto_night_bucket
    return buckets.stock_day_bucket


def compute_position_size(
    size_by_risk: float,
    size_by_bucket: float,
    size_by_strategy_cap: float,
    size_by_buying_power: float,
) -> float:
    return max(0.0, min(size_by_risk, size_by_bucket, size_by_strategy_cap, size_by_buying_power))
