"""Shadow comparison: legacy (double-counting) vs corrected cost model per scorecard.

Diagnostic ONLY — never promotes, never mutates scorecards, never trades. Recomputes each
scorecard's net expectancy/profit-factor and shadow verdict under the corrected cost model
to prove the cost fix does not silently create paper_candidates.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from app.database import AlphaScorecard, engine, init_db
from app.services.engine_config import cfg_get
from app.services.research_cost_model import legacy_round_trip_cost_pct, round_trip_cost_pct


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _shadow_verdict(sample, new_net_exp, pf, dd, min_sample, min_pf) -> str:
    if sample == 0:
        return "unproven"
    if sample < min_sample:
        return "unproven"
    if new_net_exp is None or new_net_exp <= 0:
        return "rejected"
    if pf is None or pf < min_pf:
        return "rejected"
    if dd is not None and dd > 35.0:
        return "rejected"
    return "paper_candidate"  # only if all evidence passes


def analyze(session: Session) -> dict:
    config = {}
    try:
        from app.services.config_manager import ConfigManager

        config = ConfigManager(session).get_current()
    except Exception:
        config = {}
    min_sample = int(cfg_get(config, "alpha_factory.min_sample_size", 5) or 5)
    min_pf = float(cfg_get(config, "alpha_factory.min_profit_factor", 1.05) or 1.05)
    cards = list(session.exec(select(AlphaScorecard)).all())
    rows = []
    flips_to_candidate = 0
    for sc in cards:
        oldc = legacy_round_trip_cost_pct(sc.symbol, config)["round_trip_pct"]
        newc = round_trip_cost_pct(sc.symbol, config)["round_trip_pct"]
        net_exp = _num(sc.expectancy)  # stored net (old-cost-adjusted)
        gross = (net_exp + oldc) if net_exp is not None else None  # back out old cost
        new_net = (gross - newc) if gross is not None else None
        pf = _num(sc.profit_factor)
        dd = _num(sc.max_drawdown_pct)
        sample = int(sc.sample_size or 0)
        shadow = _shadow_verdict(sample, new_net, pf, dd, min_sample, min_pf)
        if shadow == "paper_candidate" and sc.verdict != "paper_candidate":
            flips_to_candidate += 1
        rows.append({
            "symbol": sc.symbol,
            "strategy_id": sc.strategy_id,
            "old_round_trip_bps": round(oldc * 10000, 1),
            "new_round_trip_bps": round(newc * 10000, 1),
            "gross_expectancy_bps": round(gross * 10000, 1) if gross is not None else None,
            "old_net_expectancy_bps": round(net_exp * 10000, 1) if net_exp is not None else None,
            "new_net_expectancy_bps": round(new_net * 10000, 1) if new_net is not None else None,
            "profit_factor": pf,
            "old_verdict": sc.verdict,
            "new_shadow_verdict": shadow,
            "verdict_changed": shadow != sc.verdict,
            "reason": "still cost/edge-negative" if shadow in ("rejected", "unproven") else "would qualify — REVIEW",
        })
    return {
        "status": "ok",
        "scorecard_count": len(rows),
        "new_paper_candidates_from_cost_fix": flips_to_candidate,
        "cost_fix_creates_fake_candidates": flips_to_candidate > 0,
        "rows": rows,
    }


if __name__ == "__main__":
    import json

    init_db()
    with Session(engine) as s:
        out = analyze(s)
        print(json.dumps(out, indent=2, default=str))
        print(f"\n[ok] {out['scorecard_count']} scorecards; cost fix creates "
              f"{out['new_paper_candidates_from_cost_fix']} new candidate(s) "
              f"({'FAIL — review' if out['cost_fix_creates_fake_candidates'] else 'none — safe'})")
