"""Cost model for autonomous alpha research.

Research and paper governance need the same boring truth: expected movement has
to clear spread, slippage, and fees. This service is deterministic and never
submits orders or fetches provider data.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.engine_config import cfg_get


class CostModelService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def estimate(
        self,
        symbol: str,
        *,
        expected_move_pct: Optional[float] = None,
        quote: Optional[dict[str, Any]] = None,
        spread_pct: Optional[float] = None,
        asset_class: Optional[str] = None,
    ) -> dict[str, Any]:
        del self.session
        asset = asset_class or ("crypto" if "/" in str(symbol or "") else "stock")
        raw_spread = spread_pct
        if raw_spread is None and quote:
            raw_spread = quote.get("spread_pct")
        if raw_spread is None:
            raw_spread = cfg_get(self.config, "cost.default_spread_pct_crypto" if asset == "crypto" else "cost.default_spread_pct_stock", 0.001)
        spread_pct_f = max(0.0, float(raw_spread or 0.0))
        fee_pct = max(0.0, float(cfg_get(self.config, "cost.taker_fee_pct", 0.0) or 0.0))
        slip_key = "cost.slippage_buffer_major_pct" if asset == "crypto" else "cost.slippage_buffer_stock_pct"
        slippage_pct = max(0.0, float(cfg_get(self.config, slip_key, 0.0005) or 0.0))
        round_trip_pct = (spread_pct_f + slippage_pct + fee_pct) * 2.0
        expected = None if expected_move_pct is None else float(expected_move_pct)
        edge_after_cost_pct = None if expected is None else expected - round_trip_pct
        min_expected_move_pct = round_trip_pct * float(cfg_get(self.config, "alpha_factory.cost_edge_multiplier", 1.25) or 1.25)
        status = "ok"
        blockers: list[str] = []
        if expected is not None and expected <= round_trip_pct:
            status = "blocked"
            blockers.append("expected_move_does_not_clear_round_trip_cost")
        max_spread_bps = float(cfg_get(self.config, "alpha_factory.max_spread_bps", 80.0) or 80.0)
        if spread_pct_f * 10000.0 > max_spread_bps:
            status = "blocked"
            blockers.append("spread_too_wide")
        return {
            "status": status,
            "symbol": symbol,
            "asset_class": asset,
            "spread_pct": spread_pct_f,
            "spread_bps": round(spread_pct_f * 10000.0, 4),
            "slippage_pct": slippage_pct,
            "slippage_bps": round(slippage_pct * 10000.0, 4),
            "fee_pct": fee_pct,
            "fee_bps": round(fee_pct * 10000.0, 4),
            "round_trip_cost_pct": round_trip_pct,
            "round_trip_cost_bps": round(round_trip_pct * 10000.0, 4),
            "minimum_expected_move_pct": min_expected_move_pct,
            "minimum_expected_move_bps": round(min_expected_move_pct * 10000.0, 4),
            "expected_move_pct": expected,
            "edge_after_cost_pct": edge_after_cost_pct,
            "edge_after_cost_bps": None if edge_after_cost_pct is None else round(edge_after_cost_pct * 10000.0, 4),
            "blockers": blockers,
        }
