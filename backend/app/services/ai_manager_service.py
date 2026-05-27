"""AI Manager — human-readable learning summaries (not fake review cards)."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import LessonNode
from app.services.confidence_engine import ConfidenceEngine
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import filter_lessons_post_nuke, get_latest_nuke_epoch, nuke_status_export
from app.services.push_pull_engine_service import PushPullEngineService
from app.services.research_lab_service import ResearchLabService
from app.services.research_backtest_engine import ResearchBacktestEngine
from app.services.sentiment_status_service import ai_advisor_status
from app.services.strategy_performance_service import StrategyPerformanceService
from app.services.strategy_status_service import strategy_status


class AIManagerService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.confidence = ConfidenceEngine(session, self.config)

    def status(self) -> dict[str, Any]:
        conf = self.confidence.summary()
        lessons = self.lessons(limit=5)
        from app.services.memory_policy_service import MemoryPolicyService

        memory = MemoryPolicyService(self.session).status()
        nuke = get_latest_nuke_epoch(self.session)
        count = memory.get("counts", {}).get("meaningful_memory_count", 0)
        if nuke and count == 0:
            headline = "Fresh brain. No validated memories yet. Paper learning available."
        else:
            headline = "What the bot learned from paper push-pull trading"
        return {
            "status": "ok",
            "headline": headline,
            "fresh_brain": bool(nuke and count == 0),
            "nuke_status": nuke_status_export(self.session),
            "memory_policy": memory,
            "memory_categories": memory.get("counts"),
            "confidence_overall": conf.get("overall"),
            "confidence_label": conf.get("overall_label"),
            "can_unlock_live": False,
            "recent_lessons_count": count,
            "questions_answered": [
                "What did I do?",
                "Why did I do it?",
                "Did it work?",
                "What did I learn?",
                "What will I do differently next time?",
            ],
            "strategy_lab": self.strategy_lab(),
            "backtest_lab": self.backtest_lab(),
            "gemini_advisor": self.gemini_advisor_panel(),
            "memory_graph": self.memory_graph_panel(),
        }

    def strategy_lab(self) -> dict[str, Any]:
        st = strategy_status(self.session, self.config)
        perf = StrategyPerformanceService(self.session, self.config).summary()
        baseline = next(
            (p for p in (perf.get("strategies") or []) if p.get("strategy_id") == "crypto_push_pull_baseline"),
            {},
        )
        bt = self.backtest_lab().get("latest_run")
        sample = int(baseline.get("closed_trades") or 0)
        if sample == 0:
            status_label = "unproven"
        elif baseline.get("expectancy_pct") is not None and float(baseline.get("expectancy_pct") or 0) < 0:
            status_label = "weak"
        elif sample < 5:
            status_label = "keep_testing"
        elif baseline.get("expectancy_pct") is not None and float(baseline.get("expectancy_pct") or 0) > 0:
            status_label = "promising"
        else:
            status_label = "keep_testing"
        return {
            "active_strategy": st.get("strategy_name"),
            "strategy_id": st.get("strategy_id"),
            "strategy_version": st.get("strategy_version"),
            "live_scoring_model": st.get("live_scoring_model"),
            "scoring_on_live_path": st.get("scoring_on_live_path"),
            "backtest_result": (bt or {}).get("result_label"),
            "paper_result": baseline.get("plain_summary"),
            "sample_size": sample,
            "expectancy": baseline.get("expectancy_pct"),
            "current_status": status_label,
            "next_test_plan": "Run 5Min push-pull backtest on BTC/USD + ETH/USD; then paper cycles with score ranking.",
        }

    def backtest_lab(self) -> dict[str, Any]:
        from app.services.universe_strategy_discovery_service import discovery_latest, discovery_status, strategy_verdict

        ResearchLabService(self.session).ensure_library()
        runs = ResearchBacktestEngine(self.session, self.config).list_runs(5)
        latest = runs[0] if runs else None
        lesson = None
        for row in self.lessons(limit=20).get("lessons") or []:
            mt = str(row.get("memory_type") or "").lower()
            if "strategy_discovery" in mt or "backtest" in mt or "research" in str(row.get("title") or "").lower():
                lesson = row
                break
        discovery = discovery_latest(self.session)
        verdict = strategy_verdict(self.session, self.config)
        selection = discovery.get("symbol_selection") or {}
        per = discovery.get("per_symbol_results") or []
        tested = sorted({r.get("symbol") for r in per if r.get("status") == "ok"})
        return {
            "backtest_run_count": len(ResearchBacktestEngine(self.session, self.config).list_runs(500)),
            "latest_run": latest,
            "metrics": (latest or {}).get("metrics"),
            "result_label": (latest or {}).get("result_label"),
            "ai_lesson": lesson,
            "universe_discovery": {
                "title": "Universe Discovery Backtest",
                "status": discovery_status(self.session),
                "available_usd_pairs": selection.get("available_usd_pairs"),
                "eligible_for_backtest": selection.get("eligible_for_backtest"),
                "selected_symbols": selection.get("selected_symbols"),
                "tested_symbols": tested,
                "skipped_symbols": discovery.get("skipped", [])[:12],
                "top_performers": verdict.get("best_symbols", [])[:5],
                "weak_performers": verdict.get("worst_symbols", [])[:5],
                "strategy_verdict": verdict.get("current_status"),
                "funnel_answer": verdict.get("funnel_answer"),
                "next_test_plan": verdict.get("next_experiment"),
                "should_paper_trade_now": verdict.get("should_paper_trade_now"),
            },
        }

    def gemini_advisor_panel(self) -> dict[str, Any]:
        adv = ai_advisor_status(self.session, self.config)
        return {
            **adv,
            "cannot_trade": True,
            "cannot_change_live_lock": True,
            "cannot_directly_apply_config": True,
        }

    def memory_graph_panel(self) -> dict[str, Any]:
        from app.services.memory_policy_service import MemoryPolicyService

        policy = MemoryPolicyService(self.session)
        mems = policy.hive_mind_memories(30)
        consolidated = [m for m in mems if (m.get("memory_type") or "").startswith("consolidated")]
        validated = [m for m in mems if m not in consolidated]
        latest_lesson = validated[0] if validated else None
        return {
            "validated_memories": validated[:15],
            "consolidated_memories": consolidated[:10],
            "latest_useful_lesson": latest_lesson,
            "raw_events_hidden_by_default": True,
            "meaningful_memory_count": policy.status().get("counts", {}).get("meaningful_memory_count"),
        }

    def memories(self, limit: int = 40) -> dict[str, Any]:
        from app.services.memory_policy_service import MemoryPolicyService

        policy = MemoryPolicyService(self.session)
        rows = policy.hive_mind_memories(limit)
        nuke = get_latest_nuke_epoch(self.session)
        return {
            "status": "ok",
            "fresh_brain": bool(nuke and len(rows) == 0),
            "nuke_epoch": nuke,
            "memories": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "human_summary": r.get("summary") or r.get("title"),
                    "memory_type": r.get("memory_type"),
                    "symbol": r.get("symbol"),
                    "strategy_name": r.get("strategy"),
                    "occurrence_count": r.get("occurrence_count", 1),
                    "last_seen_at": r.get("last_seen_at"),
                }
                for r in rows
            ],
            "count": len(rows),
            "meaningful_memory_count": policy.status().get("counts", {}).get("meaningful_memory_count"),
        }

    def lessons(self, limit: int = 30) -> dict[str, Any]:
        return PushPullEngineService(self.session, self.config).lessons(limit)

    def strategy_confidence(self) -> dict[str, Any]:
        return self.confidence.by_strategy()


def _human_summary(row: LessonNode) -> str:
    text = (row.summary or row.detailed_lesson or row.title or "").strip()
    code = (row.memory_type or "").lower()
    sym = row.symbol or ""
    if "reject" in code or "broker" in text.lower():
        if "USDC" in (sym + text).upper():
            return (
                f"{sym}: rejected because the paper account has no USDC. "
                "Avoid USDC pairs unless USDC balance exists."
            )
        if "USDT" in (sym + text).upper():
            return (
                f"{sym}: rejected because the paper account has no USDT. "
                "Avoid USDT pairs unless USDT balance exists."
            )
        return f"{sym}: broker blocked this push — {text[:120]}"
    if "daily_trade" in text.lower() or "max experiment" in text.lower():
        return "Legacy daily trade cap memory — not active under opportunity-based allocator."
    if "spread" in text.lower():
        return f"Push failed after spread cost on {sym}. Require stronger edge before entry."
    if text:
        return text[:240]
    return row.title or "Lesson recorded from paper trading."
