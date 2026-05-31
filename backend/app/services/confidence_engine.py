"""Evidence-based confidence scores — not permission to trade live."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    ExecutionLog,
    LessonNode,
    OrderRecord,
    ResearchBacktestRun,
    StrategyRegistry,
    TradeRecord,
)
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.live_lock_tripwire import live_lock_tripwire_status
from app.services.nuke_epoch_service import filter_lessons_post_nuke, get_latest_reset_epoch
from app.services.order_metrics import order_summary
from app.services.session_engine import SessionEngine
from app.services.timestamp_safety import safe_record_timestamp


LABELS = [
    (0, 20, "Unsafe / learning only"),
    (21, 40, "Weak"),
    (41, 60, "Developing"),
    (61, 75, "Paper competent"),
    (76, 85, "Tiny-live candidate"),
    (86, 100, "Strong — still needs human approval"),
]


def score_label(score: float) -> str:
    s = max(0.0, min(100.0, float(score)))
    for lo, hi, label in LABELS:
        if lo <= s <= hi:
            return label
    return LABELS[-1][2]


def can_unlock_live() -> bool:
    """Confidence never unlocks live trading."""
    return False


class ConfidenceEngine:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.weights = dict((self.config.get("confidence") or {}).get("weights") or {})
        self._reset_epoch = get_latest_reset_epoch(session)

    def _w(self, key: str, default: float) -> float:
        return float(self.weights.get(key, default))

    def _post_nuke_trades(self) -> list[TradeRecord]:
        rows = list(self.session.exec(select(TradeRecord)).all())
        if not self._reset_epoch:
            return rows
        cutoff = self._reset_epoch.get("nuke_completed_at")
        # Safe timestamp: a TradeRecord row missing created_at (schema drift) must not
        # raise AttributeError and crash confidence/cockpit — fall back to opened_at etc.
        return [t for t in rows if (ts := safe_record_timestamp(t)) and self._is_after(ts, cutoff)]

    def _post_nuke_lessons(self) -> list[LessonNode]:
        return filter_lessons_post_nuke(
            self.session, list(self.session.exec(select(LessonNode)).all())
        )

    def _post_nuke_orders(self) -> list[OrderRecord]:
        rows = list(self.session.exec(select(OrderRecord)).all())
        if not self._reset_epoch:
            return rows
        cutoff = self._reset_epoch.get("nuke_completed_at")
        return [o for o in rows if (ts := safe_record_timestamp(o)) and self._is_after(ts, cutoff)]

    @staticmethod
    def _is_after(created: datetime, cutoff_iso: Optional[str]) -> bool:
        if not cutoff_iso:
            return True
        try:
            cutoff = datetime.fromisoformat(str(cutoff_iso).replace("Z", ""))
            return created >= cutoff
        except ValueError:
            return True

    def _evidence_count(self) -> int:
        return (
            len(self._post_nuke_trades())
            + len(self._post_nuke_lessons())
            + len(self._post_nuke_orders())
        )

    def _trade_performance_score(self) -> dict[str, Any]:
        closed = [t for t in self._post_nuke_trades() if t.status == "closed"]
        if not closed:
            return {"score": 35.0, "evidence": ["No closed paper trades yet — low sample."], "win_rate": None}
        wins = [t for t in closed if (t.pl_dollars or 0) > 0]
        losses = [t for t in closed if (t.pl_dollars or 0) <= 0]
        win_rate = len(wins) / len(closed) if closed else 0
        rets = [float(t.return_pct or 0) for t in closed if t.return_pct is not None]
        avg_ret = sum(rets) / len(rets) if rets else 0
        gross_win = sum(float(t.pl_dollars or 0) for t in wins)
        gross_loss = abs(sum(float(t.pl_dollars or 0) for t in losses)) or 0.01
        pf = gross_win / gross_loss
        score = 30.0 + win_rate * 40 + min(20, pf * 10) + min(10, avg_ret * 100)
        consec_loss = 0
        for t in sorted(closed, key=lambda x: x.closed_at or datetime.min):
            if (t.pl_dollars or 0) <= 0:
                consec_loss += 1
            else:
                consec_loss = 0
        if consec_loss >= 3:
            score -= 15
        return {
            "score": round(min(100, max(0, score)), 1),
            "win_rate": round(win_rate * 100, 1),
            "loss_rate": round((1 - win_rate) * 100, 1),
            "profit_factor": round(pf, 2),
            "avg_return_pct": round(avg_ret * 100, 2),
            "closed_trades": len(closed),
            "evidence": [f"{len(closed)} closed trades, win rate {win_rate:.0%}."],
        }

    def _execution_score(self) -> dict[str, Any]:
        if self._evidence_count() == 0:
            return {"score": 0.0, "evidence": ["No post-reset orders yet."], "orders_attempted": 0}
        om = order_summary(self.session)
        attempted = om.get("orders_attempted") or 0
        filled = om.get("orders_filled") or 0
        rejected = om.get("orders_rejected") or 0
        blocked = om.get("orders_blocked_preflight") or 0
        fill_rate = filled / attempted if attempted else 0
        score = 50.0 + fill_rate * 35 - min(25, rejected * 2) - min(15, blocked)
        return {
            "score": round(min(100, max(0, score)), 1),
            "orders_attempted": attempted,
            "orders_filled": filled,
            "orders_rejected": rejected,
            "preflight_blocked": blocked,
            "evidence": [f"Fill rate {fill_rate:.0%} on {attempted} attempts."],
        }

    def _strategy_validation_score(self) -> dict[str, Any]:
        runs = list(self.session.exec(select(ResearchBacktestRun).order_by(ResearchBacktestRun.id.desc()).limit(20)).all())
        if self._reset_epoch:
            cutoff = self._reset_epoch.get("nuke_completed_at")
            runs = [r for r in runs if (ts := safe_record_timestamp(r)) and self._is_after(ts, cutoff)]
        regs = list(self.session.exec(select(StrategyRegistry)).all())
        paper_ok = sum(1 for r in regs if r.current_stage in ("paper_experiment", "paper_active", "paper_candidate"))
        score = 40.0 + min(30, len(runs) * 3) + min(20, paper_ok * 5)
        min_n = int(cfg_get(self.config, "confidence.min_sample_trades_for_strategy", 3))
        return {
            "score": round(min(100, score), 1),
            "backtest_runs": len(runs),
            "paper_stage_strategies": paper_ok,
            "min_sample_required": min_n,
            "evidence": [f"{len(runs)} backtest runs on file."],
        }

    def _memory_score(self) -> dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=14)
        lessons = [l for l in self._post_nuke_lessons() if (ts := safe_record_timestamp(l)) and ts >= since]
        mistakes = [l for l in lessons if "block" in (l.memory_type or "") or "reject" in (l.memory_type or "")]
        fixed = [l for l in lessons if "outcome" in (l.memory_type or "") or "filled" in (l.memory_type or "")]
        score = 45.0 + min(25, len(lessons)) + min(15, len(fixed) * 2) - min(20, len(mistakes))
        return {
            "score": round(min(100, max(0, score)), 1),
            "lessons_14d": len(lessons),
            "mistake_memories": len(mistakes),
            "positive_outcomes": len(fixed),
            "evidence": [f"{len(lessons)} lessons in last 14 days."],
        }

    def _risk_score(self) -> dict[str, Any]:
        recon = BrokerReconciliationService(self.session, self.config)
        ghosts = recon.ghost_position_candidates()
        trip = live_lock_tripwire_status(self.config)
        score = 70.0
        if ghosts:
            score -= 25
        if trip.get("live_lock_status") != "locked":
            score -= 40
        if trip.get("tripwire_ok") is False:
            score -= 20
        return {
            "score": round(min(100, max(0, score)), 1),
            "ghost_candidates": len(ghosts),
            "live_lock": trip.get("live_lock_status"),
            "evidence": ["Live lock OK" if trip.get("live_lock_status") == "locked" else "Live lock issue"],
        }

    def _data_quality_score(self) -> dict[str, Any]:
        sess = SessionEngine().detect()
        score = 60.0
        if not sess.calendar_available:
            score -= 25
        if sess.us_stock_close_reason == "Calendar unavailable":
            score -= 10
        return {
            "score": round(min(100, max(0, score)), 1),
            "calendar_available": sess.calendar_available,
            "us_stocks": sess.to_dict().get("us_stocks_display"),
            "crypto": sess.to_dict().get("crypto_display"),
            "evidence": ["Market calendar loaded" if sess.calendar_available else "Calendar unavailable"],
        }

    def _broker_compatibility_score(self) -> dict[str, Any]:
        from app.services.account_pair_eligibility_service import AccountPairEligibilityService

        elig = AccountPairEligibilityService(self.session, self.config).summary()
        blocked = elig.get("blocked_count", 0)
        total = blocked + elig.get("eligible_count", 0)
        ratio = blocked / total if total else 0
        score = 75.0 - ratio * 40
        return {
            "score": round(min(100, max(0, score)), 1),
            "blocked_pairs": blocked,
            "eligible_pairs": elig.get("eligible_count", 0),
            "evidence": [f"{blocked} pairs blocked by account balance."],
        }

    def _allocator_confidence_score(self) -> dict[str, Any]:
        try:
            from app.services.capital_allocator import CapitalAllocatorService

            st = CapitalAllocatorService(self.session, self.config).status_summary()
            div = st.get("diversification_health") or {}
            score = float(div.get("concentration_score") or st.get("allocator_confidence") or 50)
            if st.get("broker_data_freshness") != "fresh":
                score = min(score, 40.0)
            return {
                "score": round(score, 1),
                "market_mode": st.get("current_market_mode"),
                "deployable_capital": st.get("deployable_capital"),
                "evidence": [f"Diversification health: {div.get('healthy', False)}"],
            }
        except Exception as exc:
            return {"score": 40.0, "evidence": [f"Allocator unavailable: {exc}"]}

    def compute_dimensions(self) -> dict[str, Any]:
        dims = {
            "trade_performance": self._trade_performance_score(),
            "execution_quality": self._execution_score(),
            "strategy_validation": self._strategy_validation_score(),
            "memory_learning": self._memory_score(),
            "risk_discipline": self._risk_score(),
            "data_quality": self._data_quality_score(),
            "broker_compatibility": self._broker_compatibility_score(),
            "allocator_confidence": self._allocator_confidence_score(),
        }
        overall = (
            dims["trade_performance"]["score"] * self._w("trade_performance", 0.25)
            + dims["execution_quality"]["score"] * self._w("execution_quality", 0.2)
            + dims["strategy_validation"]["score"] * self._w("strategy_validation", 0.15)
            + dims["memory_learning"]["score"] * self._w("memory_learning", 0.15)
            + dims["risk_discipline"]["score"] * self._w("risk_discipline", 0.15)
            + dims["data_quality"]["score"] * self._w("data_quality", 0.1)
            + dims["allocator_confidence"]["score"] * 0.05
        )
        market_regime = (dims["data_quality"]["score"] + dims["risk_discipline"]["score"]) / 2
        return {
            "overall": round(overall, 1),
            "overall_label": score_label(overall),
            "market_regime_confidence": round(market_regime, 1),
            "dimensions": dims,
            "can_unlock_live": False,
            "interpretation": "Confidence is evidence for learning — not permission to enable live trading.",
        }

    def summary(self) -> dict[str, Any]:
        evidence = self._evidence_count()
        epoch = self._reset_epoch or {}
        if evidence == 0:
            return {
                "status": "ok",
                "overall": None,
                "overall_score": 0,
                "overall_label": "No evidence yet",
                "confidence_state": "no_evidence",
                "reset_epoch_id": epoch.get("reset_epoch_id"),
                "nuke_completed_at": epoch.get("nuke_completed_at"),
                "post_nuke_sample_size": 0,
                "evidence_count": 0,
                "interpretation": "No paper evidence yet — confidence will build after post-reset trades and lessons.",
                "can_unlock_live": False,
                "dimensions": {},
            }
        data = self.compute_dimensions()
        state = "developing"
        if data["overall"] >= 76:
            state = "validated"
        elif data["overall"] < 41:
            state = "developing"
        return {
            "status": "ok",
            **data,
            "overall_score": data["overall"],
            "confidence_state": state,
            "reset_epoch_id": epoch.get("reset_epoch_id"),
            "nuke_completed_at": epoch.get("nuke_completed_at"),
            "post_nuke_sample_size": evidence,
            "evidence_count": evidence,
        }

    def by_strategy(self) -> dict[str, Any]:
        regs = list(self.session.exec(select(StrategyRegistry)).all())
        out = []
        base = self.compute_dimensions()["overall"]
        for r in regs:
            closed = list(
                self.session.exec(
                    select(TradeRecord).where(
                        TradeRecord.strategy == r.strategy_id, TradeRecord.status == "closed"
                    )
                ).all()
            )
            adj = base
            if closed:
                wins = sum(1 for t in closed if (t.pl_dollars or 0) > 0)
                adj = base * 0.5 + (wins / len(closed)) * 50
            out.append(
                {
                    "strategy_id": r.strategy_id,
                    "stage": r.current_stage,
                    "score": round(min(100, adj), 1),
                    "label": score_label(adj),
                    "closed_trades": len(closed),
                }
            )
        return {"status": "ok", "strategies": sorted(out, key=lambda x: -x["score"])}

    def by_symbol(self) -> dict[str, Any]:
        trades = list(self.session.exec(select(TradeRecord)).all())
        sym_map: dict[str, list] = {}
        for t in trades:
            sym_map.setdefault(t.symbol, []).append(t)
        base = self.compute_dimensions()["overall"]
        out = []
        for sym, rows in sym_map.items():
            closed = [r for r in rows if r.status == "closed"]
            adj = base * 0.7 if not closed else base
            if closed:
                wins = sum(1 for c in closed if (c.pl_dollars or 0) > 0)
                adj = min(100, base * 0.4 + (wins / len(closed)) * 60)
            out.append({"symbol": sym, "score": round(adj, 1), "label": score_label(adj), "trades": len(rows)})
        return {"status": "ok", "symbols": sorted(out, key=lambda x: -x["score"])[:30]}
