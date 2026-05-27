"""Deterministic app-level hard reset — NUKE EVERYTHING without Railway volume wipe."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Optional, Type

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, delete, select

from app.database import (
    AccountCooldown,
    AccountSnapshot,
    ActivityLog,
    AIConfigProposal,
    AIMemory,
    AIReview,
    AIStrategyNote,
    AIUsageLog,
    BacktestResult,
    BlockedTrade,
    BrokerError,
    ConfigCurrent,
    ConfigHistory,
    ExecutionLog,
    FastTrainingLease,
    HistoricalBar,
    HistoricalDataCoverage,
    HistoricalDataError,
    HistoricalDataRequest,
    KillSwitchEvent,
    LessonNode,
    MemeSpikeEvaluation,
    MemoryEdge,
    MemoryEvidence,
    MemoryPolicyConfig,
    MonteCarloResult,
    OrderRecord,
    PaperExperimentConfig,
    PaperExperimentDecision,
    PaperExperimentOutcome,
    PaperExperimentRun,
    ParameterSetResult,
    PortfolioDecision,
    PositionEnrichedState,
    PositionSnapshot,
    PromotionStatus,
    ResearchBacktestRun,
    RiskEvent,
    SettingsActionAudit,
    StrategyAllocation,
    StrategyCandidate,
    StrategyChangeProposal,
    StrategyConflict,
    StrategyCooldown,
    StrategyDefinition,
    StrategyEligibilityWindow,
    StrategyLifecycleEvent,
    StrategyMemory,
    StrategyMemoryLink,
    StrategyPromotionRule,
    StrategyRejection,
    StrategyRegistry,
    StrategyRetirement,
    StrategyScorecard,
    StrategySignal,
    StrategyState,
    StrategyValidationResult,
    SymbolCandidate,
    SymbolCooldown,
    SymbolMemory,
    SystemHealth,
    SystemValidationAudit,
    TradeRecord,
    WalkForwardResult,
    engine,
)
from app.services.config_manager import ConfigManager
from app.services.env_pause_service import env_pause_status
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.nuke_epoch_service import RESET_EPOCH_ACTION, record_reset_epoch

RESET_LOCK_ACTION = "reset_in_progress"
RESET_LOCK_STALE_SECONDS = 600
_THREAD_LOCK = threading.Lock()

# FK-safe delete order (children / dependents first).
DELETE_MODELS_ORDER: list[Type[SQLModel]] = [
    MemoryEvidence,
    MemoryEdge,
    StrategyMemoryLink,
    PaperExperimentOutcome,
    PaperExperimentDecision,
    PaperExperimentRun,
    WalkForwardResult,
    ParameterSetResult,
    ResearchBacktestRun,
    StrategyValidationResult,
    StrategyScorecard,
    StrategyRejection,
    StrategyRetirement,
    StrategyLifecycleEvent,
    StrategyConflict,
    StrategyAllocation,
    StrategyEligibilityWindow,
    StrategyChangeProposal,
    StrategyCandidate,
    StrategyMemory,
    SymbolMemory,
    AIMemory,
    AIStrategyNote,
    AIConfigProposal,
    AIUsageLog,
    AIReview,
    LessonNode,
    MemeSpikeEvaluation,
    ExecutionLog,
    OrderRecord,
    TradeRecord,
    PositionSnapshot,
    AccountSnapshot,
    PositionEnrichedState,
    BlockedTrade,
    RiskEvent,
    StrategySignal,
    BrokerError,
    PortfolioDecision,
    ActivityLog,
    BacktestResult,
    MonteCarloResult,
    HistoricalBar,
    HistoricalDataCoverage,
    HistoricalDataRequest,
    HistoricalDataError,
    StrategyDefinition,
    StrategyRegistry,
    StrategyState,
    SymbolCandidate,
    SymbolCooldown,
    StrategyCooldown,
    AccountCooldown,
    KillSwitchEvent,
    PromotionStatus,
    PaperExperimentConfig,
    FastTrainingLease,
    SystemValidationAudit,
    StrategyPromotionRule,
    SettingsActionAudit,
    ConfigHistory,
    MemoryPolicyConfig,
]

PRESERVE_TABLES = frozenset(
    {
        "config_current",
        "system_health",
    }
)

RESEED_AFTER_RESET = frozenset(
    {
        "system_health",
        "reset_epoch",
        "nuke_everything_audit",
    }
)


def table_inventory() -> dict[str, Any]:
    """Classify every SQLModel table for operator reports."""
    all_tables = sorted(SQLModel.metadata.tables.keys())
    delete_names = {m.__tablename__ for m in DELETE_MODELS_ORDER if getattr(m, "__tablename__", None)}
    preserve = sorted(PRESERVE_TABLES)
    delete_on_nuke = sorted(delete_names)
    reseed = sorted(RESEED_AFTER_RESET)
    other = sorted(set(all_tables) - set(delete_on_nuke) - set(preserve))
    return {
        "all_tables": all_tables,
        "delete_on_nuke": delete_on_nuke,
        "preserve_on_nuke": preserve,
        "reseed_after_nuke": reseed,
        "unclassified": other,
    }


def is_reset_in_progress(session: Session) -> bool:
    return reset_lock_status(session).get("in_progress") is True


def reset_lock_status(session: Session) -> dict[str, Any]:
    rows = list(
        session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == RESET_LOCK_ACTION)
            .order_by(SettingsActionAudit.created_at.desc())
        ).all()
    )
    if not rows:
        return {"in_progress": False}
    row = rows[0]
    details = dict(row.details_json or {})
    started = details.get("started_at") or (
        row.created_at.isoformat() + "Z" if row.created_at else None
    )
    stale = False
    if row.created_at:
        stale = row.created_at < datetime.utcnow() - timedelta(seconds=RESET_LOCK_STALE_SECONDS)
    if stale:
        _clear_reset_lock_rows(session)
        return {"in_progress": False, "cleared_stale_lock": True}
    return {
        "in_progress": True,
        "started_at": started,
        "operator": row.actor,
        "reset_epoch_id": details.get("reset_epoch_id"),
    }


def _clear_reset_lock_rows(session: Session) -> None:
    session.exec(delete(SettingsActionAudit).where(SettingsActionAudit.action == RESET_LOCK_ACTION))


def _acquire_reset_lock(session: Session, operator: str, reset_epoch_id: str) -> None:
    _clear_reset_lock_rows(session)
    session.add(
        SettingsActionAudit(
            action=RESET_LOCK_ACTION,
            actor=operator,
            broker_mode="paper",
            paper_broker=True,
            live_trading_locked=True,
            live_orders_enabled=False,
            details_json={
                "started_at": datetime.utcnow().isoformat() + "Z",
                "reset_epoch_id": reset_epoch_id,
            },
        )
    )
    session.flush()


def _count_rows(session: Session, model: Type[SQLModel]) -> int:
    try:
        return len(list(session.exec(select(model)).all()))
    except Exception:
        return -1


def post_nuke_table_counts(session: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in DELETE_MODELS_ORDER:
        name = getattr(model, "__tablename__", model.__name__)
        counts[name] = _count_rows(session, model)
    for name in PRESERVE_TABLES:
        if name == "config_current":
            counts[name] = 1 if session.get(ConfigCurrent, 1) else 0
        elif name == "system_health":
            counts[name] = 1 if session.get(SystemHealth, 1) else 0
    return counts


def clear_runtime_caches() -> list[str]:
    cleared: list[str] = []
    try:
        from app.services import hive_brain_graph_service as hb

        if hasattr(hb, "_GRAPH_RESPONSE_CACHE"):
            hb._GRAPH_RESPONSE_CACHE.clear()
            cleared.append("hive_brain_graph_service._GRAPH_RESPONSE_CACHE")
    except Exception:
        pass
    return cleared


def _delete_all_app_data(session: Session) -> tuple[dict[str, Any], list[dict[str, str]]]:
    deleted: dict[str, Any] = {}
    warnings: list[dict[str, str]] = []
    session.expunge_all()

    for model in DELETE_MODELS_ORDER:
        table = getattr(model, "__tablename__", None)
        if not table:
            continue
        try:
            result = session.exec(delete(model))
            session.flush()
            deleted[table] = result.rowcount if hasattr(result, "rowcount") else "ok"
        except Exception as exc:
            warnings.append({"table": table, "error": str(exc)[:300]})
            deleted[table] = f"error:{type(exc).__name__}"
    session.expire_all()
    return deleted, warnings


def _reseed_bootstrap_rows(session: Session) -> dict[str, Any]:
    reseeded: dict[str, Any] = {}
    h = session.get(SystemHealth, 1)
    if not h:
        session.add(
            SystemHealth(
                id=1,
                alpaca_connected=False,
                gemini_configured=False,
                details={"fresh_brain": True, "reseeded_at": datetime.utcnow().isoformat() + "Z"},
            )
        )
        reseeded["system_health"] = "created"
    else:
        h.details = {**(h.details or {}), "fresh_brain": True}
        session.add(h)
        reseeded["system_health"] = "updated"
    cfg = session.get(ConfigCurrent, 1)
    reseeded["config_current"] = "present" if cfg else "missing_will_seed_on_read"
    return reseeded


def execute_nuke_reset(session: Session, operator: str = "operator") -> dict[str, Any]:
    """
    Full transactional app reset. Does not touch config learning/scheduler flags or live lock.
    """
    with _THREAD_LOCK:
        if is_reset_in_progress(session):
            return {
                "status": "refused",
                "reason": "reset_already_in_progress",
                "fresh_brain": False,
            }

        config = ConfigManager(session).get_current()
        pre_reset_epoch_id = f"reset-pending-{datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')}"
        _acquire_reset_lock(session, operator, pre_reset_epoch_id)
        session.commit()

        deleted: dict[str, Any] = {}
        warnings: list[dict[str, str]] = []
        try:
            deleted, warnings = _delete_all_app_data(session)
            session.commit()
            reseeded = _reseed_bootstrap_rows(session)
            epoch = record_reset_epoch(session, operator, deleted=deleted)
            _clear_reset_lock_rows(session)

            session.add(
                SettingsActionAudit(
                    action="nuke_everything",
                    actor=operator,
                    broker_mode="paper",
                    paper_broker=True,
                    live_trading_locked=True,
                    live_orders_enabled=False,
                    details_json={
                        "deleted": deleted,
                        "at": datetime.utcnow().isoformat() + "Z",
                        **epoch,
                    },
                )
            )
            session.flush()
            caches_cleared = clear_runtime_caches()
            post_counts = post_nuke_table_counts(session)
            env = env_pause_status()
            apl = dict((config.get("autonomous_paper_learning") or {}))
            desired_learning = bool(apl.get("mode_enabled"))
            desired_scheduler = bool(apl.get("scheduler_enabled"))
            lock = live_lock_tripwire_status(config)

            resume: dict[str, Any] = {"skipped": True, "reason": "env_pause_active"}
            if not env.get("any_env_pause"):
                from app.services.paper_learning_start_service import start_fresh_paper_learning

                resume = start_fresh_paper_learning(session, operator=f"nuke:{operator}")
                desired_learning = bool(
                    (ConfigManager(session).get_current().get("autonomous_paper_learning") or {}).get(
                        "mode_enabled"
                    )
                )
                desired_scheduler = bool(
                    (ConfigManager(session).get_current().get("autonomous_paper_learning") or {}).get(
                        "scheduler_enabled"
                    )
                )

            if env.get("any_env_pause"):
                headline = (
                    "Fresh brain. No memories yet. Env pause active — execution blocked until "
                    "Railway env vars cleared."
                )
            elif resume.get("status") == "ok":
                headline = "Fresh brain. No memories yet. Paper learning and scheduler are ON."
            elif desired_learning:
                headline = "Fresh brain. No memories yet. Paper learning available."
            else:
                headline = "Fresh brain. No memories yet. Use Start Fresh Paper Learning on Mission Control."

            broker_resync: dict[str, Any] = {"status": "skipped", "reason": "alpaca_not_configured"}
            try:
                from app.services.alpaca_adapter import AlpacaAdapter

                adapter = AlpacaAdapter(session)
                if adapter.configured:
                    account_snap = adapter.sync_account_cached(force=True)
                    positions = adapter.sync_positions_cached(force=True)
                    broker_resync = {
                        "status": "ok",
                        "account_synced": bool(account_snap),
                        "positions_synced": len(positions),
                        "paper_broker": True,
                    }
            except Exception as exc:
                broker_resync = {
                    "status": "error",
                    "reason": type(exc).__name__,
                    "message": str(exc)[:200],
                }

            return {
                "status": "ok",
                "fresh_brain": True,
                "message": headline,
                "tables_cleared": list(deleted.keys()),
                "rows_deleted": deleted,
                "tables_preserved": sorted(PRESERVE_TABLES),
                "table_inventory": table_inventory(),
                "reset_epoch": epoch,
                "reset_epoch_id": epoch.get("reset_epoch_id"),
                "nuke_completed_at": epoch.get("nuke_completed_at"),
                "nuke_epoch": epoch,
                "post_nuke_counts": post_counts,
                "reseeded": reseeded,
                "runtime_caches_cleared": caches_cleared,
                "warnings": warnings,
                "env_pause": env,
                "broker_resync_after_reset": broker_resync,
                "desired_learning_enabled": desired_learning,
                "desired_scheduler_enabled": desired_scheduler,
                "config_pause_flags_changed": False,
                "ticker_may_create_post_nuke_memories": desired_learning and not env.get("any_env_pause"),
                "start_fresh_resume": resume,
                "live_lock": lock,
                "live_lock_status": lock.get("live_lock_status"),
                "live_trading_enabled": lock.get("live_trading_enabled"),
            }
        except Exception as exc:
            _clear_reset_lock_rows(session)
            session.rollback()
            return {
                "status": "error",
                "reason": type(exc).__name__,
                "message": str(exc)[:500],
                "fresh_brain": False,
                "warnings": warnings,
            }


def reset_epoch_export(session: Session) -> dict[str, Any]:
    from app.services.nuke_epoch_service import get_latest_reset_epoch, nuke_status_export

    epoch = get_latest_reset_epoch(session)
    return {
        "status": "ok",
        "reset_epoch": epoch,
        "nuke_status": nuke_status_export(session),
        "post_nuke_table_counts": post_nuke_table_counts(session),
    }
