"""Read-only diagnostic for Alpha Factory scorecards.

Classifies WHY each scorecard failed promotion and surfaces the cost-vs-edge truth
(the production blocker is `edge_after_cost_not_positive`, but the per-scorecard cost
breakdown is not stored). This script computes the deterministic round-trip cost per
symbol and shows whether the setup is cost-negative, data-starved, or genuinely bad.

Pure read: never mutates scorecards, never trades, never promotes. Run:
    python backend/scripts/analyze_alpha_scorecards.py
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from app.database import AlphaScorecard, engine, init_db
from app.services.engine_config import cfg_get
from app.services.research_cost_model import round_trip_cost_pct


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def classify(sc: AlphaScorecard, config: dict, min_sample: int) -> dict:
    exp = _num(sc.expectancy)
    sample = int(sc.sample_size or 0)
    bars = int(sc.bar_count or 0)
    rt = round_trip_cost_pct(sc.symbol, config)
    rt_pct = rt["round_trip_pct"]
    # gross expectancy = net expectancy + round-trip cost we subtracted
    gross_exp = (exp + rt_pct) if exp is not None else None
    if sample == 0 or bars == 0:
        cat = "data_insufficient"
    elif sample < min_sample:
        cat = "not_enough_trades"
    elif exp is not None and exp <= 0 and gross_exp is not None and gross_exp > 0:
        cat = "costs_too_high"
    elif exp is not None and exp <= 0:
        cat = "negative_expectancy"
    elif str(sc.data_freshness_status) not in ("fresh", "cached_ok", "unknown"):
        cat = "stale_data"
    else:
        cat = "other"
    return {
        "symbol": sc.symbol,
        "normalized_symbol": sc.normalized_symbol,
        "strategy_id": sc.strategy_id,
        "strategy_family": sc.strategy_family,
        "verdict": sc.verdict,
        "sample_size": sample,
        "bar_count": bars,
        "win_rate": _num(sc.win_rate),
        "expectancy": exp,
        "gross_expectancy_est": round(gross_exp, 6) if gross_exp is not None else None,
        "profit_factor": _num(sc.profit_factor),
        "edge_after_cost_bps": _num(sc.edge_after_cost_bps),
        "round_trip_cost_pct": round(rt_pct, 6),
        "round_trip_cost_bps": round(rt_pct * 10000, 1),
        "break_even_move_pct": round(rt_pct, 6),
        "data_freshness_status": sc.data_freshness_status,
        "blocker_reasons": list(sc.blocker_reasons_json or []),
        "category": cat,
    }


def analyze(session: Session) -> dict:
    config = {}
    try:
        from app.services.config_manager import ConfigManager

        config = ConfigManager(session).get_current()
    except Exception:
        config = {}
    min_sample = int(cfg_get(config, "alpha_factory.min_sample_size", 5) or 5)
    cards = list(session.exec(select(AlphaScorecard).order_by(AlphaScorecard.updated_at.desc())).all())
    rows = [classify(c, config, min_sample) for c in cards]

    cats = Counter(r["category"] for r in rows)
    blockers = Counter(b for r in rows for b in r["blocker_reasons"])
    # closest to paper_candidate: sufficient sample, least-negative net edge
    eligible = [r for r in rows if r["sample_size"] >= min_sample and r["expectancy"] is not None]
    closest = max(eligible, key=lambda r: r["expectancy"], default=None)
    with_exp = [r for r in rows if r["expectancy"] is not None]
    best = max(with_exp, key=lambda r: r["expectancy"], default=None)
    worst = min(with_exp, key=lambda r: r["expectancy"], default=None)
    families_tested = sorted({r["strategy_family"] for r in rows})
    data_starved = [r["symbol"] for r in rows if r["category"] == "data_insufficient"]

    return {
        "status": "ok",
        "scorecard_count": len(rows),
        "category_breakdown": dict(cats),
        "common_failure_reasons": blockers.most_common(6),
        "closest_to_paper_candidate": closest,
        "biggest_blocker": (blockers.most_common(1)[0][0] if blockers else None),
        "best_symbol": (best["symbol"] if best else None),
        "worst_symbol": (worst["symbol"] if worst else None),
        "data_missing_symbols": data_starved,
        "strategy_families_tested": families_tested,
        "scorecards": rows,
    }


if __name__ == "__main__":
    init_db()
    with Session(engine) as s:
        import json

        out = analyze(s)
        slim = {k: v for k, v in out.items() if k != "scorecards"}
        print(json.dumps(slim, indent=2, default=str))
        print(f"\n[ok] analyzed {out['scorecard_count']} scorecards")
