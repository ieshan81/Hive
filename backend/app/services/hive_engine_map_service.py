"""Hive Engine Map — read-only aggregation of the whole trading engine's truth.

One read-only view of every lifecycle node (Universe → … → Promotion), the paper/live separation,
and the latest completed trade lifecycle. Aggregates EXISTING read models; submits no order, makes
no mutation, exposes no raw secrets. No live path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import (
    AlphaScorecard,
    LessonNode,
    OrderRecord,
    PaperExperimentOutcome,
    PositionSnapshot,
    ResearchBacktestRun,
    SymbolCandidate,
)


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _count(session: Session, model, *where) -> int:
    q = select(func.count()).select_from(model)
    for w in where:
        q = q.where(w)
    try:
        return int(session.exec(q).one() or 0)
    except Exception:
        return 0


def _node(key, label, status, *, endpoint, service, evidence_id=None, last_error=None,
          blockers=None, can_mutate=False, operator_required=False, live_path=False) -> dict[str, Any]:
    return {
        "key": key, "label": label, "status": status,
        "source_endpoint": endpoint, "service": service,
        "latest_evidence_id": evidence_id, "last_error": last_error,
        "blockers": blockers or [], "can_mutate": can_mutate,
        "operator_required": operator_required, "live_path": live_path,
    }


class HiveEngineMapService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def map(self) -> dict[str, Any]:
        s = self.session
        # --- aggregate existing read models (resilient) ---
        try:
            from app.services.alpha_research_read_model_service import AlphaResearchReadModelService
            arm = AlphaResearchReadModelService(s, self.config)
            af = arm.status()
            paper_exp = __import__("app.services.paper_exploration_service", fromlist=["PaperExplorationService"]).PaperExplorationService(s, self.config).status()
        except Exception:
            af, paper_exp = {}, {}
        try:
            from app.services.mission_control_read_model import _execution_safety
            from app.services.config_manager import ConfigManager
            exec_safety = _execution_safety(s, ConfigManager(s).get_current())
        except Exception:
            exec_safety = {}
        try:
            mem = __import__("app.services.memory_governance_service", fromlist=["MemoryGovernanceService"]).MemoryGovernanceService(s).archive_noisy_active_memory(dry_run=True)
        except Exception:
            mem = {}

        scorecards = _count(s, AlphaScorecard)
        candidates = _count(s, SymbolCandidate)
        positions = _count(s, PositionSnapshot, PositionSnapshot.qty > 0)
        backtests = _count(s, ResearchBacktestRun)
        outcomes = _count(s, PaperExperimentOutcome)
        active_mem = _count(s, LessonNode, LessonNode.status == "active")

        latest_outcome = s.exec(
            select(PaperExperimentOutcome).where(PaperExperimentOutcome.trade_id != None)  # noqa: E711
            .order_by(PaperExperimentOutcome.created_at.desc()).limit(1)
        ).first() or s.exec(select(PaperExperimentOutcome).order_by(PaperExperimentOutcome.created_at.desc()).limit(1)).first()

        # --- paper/live separation (single source of truth) ---
        separation = {
            "real_money_locked": not bool(exec_safety.get("live_orders_enabled", False)),
            "live_disabled": bool(exec_safety.get("live_trading_locked", True)),
            "standard_paper_entries": "ALLOWED" if exec_safety.get("new_entries_allowed") else "BLOCKED",
            "paper_exploration": "ALLOWED" if paper_exp.get("paper_exploration_allowed") else "BLOCKED",
            "exits": "ACTIVE" if exec_safety.get("exits_allowed", True) else "BLOCKED",
        }

        # --- lifecycle nodes ---
        nodes = [
            _node("universe", "Universe", "ok" if candidates else "idle",
                  endpoint="/api/universe", service="autonomous_strategy_generator", evidence_id=candidates),
            _node("signal", "Signal", "ok" if backtests else "idle",
                  endpoint="/api/alpha-factory/research-runs", service="research worker", evidence_id=backtests),
            _node("scorecard", "Scorecard", "ok" if scorecards else "idle",
                  endpoint="/api/alpha-factory/scorecards", service="AutonomousAlphaFactoryService", evidence_id=scorecards),
            _node("candidate", "Near-Miss / Candidate", "ok",
                  endpoint="/api/alpha-factory/near-misses", service="PaperExplorationService",
                  evidence_id=(paper_exp.get("current_exploration_candidate") or {}).get("symbol")),
            _node("risk_cage", "Risk Cage", "armed",
                  endpoint="/api/mission-control/status", service="ExecutionCage", operator_required=True,
                  blockers=[] if separation["paper_exploration"] == "ALLOWED" else [paper_exp.get("paper_exploration_block_reason")]),
            _node("preflight", "Preflight", "armed",
                  endpoint="/api/alpha-factory/run-exploration", service="run_preflight", operator_required=True),
            _node("broker", "Broker (paper)", "connected" if exec_safety.get("broker_connected") else "unknown",
                  endpoint="/api/positions", service="PaperExecutionService → AlpacaAdapter", operator_required=True),
            _node("position", "Position State", "flat" if positions == 0 else "open",
                  endpoint="/api/positions", service="PositionSnapshot", evidence_id=positions),
            _node("exit_monitor", "Exit Monitor", "active" if separation["exits"] == "ACTIVE" else "blocked",
                  endpoint="/api/autopilot/decision-state", service="exit_monitor_service"),
            _node("outcome", "Outcome", "ok" if outcomes else "idle",
                  endpoint="/api/alpha-factory/export-bundle", service="ClosedTradeOutcomeService", evidence_id=outcomes),
            _node("memory", "Memory", "ok" if active_mem else "idle",
                  endpoint="/api/memory/governance-summary", service="MemoryGovernanceService",
                  evidence_id=mem.get("evidence_linked_preserved"),
                  blockers=([f"{mem.get('would_archive')} noisy lessons"] if mem.get("would_archive") else [])),
            _node("backtest_lab", "Backtest Lab", "ok" if backtests else "idle",
                  endpoint="/api/lab/status", service="ResearchLabService", evidence_id=backtests),
            _node("promotion", "Promotion", "gated",
                  endpoint="/api/alpha-factory/status", service="promotion.evaluate",
                  evidence_id=af.get("paper_candidate_count"),
                  blockers=["needs >=20 closed trades + PF>1.10 + positive expectancy"], live_path=False),
        ]

        return {
            "status": "ok",
            "generated_at": _now(),
            "orders_authority": "cage_only",
            "paper_live_separation": separation,
            "nodes": nodes,
            "latest_trade_lifecycle": None if not latest_outcome else {
                "symbol": latest_outcome.symbol,
                "trade_id": latest_outcome.trade_id,
                "entry_price": latest_outcome.entry_price,
                "exit_price": latest_outcome.exit_price,
                "realized_pnl": latest_outcome.realized_pnl,
                "realized_pnl_pct": latest_outcome.realized_pnl_pct,
                "exit_reason": latest_outcome.canonical_exit_reason or latest_outcome.exit_reason,
                "outcome_status": "closed" if latest_outcome.realized_pnl is not None else "incomplete",
                "memory_lesson_status": "linked" if latest_outcome.lesson_created else "pending",
            },
            "counts": {
                "universe": candidates, "scorecards": scorecards, "backtests": backtests,
                "open_positions": positions, "closed_outcomes": outcomes, "active_memory": active_mem,
                "paper_candidates": af.get("paper_candidate_count", 0),
            },
        }
