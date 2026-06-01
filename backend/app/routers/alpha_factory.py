"""Autonomous Alpha Factory API.

GET routes are read-only. POST routes are operator research controls and never
submit broker orders.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.services.alpha_research_read_model_service import AlphaResearchReadModelService
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService
from app.services.autonomous_alpha_scheduler import AutonomousAlphaScheduler
from app.services.cost_model_service import CostModelService
from app.services.operator_auth import require_operator_token
from app.services.parameter_sweep_service import ParameterSweepService
from app.services.walk_forward_validation_service import WalkForwardValidationService

router = APIRouter(prefix="/api/alpha-factory", tags=["alpha-factory"])


def _actor(body: dict) -> str:
    return str((body or {}).get("actor") or (body or {}).get("operator") or "operator")


def _block_ai_actor(body: dict) -> None:
    if _actor(body).lower() in {"ai", "agent", "gemini", "ai_advisor", "ai_research"}:
        raise HTTPException(403, "AI actor cannot invoke autonomous alpha operator controls")


@router.get("/status")
def status(session: Session = Depends(get_session)):
    """READ ONLY: Alpha Factory status from persisted scorecards and audits."""
    return AlphaResearchReadModelService(session).status()


@router.get("/scorecards")
def scorecards(limit: int = 100, session: Session = Depends(get_session)):
    """READ ONLY: persisted alpha scorecards."""
    return AlphaResearchReadModelService(session).scorecards(limit=limit)


@router.get("/best-candidates")
def best_candidates(limit: int = 10, session: Session = Depends(get_session)):
    """READ ONLY: ranked paper-candidate evidence."""
    return AlphaResearchReadModelService(session).best_candidates(limit=limit)


@router.get("/near-misses")
def near_misses(limit: int = 10, session: Session = Depends(get_session)):
    """READ ONLY: scorecards closest to qualifying + the single missing requirement. No trade/promote."""
    return AlphaResearchReadModelService(session).near_misses(limit=limit)


@router.get("/session-summary")
def session_summary(session: Session = Depends(get_session)):
    """READ ONLY: consolidated market-session research truth (metrics, scorecards, near-misses, memory)."""
    return AlphaResearchReadModelService(session).session_summary()


@router.get("/research-runs")
def research_runs(limit: int = 50, session: Session = Depends(get_session)):
    """READ ONLY: autonomous alpha research run history."""
    return AlphaResearchReadModelService(session).research_runs(limit=limit)


@router.get("/memory-summary")
def memory_summary(session: Session = Depends(get_session)):
    """READ ONLY: consolidated Alpha Factory memory summary."""
    return AlphaResearchReadModelService(session).memory_summary()


@router.get("/autonomous-status")
def autonomous_status(session: Session = Depends(get_session)):
    """READ ONLY: scheduler status."""
    return AlphaResearchReadModelService(session).autonomous_status()


@router.get("/explain")
def explain(symbol: str, strategy_family: str = "momentum_continuation", session: Session = Depends(get_session)):
    """READ ONLY: explain one candidate without running research."""
    return AutonomousAlphaFactoryService(session).explain_candidate(symbol, strategy_family)


@router.get("/can-trade-paper")
def can_trade_paper(
    symbol: str,
    strategy_family: str | None = None,
    strategy_id: str | None = None,
    session: Session = Depends(get_session),
):
    """READ ONLY: whether this symbol/setup has alpha evidence for paper entry."""
    return {"status": "ok", **AutonomousAlphaFactoryService(session).can_trade_paper(symbol, strategy_family, strategy_id)}


@router.post("/run-cycle")
def run_cycle(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: run Alpha Factory research cycle. No orders."""
    _block_ai_actor(body)
    out = AutonomousAlphaFactoryService(session).run_autonomous_cycle(body, operator=_actor(body))
    session.commit()
    return out


@router.post("/run-autonomous-cycle")
def run_autonomous_cycle(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: compatibility alias for run-cycle. No orders."""
    _block_ai_actor(body)
    out = AutonomousAlphaFactoryService(session).run_autonomous_cycle(body, operator=_actor(body))
    session.commit()
    return out


@router.post("/run-research-now")
def run_research_now(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: generate candidates only. No orders."""
    _block_ai_actor(body)
    out = AutonomousAlphaFactoryService(session).run_research_cycle(body, operator=_actor(body))
    session.commit()
    return out


@router.post("/run-backtests")
def run_backtests(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: run cached-data research backtests. No orders."""
    _block_ai_actor(body)
    out = AutonomousAlphaFactoryService(session).run_backtest_cycle(body, operator=_actor(body))
    session.commit()
    return out


@router.post("/promote-candidates")
def promote_candidates(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: build/update scorecards and promotion verdicts. No orders."""
    _block_ai_actor(body)
    out = AutonomousAlphaFactoryService(session).run_candidate_promotion_cycle(operator=_actor(body))
    session.commit()
    return out


@router.post("/consolidate-memory")
def consolidate_memory(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: consolidate Alpha Factory evidence into Hive memories."""
    _block_ai_actor(body)
    out = AutonomousAlphaFactoryService(session).run_memory_consolidation_cycle(operator=_actor(body))
    session.commit()
    return out


@router.post("/pause")
def pause(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: pause autonomous alpha research scheduler only."""
    _block_ai_actor(body)
    out = AutonomousAlphaScheduler(session).pause(operator=_actor(body))
    session.commit()
    return out


@router.post("/resume")
def resume(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: resume autonomous alpha research scheduler only."""
    _block_ai_actor(body)
    out = AutonomousAlphaScheduler(session).resume(operator=_actor(body))
    session.commit()
    return out


@router.post("/scheduler/run-due")
def scheduler_run_due(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: run due scheduler tick. No orders."""
    _block_ai_actor(body)
    out = AutonomousAlphaScheduler(session).run_due(operator=_actor(body), force=bool(body.get("force")))
    session.commit()
    return out


@router.post("/parameter-sweep")
def parameter_sweep(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: parameter sweep through research backtester. No orders."""
    _block_ai_actor(body)
    out = ParameterSweepService(session).run_sweep(
        strategy_id=str(body.get("strategy_id") or "crypto_push_pull_baseline"),
        symbols=[str(s) for s in (body.get("symbols") or ["BTC/USD"])],
        parameter_grid=body.get("parameter_grid") or {},
        timeframe=str(body.get("timeframe") or "5Min"),
        max_trials=int(body.get("max_trials") or 8),
    )
    session.commit()
    return out


@router.post("/walk-forward")
def walk_forward(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: walk-forward validation. No orders."""
    _block_ai_actor(body)
    out = WalkForwardValidationService(session).run_validation(
        strategy_id=str(body.get("strategy_id") or "crypto_push_pull_baseline"),
        symbol=str((body.get("symbols") or ["BTC/USD"])[0]),
        parameters=body.get("parameters") or {},
        timeframe=str(body.get("timeframe") or "5Min"),
        windows=int(body.get("windows") or 3),
    )
    session.commit()
    return out


@router.post("/cost-check")
def cost_check(
    body: dict = Body(default_factory=dict),
    session: Session = Depends(get_session),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: deterministic cost check. No orders."""
    _block_ai_actor(body)
    return CostModelService(session).estimate(
        str(body.get("symbol") or "BTC/USD"),
        expected_move_pct=body.get("expected_move_pct"),
        spread_pct=body.get("spread_pct"),
        quote=body.get("quote") if isinstance(body.get("quote"), dict) else None,
        asset_class=body.get("asset_class"),
    )
