"""Push-pull tick scan — universe → freshness → signal → eligibility → order."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.bar_freshness_service import BarFreshnessService
from app.services.config_manager import ConfigManager
from app.services.training_execution_service import TrainingExecutionService
from app.services.universe_builder import build_merged_universe


class PushPullScanService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.pl = AggressivePaperLearningService(session)
        self.training = TrainingExecutionService(session, self.config)
        self.bar = BarFreshnessService(session, self.config)

    def run_tick_scan(self, *, max_evaluate: int = 8) -> dict[str, Any]:
        """Full push-pull scan with reason breakdown (called each training cycle)."""
        universe = build_merged_universe(self.session, self.config, limit=60)
        reason_counts: Counter[str] = Counter()
        candidates_created = 0
        approved_count = 0
        skipped_count = 0
        order_count = 0
        push_signals = 0
        decisions_out: list[dict] = []

        active = [u for u in universe if u.get("status") == "Active"]
        blocked = [u for u in universe if u.get("status") == "Blocked"]
        watch = [u for u in universe if u.get("status") == "Watch-only"]

        for u in blocked:
            br = u.get("blocked_reason") or "blocked"
            if "stale" in str(br).lower() or u.get("bar_freshness") == "stale":
                reason_counts["data_stale"] += 1
            elif "balance" in str(br).lower() or "USDC" in str(br) or "USDT" in str(br):
                reason_counts["quote_currency_unfunded"] += 1
            elif "spread" in str(br).lower():
                reason_counts["spread_too_wide"] += 1
            else:
                reason_counts["blocked_other"] += 1

        scan = self.pl.scan_experiment_eligibility()
        eligible_strats = scan.get("eligible") or []

        evaluated = 0
        for row in eligible_strats[:3]:
            if evaluated >= max_evaluate:
                break
            from sqlmodel import select
            from app.database import StrategyRegistry
            from app.services.account_pair_eligibility_service import AccountPairEligibilityService

            reg = self.session.exec(
                select(StrategyRegistry).where(StrategyRegistry.strategy_id == row.get("strategy_id"))
            ).first()
            symbols = (reg.symbols if reg else None) or []
            if not isinstance(symbols, list):
                symbols = [str(symbols)]
            tradeable = AccountPairEligibilityService(self.session, self.config).filter_tradeable_symbols(
                symbols, strategy_id=row.get("strategy_id", "")
            )
            for sym in tradeable[:4]:
                if evaluated >= max_evaluate:
                    break
                evaluated += 1
                u_row = next((x for x in universe if x.get("symbol") == sym), None)
                fresh = self.bar.check(sym)
                if not fresh.get("executable"):
                    reason_counts["data_stale"] += 1
                    skipped_count += 1
                    continue

                push_signals += 1
                candidates_created += 1
                ev = self.pl.evaluate(row["strategy_id"], sym, side="buy")
                decisions_out.append(ev)
                rc = ev.get("reason_code") or "unknown"
                if ev.get("decision") == "approved":
                    approved_count += 1
                    from sqlmodel import select as sel
                    from app.database import PaperExperimentDecision

                    dec_row = self.session.exec(
                        sel(PaperExperimentDecision)
                        .where(PaperExperimentDecision.strategy_id == row["strategy_id"])
                        .order_by(PaperExperimentDecision.created_at.desc())
                    ).first()
                    if dec_row:
                        ex = self.training.execute_approved_decision(dec_row.id)
                        if ex.get("submitted"):
                            order_count += 1
                        decisions_out.append({"execute": ex})
                    break
                else:
                    skipped_count += 1
                    if rc in ("spread_check",):
                        reason_counts["spread_too_wide"] += 1
                    elif rc in ("account_pair_eligibility",):
                        reason_counts["quote_currency_unfunded"] += 1
                    elif rc in ("duplicate_buy",):
                        reason_counts["duplicate_buy"] += 1
                    elif rc in ("no_stop_loss", "not_eligible", "mode_disabled"):
                        reason_counts["no_push_signal"] += 1
                    else:
                        reason_counts[rc] += 1
                if approved_count > 0:
                    break
            if approved_count > 0:
                break

        if not eligible_strats and universe:
            reason_counts["no_eligible_strategy"] += 1
        if push_signals == 0 and not reason_counts:
            reason_counts["no_push_signal"] = len(active) or len(universe)

        plain = _plain_tick_summary(
            symbols_scanned=len(universe),
            active=len(active),
            blocked=len(blocked),
            push_signals=push_signals,
            approved=approved_count,
            skipped=skipped_count,
            orders=order_count,
            reasons=reason_counts,
        )

        return {
            "symbols_scanned_count": len(universe),
            "active_symbols_count": len(active),
            "blocked_symbols_count": len(blocked),
            "watch_only_count": len(watch),
            "push_signals_found": push_signals,
            "candidates_created": candidates_created,
            "approved_count": approved_count,
            "skipped_count": skipped_count,
            "order_count": order_count,
            "reason_breakdown": dict(reason_counts),
            "plain_summary": plain,
            "result": "order_placed" if order_count else ("approved_pending" if approved_count else "no_approved_candidate"),
            "decisions": decisions_out,
            "universe_sample": universe[:25],
        }


def _plain_tick_summary(
    *,
    symbols_scanned: int,
    active: int,
    blocked: int,
    push_signals: int,
    approved: int,
    skipped: int,
    orders: int,
    reasons: Counter,
) -> str:
    if orders:
        return f"Scanned {symbols_scanned} symbols — paper order submitted ({orders})."
    if approved:
        return f"Scanned {symbols_scanned} symbols — entry approved, awaiting fill."
    parts = []
    label_map = {
        "no_push_signal": "no push signal",
        "spread_too_wide": "spread too wide",
        "quote_currency_unfunded": "quote currency unfunded",
        "data_stale": "stale data",
        "duplicate_buy": "duplicate buy protection",
        "blocked_other": "blocked",
        "no_eligible_strategy": "no eligible strategy",
    }
    for code, n in reasons.most_common(8):
        parts.append(f"{n} {label_map.get(code, code.replace('_', ' '))}")
    detail = ", ".join(parts) if parts else "no stronger entry this tick"
    return f"Scanned {symbols_scanned} symbols ({active} active, {blocked} blocked). No approved candidate: {detail}."
