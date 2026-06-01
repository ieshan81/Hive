"""Kronos market-model adapter — research spike, OPTIONAL, OFF by default.

Kronos (shiyu-coder/Kronos, "Kronos: A Foundation Model for the Language of Financial
Markets") forecasts K-line / candlestick data. This adapter is a SAFE, OPTIONAL feature
source for Alpha Factory *scoring only*:

* never places, sizes, approves, or cancels an order;
* never bypasses Alpha Factory, the cost model, walk-forward validation, the kill switch,
  broker truth, or the risk cage;
* never required for boot — if the package/model is absent it reports ``available=false``
  and Alpha Factory continues on deterministic evidence;
* its weight in an alpha score is capped (default 0.10, hard-capped) and may only *nudge*
  ranking. It can NEVER promote a candidate, and can NEVER turn zero-sample or
  negative-expectancy evidence into a ``paper_candidate``.

No model weights live in the repo and nothing is downloaded at import/boot time.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Optional

MODEL_NAME = "kronos"
_VALID_SIZES = ("mini", "small", "base")
_HARD_WEIGHT_CAP = 0.25  # Kronos can never exceed this share of an alpha score.


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def kronos_config() -> dict[str, Any]:
    """Read-only env-derived config. KRONOS_ENABLED defaults False (we never set env)."""
    size = str(os.environ.get("KRONOS_MODEL_SIZE", "mini") or "mini").strip().lower()
    if size not in _VALID_SIZES:
        size = "mini"
    try:
        max_ctx = int(os.environ.get("KRONOS_MAX_CONTEXT", "512") or 512)
    except (TypeError, ValueError):
        max_ctx = 512
    try:
        weight = float(os.environ.get("KRONOS_WEIGHT_IN_ALPHA_SCORE", "0.10") or 0.10)
    except (TypeError, ValueError):
        weight = 0.10
    return {
        "enabled": _env_bool("KRONOS_ENABLED", False),
        "model_size": size,
        "max_context": max(16, min(4096, max_ctx)),
        "weight_in_alpha_score": max(0.0, min(_HARD_WEIGHT_CAP, weight)),
    }


class KronosMarketModelService:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.cfg = kronos_config()

    # ---- availability ----
    def is_available(self) -> bool:
        """True only when explicitly enabled AND the optional dependency is importable.
        Never raises; missing dependency / disabled flag => False."""
        if not self.cfg["enabled"]:
            return False
        try:
            return (
                importlib.util.find_spec("kronos") is not None
                and importlib.util.find_spec("torch") is not None
            )
        except Exception:
            return False

    def _unavailable(self, symbol: str, timeframe: str, reason: str, error: Optional[str] = None) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "model_name": MODEL_NAME,
            "available": False,
            "forecast_direction": "unavailable",
            "confidence": None,
            "expected_move_bps": None,
            "volatility_forecast": None,
            "reason": reason,
            "error_if_unavailable": error,
            "evidence_json": {"enabled": self.cfg["enabled"], "model_size": self.cfg["model_size"]},
        }

    # ---- forecast ----
    def forecast_symbol(self, symbol: str, timeframe: str, candles: Any) -> dict[str, Any]:
        """Return a forecast structure. When Kronos is unavailable (default), returns a
        well-formed unavailable result rather than raising."""
        symbol = str(symbol or "")
        timeframe = str(timeframe or "")
        if not self.is_available():
            reason = "kronos_disabled" if not self.cfg["enabled"] else "kronos_dependency_missing"
            return self._unavailable(symbol, timeframe, reason)
        if not candles:
            return self._unavailable(symbol, timeframe, "no_candles")
        # Dependency present + enabled but no weights ship in-repo / no boot download:
        # run inside a guard so any inference/load failure degrades gracefully (no crash,
        # no fabricated forecast).
        try:
            raise RuntimeError("kronos_inference_not_wired")  # spike: interface only, no weights bundled
        except Exception as exc:  # noqa: BLE001
            return self._unavailable(symbol, timeframe, "kronos_inference_unavailable", error=type(exc).__name__)

    def score_forecast(self, symbol: str, strategy_family: str, candles: Any) -> dict[str, Any]:
        """Optional ranking feature. Returns a capped contribution; can_promote is ALWAYS
        False — Kronos may only nudge ranking, never promote."""
        fc = self.forecast_symbol(symbol, "5Min", candles)
        contribution = 0.0
        if fc.get("available") and fc.get("forecast_direction") in ("bullish", "bearish"):
            signed = 1.0 if fc["forecast_direction"] == "bullish" else -1.0
            contribution = signed * float(fc.get("confidence") or 0.0) * self.cfg["weight_in_alpha_score"]
            contribution = max(-self.cfg["weight_in_alpha_score"], min(self.cfg["weight_in_alpha_score"], contribution))
        return {
            "symbol": symbol,
            "strategy_family": strategy_family,
            "available": bool(fc.get("available")),
            "score_contribution": round(contribution, 6),
            "weight_cap": self.cfg["weight_in_alpha_score"],
            "can_promote": False,  # invariant: Kronos can never promote a candidate
            "forecast": fc,
        }

    def explain_forecast_result(self, result: dict[str, Any]) -> str:
        if not self.cfg["enabled"]:
            return "Kronos disabled. Alpha Factory using deterministic evidence only."
        if not (result or {}).get("available"):
            return "Kronos unavailable. Continuing without market-model forecast."
        direction = (result or {}).get("forecast_direction", "neutral")
        sym = (result or {}).get("symbol", "symbol")
        return f"Kronos {direction} on {sym}, but candidate remains unproven until backtest and cost gates pass."

    def status_summary(self) -> dict[str, Any]:
        """Read-only summary for /api/alpha-factory/status (kronos_* fields)."""
        available = self.is_available()
        if not self.cfg["enabled"]:
            plain = "Kronos disabled. Alpha Factory using deterministic evidence only."
        elif not available:
            plain = "Kronos unavailable. Continuing without market-model forecast."
        else:
            plain = "Kronos enabled and available (advisory ranking feature only; cannot promote)."
        return {
            "kronos_enabled": self.cfg["enabled"],
            "kronos_available": available,
            "kronos_weight_cap": self.cfg["weight_in_alpha_score"],
            "kronos_last_result": None,
            "kronos_plain_english": plain,
        }


def apply_kronos_to_ranking(
    base_verdict: str,
    base_rank_score: float,
    kronos_score: dict[str, Any],
    weight_cap: float = 0.10,
) -> tuple[str, float]:
    """Combine a base verdict + rank score with an optional Kronos contribution.

    INVARIANT: the verdict is returned UNCHANGED — Kronos can only nudge the numeric rank
    score within the weight cap, never change a verdict or promote a candidate.
    """
    contribution = float((kronos_score or {}).get("score_contribution") or 0.0)
    cap = abs(float(weight_cap))
    contribution = max(-cap, min(cap, contribution))
    return base_verdict, float(base_rank_score) + contribution
