"""Deterministic strategy validation gate — lifecycle transitions, no orders."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    OrderRecord,
    StrategyEligibilityWindow,
    StrategyLifecycleEvent,
    StrategyPromotionRule,
    StrategyRegistry,
    StrategyRejection,
    StrategyValidationResult,
    SystemValidationAudit,
)
from app.services.config_manager import ConfigManager
from app.services.research_performance import evaluate_metrics
from app.services.strategy_conflict_service import StrategyConflictService
from app.services.strategy_registry_service import StrategyRegistryService
from app.services.strategy_scorecard_service import StrategyScorecardService
from app.services.strategy_stages import can_transition


class StrategyValidationGate:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.live_locked = not bool(self.config.get("live_trading_enabled", False))

    def _audit(self, action: str, strategy_id: str | None, decision: str, reasoning: str, inputs: dict | None = None) -> None:
        seed = hashlib.md5(f"{strategy_id}|{action}|{datetime.utcnow().isoformat()}".encode()).hexdigest()
        self.session.add(
            SystemValidationAudit(
                actor="gate",
                action=action,
                target_strategy_id=strategy_id,
                inputs_json=inputs,
                decision=decision,
                reasoning=reasoning[:500],
                deterministic_seed=seed,
            )
        )

    def validate_strategy(self, strategy_id: str, target_stage: Optional[str] = None) -> dict[str, Any]:
        reg = self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == strategy_id)
        ).first()
        if not reg:
            return {"status": "error", "message": "strategy not in registry"}

        scorecard_svc = StrategyScorecardService(self.session, self.config)
        sc = scorecard_svc.compute(strategy_id)
        metrics = {
            "expectancy": sc.expectancy_net,
            "profit_factor": sc.profit_factor_net,
            "max_drawdown_pct": sc.max_drawdown,
            "num_trades": sc.sample_size,
        }
        ev = evaluate_metrics(metrics, self.config)

        tgt = target_stage or self._suggest_target(reg, ev, sc)
        passed, failures, warnings = self._run_gate(reg, tgt, metrics, sc)
        result = StrategyValidationResult(
            strategy_id=strategy_id,
            gate_name=f"{reg.current_stage}_to_{tgt}",
            target_stage=tgt,
            passed=passed,
            metrics_json=metrics,
            failure_reasons_json=failures,
            warning_reasons_json=warnings,
            data_freshness_ok=not bool(sc.data_warning),
            sample_size_ok=(sc.sample_size or 0) >= int(self.config.get("research", {}).get("low_sample_trade_threshold", 10)),
            cost_realism_ok=(sc.profit_factor_net or 0) >= 1.0,
            memory_ok=reg.validated_memory_count >= 0,
            portfolio_ok=True,
            broker_ok=True,
            reconciliation_ok=True,
            risk_ok=not ev["reject"],
        )
        self.session.add(result)
        reg.latest_validation_id = result.id

        transitioned = None
        if passed and tgt != reg.current_stage:
            ok, reason = can_transition(reg.current_stage, tgt, live_trading_locked=self.live_locked)
            if ok:
                transitioned = self._transition(reg, tgt, "gate_pass", failures)
            elif reason == "LIVE_TRADING_LOCKED" and tgt == "tiny_live":
                transitioned = self._transition(reg, "live_locked", "LIVE_TRADING_LOCKED", [reason])
            else:
                failures.append(reason or "transition_denied")
        elif not passed and ev["reject"]:
            if reg.current_stage == "paper_active" and reg.quarantine_status:
                warnings.append("runtime_position_override_keeps_paper_active")
            elif reg.current_stage not in ("rejected", "retired"):
                self._transition(reg, "rejected", "metrics_fail", failures)
                self._record_rejection(strategy_id, failures)

        self.session.add(reg)
        self._audit("validate", strategy_id, "pass" if passed else "fail", "; ".join(failures) or "ok", metrics)
        return {
            "status": "ok",
            "strategy_id": strategy_id,
            "passed": passed,
            "target_stage": tgt,
            "current_stage": reg.current_stage,
            "transitioned": transitioned,
            "failures": failures,
            "warnings": warnings,
            "promote_allowed": sc.promote_allowed,
        }

    def validate_all(self) -> dict[str, Any]:
        rows = self.session.exec(select(StrategyRegistry)).all()
        results = []
        for r in rows:
            results.append(self.validate_strategy(r.strategy_id))
        StrategyConflictService(self.session, self.config).evaluate()
        return {"status": "ok", "validated": len(results), "results": results}

    def promote_candidates(self) -> dict[str, Any]:
        promoted = expired = blocked = 0
        now = datetime.utcnow()
        candidates = list(
            self.session.exec(
                select(StrategyRegistry).where(
                    StrategyRegistry.current_stage.in_(["watchlist", "paper_candidate", "paper_active"])
                )
            ).all()
        )
        for reg in candidates:
            out = self.validate_strategy(reg.strategy_id)
            if out.get("transitioned"):
                promoted += 1
            win = self._active_window(reg.strategy_id)
            if win and win.closed_at is None:
                if win.hard_block_reason:
                    self._break_eligibility(win, reg, win.hard_block_reason)
                    blocked += 1
                elif now >= win.latest_decision_at_utc and win.eligibility_health != "clean":
                    self._expire_window(win, reg)
                    expired += 1
                elif now >= win.earliest_promote_at_utc and win.maintenance_pass:
                    if self.live_locked:
                        self._transition(reg, "live_locked", "eligibility_window_day7", [])
                    else:
                        self._transition(reg, "live_candidate", "eligibility_ready", [])
                    promoted += 1
            elif reg.current_stage == "paper_active" and out.get("passed"):
                self._maybe_open_window(reg)
        self._audit("promote_candidates", None, "ok", f"p={promoted} e={expired} b={blocked}")
        return {"status": "ok", "promoted": promoted, "expired": expired, "blocked": blocked}

    def retire_failed(self) -> dict[str, Any]:
        n = 0
        for reg in self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.current_stage == "rejected")
        ).all():
            metrics = StrategyRegistryService(self.session)._latest_metrics(reg.strategy_id)
            if (metrics.get("num_trades") or 0) > 0 and (metrics.get("expectancy") or 0) < -0.01:
                if reg.current_stage != "retired":
                    self._transition(reg, "retired", "decay", ["persistent_negative_expectancy"])
                    n += 1
        return {"status": "ok", "retired": n}

    def pause(self, strategy_id: str, reason: str = "operator_pause") -> dict:
        reg = self._get_reg(strategy_id)
        self._transition(reg, "paused", reason, [])
        return {"status": "ok", "stage": reg.current_stage}

    def resume(self, strategy_id: str) -> dict:
        reg = self._get_reg(strategy_id)
        prev = reg.previous_stage or "watchlist"
        if prev in ("tiny_live", "standard_live") and self.live_locked:
            prev = "paper_active"
        ok, msg = can_transition("paused", prev, live_trading_locked=self.live_locked)
        if not ok:
            prev = "watchlist"
        self._transition(reg, prev, "resume", [])
        return {"status": "ok", "stage": reg.current_stage}

    def rebalance(self) -> dict:
        return StrategyConflictService(self.session, self.config).evaluate()

    def _get_reg(self, strategy_id: str) -> StrategyRegistry:
        reg = self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == strategy_id)
        ).first()
        if not reg:
            raise ValueError("not found")
        return reg

    def _suggest_target(self, reg: StrategyRegistry, ev: dict, sc) -> str:
        if reg.current_stage == "paper_active" and reg.quarantine_status:
            return "paper_active"
        if ev["reject"]:
            return "rejected"
        if reg.current_stage == "research_only" and sc.sample_size and sc.sample_size >= 100 and sc.promote_allowed:
            return "watchlist"
        if reg.current_stage == "watchlist" and sc.promote_allowed:
            return "paper_candidate"
        if reg.current_stage == "paper_candidate":
            return "paper_active"
        if reg.current_stage == "paper_active" and sc.promote_allowed:
            return "live_candidate"
        return reg.current_stage

    def _run_gate(self, reg: StrategyRegistry, tgt: str, metrics: dict, sc) -> tuple[bool, list, list]:
        rule = self.session.exec(
            select(StrategyPromotionRule).where(
                StrategyPromotionRule.stage_from == reg.current_stage,
                StrategyPromotionRule.stage_to == tgt,
                StrategyPromotionRule.enabled == True,  # noqa: E712
            )
        ).first()
        failures: list[str] = []
        warnings: list[str] = []
        th = (rule.threshold_value_json if rule else {}) or {}

        if tgt == "rejected":
            return True, [], []

        if metrics.get("expectancy") is not None and float(metrics["expectancy"]) < float(th.get("min_expectancy", 0)):
            failures.append("negative_expectancy")
        if metrics.get("profit_factor") is not None and float(metrics["profit_factor"]) < float(
            th.get("min_profit_factor", 1.3)
        ):
            failures.append("profit_factor_below_threshold")
        if metrics.get("max_drawdown_pct") and float(metrics["max_drawdown_pct"]) > float(
            th.get("max_drawdown_pct", 100)
        ):
            failures.append("max_drawdown_exceeded")
        if (metrics.get("num_trades") or 0) < int(th.get("min_backtest_trades", 0)):
            failures.append("insufficient_trades")
        if sc.data_warning and th.get("block_stale_data_hard"):
            failures.append("stale_data")
        if sc.parameter_variation_warning and th.get("block_parameter_sweep_no_variation"):
            failures.append("parameter_sweep_no_variation")

        if reg.pending_memory_count > 0 and reg.validated_memory_count == 0 and tgt in ("paper_active", "live_candidate"):
            warnings.append("pending_memories_only")

        from app.database import StrategyMemoryLink

        bad = self.session.exec(
            select(StrategyMemoryLink).where(
                StrategyMemoryLink.strategy_id == reg.strategy_id,
                StrategyMemoryLink.memory_type == "rejected_strategy_memory",
                StrategyMemoryLink.memory_status == "validated",
            )
        ).first()
        if bad and th.get("block_validated_rejection_memory"):
            failures.append("validated_rejection_memory")

        if tgt in ("tiny_live", "standard_live") and self.live_locked:
            failures.append("LIVE_TRADING_LOCKED")

        return len(failures) == 0, failures, warnings

    def _transition(self, reg: StrategyRegistry, to_stage: str, code: str, failures: list) -> str:
        ok, reason = can_transition(reg.current_stage, to_stage, live_trading_locked=self.live_locked)
        if not ok and reason != "LIVE_TRADING_LOCKED":
            return reg.current_stage
        if reason == "LIVE_TRADING_LOCKED" and to_stage == "tiny_live":
            to_stage = "live_locked"
        frm = reg.current_stage
        reg.previous_stage = frm
        reg.current_stage = to_stage
        reg.can_trade_paper = to_stage in ("paper_active", "paper_candidate")
        reg.can_trade_live = False
        reg.live_locked = True
        reg.updated_at = datetime.utcnow()
        reg.last_reviewed_at = datetime.utcnow()
        self.session.add(
            StrategyLifecycleEvent(
                strategy_id=reg.strategy_id,
                from_stage=frm,
                to_stage=to_stage,
                reason_code=code,
                reason_text="; ".join(failures) if failures else code,
                evidence_json={"failures": failures},
                decided_by="validation_gate",
            )
        )
        self.session.add(reg)
        return to_stage

    def _record_rejection(self, strategy_id: str, failures: list) -> None:
        self.session.add(
            StrategyRejection(
                strategy_id=strategy_id,
                gate_name="validation_gate",
                failure_codes_json=failures,
                permanent=False,
                rationale="; ".join(failures),
                evidence_json={"failures": failures},
            )
        )

    def _maybe_open_window(self, reg: StrategyRegistry) -> None:
        existing = self._active_window(reg.strategy_id)
        if existing:
            return
        now = datetime.utcnow()
        rule = self.session.exec(
            select(StrategyPromotionRule).where(StrategyPromotionRule.rule_key == "eligibility_window")
        ).first()
        th = (rule.threshold_value_json if rule else {}) or {}
        days_min = int(th.get("earliest_promote_days", 7))
        days_max = int(th.get("latest_decision_days", 14))
        self.session.add(
            StrategyEligibilityWindow(
                strategy_id=reg.strategy_id,
                stage="live_candidate",
                eligibility_start_at_utc=now,
                earliest_promote_at_utc=now + timedelta(days=days_min),
                latest_decision_at_utc=now + timedelta(days=days_max),
                eligibility_health="clean",
                maintenance_pass=True,
                capacity_pass=True,
                correlation_pass=True,
            )
        )

    def _active_window(self, strategy_id: str) -> Optional[StrategyEligibilityWindow]:
        return self.session.exec(
            select(StrategyEligibilityWindow)
            .where(
                StrategyEligibilityWindow.strategy_id == strategy_id,
                StrategyEligibilityWindow.closed_at == None,  # noqa: E711
            )
            .order_by(StrategyEligibilityWindow.created_at.desc())
        ).first()

    def _break_eligibility(self, win: StrategyEligibilityWindow, reg: StrategyRegistry, reason: str) -> None:
        win.eligibility_health = "hard_blocked"
        win.hard_block_reason = reason
        win.closed_at = datetime.utcnow()
        self._transition(reg, "paper_active", "eligibility_broken", [reason])

    def _expire_window(self, win: StrategyEligibilityWindow, reg: StrategyRegistry) -> None:
        win.eligibility_health = "expired"
        win.decision = "expire_requalify"
        win.decision_reason = "day_14_deadline"
        win.closed_at = datetime.utcnow()
        self._transition(reg, "paper_active", "eligibility_expired", ["day_14"])

    def assert_no_orders_created(self, orders_before: int) -> bool:
        after = len(self.session.exec(select(OrderRecord)).all())
        return after == orders_before
