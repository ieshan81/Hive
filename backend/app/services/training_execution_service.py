"""Wire approved training decisions into caged PaperExecutionService — no live path."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    LessonNode,
    OrderRecord,
    PaperExperimentDecision,
    PaperExperimentOutcome,
    PortfolioDecision,
    PositionSnapshot,
    StrategySignal,
    SystemValidationAudit,
)
from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.broker_safety import broker_base_url, is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.lesson_memory_service import LessonMemoryService
from app.services.meme_volatility_spike_detector import MemeVolatilitySpikeDetector
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.paper_execution_service import PaperExecutionService
from app.services.portfolio_gate import ApprovedCandidate
from app.services.symbol_tier_service import SymbolTierService


class TrainingExecutionService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.pl = AggressivePaperLearningService(session)
        self.paper = PaperExecutionService(session, self.config)
        self.lessons = LessonMemoryService(session, self.config)
        self.tiers = SymbolTierService(self.config)

    def _audit_truth(self, action: str, decision: str, details: dict) -> None:
        self.session.add(
            SystemValidationAudit(
                actor="training_execution",
                action=action,
                decision=decision,
                inputs_json={
                    **details,
                    "broker_mode": "paper" if is_paper_broker_url() else "unknown",
                    "paper_broker": is_paper_broker_url(),
                    "broker_base_url": broker_base_url(),
                    "live_trading_locked": True,
                    "live_orders_enabled": bool(cfg_get(self.config, "execution.live_orders_enabled", False)),
                },
                reasoning=details.get("message", "")[:500],
            )
        )

    def preflight_training(self) -> dict[str, Any]:
        blockers = []
        if not self.pl.cfg.get("mode_enabled"):
            blockers.append("training_mode_disabled")
        if not is_paper_broker_url():
            blockers.append("broker_not_paper")
        if not bool(cfg_get(self.config, "execution.paper_orders_enabled", False)):
            blockers.append("paper_orders_disabled")
        if bool(cfg_get(self.config, "live_trading_enabled", False)):
            blockers.append("live_trading_must_stay_off")
        if not bool(self.pl.cfg.get("require_position_monitor", True)):
            blockers.append("exit_monitor_not_configured")
        return {
            "status": "ok" if not blockers else "blocked",
            "blockers": blockers,
            "training_mode_enabled": bool(self.pl.cfg.get("mode_enabled")),
            **live_lock_status(self.config),
        }

    def open_training_positions(self) -> list[dict]:
        rows = list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
        reviewer = OpenPositionReviewService(self.session, self.config)
        out = []
        for p in rows:
            out.append(reviewer.review_position(p.symbol, p))
        return out

    def execute_approved_decision(self, decision_id: int) -> dict[str, Any]:
        pf = self.preflight_training()
        if pf.get("blockers"):
            return {"status": "blocked", "blockers": pf["blockers"], **pf}

        dec = self.session.get(PaperExperimentDecision, decision_id)
        if not dec or dec.decision != "approved":
            return {"status": "error", "message": "Decision not approved"}
        if dec.execution_status in ("submitted", "filled"):
            return {"status": "skipped", "message": "Already executed", "execution_status": dec.execution_status}

        spike = MemeVolatilitySpikeDetector(self.session, self.config).evaluate_symbol(dec.symbol)
        if spike.get("suggested_action") == "block":
            dec.execution_status = "blocked_spike"
            self.session.add(dec)
            self._training_memory("training_blocked_memory", dec, spike.get("reason_codes", []))
            return {"status": "blocked", "reason": "meme_spike_detector", "spike": spike}

        existing = self.session.exec(
            select(PositionSnapshot).where(
                PositionSnapshot.symbol == dec.symbol, PositionSnapshot.qty > 0
            )
        ).first()
        if existing and dec.side == "buy":
            return {"status": "blocked", "reason": "same_symbol_position_conflict"}

        return self._submit_training_order(dec, spike)

    def execute_pending_approved(self, limit: int = 1) -> dict[str, Any]:
        rows = list(
            self.session.exec(
                select(PaperExperimentDecision)
                .where(
                    PaperExperimentDecision.decision == "approved",
                    PaperExperimentDecision.execution_status == None,  # noqa: E711
                )
                .order_by(PaperExperimentDecision.created_at.desc())
                .limit(limit)
            ).all()
        )
        results = []
        for r in rows:
            results.append(self.execute_approved_decision(r.id))
        return {"status": "ok", "results": results}

    def _submit_training_order(self, dec: PaperExperimentDecision, spike: dict) -> dict[str, Any]:
        alpaca = AlpacaAdapter(self.session)
        quote_sym = normalize_crypto_symbol(dec.symbol)
        quote = alpaca.get_quote(quote_sym, "crypto") or {}
        mid = float(quote.get("mid") or quote.get("ask") or 0)
        if mid <= 0:
            return {"status": "error", "message": "no_quote"}

        notional = float(dec.approved_notional or self.pl.cfg.get("default_experiment_notional_usd", 10))
        qty = round(notional / mid, 6)
        tier_info = self.tiers.classify(dec.symbol)
        tier = getattr(tier_info, "tier", str(tier_info))
        stop_pct = float((self.config.get("crypto_push_pull") or {}).get("stop_loss_pct", 0.02))
        stop_loss = mid * (1 - stop_pct) if dec.side == "buy" else mid * (1 + stop_pct)
        max_hold_h = float(self.pl.cfg.get("meme_coin_max_hold_minutes", 240)) / 60.0
        if spike.get("tier") == "MAJOR_CRYPTO":
            max_hold_h = float(self.pl.cfg.get("major_crypto_max_hold_hours", 48))

        cycle_run_id = f"training-{uuid.uuid4().hex[:12]}"
        sig = StrategySignal(
            strategy=dec.strategy_id,
            symbol=dec.symbol,
            asset_class="crypto",
            signal="buy" if dec.side == "buy" else "sell",
            side=dec.side,
            strength=0.7,
            confidence=0.65,
            status="generated",
            stop_loss=stop_loss,
            take_profit=mid * 1.03 if dec.side == "buy" else mid * 0.97,
            signal_type="entry" if dec.side == "buy" else "exit",
            cycle_run_id=cycle_run_id,
            signal_metadata={
                "training_trade": True,
                "hive_learning_trade": True,
                "approved_notional": notional,
                "position_qty": qty,
                "current_price": mid,
                "tier": tier,
                "max_hold_hours": max_hold_h,
                "expected_hold_time": f"{max_hold_h}h",
                "exit_strategy": "time_stop_and_momentum",
                "spread_pct": quote.get("spread_pct"),
                "paper_experiment_decision_id": dec.id,
                "broker_mode": "paper",
                "live_trading_locked": True,
            },
        )
        self.session.add(sig)
        self.session.flush()

        pdec = PortfolioDecision(
            cycle_run_id=cycle_run_id,
            signal_id=sig.id,
            symbol=dec.symbol,
            side=dec.side,
            signal_type=sig.signal_type,
            portfolio_status="approved",
            portfolio_reason_code="training_experiment",
            human_reason="Aggressive learning training trade (caged paper)",
            ranking_score=1.0,
            portfolio_rank=1,
            selected_for_execution=True,
            evidence_json={"training": True, "decision_id": dec.id},
        )
        self.session.add(pdec)
        self.session.flush()

        from app.services.account_pair_eligibility_service import AccountPairEligibilityService

        elig_block = AccountPairEligibilityService(self.session, self.config).preflight_block(
            dec.symbol, dec.side or "buy", dec.strategy_id or ""
        )
        if elig_block:
            dec.execution_status = "blocked_eligibility"
            self.session.add(dec)
            self._training_memory("training_blocked_memory", dec, [elig_block[1]])
            return {"status": "blocked", "reason": elig_block[0], "message": elig_block[1]}

        account = alpaca.sync_account()
        positions = alpaca.sync_positions()
        open_syms = {o.get("symbol") for o in alpaca.get_open_orders()}
        cand = self.paper.candidate_from_signal(sig, pdec)
        log = self.paper.submit_candidate(
            cand,
            cycle_run_id=cycle_run_id,
            portfolio_decision=pdec,
            account=account,
            positions=positions,
            open_order_symbols=open_syms,
            signal_row=sig,
        )

        dec.execution_status = log.status
        if log.status in ("paper_order_submitted", "paper_order_filled", "paper_order_partially_filled"):
            order = self.session.exec(
                select(OrderRecord).where(OrderRecord.signal_id == sig.id).order_by(OrderRecord.id.desc())
            ).first()
            dec.execution_order_id = order.id if order else None
            self._training_memory("training_entry_memory", dec, ["caged_paper_submit"])
            self._audit_truth(
                "training_order_submit",
                "submitted",
                {"symbol": dec.symbol, "signal_id": sig.id, "status": log.status, "broker_mode": "paper"},
            )
        else:
            self._training_memory("training_blocked_memory", dec, [log.reject_reason or "preflight_blocked"])

        self.session.add(dec)
        self.session.flush()
        return {
            "status": "ok",
            "signal_id": sig.id,
            "cycle_run_id": cycle_run_id,
            "execution_status": log.status,
            "reject_reason": log.reject_reason,
            "broker_mode": "paper",
            "live_trading_locked": True,
            "submitted": log.status in ("paper_order_submitted", "paper_order_filled"),
        }

    def monitor_exits(self) -> dict[str, Any]:
        reviews = OpenPositionReviewService(self.session, self.config).review_all()
        if not self.pl.cfg.get("mode_enabled"):
            return {
                "status": "ok",
                "reviews": reviews,
                "exits_attempted": 0,
                "exit_monitor_ready": bool(self.pl.cfg.get("require_position_monitor", True)),
                "training_mode_enabled": False,
                "message": "Training mode disabled — reviews only, no exit orders",
            }
        pf = self.preflight_training()
        exits = []
        for rev in reviews.get("reviews", []):
            if rev.get("action") != "exit_recommended":
                continue
            sym = rev["symbol"]
            pos = self.session.exec(
                select(PositionSnapshot).where(PositionSnapshot.symbol == sym, PositionSnapshot.qty > 0)
            ).first()
            if not pos:
                continue
            out = self._submit_exit(sym, pos.qty, rev.get("strategy"), review=rev)
            exits.append(out)
            self._training_memory_outcome(sym, rev)
        return {
            "status": "ok",
            "reviews": reviews,
            "exits_attempted": len(exits),
            "exit_results": exits,
            "exit_monitor_ready": bool(self.pl.cfg.get("require_position_monitor", True)),
            "training_mode_enabled": bool(self.pl.cfg.get("mode_enabled")),
        }

    def _submit_exit(
        self,
        symbol: str,
        qty: float,
        strategy: Optional[str],
        *,
        review: Optional[dict] = None,
    ) -> dict[str, Any]:
        if not self.pl.cfg.get("mode_enabled"):
            return {"status": "skipped", "reason": "training_disabled"}
        review = review or {}
        reason = str(review.get("reason") or "")
        purpose = "stale_position_exit"
        if "max_hold" in reason:
            purpose = "max_hold_exit"
        elif review.get("action") == "exit_recommended":
            purpose = "max_hold_exit" if review.get("stale") else "stale_position_exit"

        cycle_run_id = f"training-exit-{uuid.uuid4().hex[:10]}"
        px = float(review.get("current_price") or 0)
        sig = StrategySignal(
            strategy=strategy or "training_exit",
            symbol=symbol,
            asset_class="crypto",
            signal="sell",
            side="sell",
            strength=0.9,
            confidence=0.9,
            status="generated",
            signal_type="exit",
            cycle_run_id=cycle_run_id,
            signal_metadata={
                "training_trade": True,
                "training_exit": True,
                "close_existing_position": True,
                "purpose": purpose,
                "asset_class": "crypto",
                "position_qty": qty,
                "broker_confirmed_qty": qty,
                "current_price": px,
                "broker_mode": "paper",
                "exit_only": True,
            },
        )
        self.session.add(sig)
        self.session.flush()
        pdec = PortfolioDecision(
            cycle_run_id=cycle_run_id,
            signal_id=sig.id,
            symbol=symbol,
            side="sell",
            signal_type="exit",
            portfolio_status="approved",
            portfolio_reason_code="training_exit",
            human_reason="Training exit monitor (stale/time-stop)",
            portfolio_rank=1,
            selected_for_execution=True,
        )
        self.session.add(pdec)
        self.session.flush()
        alpaca = AlpacaAdapter(self.session)
        account = alpaca.sync_account()
        positions = alpaca.sync_positions()
        try:
            open_orders = alpaca.get_open_orders() or []
        except Exception:
            open_orders = []
        open_syms = {str(o.get("symbol") or "") for o in open_orders}
        cand = self.paper.candidate_from_signal(sig, pdec)
        cand.position_qty = qty
        cand.entry_price = px if px > 0 else cand.entry_price
        log = self.paper.submit_candidate(
            cand,
            cycle_run_id=cycle_run_id,
            portfolio_decision=pdec,
            account=account,
            positions=positions,
            open_order_symbols=open_syms,
            signal_row=sig,
        )
        stage = "caged_order_submitted"
        if log.status == "preflight_blocked":
            stage = "internal_preflight_block"
        elif log.status == "paper_order_rejected":
            stage = "broker_rejection"
        elif log.status in ("paper_order_submitted", "paper_order_filled", "paper_order_partially_filled"):
            stage = "caged_order_submitted"
        return {
            "symbol": symbol,
            "status": log.status,
            "reject_reason": log.reject_reason,
            "broker_order_id": log.broker_order_id,
            "requested_qty": qty,
            "purpose": purpose,
            "execution_path": "TrainingExecutionService→PaperExecutionService",
            "preflight_stage": stage,
            "gates_failed": log.gates_failed_json,
            "gates_passed": log.gates_passed_json,
        }

    def run_training_cycle(self) -> dict[str, Any]:
        pf = self.preflight_training()
        if pf.get("blockers"):
            return {"status": "blocked", "blockers": pf["blockers"]}

        monitor = self.monitor_exits()
        scan = self.pl.scan_experiment_eligibility()
        decisions = []
        from app.database import StrategyRegistry

        for row in scan.get("eligible", [])[:3]:
            reg = self.session.exec(
                select(StrategyRegistry).where(StrategyRegistry.strategy_id == row.get("strategy_id"))
            ).first()
            symbols = (reg.symbols if reg else None) or ["BTC/USD"]
            sym = symbols[0] if isinstance(symbols, list) and symbols else "BTC/USD"
            ev = self.pl.evaluate(row["strategy_id"], sym, side="buy")
            if ev.get("decision") == "approved":
                dec_row = self.session.exec(
                    select(PaperExperimentDecision)
                    .where(PaperExperimentDecision.strategy_id == row["strategy_id"])
                    .order_by(PaperExperimentDecision.created_at.desc())
                ).first()
                if dec_row:
                    ex = self.execute_approved_decision(dec_row.id)
                    decisions.append({"evaluate": ev, "execute": ex})
                    break

        return {
            "status": "ok",
            "monitor": monitor,
            "decisions": decisions,
            "broker_mode": "paper",
            "live_trading_locked": True,
        }

    def _training_memory(self, mtype: str, dec: PaperExperimentDecision, codes: list) -> None:
        self.lessons.upsert_lesson(
            memory_type=mtype,
            title=f"Training {dec.decision}: {dec.symbol}",
            summary=dec.reason_text or str(codes),
            detailed_lesson=f"Training trade {mtype} for {dec.strategy_id} on {dec.symbol}. Broker: paper.",
            strategy_name=dec.strategy_id,
            symbol=dec.symbol,
            source="training_execution",
            pattern_key=f"train|{dec.id}|{mtype}",
            can_influence_ranking=False,
            visible_to_ai=True,
        )

    def _training_memory_outcome(self, symbol: str, review: dict) -> None:
        self.session.add(
            PaperExperimentOutcome(
                strategy_id=review.get("strategy") or "unknown",
                symbol=symbol,
                exit_reason=review.get("reason"),
                hold_minutes=review.get("hold_minutes"),
                lesson_created=True,
            )
        )
        self.lessons.upsert_lesson(
            memory_type="training_outcome_memory",
            title=f"Training exit: {symbol}",
            summary=review.get("reason", "exit"),
            detailed_lesson="Training exit routed through caged paper path.",
            symbol=symbol,
            strategy_name=review.get("strategy"),
            source="training_exit_monitor",
            pattern_key=f"train_out|{symbol}|{datetime.utcnow().date()}",
        )

    def list_training_memories(self, limit: int = 30) -> list[dict]:
        from app.services.memory_categories import TRAINING_MEMORY_TYPES

        rows = self.session.exec(
            select(LessonNode)
            .where(LessonNode.memory_type.in_(list(TRAINING_MEMORY_TYPES)))
            .order_by(LessonNode.created_at.desc())
            .limit(limit)
        ).all()
        return [self.lessons._lesson_detail(r) for r in rows]
