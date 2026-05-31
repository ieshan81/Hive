"""Cron-driven paper learning scheduler — tick endpoint only, no in-process loop."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import ExecutionLog, SettingsActionAudit
from app.services.autonomous_paper_learning_service import AutonomousPaperLearningService
from app.services.config_manager import ConfigManager, _deep_merge
from app.services.engine_config import cfg_get
from app.services.paper_autopilot_caps import (
    LIVE_OR_FILLED_STATUSES,
    cap_status,
    replaces_fixed_daily_entry_cap,
    resolve_cap,
)


class AutonomousPaperScheduler:
    SCHEDULER_STATE_KEY = "autonomous_scheduler"

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._state = self._load_state()

    def _load_state(self) -> dict:
        rows = list(
            self.session.exec(
                select(SettingsActionAudit).where(SettingsActionAudit.action == self.SCHEDULER_STATE_KEY)
            ).all()
        )
        row = max(rows, key=lambda r: r.created_at or datetime.min, default=None) if rows else None
        if row and row.details_json:
            return dict(row.details_json)
        return {
            "scheduler_enabled": False,
            "paused": False,
            "paused_reason": None,
            "ticks_today": 0,
            "last_tick_at": None,
            "next_planned_at_utc": None,
            "broker_error_streak": 0,
            "rejection_streak": 0,
            "day_key": datetime.utcnow().strftime("%Y-%m-%d"),
        }

    def _persist_state(self, operator: str = "scheduler") -> None:
        self.session.add(
            SettingsActionAudit(
                action=self.SCHEDULER_STATE_KEY,
                actor=operator,
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json=self._state,
            )
        )

    def _reset_daily_if_needed(self) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._state.get("day_key") != today:
            self._state["day_key"] = today
            self._state["ticks_today"] = 0

    def _rejected_count(self) -> int:
        return int(
            self.session.exec(
                select(func.count())
                .select_from(ExecutionLog)
                .where(ExecutionLog.status == "paper_order_rejected")
            ).one()
            or 0
        )

    def _live_or_filled_count(self) -> int:
        return int(
            self.session.exec(
                select(func.count())
                .select_from(ExecutionLog)
                .where(ExecutionLog.status.in_(list(LIVE_OR_FILLED_STATUSES)))
            ).one()
            or 0
        )

    def _journal_tick(self, operator: str, supervised: bool, tick_result: dict) -> None:
        """Append a compact per-tick journal row. Best-effort; never raises."""
        try:
            from app.services.paper_autopilot_journal import record_tick

            record_tick(self.session, operator=operator, supervised=supervised, tick_result=tick_result)
        except Exception:
            pass

    def _maybe_rotate_daily(self, operator: str) -> None:
        """Optional operator-enabled daily bundle rotation (retains newest N days)."""
        apl_cfg = dict(self.config.get("autonomous_paper_learning") or {})
        if not apl_cfg.get("daily_export_enabled"):
            return
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._state.get("last_daily_export_day") == today:
            return
        try:
            from app.services.paper_autopilot_journal import rotate_daily_bundle

            keep = int(apl_cfg.get("daily_export_retention", 14) or 14)
            rotate_daily_bundle(self.session, self.config, keep=keep)
            self._state["last_daily_export_day"] = today
            self._persist_state(operator)
        except Exception:
            pass

    def _effective_interval(self) -> tuple[int, int, Optional[str]]:
        """Configured interval plus an effective interval that backs off (widens) when the
        broker is unhealthy, so the scheduler *paces* itself rather than hard-stopping.
        Pure read of config/state — the external cron drives the real cadence."""
        configured = max(60, int(self.cfg.get("scheduler_interval_seconds", 600)))
        err = int(self._state.get("broker_error_streak", 0))
        rej = int(self._state.get("rejection_streak", 0))
        worst = max(err, rej)
        effective = configured
        backoff_reason: Optional[str] = None
        if worst > 0:
            effective = min(configured * (1 + worst), configured * 8)
            backoff_reason = f"broker_error_streak={err}" if err >= rej else f"rejection_streak={rej}"
        return configured, int(effective), backoff_reason

    def _adaptive_budget_summary(self) -> dict[str, Any]:
        """Compact echo of the adaptive budget + protections config for status/diagnostics —
        shows the fixed daily entry cap has been replaced by risk-based gating."""
        apl = self.config.get("autonomous_paper_learning") or {}
        ob = apl.get("opportunity_budget") or {}
        pr = apl.get("protections") or {}
        return {
            "enabled": bool(ob.get("enabled", True)),
            "replaces_fixed_daily_entry_cap": replaces_fixed_daily_entry_cap(self.config),
            "max_daily_risk_pct": ob.get("max_daily_risk_pct", 4.0),
            "min_edge_after_cost_bps": ob.get("min_edge_after_cost_bps", 15.0),
            "min_signal_score": ob.get("min_signal_score", 0.50),
            "circuit_breaker_max_orders_per_day": ob.get("absolute_max_orders_per_day", 200),
            "protections_enabled": bool(pr.get("enabled", True)),
            "protections": [
                "max_drawdown",
                "stoploss_guard",
                "low_profit_symbol",
                "cooldown_after_exit",
                "churn_guard",
            ],
        }

    def status(self) -> dict[str, Any]:
        self._reset_daily_if_needed()
        use_allocator = bool(self.cfg.get("use_capital_allocator", True))
        configured_interval, effective_interval, backoff_reason = self._effective_interval()
        interval = effective_interval
        last = self._state.get("last_tick_at")
        next_at = None
        if last and self._state.get("scheduler_enabled") and not self._state.get("paused"):
            try:
                last_dt = datetime.fromisoformat(str(last).replace("Z", ""))
                next_at = (last_dt + timedelta(seconds=interval)).isoformat() + "Z"
            except ValueError:
                next_at = None
        abs_tick_cap = resolve_cap(self.config, "absolute_max_scheduler_ticks_per_day")
        ticks_today = int(self._state.get("ticks_today", 0))
        try:
            caps = cap_status(self.session, self.config)
        except Exception:
            caps = {}
        return {
            "scheduler_enabled": bool(self.cfg.get("scheduler_enabled")),
            "paused": bool(self._state.get("paused")),
            "paused_reason": self._state.get("paused_reason"),
            "interval_seconds": configured_interval,
            "configured_interval_seconds": configured_interval,
            "effective_interval_seconds": effective_interval,
            "backoff_reason": backoff_reason,
            "ticks_today": ticks_today,
            "ticks_today_telemetry_only": True,
            "max_ticks_per_day": 0 if use_allocator else int(self.cfg.get("max_scheduler_ticks_per_day", 0) or 0),
            "absolute_max_scheduler_ticks_per_day": abs_tick_cap,
            "ticks_today_remaining": max(0, abs_tick_cap - ticks_today),
            "last_tick_at": last,
            "next_planned_at_utc": next_at,
            "broker_error_streak": int(self._state.get("broker_error_streak", 0)),
            "rejection_streak": int(self._state.get("rejection_streak", 0)),
            "auto_pause_after_consecutive_broker_errors": resolve_cap(
                self.config, "auto_pause_after_consecutive_broker_errors"
            ),
            "auto_pause_after_consecutive_rejections": resolve_cap(
                self.config, "auto_pause_after_consecutive_rejections"
            ),
            "use_capital_allocator": use_allocator,
            "live_locked": True,
            "adaptive_opportunity_budget": self._adaptive_budget_summary(),
            **caps,
        }

    def enable(self, operator: str = "operator") -> dict[str, Any]:
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "autonomous_paper_learning": {
                    **(cur.get("autonomous_paper_learning") or {}),
                    "scheduler_enabled": True,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "scheduler_enable")
        self.config = cfg_mgr.get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._state["scheduler_enabled"] = True
        self._state["paused"] = False
        self._state["paused_reason"] = None
        self._persist_state(operator)
        return {"status": "ok", **self.status()}

    def pause(self, operator: str = "operator") -> dict[str, Any]:
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "autonomous_paper_learning": {
                    **(cur.get("autonomous_paper_learning") or {}),
                    "scheduler_enabled": False,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "scheduler_pause")
        self.config = cfg_mgr.get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._state["scheduler_enabled"] = False
        self._state["paused"] = True
        self._state["paused_reason"] = "operator_pause"
        self._persist_state(operator)
        return {"status": "ok", **self.status()}

    def tick(self, *, operator: str = "cron", supervised: bool = False) -> dict[str, Any]:
        from app.services.nuke_reset_service import is_reset_in_progress

        if is_reset_in_progress(self.session):
            return {"status": "skipped", "reason": "reset_in_progress"}
        self._reset_daily_if_needed()
        apl_cfg = dict(self.config.get("autonomous_paper_learning") or {})
        # Supervised (operator-driven) ticks may run without the always-on cron
        # being enabled, but every other gate (pause, mode, caps, cage) still applies.
        if not supervised and not apl_cfg.get("scheduler_enabled"):
            return {"status": "noop", "reason": "scheduler_disabled"}
        if self._state.get("paused"):
            return {"status": "noop", "reason": "scheduler_paused", "paused_reason": self._state.get("paused_reason")}
        if not apl_cfg.get("mode_enabled"):
            return {"status": "noop", "reason": "autonomous_paper_learning_off"}

        # ---- Pacing (cron only; supervised ticks/bursts bypass) ----
        # Min-interval + backoff prevents API/broker spam. This PACES (skips early) — it
        # never hard-stops for the day, so the scheduler keeps scanning on cadence.
        configured_interval, effective_interval, backoff_reason = self._effective_interval()
        if operator == "cron":
            last = self._state.get("last_tick_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(str(last).replace("Z", ""))
                    elapsed = (datetime.utcnow() - last_dt).total_seconds()
                    if elapsed < effective_interval * 0.8:
                        return {
                            "status": "skipped",
                            "reason": "tick_paced",
                            "elapsed_seconds": round(elapsed, 1),
                            "configured_interval_seconds": configured_interval,
                            "effective_interval_seconds": effective_interval,
                            "backoff_reason": backoff_reason,
                        }
                except ValueError:
                    pass

        # ---- Tick COUNT is telemetry only — the daily tick cap no longer hard-pauses. ----
        # Pacing/backoff above prevents spam; the scheduler keeps scanning all day. Order
        # safety lives in the execution cage + adaptive opportunity budget (which gate every
        # order), not in a tick counter. ticks_today is surfaced in status() for diagnostics.

        use_allocator = bool(apl_cfg.get("use_capital_allocator", True))
        max_ticks = int(apl_cfg.get("max_scheduler_ticks_per_day", 0) or 0)
        if use_allocator:
            max_ticks = 0  # opportunity-based when allocator is active
        if max_ticks > 0 and int(self._state.get("ticks_today", 0)) >= max_ticks:
            self._state["paused"] = True
            self._state["paused_reason"] = "daily_tick_cap"
            self._persist_state(operator)
            return {"status": "stopped", "reason": "daily_tick_cap_reached"}

        max_trades = 0 if use_allocator else int(apl_cfg.get("max_paper_trades_per_day", 0) or 0)
        if max_trades > 0:
            start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            filled_today = len(
                list(
                    self.session.exec(
                        select(ExecutionLog).where(
                            ExecutionLog.created_at >= start,
                            ExecutionLog.status == "paper_order_filled",
                        )
                    ).all()
                )
            )
            if filled_today >= max_trades:
                self._state["paused"] = True
                self._state["paused_reason"] = "daily_trade_cap"
                self._persist_state(operator)
                return {"status": "stopped", "reason": "daily_paper_trade_cap"}

        svc = AutonomousPaperLearningService(self.session, self.config)
        rejected_before = self._rejected_count()
        result = svc.run_one_cycle(operator=operator)
        rejected_after = self._rejected_count()
        rejected_this_tick = max(0, rejected_after - rejected_before)
        self._state["ticks_today"] = int(self._state.get("ticks_today", 0)) + 1
        self._state["last_tick_at"] = datetime.utcnow().isoformat() + "Z"

        # ---- Consecutive broker-error auto-pause ----
        if result.get("status") in ("error", "blocked") and "broker" in str(result.get("reason", "")).lower():
            self._state["broker_error_streak"] = int(self._state.get("broker_error_streak", 0)) + 1
            if self._state["broker_error_streak"] >= resolve_cap(
                self.config, "auto_pause_after_consecutive_broker_errors"
            ):
                self._state["paused"] = True
                self._state["paused_reason"] = "consecutive_broker_errors"
        else:
            self._state["broker_error_streak"] = 0

        # ---- Consecutive rejection auto-pause ----
        if rejected_this_tick > 0:
            self._state["rejection_streak"] = int(self._state.get("rejection_streak", 0)) + 1
            if self._state["rejection_streak"] >= resolve_cap(
                self.config, "auto_pause_after_consecutive_rejections"
            ):
                self._state["paused"] = True
                self._state["paused_reason"] = "consecutive_rejections"
        else:
            self._state["rejection_streak"] = 0

        # Auto-consolidate raw memories into visible learned memories (throttled, DB-only).
        # Previously consolidation only ran from a manual endpoint, so the Hive Mind stayed
        # at thousands-of-raw / zero-learned ("fresh brain"). Never trades; never crashes the tick.
        self._maybe_consolidate_memory(operator)

        self._persist_state(operator)
        self.session.flush()
        tick_result = {
            "status": "ok",
            "tick": self.status(),
            "cycle_result": result,
            "rejected_this_tick": rejected_this_tick,
        }
        self._journal_tick(operator, supervised, tick_result)
        self._maybe_rotate_daily(operator)
        return tick_result

    def _maybe_consolidate_memory(self, operator: str) -> None:
        """Throttled, fail-safe memory consolidation so raw lessons become visible learned
        memories. Read/DB-only — never places orders, never enables live, never crashes the tick."""
        apl = self.config.get("autonomous_paper_learning") or {}
        mc = apl.get("memory_consolidation") or {}
        if not bool(mc.get("auto_enabled", True)):
            return
        interval_min = float(mc.get("auto_interval_minutes", 30) or 30)
        last = self._state.get("last_memory_consolidation_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(str(last).replace("Z", ""))
                if (datetime.utcnow() - last_dt).total_seconds() < interval_min * 60:
                    return
            except ValueError:
                pass
        try:
            from app.services.memory_consolidation_service import MemoryConsolidationService

            MemoryConsolidationService(self.session, self.config).run()
            self._state["last_memory_consolidation_at"] = datetime.utcnow().isoformat() + "Z"
        except Exception:
            pass  # memory work must never break the trading tick

    # Block-reason codes that should halt a supervised burst so the operator can
    # review before any further ticks fire.
    _BURST_STOP_CODES = (
        "DUPLICATE_SYMBOL_POSITION",
        "DUPLICATE_RECENT_ORDER",
        "DUPLICATE_OPEN_ORDER",
        "OPEN_POSITION_MISSING_EXIT_PLAN",
        "ABSOLUTE_MAX_OPEN_POSITIONS",
        "ABSOLUTE_HOURLY_ENTRY_CAP",
        "ABSOLUTE_DAILY_ENTRY_CAP",
        "ABSOLUTE_CYCLE_CAP",
        "KILL_SWITCH_ACTIVE",
        "RECONCILIATION_DRIFT",
    )

    def _burst_environment_block(self) -> Optional[str]:
        """Pre-tick hard-stop check: kill switch active or reconciliation drift halt."""
        try:
            from app.services.alpaca_adapter import AlpacaAdapter
            from app.services.kill_switch_service import KillSwitchService

            acct = AlpacaAdapter(self.session).sync_account_cached()
            ok, _switches = KillSwitchService(self.session, self.config).evaluate(
                equity=getattr(acct, "equity", 0) or 0,
                daily_pl_pct=getattr(acct, "daily_pl_pct", 0) or 0,
                drawdown_pct=getattr(acct, "drawdown_pct", 0) or 0,
            )
            if not ok:
                return "kill_switch_active"
        except Exception:
            pass
        try:
            from app.services.broker_reconciliation_service import BrokerReconciliationService

            max_drift = float(cfg_get(self.config, "risk.reconciliation_drift_halt_bps", 5.0))
            recon = BrokerReconciliationService(self.session, self.config).exit_only_reconciliation_status()
            drift = float(recon.get("max_drift_bps") or recon.get("drift_bps") or 0)
            if drift > max_drift:
                return f"reconciliation_drift_{drift:.2f}bps"
        except Exception:
            pass
        return None

    def _scan_block_codes(self, cycle_result: dict) -> Optional[str]:
        try:
            ts = cycle_result.get("tick_summary") or {}
            blob = " ".join(
                [
                    str(cycle_result.get("reason") or ""),
                    str(ts.get("reason_breakdown") or ""),
                    str(ts.get("no_trade_reason_breakdown") or ""),
                    str(ts.get("rejected_candidates") or ""),
                ]
            ).upper()
        except Exception:
            return None
        for code in self._BURST_STOP_CODES:
            if code in blob:
                return code
        return None

    def supervised_burst(self, *, max_ticks: int = 3, operator: str = "operator") -> dict[str, Any]:
        """Run up to ``max_ticks`` operator-supervised ticks, stopping early on any
        material event so the operator can review.

        Auto-stops on: order placed/filled, broker rejection, kill switch,
        reconciliation drift, open-position cap, daily/hourly entry cap,
        duplicate-buy block, missing-exit-plan block, or the scheduler pausing.
        Every tick runs the full ExecutionCage; nothing here bypasses a gate.
        """
        self._reset_daily_if_needed()
        n = max(1, min(int(max_ticks or 1), 10))
        results: list[dict[str, Any]] = []
        stop_reason: Optional[str] = None
        orders_before = self._live_or_filled_count()

        if self._state.get("paused"):
            return {
                "status": "noop",
                "reason": "scheduler_paused",
                "paused_reason": self._state.get("paused_reason"),
                "ticks_run": 0,
                "scheduler": self.status(),
                "live_locked": True,
            }

        for i in range(n):
            env = self._burst_environment_block()
            if env:
                stop_reason = env
                break

            res = self.tick(operator=operator, supervised=True)
            results.append({"tick_index": i + 1, **res})

            status = res.get("status")
            if status in ("noop", "skipped", "stopped"):
                stop_reason = f"{status}:{res.get('reason')}"
                break

            cycle_result = res.get("cycle_result") or {}
            orders_after = self._live_or_filled_count()
            if int(cycle_result.get("orders_created", 0) or 0) > 0 or orders_after > orders_before:
                stop_reason = "order_placed"
                break
            orders_before = orders_after

            if int(res.get("rejected_this_tick", 0) or 0) > 0:
                stop_reason = "order_rejected"
                break

            code = self._scan_block_codes(cycle_result)
            if code:
                stop_reason = f"blocked:{code}"
                break

            if self._state.get("paused"):
                stop_reason = f"paused:{self._state.get('paused_reason')}"
                break

            try:
                caps = cap_status(self.session, self.config)
                if caps.get("entry_cap_hit"):
                    stop_reason = "entry_cap_hit:" + ",".join(caps.get("entry_cap_hit_reasons") or [])
                    break
            except Exception:
                pass

        self._persist_state(operator)
        self.session.flush()
        return {
            "status": "ok",
            "requested_ticks": n,
            "ticks_run": len(results),
            "stopped_reason": stop_reason,
            "results": results,
            "scheduler": self.status(),
            "live_locked": True,
        }

    def stop_after_tick(self, operator: str = "operator") -> dict[str, Any]:
        """Pause the always-on scheduler without flipping config.

        The in-flight cron tick (if any) finishes; the next one no-ops. Leaves
        ``autonomous_paper_learning.scheduler_enabled`` untouched so Enable resumes.
        """
        self._state["paused"] = True
        self._state["paused_reason"] = "operator_stop_after_tick"
        self._persist_state(operator)
        self.session.flush()
        return {"status": "ok", **self.status()}
