"""
Deflated Sharpe Ratio + Walk-Forward math (DOMAIN 6, spec-compliant).

Pure functions — no DB, no broker, no I/O. Composable with the existing
WalkForwardEngine. References:

  Bailey & Lopez de Prado, "The Deflated Sharpe Ratio", JPM 40(5), 2014:
    SR_0 = sqrt(Var(SR_estimates)) * ((1-y)*Phi^-1(1-1/N) + y*Phi^-1(1-1/N*e^-1))
    DSR  = Phi((SR_hat - SR_0)*sqrt(T-1)/sqrt(1 - skew*SR_hat + (kurt-1)/4*SR_hat^2))
  Promotion gate: DSR > 0.95 (one-sided p < 0.05).

  Pardo 2008 walk-forward:
    Default ratio 3:1 in-sample : out-of-sample.
    Promotion gate: mean(WFE) >= 0.5 across >=5 walks AND min(OOS_sharpe) > 0.3.

  Expected decay (McLean & Pontiff 2016; Falck/Rej/Thesmar 2021):
    live_sharpe ~= 0.5 * backtest_sharpe.
    Strategy promotes to "active paper" only if backtest_sharpe >= 2.0.
"""

from __future__ import annotations

import math
import statistics
from typing import Any


EULER_MASCHERONI = 0.5772156649015329


def _phi(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _phi_inv(p: float) -> float:
    """Inverse standard normal CDF via Newton iteration."""
    if p <= 0:
        return -8.0
    if p >= 1:
        return 8.0
    x = 0.0
    for _ in range(60):
        fx = _phi(x) - p
        fpx = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
        if fpx == 0:
            break
        x -= fx / fpx
        if abs(fx) < 1e-9:
            break
    return x


def annualised_sharpe(returns: list[float], periods_per_year: float = 252.0) -> float:
    if len(returns) < 2:
        return 0.0
    mean = statistics.mean(returns)
    sd = statistics.stdev(returns)
    if sd == 0:
        return 0.0
    return (mean / sd) * math.sqrt(periods_per_year)


def _skew(data: list[float]) -> float:
    n = len(data)
    if n < 3:
        return 0.0
    m = statistics.mean(data)
    s = statistics.stdev(data)
    if s == 0:
        return 0.0
    return (sum((x - m) ** 3 for x in data) / n) / (s ** 3)


def _excess_kurtosis(data: list[float]) -> float:
    n = len(data)
    if n < 4:
        return 0.0
    m = statistics.mean(data)
    s = statistics.stdev(data)
    if s == 0:
        return 0.0
    return (sum((x - m) ** 4 for x in data) / n) / (s ** 4) - 3.0


def compute_dsr(
    sr_hat: float,
    n_trials: int,
    t_periods: int,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    var_sr_estimates: float = 1.0,
) -> dict[str, float]:
    """
    Returns DSR + the threshold (>0.95) the spec uses for promotion.
    """
    if n_trials < 1 or t_periods < 2:
        return {
            "sr_hat": round(sr_hat, 4),
            "sr_0": 0.0,
            "dsr_p": 0.5,
            "passes_dsr_gate": False,
            "dsr_threshold": 0.95,
        }

    var_sr = max(var_sr_estimates, 0.01)
    z1 = _phi_inv(1.0 - 1.0 / n_trials)
    z2 = _phi_inv(1.0 - 1.0 / (n_trials * math.e))
    sr_0 = math.sqrt(var_sr) * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)

    denom_sq = 1.0 - skew * sr_hat + ((excess_kurtosis - 1.0) / 4.0) * (sr_hat ** 2)
    denom = math.sqrt(max(denom_sq, 1e-6))
    numerator = (sr_hat - sr_0) * math.sqrt(max(t_periods - 1, 1))
    dsr_p = _phi(numerator / denom) if denom > 0 else 0.5

    return {
        "sr_hat": round(sr_hat, 4),
        "sr_0": round(sr_0, 4),
        "dsr_p": round(dsr_p, 4),
        "passes_dsr_gate": dsr_p >= 0.95,
        "dsr_threshold": 0.95,
        "n_trials": n_trials,
        "t_periods": t_periods,
    }


def run_walk_forward(
    returns: list[float],
    *,
    is_period: int = 30,
    oos_period: int = 10,
    step: int = 10,
    periods_per_year: float = 252.0,
) -> dict[str, Any]:
    """Pardo (2008) walk-forward.  Returns WFE, mean OOS, verdict."""
    walks: list[dict[str, float]] = []
    pos = 0
    window = is_period + oos_period
    while pos + window <= len(returns):
        is_slice = returns[pos: pos + is_period]
        oos_slice = returns[pos + is_period: pos + window]
        is_sr = annualised_sharpe(is_slice, periods_per_year)
        oos_sr = annualised_sharpe(oos_slice, periods_per_year)
        wfe = (oos_sr / is_sr) if is_sr != 0 else 0.0
        walks.append({
            "window_start": pos,
            "is_sharpe": round(is_sr, 4),
            "oos_sharpe": round(oos_sr, 4),
            "wfe": round(wfe, 4),
        })
        pos += step

    if not walks:
        return {
            "walks_count": 0,
            "mean_wfe": 0.0,
            "mean_oos_sharpe": 0.0,
            "min_oos_sharpe": 0.0,
            "verdict": "insufficient_data",
            "walks": [],
            "passes_walk_forward_gate": False,
        }

    wfes = [w["wfe"] for w in walks]
    oos_sharpes = [w["oos_sharpe"] for w in walks]
    mean_wfe = statistics.mean(wfes)
    mean_oos = statistics.mean(oos_sharpes)
    min_oos = min(oos_sharpes)
    passes = len(walks) >= 5 and mean_wfe >= 0.5 and min_oos > 0.3

    return {
        "walks_count": len(walks),
        "mean_wfe": round(mean_wfe, 4),
        "mean_oos_sharpe": round(mean_oos, 4),
        "min_oos_sharpe": round(min_oos, 4),
        "verdict": "promote_to_paper" if passes else "shadow_only",
        "walks": walks,
        "passes_walk_forward_gate": passes,
    }


def build_promotion_verdict(returns: list[float], n_trials: int) -> dict[str, Any]:
    """One-call composite: WFE + DSR + decay gate.  Used by backtest router."""
    if len(returns) < 5:
        return {
            "verdict": "insufficient_data",
            "blockers": ["fewer_than_5_returns"],
            "trades": len(returns),
        }

    sr = annualised_sharpe(returns)
    skew = _skew(returns)
    kurt = _excess_kurtosis(returns)
    dsr = compute_dsr(sr, n_trials, len(returns), skew, kurt)
    wf = run_walk_forward(returns)

    live_sr_est = 0.5 * sr
    decay_pass = live_sr_est >= 1.0
    all_gates_pass = dsr["passes_dsr_gate"] and wf["passes_walk_forward_gate"] and decay_pass

    blockers: list[str] = []
    if not dsr["passes_dsr_gate"]:
        blockers.append(f"dsr_p={dsr['dsr_p']:.3f}<0.95")
    if not wf["passes_walk_forward_gate"]:
        blockers.append(f"wfe={wf['mean_wfe']:.3f}/min_oos={wf['min_oos_sharpe']:.3f}")
    if not decay_pass:
        blockers.append(f"live_sr_est={live_sr_est:.2f}<1.0_need_bt_sr>=2.0")

    return {
        "verdict": "promote_to_paper" if all_gates_pass else "shadow_only",
        "sharpe_backtest": round(sr, 4),
        "live_sharpe_estimate": round(live_sr_est, 4),
        "skew": round(skew, 4),
        "excess_kurtosis": round(kurt, 4),
        "dsr": dsr,
        "walk_forward": wf,
        "decay_gate_pass": decay_pass,
        "blockers": blockers,
        "trades": len(returns),
    }
