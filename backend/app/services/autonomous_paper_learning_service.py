"""Autonomous Paper Learning — orchestrates paper-only learning cycles (not live)."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import OrderRecord, PositionSnapshot, SettingsActionAudit
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.broker_safety import is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager, _deep_merge
from app.services.engine_config import cfg_get
from app.services.fast_crypto_training_loop import FastCryptoTrainingLoop
from app.services.fast_training_lease_service import AUTONOMOUS_LEASE_KEY, FastTrainingLeaseService
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.research_lab_service import ResearchLabService
from app.services.session_engine import SessionEngine


class AutonomousPaperLearningService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self.pl = AggressivePaperLearningService(session)
        self.ft = FastCryptoTrainingLoop(session, self.config)
        self.lease = FastTrainingLeaseService(
            session,
            lease_key=AUTONOMOUS_LEASE_KEY,
            use_db_lease=bool(cfg_get(self.config, "fast_training.use_db_lease", True)),
        )

    def _audit(self, action: str, operator: str, details: dict) -> None:
        self.session.add(
            SettingsActionAudit(
                action=action,
                actor=operator,
                broker_mode="paper" if is_paper_broker_url() else "unknown",
                paper_broker=is_paper_broker_url(),
                live_trading_locked=live_lock_status(self.config).get("live_lock_status") == "locked",
                live_orders_enabled=bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
                details_json={**details, **live_lock_tripwire_status(self.config)},
            )
        )

    def _order_count(self) -> int:
        return len(list(self.session.exec(select(OrderRecord)).all()))

    def _autonomous_tick_count(self) -> int:
        n = self.session.exec(
            select(func.count())
            .select_from(SettingsActionAudit)
            .where(SettingsActionAudit.action == "autonomous_run_one_cycle")
        ).one()
        return int(n or 0)

    def _learning_capacity(self) -> dict[str, Any]:
        from app.services.capital_allocator import _unlimited

        allocator_on = bool(self.cfg.get("use_capital_allocator", True))
        max_trades = self.cfg.get("max_paper_trades_per_day", 0)
        max_pos = self.cfg.get("max_open_paper_positions", 0)
        if allocator_on:
            max_trades, max_pos = 0, 0
        return {
            "paper_trade_frequency": "opportunity_based",
            "daily_paper_trade_cap": None if _unlimited(max_trades) else max_trades,
            "max_open_paper_positions": None if _unlimited(max_pos) else max_pos,
            "position_control": "formula_allocator",
            "max_paper_trades_per_day": None if _unlimited(max_trades) else max_trades,
            "max_open_paper_positions_legacy": None if _unlimited(max_pos) else max_pos,
        }

    def _allocator_summary(self) -> dict[str, Any]:
        try:
            from app.services.capital_allocator import CapitalAllocatorService

            return CapitalAllocatorService(self.session, self.config).status_summary()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def status(self) -> dict[str, Any]:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        session_state = SessionEngine().detect()
        recon = BrokerReconciliationService(self.session, self.config)
        ghosts = recon.ghost_position_candidates()
        ft_st = self.ft.status()
        sched = AutonomousPaperScheduler(self.session, self.config).status()
        from app.services.paper_learning_truth import paper_learning_display_status

        display = paper_learning_display_status(self.session, self.config)
        mode_on = bool(display.get("mode_enabled"))
        can_place = bool(display.get("can_place_paper_orders"))
        current_mode = display.get("current_mode") or "watching"
        return {
            "status": "ok",
            "ui_label": "Autonomous Paper Learning",
            "mode_enabled": mode_on,
            "paper_learning_on": mode_on,
            "can_place_paper_orders": can_place,
            "scheduler": sched,
            "safety_banner": display,
            "session": session_state.to_dict(),
            "bot_can_place_paper_orders": can_place,
            "open_paper_positions": len(
                list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
            ),
            "ghost_position_candidates": ghosts,
            "broker_truth_synced": len(ghosts) == 0,
            "blockers": display.get("blockers") or ft_st.get("blockers") or [],
            "current_mode": current_mode,
            "plain_message": display.get("plainMessage") or display.get("plain_message"),
            "learning_capacity": self._learning_capacity(),
            "capital_allocator": self._allocator_summary(),
            "caps": self._learning_capacity(),
            **live_lock_status(self.config),
        }

    def _refuse(self, reason: str, operator: str) -> dict[str, Any]:
        self._audit("autonomous_paper_refused", operator, {"reason": reason})
        return {"status": "refused", "reason": reason, **self.status()}

    def enable(self, operator: str = "operator") -> dict[str, Any]:
        lock = live_lock_status(self.config)
        if lock.get("live_lock_status") != "locked":
            return self._refuse("live_lock_not_locked", operator)
        if not is_paper_broker_url():
            return self._refuse("broker_not_paper", operator)
        if bool(self.config.get("live_trading_enabled", False)):
            return self._refuse("live_trading_flag_set", operator)
        if not bool(cfg_get(self.config, "execution.paper_orders_enabled", False)):
            return self._refuse("paper_orders_disabled", operator)
        if BrokerReconciliationService(self.session, self.config).ghost_position_candidates():
            return self._refuse("ghost_position_candidates_need_review", operator)

        ft_out = self.ft.enable(operator)
        if ft_out.get("status") not in ("ok",):
            return self._refuse(ft_out.get("reason") or ft_out.get("message", "fast_training_enable_failed"), operator)

        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "autonomous_paper_learning": {
                    **(cur.get("autonomous_paper_learning") or {}),
                    "mode_enabled": True,
                },
                "live_trading_enabled": False,
                "execution": {
                    **(cur.get("execution") or {}),
                    "live_orders_enabled": False,
                    "paper_orders_enabled": True,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "autonomous_paper_learning_enable")
        self.config = cfg_mgr.get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._audit("autonomous_paper_enable", operator, {"mode_enabled": True})
        self.session.flush()
        return {"status": "ok", "message": "Autonomous Paper Learning enabled", **self.status()}

    def pause(self, operator: str = "operator") -> dict[str, Any]:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        AutonomousPaperScheduler(self.session, self.config).pause(operator)
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {"autonomous_paper_learning": {**(cur.get("autonomous_paper_learning") or {}), "mode_enabled": False}},
        )
        cfg_mgr._activate(merged, operator, "autonomous_paper_pause")
        self.ft.disable(operator)
        self.config = cfg_mgr.get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._audit("autonomous_paper_pause", operator, {})
        self.session.flush()
        return {"status": "ok", "message": "Autonomous Paper Learning paused", **self.status()}

    def disable_all_paper_trading(self, operator: str = "operator") -> dict[str, Any]:
        from app.services.autonomous_paper_scheduler import AutonomousPaperScheduler

        AutonomousPaperScheduler(self.session, self.config).pause(operator)
        self.ft.disable(operator)
        self.pl.disable(operator)
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = _deep_merge(
            cur,
            {
                "autonomous_paper_learning": {
                    **(cur.get("autonomous_paper_learning") or {}),
                    "mode_enabled": False,
                    "scheduler_enabled": False,
                },
                "fast_training": {
                    **(cur.get("fast_training") or {}),
                    "fast_training_loop_enabled": False,
                    "fast_training_execute_orders": False,
                },
                "execution": {
                    **(cur.get("execution") or {}),
                    "paper_orders_enabled": False,
                    "live_orders_enabled": False,
                },
            },
        )
        cfg_mgr._activate(merged, operator, "disable_all_paper_trading")
        self.config = cfg_mgr.get_current()
        self.cfg = dict(self.config.get("autonomous_paper_learning") or {})
        self._audit("disable_all_paper_trading", operator, {})
        self.session.flush()
        return {"status": "ok", "message": "All paper trading disabled", **self.status()}

    def run_one_cycle(self, *, operator: str = "operator") -> dict[str, Any]:
        from app.services.nuke_reset_service import is_reset_in_progress

        if is_reset_in_progress(self.session):
            return {
                "status": "skipped",
                "reason": "reset_in_progress",
                "orders_created": 0,
            }
        if not bool(self.cfg.get("mode_enabled")):
            return {"status": "blocked", "reason": "autonomous_paper_learning_disabled", "orders_created": 0}

        ok, holder = self.lease.acquire()
        if not ok:
            return {
                "status": "blocked",
                "reason": "lease_held",
                "holder_id": holder,
                "orders_created": 0,
            }

        from app.services.activity_logger import log_activity
        from app.services.push_pull_strategy_seed import ensure_crypto_push_pull_baseline

        ensure_crypto_push_pull_baseline(self.session, self.config)
        log_activity(self.session, "tick_started", "Push-pull tick started", {"operator": operator}, commit=False)

        trade_state_repair: dict[str, Any] = {"status": "skipped"}
        try:
            from app.services.trade_state_repair_service import TradeStateRepairService

            trade_state_repair = TradeStateRepairService(self.session, self.config).repair_stale_open_trades_when_broker_flat(
                dry_run=False
            )
        except Exception as exc:
            trade_state_repair = {"status": "error", "reason": type(exc).__name__, "message": str(exc)[:200]}

        refresh_summary: dict[str, Any] = {"status": "skipped", "reason": "disabled"}
        if bool(cfg_get(self.config, "autonomous_paper_learning.refresh_market_data_before_tick", True)):
            try:
                from app.services.market_data_refresh_service import MarketDataRefreshService
                from app.services.capital_allocator import CapitalAllocatorService

                market_mode = CapitalAllocatorService(self.session, self.config).build_plan().get("current_market_mode")
                refresher = MarketDataRefreshService(self.session, self.config)
                lookback_hours = int(
                    cfg_get(self.config, "autonomous_paper_learning.refresh_lookback_hours", 12) or 12
                )
                runs: list[dict[str, Any]] = []
                runs.append(refresher.refresh_bars(
                    asset_type="crypto",
                    timeframe="1Min",
                    lookback_hours=max(2, min(lookback_hours, 6)),
                    operator=operator,
                ))
                runs.append(refresher.refresh_bars(
                    asset_type="crypto",
                    timeframe="5Min",
                    lookback_hours=lookback_hours,
                    operator=operator,
                ))
                if market_mode == "US_STOCK_OPEN" and bool(
                    cfg_get(self.config, "autonomous_paper_learning.refresh_stocks_during_market_hours", True)
                ):
                    runs.append(refresher.refresh_bars(
                        asset_type="stock",
                        timeframe="1Min",
                        lookback_hours=max(2, min(lookback_hours, 6)),
                        operator=operator,
                    ))
                    runs.append(refresher.refresh_bars(
                        asset_type="stock",
                        timeframe="5Min",
                        lookback_hours=lookback_hours,
                        operator=operator,
                    ))
                refresh_summary = {
                    "status": "ok" if any(r.get("refreshed_count") for r in runs) else "partial",
                    "market_mode": market_mode,
                    "runs": runs,
                    "fresh_count": sum(int(r.get("fresh_count") or 0) for r in runs),
                    "stale_count": sum(int(r.get("stale_count") or 0) for r in runs),
                    "refreshed_count": sum(int(r.get("refreshed_count") or 0) for r in runs),
                }
            except Exception as exc:
                refresh_summary = {
                    "status": "error",
                    "reason": "market_data_refresh_failed",
                    "message": str(exc)[:200],
                }

        scanner_summary: dict[str, Any] = {"status": "skipped"}
        if bool(cfg_get(self.config, "autonomous_paper_learning.run_scanners_each_tick", True)):
            try:
                from app.services import scanner_stack

                scanner_summary = scanner_stack.run_all(self.session)
            except Exception as exc:
                scanner_summary = {"status": "error", "message": str(exc)[:200]}

        backtest_summary: dict[str, Any] = {"status": "skipped"}
        n_ticks = self._autonomous_tick_count()
        every_n = int(cfg_get(self.config, "autonomous_paper_learning.run_backtest_lab_every_n_ticks", 12) or 12)
        if every_n > 0 and n_ticks > 0 and n_ticks % every_n == 0:
            try:
                backtest_summary = self.run_backtest_lab_now(
                    operator=operator,
                    limit=int(cfg_get(self.config, "autonomous_paper_learning.backtest_lab_limit", 2) or 2),
                )
            except Exception as exc:
                backtest_summary = {"status": "error", "message": str(exc)[:200]}

        orders_before = self._order_count()
        result = self.ft.run_once(actor=operator)
        orders_after = self._order_count()
        entries = result.get("entries") or {}
        out = {
            **result,
            "holder_id": holder,
            "orders_before": orders_before,
            "orders_after": orders_after,
            "orders_created": max(0, orders_after - orders_before),
            "cycle_type": "autonomous_paper_learning",
            "market_data_refresh": refresh_summary,
            "trade_state_repair": trade_state_repair,
        }
        if entries.get("action") == "no_trade" or entries.get("reason") == "no_account_eligible_symbols":
            out["status"] = "ok"
            out["action"] = "no_trade"
            out["reason"] = entries.get("reason") or "no_account_eligible_symbols"
            out["message"] = entries.get("message") or "No account-eligible symbols for paper buy."
            out["orders_submitted"] = False
        self.lease.release(holder, out)
        entries = result.get("entries") or {}
        tick_summary = entries.get("tick_summary") or result.get("tick_summary") or {}
        audit_payload = {
            "new_orders": out["orders_created"],
            "orders_created": out["orders_created"],
            "market_data_refresh": refresh_summary,
            "trade_state_repair": trade_state_repair,
            "scanner_stack": scanner_summary,
            "backtest_lab": backtest_summary,
            "action": out.get("action") or entries.get("action"),
            "reason": out.get("reason") or entries.get("reason") or tick_summary.get("result"),
            "plain_summary": tick_summary.get("plain_summary") or out.get("message"),
            **{k: tick_summary[k] for k in (
                "symbols_scanned_count",
                "fresh_bar_count",
                "stale_bar_count",
                "fresh_quote_count",
                "stale_quote_count",
                "quote_refresh_attempts",
                "eligible_strategy_count",
                "active_symbols_count",
                "blocked_symbols_count",
                "push_signals_found",
                "candidates_created",
                "approved_count",
                "skipped_count",
                "order_count",
                "reason_breakdown",
                "scoring_model",
                "strategy_version",
                "push_pull_scores",
                "selected_candidate",
                "rejected_candidates",
                "top_candidate",
                "no_trade_reason_breakdown",
                "threshold_values",
            ) if k in tick_summary},
        }
        self._audit("autonomous_run_one_cycle", operator, audit_payload)
        from app.services.activity_logger import log_activity

        plain = tick_summary.get("plain_summary") or f"Tick complete — {out.get('orders_created', 0)} orders"
        log_activity(
            self.session,
            "tick",
            plain,
            {"operator": operator, **audit_payload},
            commit=False,
        )
        self.session.flush()
        return {**out, "tick_summary": tick_summary}

    def run_backtest_lab_now(self, *, operator: str = "operator", limit: int = 3) -> dict[str, Any]:
        lab = ResearchLabService(self.session)
        proposed = lab.propose_backtests_from_memory(limit=limit)
        ran = []
        for job in proposed.get("proposals", [])[:limit]:
            if job.get("strategy_id"):
                try:
                    ran.append(
                        lab.run_backtest(
                            {
                                "strategy_id": job["strategy_id"],
                                "symbols": job.get("symbols") or ["BTC/USD"],
                            }
                        )
                    )
                except Exception as exc:
                    ran.append({"status": "error", "strategy_id": job["strategy_id"], "message": str(exc)[:200]})
        self._audit("autonomous_backtest_lab", operator, {"proposed": len(proposed.get("proposals", [])), "ran": len(ran)})
        self.session.flush()
        return {
            "status": "ok",
            "message": "Backtest lab run (research only, no orders)",
            "proposed": proposed,
            "runs": ran,
            "orders_created": 0,
        }
