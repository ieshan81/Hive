"""Targeted push-pull paper research — HYPE/RENDER default, paper-only."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import SettingsActionAudit
from app.services.config_manager import ConfigManager
from app.services.research_backtest_engine import ResearchBacktestEngine
from app.services.research_memory_service import ResearchMemoryService

DEFAULT_SYMBOLS = ["HYPE/USD", "RENDER/USD"]
_LATEST: dict[str, Any] = {}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def experiment_status(session: Session) -> dict[str, Any]:
    latest = experiment_latest(session)
    return {
        "status": "ok",
        "generated_at_utc": _now(),
        "has_latest": bool(latest.get("per_symbol_results")),
        "latest_at": latest.get("generated_at_utc"),
        "default_symbols": DEFAULT_SYMBOLS,
        "paper_only": True,
        "live_trading": False,
    }


def experiment_latest(session: Session) -> dict[str, Any]:
    if _LATEST:
        return _LATEST
    row = session.exec(
        select(SettingsActionAudit)
        .where(SettingsActionAudit.action == "targeted_experiment_latest")
        .order_by(SettingsActionAudit.created_at.desc())
    ).first()
    if row and row.details_json:
        return row.details_json
    return {"status": "not_run_yet", "message": "POST /api/research/targeted-experiment/run"}


def run_targeted_experiment(
    session: Session,
    body: Optional[dict] = None,
    *,
    operator: str = "operator",
) -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    body = body or {}
    symbols = body.get("symbols") or DEFAULT_SYMBOLS
    timeframe = body.get("timeframe", "1Min")
    lookback_days = int(body.get("lookback_days", 30))

    bt = ResearchBacktestEngine(session, cfg)
    mem = ResearchMemoryService(session, cfg)
    per_symbol: list[dict] = []

    for sym in symbols:
        out = bt.run(
            "crypto_push_pull_baseline",
            [sym],
            lookback_days=lookback_days,
            timeframe=timeframe,
        )
        metrics = out.get("metrics") or {}
        per_symbol.append(
            {
                "symbol": sym,
                "timeframe": timeframe,
                "run_id": out.get("run_id"),
                "status": out.get("status"),
                "num_trades": metrics.get("num_trades"),
                "win_rate": metrics.get("win_rate"),
                "expectancy": metrics.get("expectancy"),
                "profit_factor": metrics.get("profit_factor"),
                "max_drawdown": metrics.get("max_drawdown"),
            }
        )
        if out.get("run_id"):
            mem.from_backtest_run(out["run_id"])

    best = max(per_symbol, key=lambda x: float(x.get("expectancy") or -999), default=None)
    worst = min(per_symbol, key=lambda x: float(x.get("expectancy") or 999), default=None)
    total_trades = sum(int(x.get("num_trades") or 0) for x in per_symbol)

    summary = (
        f"Targeted experiment on {', '.join(symbols)} {timeframe}: {total_trades} trades. "
        f"Best {best.get('symbol') if best else 'n/a'}. Do not promote without walk-forward."
    )
    mem.create_typed(
        "strategy_discovery_verdict",
        title="HYPE/RENDER targeted experiment",
        summary=summary[:500],
        strategy_id="crypto_push_pull_baseline",
        evidence={"per_symbol": per_symbol, "symbols": symbols},
        action_status="candidate",
        pattern_key=f"targeted_exp|{','.join(symbols)}|{timeframe}",
        aggregate=True,
    )

    payload = {
        "status": "ok",
        "generated_at_utc": _now(),
        "operator": operator,
        "symbols": symbols,
        "timeframe": timeframe,
        "per_symbol_results": per_symbol,
        "best_symbol": best,
        "worst_symbol": worst,
        "total_trades": total_trades,
        "do_not_promote_yet": True,
        "paper_only": True,
    }
    session.add(
        SettingsActionAudit(
            action="targeted_experiment_latest",
            actor=operator,
            details_json=payload,
        )
    )
    _LATEST.clear()
    _LATEST.update(payload)
    session.commit()
    return payload
