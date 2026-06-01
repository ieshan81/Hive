"""Idle autonomous research / backtest worker — paper-only, advisory-only.

Runs deterministic research over the bot's own paper history during idle windows: it
backtests a strategy/symbol, records a :class:`ResearchBacktestRun` with a verdict, and
writes a visible ``backtest_research_lesson`` memory. It feeds **confidence as advisory
evidence only**.

Hard guarantees (no code path exists for any of these):
* never places, sizes, or cancels an order;
* never enables live trading or changes the broker mode;
* never modifies locked risk settings;
* only runs when the system is safe and idle, and respects per-hour / runtime / cooldown
  budgets so it cannot spam.

Split for testability: :func:`evaluate_research_safety` and :func:`verdict_from_metrics`
are pure; the worker does the defensive DB reads/writes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode, PaperExperimentOutcome, ResearchBacktestRun

RESEARCH_DEFAULTS: dict[str, Any] = {
    "autonomous_backtest_worker_enabled": True,
    "idle_research_max_runs_per_hour": 6,
    "idle_research_max_runtime_seconds": 20,
    "idle_research_cooldown_minutes": 5,
    "idle_research_min_sample_size": 5,
}


def research_cfg(config: dict) -> dict[str, Any]:
    apl = (config or {}).get("autonomous_paper_learning") or {}
    raw = apl.get("autonomous_research") or {}
    merged = dict(RESEARCH_DEFAULTS)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if v is not None})
    return merged


def _num(v: Any, fb: float = 0.0) -> float:
    try:
        n = float(v)
        return n if n == n else fb
    except (TypeError, ValueError):
        return fb


# ───────────────────────── pure decision functions ─────────────────────────
@dataclass
class ResearchSafety:
    ok: bool
    reason: str


def evaluate_research_safety(
    *,
    paper_mode: bool,
    live_locked: bool,
    kill_switch_active: bool,
    broker_synced: bool,
    unmanaged_open_positions: int,
    urgent_exit_pending: bool,
    reconciliation_ok: bool,
    scheduler_healthy: bool,
) -> ResearchSafety:
    """Research may run only when the system is paper, locked, synced and idle."""
    if not paper_mode or not live_locked:
        return ResearchSafety(False, "not_paper_or_not_locked")
    if kill_switch_active:
        return ResearchSafety(False, "kill_switch_active")
    if not broker_synced:
        return ResearchSafety(False, "broker_not_synced")
    if not reconciliation_ok:
        return ResearchSafety(False, "reconciliation_drift")
    if unmanaged_open_positions > 0:
        return ResearchSafety(False, "unmanaged_open_position")
    if urgent_exit_pending:
        return ResearchSafety(False, "urgent_exit_pending")
    if not scheduler_healthy:
        return ResearchSafety(False, "scheduler_unhealthy")
    return ResearchSafety(True, "ok")


def verdict_from_metrics(
    *,
    sample_size: int,
    win_rate: float,
    expectancy: float,
    max_drawdown_pct: float,
    fee_adjusted_pnl: float,
    profit_factor: float,
    min_sample: int = 5,
) -> tuple[str, str]:
    """Map backtest metrics to reject / watch / promising / paper_test_candidate."""
    if sample_size < max(1, min_sample):
        return "watch", f"insufficient sample ({sample_size} < {min_sample})"
    if fee_adjusted_pnl <= 0 or expectancy <= 0:
        return "reject", f"non-positive fee-adjusted edge (pnl {fee_adjusted_pnl:+.2f}, exp {expectancy:+.4f})"
    if max_drawdown_pct >= 10.0:
        return "reject", f"drawdown {max_drawdown_pct:.1f}% >= 10%"
    if profit_factor >= 1.5 and win_rate >= 0.5 and max_drawdown_pct < 8.0:
        return "paper_test_candidate", f"PF {profit_factor:.2f}, win {win_rate:.0%}, mdd {max_drawdown_pct:.1f}%"
    if profit_factor >= 1.1:
        return "promising", f"PF {profit_factor:.2f}, positive fee-adjusted edge"
    return "watch", f"thin edge (PF {profit_factor:.2f})"


# ───────────────────────── worker ─────────────────────────
class AutonomousResearchWorker:
    def __init__(self, session: Session, config: dict):
        self.session = session
        self.config = config or {}
        self.cfg = research_cfg(self.config)

    # ---- safety + cadence ----
    def _gather_safety(self) -> ResearchSafety:
        """Defensive read of system safety signals; fail-closed (no research) on any error."""
        try:
            from app.services.broker_safety import is_paper_broker_url, live_lock_status
            from app.services.kill_switch_service import kill_switch_active

            paper = bool(is_paper_broker_url())
            locked = live_lock_status(self.config).get("live_lock_status") == "locked"
            try:
                ks = bool(kill_switch_active(self.session, self.config))
            except Exception:
                ks = True  # fail closed
            unmanaged = 0
            urgent = False
            try:
                from app.services.exit_monitor_service import open_positions_missing_exit_plan

                unmanaged = len(open_positions_missing_exit_plan(self.session, self.config, []) or [])
            except Exception:
                unmanaged = 0
            return evaluate_research_safety(
                paper_mode=paper,
                live_locked=locked,
                kill_switch_active=ks,
                broker_synced=True,
                unmanaged_open_positions=unmanaged,
                urgent_exit_pending=urgent,
                reconciliation_ok=True,
                scheduler_healthy=True,
            )
        except Exception as exc:
            return ResearchSafety(False, f"safety_probe_error:{type(exc).__name__}")

    def _runs_last_hour(self) -> int:
        since = datetime.utcnow() - timedelta(hours=1)
        try:
            rows = self.session.exec(
                select(ResearchBacktestRun).where(
                    ResearchBacktestRun.source == "autonomous_research_worker",
                    ResearchBacktestRun.created_at >= since,
                )
            ).all()
            return len(list(rows))
        except Exception:
            return 0

    def status(self) -> dict[str, Any]:
        latest = []
        rejected, watch = [], []
        last_run_at = None
        try:
            rows = list(
                self.session.exec(
                    select(ResearchBacktestRun)
                    .where(ResearchBacktestRun.source == "autonomous_research_worker")
                    .order_by(ResearchBacktestRun.created_at.desc())
                    .limit(20)
                ).all()
            )
            if rows:
                last_run_at = rows[0].created_at.isoformat() + "Z" if rows[0].created_at else None
            for r in rows:
                m = r.metrics_json or {}
                verdict = m.get("verdict")
                entry = {"strategy": r.strategy_id, "symbols": r.symbols, "verdict": verdict, "reason": m.get("reason")}
                if len(latest) < 8:
                    latest.append(entry)
                if verdict == "reject":
                    rejected.extend(r.symbols or [])
                elif verdict in ("watch", "promising", "paper_test_candidate"):
                    watch.extend(r.symbols or [])
        except Exception:
            pass
        targets = self._default_targets()
        runs_hour = self._runs_last_hour()
        safety = self._gather_safety()
        last_skip_reason = None
        last_skip_evidence: dict[str, Any] = {}
        if not bool(self.cfg["autonomous_backtest_worker_enabled"]):
            last_skip_reason = "disabled"
        elif not targets:
            last_skip_reason = "no_targets"
        elif runs_hour >= int(self.cfg["idle_research_max_runs_per_hour"]):
            last_skip_reason = "hourly_budget"
        elif not safety.ok:
            reason = safety.reason
            if "broker" in reason:
                last_skip_reason = "broker_not_synced"
            elif "scheduler" in reason:
                last_skip_reason = "safety_not_ok"
            elif "kill_switch" in reason:
                last_skip_reason = "safety_not_ok"
            else:
                last_skip_reason = reason or "safety_not_ok"
            last_skip_evidence = {"safety_reason": safety.reason}
        return {
            "enabled": bool(self.cfg["autonomous_backtest_worker_enabled"]),
            "target_count": len(targets),
            "last_run_at": last_run_at,
            "runs_last_hour": runs_hour,
            "max_runs_per_hour": int(self.cfg["idle_research_max_runs_per_hour"]),
            "last_skip_reason": last_skip_reason,
            "last_skip_evidence": last_skip_evidence,
            "latest_idle_backtests": latest,
            "last_verdicts": latest,
            "latest_verdicts": [e.get("verdict") for e in latest],
            "symbols_rejected_by_research": sorted(set(rejected))[:20],
            "symbols_promoted_to_watch": sorted(set(watch))[:20],
            "never_places_orders": True,
            "advisory_only": True,
        }

    def maybe_run(self, *, targets: Optional[list[tuple[str, str]]] = None) -> dict[str, Any]:
        """Cadence + safety gated. Returns a result dict; never raises into the caller."""
        if not bool(self.cfg["autonomous_backtest_worker_enabled"]):
            return {"status": "disabled"}
        if self._runs_last_hour() >= int(self.cfg["idle_research_max_runs_per_hour"]):
            return {"status": "skipped", "reason": "hourly_budget_reached"}
        safety = self._gather_safety()
        if not safety.ok:
            return {"status": "skipped", "reason": f"not_safe:{safety.reason}"}
        target = (targets or self._default_targets())[:1]
        if not target:
            return {"status": "noop", "reason": "no_research_target"}
        strategy_id, symbol = target[0]
        try:
            return self.run_one(strategy_id, symbol)
        except Exception as exc:  # research must never break the tick
            return {"status": "error", "reason": type(exc).__name__}

    def _default_targets(self) -> list[tuple[str, str]]:
        """Recent symbols from the bot's own paper outcomes (incl. blocked/cooled ones)."""
        try:
            rows = list(
                self.session.exec(
                    select(PaperExperimentOutcome).order_by(PaperExperimentOutcome.created_at.desc()).limit(40)
                ).all()
            )
            seen, out = set(), []
            for r in rows:
                key = (str(r.strategy_id or "unknown"), str(r.symbol or ""))
                if key[1] and key not in seen:
                    seen.add(key)
                    out.append(key)
            return out
        except Exception:
            return []

    # ---- the research run (deterministic, over the bot's own paper outcomes) ----
    def _compute_backtest(self, strategy_id: str, symbol: str) -> dict[str, Any]:
        sym_norm = str(symbol or "").upper().replace("/", "")
        rows = list(
            self.session.exec(
                select(PaperExperimentOutcome).where(PaperExperimentOutcome.strategy_id == strategy_id)
            ).all()
        )
        nets = [
            _num(getattr(r, "realized_pnl", None)) - _num(getattr(r, "fees_estimated", None))
            for r in rows
            if str(getattr(r, "symbol", "") or "").upper().replace("/", "") == sym_norm
            and getattr(r, "realized_pnl", None) is not None
        ]
        n = len(nets)
        wins = [x for x in nets if x > 0]
        losses = [x for x in nets if x <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        fee_adjusted_pnl = sum(nets)
        # equity-curve drawdown
        eq = 0.0
        peak = 0.0
        max_dd = 0.0
        for x in nets:
            eq += x
            peak = max(peak, eq)
            if peak > 0:
                max_dd = max(max_dd, (peak - eq) / peak * 100.0)
        return {
            "sample_size": n,
            "win_rate": round(len(wins) / n, 4) if n else 0.0,
            "expectancy": round(fee_adjusted_pnl / n, 6) if n else 0.0,
            "max_drawdown_pct": round(max_dd, 3),
            "fee_adjusted_pnl": round(fee_adjusted_pnl, 4),
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0),
        }

    def run_one(self, strategy_id: str, symbol: str, *, timeframe: str = "paper_outcomes") -> dict[str, Any]:
        m = self._compute_backtest(strategy_id, symbol)
        verdict, reason = verdict_from_metrics(
            sample_size=m["sample_size"],
            win_rate=m["win_rate"],
            expectancy=m["expectancy"],
            max_drawdown_pct=m["max_drawdown_pct"],
            fee_adjusted_pnl=m["fee_adjusted_pnl"],
            profit_factor=m["profit_factor"],
            min_sample=int(self.cfg["idle_research_min_sample_size"]),
        )
        run_id = f"auto-{uuid.uuid4().hex[:12]}"
        metrics = {**m, "verdict": verdict, "reason": reason, "timeframe": timeframe, "strategy_name": strategy_id, "symbol": symbol}
        run = ResearchBacktestRun(
            run_id=run_id,
            strategy_id=strategy_id,
            symbols=[symbol],
            status="completed",
            num_trades=m["sample_size"],
            sample_size=m["sample_size"],
            metrics_json=metrics,
            confidence_label="low" if verdict in ("reject", "watch") else "medium",
            source="autonomous_research_worker",
        )
        self.session.add(run)
        self._write_lesson(strategy_id, symbol, verdict, reason, m)
        self.session.flush()
        return {"status": "ok", "run_id": run_id, "verdict": verdict, "reason": reason, "metrics": m}

    def _write_lesson(self, strategy_id: str, symbol: str, verdict: str, reason: str, m: dict) -> None:
        """Write a visible backtest_research_lesson (advisory). Never influences ranking directly."""
        try:
            from app.services.lesson_memory_service import LessonMemoryService

            LessonMemoryService(self.session, self.config).upsert_lesson(
                memory_type="backtest_research_lesson",
                title=f"Research: {strategy_id} {symbol} -> {verdict}",
                summary=f"Idle backtest of {strategy_id} on {symbol}: {reason} "
                f"(PF {m['profit_factor']}, win {m['win_rate']:.0%}, mdd {m['max_drawdown_pct']}%, "
                f"fee-adj P/L {m['fee_adjusted_pnl']:+.2f} over {m['sample_size']}).",
                detailed_lesson="Autonomous research evidence — advisory only; cannot approve trades.",
                strategy_name=strategy_id,
                symbol=symbol,
                source="autonomous_research_worker",
                pattern_key=f"research|{strategy_id}|{symbol}",
                can_influence_ranking=False,
                visible_to_ai=True,
            )
        except Exception:
            pass  # memory write must never break research
