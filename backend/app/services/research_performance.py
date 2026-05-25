"""Research performance gates — reject/promote rules from config only."""

from __future__ import annotations

from typing import Any


def evaluate_metrics(metrics: dict[str, Any], config: dict) -> dict[str, Any]:
    rcfg = config.get("research") or {}
    exp = metrics.get("expectancy")
    pf = metrics.get("profit_factor")
    mdd = metrics.get("max_drawdown_pct") or (metrics.get("max_drawdown") or 0) * 100
    if metrics.get("max_drawdown") is not None and metrics.get("max_drawdown_pct") is None:
        mdd = float(metrics.get("max_drawdown", 0)) * 100
    trades = int(metrics.get("num_trades") or 0)
    conf = metrics.get("confidence") or metrics.get("confidence_label") or "low"

    min_pf = float(rcfg.get("promotion_min_profit_factor", 1.1))
    max_dd = float(rcfg.get("promotion_max_drawdown_pct", 25.0))
    low_sample = int(rcfg.get("low_sample_trade_threshold", 10))

    reasons: list[str] = []
    if exp is not None and float(exp) < 0:
        reasons.append("negative expectancy")
    if pf is not None and float(pf) < 1.0:
        reasons.append("profit_factor below 1")
    if pf is not None and float(pf) < min_pf:
        reasons.append(f"profit_factor below {min_pf}")
    if mdd and float(mdd) > max_dd:
        reasons.append(f"max_drawdown above {max_dd}%")
    if mdd and float(mdd) >= 90:
        reasons.append("extreme drawdown after costs")
    if trades < low_sample:
        reasons.append("insufficient trade sample for promotion")

    reject = bool(reasons) or (exp is not None and float(exp) < 0)
    promote_allowed = not reject and trades >= low_sample and (pf or 0) >= min_pf

    if reject:
        recommended = "do_not_promote"
    elif promote_allowed:
        recommended = "walk_forward_validation"
    else:
        recommended = "revise_parameters"

    return {
        "reject": reject,
        "promote_allowed": promote_allowed,
        "rejection_reason": "; ".join(reasons) if reasons else None,
        "recommended_action": recommended,
        "confidence": conf,
    }
