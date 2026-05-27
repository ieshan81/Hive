from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session

router = APIRouter(prefix="/api/push-pull", tags=["push-pull"])


@router.get("/status")
def status(session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).status()


@router.get("/latest-tick")
def latest_tick(session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).latest_tick()


@router.get("/decisions")
def decisions(limit: int = 50, session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).decisions(limit)


@router.get("/lessons")
def lessons(limit: int = 40, session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).lessons(limit)


@router.get("/signals")
def signals(symbol: str | None = None, timeframe: str = "5Min", session: Session = Depends(get_session)):
    from app.services.push_pull_engine_service import PushPullEngineService

    return PushPullEngineService(session).signals(symbol=symbol, timeframe=timeframe)


@router.get("/paper-order-proof")
def paper_order_proof(session: Session = Depends(get_session)):
    from app.services.paper_order_proof_service import PaperOrderProofService

    return PaperOrderProofService(session).summary()


@router.get("/diagnosis")
def diagnosis(session: Session = Depends(get_session)):
    from app.services.push_pull_diagnosis_service import PushPullDiagnosisService

    return PushPullDiagnosisService(session).why_no_order()


@router.get("/exit-monitor/status")
def exit_monitor(session: Session = Depends(get_session)):
    from app.services.exit_monitor_service import exit_monitor_status

    return exit_monitor_status(session)


# ─────────────────────────────────────────────────────────────────────────
# Live scoring path using research push-pull formulas
# ─────────────────────────────────────────────────────────────────────────

DEFAULT_LIVE_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD"]


def _score_live(session: Session, symbols: list[str]) -> dict:
    from datetime import datetime
    from app.services.alpaca_adapter import AlpacaAdapter
    from app.services.push_pull_scorer import evaluate_entry, classify_regime

    adapter = AlpacaAdapter(session)
    if not adapter.configured:
        return {
            "status": "ok",
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "scores": [],
            "note": "Alpaca not configured — live scoring unavailable.",
        }

    out = []
    for sym in symbols:
        bars_1m = adapter.get_crypto_bars(sym, timeframe="1Min", limit=30) or []
        bars_5m = adapter.get_crypto_bars(sym, timeframe="5Min", limit=12) or []
        quote = adapter.get_quote(sym, "crypto") or {}
        if not bars_1m:
            out.append({"symbol": sym, "pass": False, "reason": "NO_BARS"})
            continue
        regime = classify_regime(bars_1m)
        evaluation = evaluate_entry(
            sym, bars_1m, bars_5m, quote,
            bar_age_seconds=0.0,
            universe_rank_score=0.5,
            sentiment_alignment=0.0,
            regime=regime,
            side="buy",
        )
        out.append(evaluation)
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "scores": out,
        "symbols_evaluated": len(symbols),
        "passed_count": sum(1 for s in out if s.get("pass")),
    }


@router.get("/scores")
def live_scores(session: Session = Depends(get_session)):
    """Push-pull live scoring across default symbol set."""
    return _score_live(session, DEFAULT_LIVE_SYMBOLS)


@router.get("/candidates")
def live_candidates(session: Session = Depends(get_session)):
    """Symbols that pass the push/quality/edge gates."""
    scored = _score_live(session, DEFAULT_LIVE_SYMBOLS)
    candidates = [s for s in scored.get("scores", []) if s.get("pass")]
    return {
        **scored,
        "candidates": candidates,
        "candidate_count": len(candidates),
    }


@router.get("/no-trade-reasons")
def no_trade_reasons(session: Session = Depends(get_session)):
    """Breakdown of why eligible-but-blocked symbols were rejected."""
    from collections import Counter

    scored = _score_live(session, DEFAULT_LIVE_SYMBOLS)
    counter: Counter = Counter()
    by_symbol: dict[str, list] = {}
    for s in scored.get("scores", []):
        if not s.get("pass"):
            for r in (s.get("reasons") or [s.get("reason", "unknown")]):
                counter[r] += 1
            by_symbol[s["symbol"]] = s.get("reasons", [])
    return {
        "status": "ok",
        "generated_at_utc": scored.get("generated_at_utc"),
        "reason_breakdown": dict(counter),
        "by_symbol": by_symbol,
    }
