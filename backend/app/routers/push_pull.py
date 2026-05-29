"""Push-Pull read endpoints.

Dashboard GET routes in this module are read-only. They summarize persisted
tick/scan state and do not fetch Alpaca bars/quotes or rescore live data.
Use operator POST routes such as /api/universe/score or
/api/autonomous-paper-learning/run-one-cycle for heavy work.
"""

from __future__ import annotations

from datetime import datetime
from collections import Counter

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/push-pull", tags=["push-pull"])

DEFAULT_LIVE_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD"]


@router.get("/status")
def status(session: Session = Depends(get_session)):
    """READ ONLY: persisted push-pull scheduler/tick status."""
    from app.services.mission_control_read_model import build_mission_control_status

    st = build_mission_control_status(session)
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        **(st.get("push_pull") or {}),
        "read_model_only": True,
    }


@router.get("/latest-tick")
def latest_tick(session: Session = Depends(get_session)):
    """READ ONLY: latest persisted tick summary."""
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).latest_tick()


@router.get("/decisions")
def decisions(limit: int = 50, session: Session = Depends(get_session)):
    """READ ONLY: persisted paper experiment decisions."""
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).decisions(limit)


@router.get("/lessons")
def lessons(limit: int = 40, session: Session = Depends(get_session)):
    """READ ONLY: persisted lessons."""
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).lessons(limit)


@router.get("/signals")
def signals(symbol: str | None = None, timeframe: str = "5Min", session: Session = Depends(get_session)):
    """READ ONLY: persisted/derived signal labels from cached state."""
    from app.services.mission_control_read_model import build_mission_control_status

    st = build_mission_control_status(session)
    candidates = (st.get("universe") or {}).get("top_candidates") or []
    selected = None
    if symbol:
        target = symbol.upper().replace("-", "/")
        selected = next((c for c in candidates if str(c.get("symbol") or "").upper() == target), None)
    selected = selected or (candidates[0] if candidates else None)
    return {
        "status": st.get("status"),
        "generated_at_utc": st.get("generated_at_utc"),
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_signal": selected,
        "push_pull_labels": {
            "last_result": (st.get("push_pull") or {}).get("last_result"),
            "top_rejected_reason": (st.get("push_pull") or {}).get("top_rejected_reason"),
            "data_stale": (st.get("push_pull") or {}).get("data_stale"),
        },
        "read_model_only": True,
    }


@router.get("/paper-order-proof")
def paper_order_proof(session: Session = Depends(get_session)):
    """READ ONLY: persisted paper order proof."""
    from app.services.paper_order_proof_service import PaperOrderProofService

    return PaperOrderProofService(session).summary()


@router.get("/diagnosis")
def diagnosis(session: Session = Depends(get_session)):
    """READ ONLY: persisted no-order diagnosis."""
    from app.services.push_pull_diagnosis_service import PushPullDiagnosisService

    return PushPullDiagnosisService(session).why_no_order()


@router.get("/exit-monitor/status")
def exit_monitor(session: Session = Depends(get_session)):
    """READ ONLY: exit monitor status from local state."""
    from app.services.exit_monitor_service import exit_monitor_status

    return exit_monitor_status(session)


def _score_live(session: Session, symbols: list[str]) -> dict:
    from app.services.mission_control_read_model import build_mission_control_status

    st = build_mission_control_status(session)
    scores = (st.get("universe") or {}).get("top_candidates") or []
    normalized = []
    for row in scores:
        normalized.append(
            {
                **row,
                "pass": bool(row.get("entry_allowed") or row.get("eligible") or row.get("symbol")),
                "push_score": row.get("push_score") or 0,
                "edge_bps": row.get("edge_after_cost_bps") or row.get("edge_bps") or 0,
                "quality_score": row.get("trade_quality_score") or row.get("quality_score") or 0,
                "reason": row.get("no_trade_reason"),
            }
        )
    return {
        "status": st.get("status"),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "scores": normalized,
        "symbols_evaluated": (st.get("universe") or {}).get("funnel", {}).get("scored", len(normalized)),
        "passed_count": (st.get("universe") or {}).get("funnel", {}).get("eligible", len(normalized)),
        "read_model_only": True,
        "note": "GET returns the last persisted scan. Use POST /api/universe/score or agent cycle to rescore.",
    }


@router.get("/scores")
def live_scores(session: Session = Depends(get_session)):
    """READ ONLY: last persisted push-pull score rows."""
    return _score_live(session, DEFAULT_LIVE_SYMBOLS)


@router.get("/candidates")
def live_candidates(session: Session = Depends(get_session)):
    """READ ONLY: last persisted candidate rows."""
    scored = _score_live(session, DEFAULT_LIVE_SYMBOLS)
    candidates = [s for s in scored.get("scores", []) if s.get("pass")]
    return {
        **scored,
        "candidates": candidates,
        "candidate_count": len(candidates),
    }


@router.get("/no-trade-reasons")
def no_trade_reasons(session: Session = Depends(get_session)):
    """READ ONLY: blocker breakdown from last persisted score rows."""
    scored = _score_live(session, DEFAULT_LIVE_SYMBOLS)
    counter: Counter = Counter()
    by_symbol: dict[str, list] = {}
    for s in scored.get("scores", []):
        if not s.get("pass"):
            for r in (s.get("reasons") or [s.get("reason", "unknown")]):
                counter[r] += 1
            if s.get("symbol"):
                by_symbol[str(s["symbol"])] = s.get("reasons", [])
    return {
        "status": "ok",
        "generated_at_utc": scored.get("generated_at_utc"),
        "reason_breakdown": dict(counter),
        "by_symbol": by_symbol,
        "read_model_only": True,
    }
