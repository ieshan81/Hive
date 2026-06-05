"""Push-pull tick scan — universe → score → signal → eligibility → order."""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from sqlmodel import Session

from app.services.aggressive_paper_learning_service import AggressivePaperLearningService
from app.services.bar_freshness_service import BarFreshnessService
from app.services.config_manager import ConfigManager
from app.services.push_pull_scoring_service import score_active_universe
from app.services.push_pull_strategy_seed import ensure_crypto_push_pull_baseline
from app.services.quote_freshness_service import QuoteFreshnessService
from app.services.training_execution_service import TrainingExecutionService
from app.services.universe_builder import build_merged_universe


class PushPullScanService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.pl = AggressivePaperLearningService(session)
        self.training = TrainingExecutionService(session, self.config)
        self.bar = BarFreshnessService(session, self.config)
        self.quote = QuoteFreshnessService(session, self.config)

    def run_tick_scan(self, *, max_evaluate: int | None = None) -> dict[str, Any]:
        """Full push-pull scan — trade every entry_allowed symbol (no shortlist cap)."""
        from app.services.scan_limits import scan_limit, slice_limit

        ensure_crypto_push_pull_baseline(self.session, self.config)

        universe_limit = scan_limit(self.config, "universe.max_scanned_symbols_per_cycle", 0)
        if max_evaluate is None:
            max_evaluate = scan_limit(self.config, "universe.max_scanned_symbols_per_cycle", 0)

        universe = build_merged_universe(self.session, self.config, limit=universe_limit, lightweight=True)
        reason_counts: Counter[str] = Counter()
        candidates_created = 0
        approved_count = 0
        skipped_count = 0
        order_count = 0
        push_signals = 0
        decisions_out: list[dict] = []
        fresh_bar_count = 0
        stale_bar_count = 0
        fresh_quote_count = 0
        stale_quote_count = 0
        quote_refresh_attempts = 0

        active = [u for u in universe if u.get("status") == "Active"]
        blocked = [u for u in universe if u.get("status") == "Blocked"]
        watch = [u for u in universe if u.get("status") == "Watch-only"]

        for u in universe:
            if u.get("bar_freshness") == "fresh":
                fresh_bar_count += 1
            elif u.get("bar_freshness") == "stale":
                stale_bar_count += 1
            qf = u.get("quote_freshness")
            if qf == "fresh":
                fresh_quote_count += 1
            elif qf == "stale":
                stale_quote_count += 1

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

        scoring = score_active_universe(self.session, self.config, universe=universe)
        from app.services.cycle_context import current_cycle_run_id

        cycle_run_id = current_cycle_run_id.get()

        # Exits first — SL/TP/loss band before new entries
        try:
            self.training.monitor_exits()
        except Exception:
            pass

        for code, n in (scoring.get("no_trade_reason_breakdown") or {}).items():
            reason_counts[code.lower()] += int(n)

        scan = self.pl.scan_experiment_eligibility()
        eligible_strats = scan.get("eligible") or []
        eligible_strategy_count = len(eligible_strats)
        eligible_by_asset: dict[str, dict] = {}
        for row in eligible_strats:
            asset = str(row.get("asset_class") or "").lower()
            sid = str(row.get("strategy_id") or "")
            if not asset:
                asset = "crypto" if sid.startswith("crypto_") else ("stock" if sid.startswith("stock_") else "")
            if asset in ("crypto", "stock") and asset not in eligible_by_asset:
                eligible_by_asset[asset] = row

        from app.services.activity_logger import log_activity

        log_activity(
            self.session,
            "strategy_eligibility_checked",
            f"Strategy eligibility: {eligible_strategy_count} paper-experiment strategies eligible",
            {
                "eligible_count": eligible_strategy_count,
                "eligible_ids": [r.get("strategy_id") for r in eligible_strats[:10]],
                "blocked_count": len(scan.get("blocked") or []),
                "scoring_model": scoring.get("scoring_model"),
            },
            commit=False,
        )

        ranked = scoring.get("scores") or []
        selected = scoring.get("selected_candidate")
        eligible_rows = [r for r in ranked if r.get("entry_allowed")]
        rows_to_trade = slice_limit(eligible_rows, max_evaluate)

        shadow_pass = self._run_shadow_observer_pass(
            ranked=ranked,
            eligible_strats=eligible_strats,
            cycle_run_id=cycle_run_id,
        )
        shadow_created = int(shadow_pass.get("shadow_trades_created") or 0)
        shadow_observed = int(shadow_pass.get("shadow_setups_observed") or 0)
        shadow_errors = int(shadow_pass.get("shadow_errors") or 0)
        shadow_diagnostics = shadow_pass.get("shadow_diagnostics") or {}

        evaluated = 0
        for row_score in rows_to_trade:
            sym = row_score.get("symbol")
            if not sym:
                continue
            evaluated += 1
            asset_class = str(row_score.get("asset_class") or ("crypto" if "/" in sym else "stock")).lower()
            strategy_row = eligible_by_asset.get(asset_class) or (eligible_strats[0] if eligible_strats else None)
            strategy_id = (strategy_row or {}).get("strategy_id")
            if not strategy_id:
                skipped_count += 1
                reason_counts[f"no_{asset_class}_strategy"] += 1
                decisions_out.append({"score": row_score, "decision": "skipped", "reason": f"no_{asset_class}_strategy"})
                continue
            push_signals += 1
            candidates_created += 1

            fresh = self.bar.check(sym, allow_fetch=True)
            if not fresh.get("executable") and row_score.get("entry_allowed"):
                fresh = {"executable": True, "bar_freshness": row_score.get("bar_freshness", "fresh")}
            if not fresh.get("executable"):
                reason_counts["data_stale"] += 1
                skipped_count += 1
                continue

            from app.services.entry_quality_decision_service import EntryQualityDecisionService

            quality_decision = EntryQualityDecisionService(self.session, self.config).decide(row_score)
            ev = self.pl.evaluate(strategy_id, sym, side="buy", signal_meta={**row_score, "entry_quality_decision": quality_decision})
            ev = {**ev, "live_score": row_score, "entry_quality_decision": quality_decision}
            decisions_out.append(ev)
            rc = ev.get("reason_code") or "unknown"
            paper_submitted = False
            paper_blocked_reason: str | None = None
            if ev.get("decision") == "approved":
                approved_count += 1
                from sqlmodel import select as sel
                from app.database import PaperExperimentDecision

                dec_row = self.session.exec(
                    sel(PaperExperimentDecision)
                    .where(
                        PaperExperimentDecision.strategy_id == strategy_id,
                        PaperExperimentDecision.symbol == sym,
                        PaperExperimentDecision.decision == "approved",
                    )
                    .order_by(PaperExperimentDecision.created_at.desc())
                ).first()
                if dec_row:
                    ex = self.training.execute_approved_decision(dec_row.id)
                    quote_refresh_attempts += 1 if ex.get("quote_refreshed") else 0
                    if ex.get("submitted"):
                        order_count += 1
                        paper_submitted = True
                    else:
                        paper_blocked_reason = str(ex.get("reject_reason") or ex.get("human_reason") or "paper_not_submitted")
                    if ex.get("reject_reason") == "STALE_QUOTE":
                        reason_counts["stale_quote_after_refresh"] += 1
                    elif ex.get("reject_reason"):
                        reason_counts[str(ex.get("reject_reason")).lower()] += 1
                    decisions_out.append({"execute": ex, "score": row_score})
            else:
                paper_blocked_reason = rc or row_score.get("no_trade_reason")
                from app.services.autopilot_decision_classifier import classify_block_reason

                skipped_count += 1
                if rc in ("spread_check",):
                    reason_counts["spread_too_wide"] += 1
                elif rc in ("account_pair_eligibility",):
                    reason_counts["quote_currency_unfunded"] += 1
                elif rc in ("duplicate_buy",):
                    reason_counts["duplicate_buy"] += 1
                elif rc in ("data_stale",):
                    reason_counts["data_stale"] += 1
                elif rc in ("no_stop_loss", "not_eligible", "mode_disabled"):
                    reason_counts["allocator_block"] += 1
                else:
                    reason_counts[rc] += 1
                ev.update(
                    {
                        **classify_block_reason(rc),
                        "next_candidate_considered": True,
                    }
                )

        if eligible_strategy_count == 0:
            reason_counts["no_eligible_strategy"] += 1
        if push_signals == 0 and not reason_counts:
            reason_counts["no_push_signal"] = len(active) or len(universe)

        top = ranked[0] if ranked else None
        plain = _plain_tick_summary(
            symbols_scanned=len(universe),
            active=len(active),
            blocked=len(blocked),
            fresh=fresh_bar_count,
            stale=stale_bar_count,
            eligible_strats=eligible_strategy_count,
            push_signals=push_signals,
            approved=approved_count,
            skipped=skipped_count,
            orders=order_count,
            reasons=reason_counts,
            top_symbol=top.get("symbol") if top else None,
            top_score=top.get("trade_quality_score") if top else None,
            selected=selected,
        )

        return {
            "symbols_scanned_count": len(universe),
            "fresh_bar_count": fresh_bar_count,
            "stale_bar_count": stale_bar_count,
            "fresh_quote_count": fresh_quote_count,
            "stale_quote_count": stale_quote_count,
            "quote_refresh_attempts": quote_refresh_attempts,
            "eligible_strategy_count": eligible_strategy_count,
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
            "scoring_model": scoring.get("scoring_model"),
            "strategy_version": scoring.get("strategy_version"),
            "push_pull_scores": ranked,
            "selected_candidate": selected,
            "rejected_candidates": scoring.get("rejected_candidates"),
            "no_trade_reason_breakdown": scoring.get("no_trade_reason_breakdown"),
            "top_candidate": top,
            "threshold_values": scoring.get("threshold_values"),
            "shadow_trades_created": shadow_created,
            "shadow_setups_observed": shadow_observed,
            "shadow_errors": shadow_errors,
            "shadow_diagnostics": shadow_diagnostics,
        }

    def _run_shadow_observer_pass(
        self,
        *,
        ranked: list[dict],
        eligible_strats: list[dict],
        cycle_run_id: Optional[str],
    ) -> dict[str, Any]:
        """Score all ranked setups through shadow observer (not only entry_allowed paper rows)."""
        from collections import Counter as _Counter

        from app.services.activity_logger import log_activity
        from app.services.shadow_floor_utils import quality_on_shadow_scale
        from app.services.shadow_outcome_service import ShadowOutcomeService
        from app.services.shadow_tick_diagnostics import build_shadow_tick_diagnostics, record_near_miss
        from app.services.shadow_trade_service import ShadowTradeService, shadow_league_enabled

        shadow_created = 0
        shadow_observed = 0
        shadow_errors = 0
        shadow_attempts = 0
        rows_scored = 0
        rows_above_obs = 0
        rows_above_shadow = 0
        max_quality = 0.0
        quality_scale = "0_1"
        near_misses: list[dict] = []
        skip_counts: _Counter[str] = _Counter()
        eligible_by_asset: dict[str, dict] = {}
        for row in eligible_strats:
            asset = str(row.get("asset_class") or "").lower()
            sid = str(row.get("strategy_id") or "")
            if not asset:
                asset = "crypto" if sid.startswith("crypto_") else ("stock" if sid.startswith("stock_") else "")
            if asset in ("crypto", "stock") and asset not in eligible_by_asset:
                eligible_by_asset[asset] = row

        if not shadow_league_enabled(self.config):
            diag = build_shadow_tick_diagnostics(
                self.config,
                rows_scored=0,
                rows_above_observation_floor=0,
                rows_above_shadow_floor=0,
                max_setup_quality=0.0,
                quality_scale=quality_scale,
                shadow_attempts=0,
                shadow_observations_created=0,
                shadow_trades_created=0,
                shadow_errors=0,
                near_misses=[],
                skip_reason_counts={"shadow_disabled": 1},
            )
            return {
                "shadow_trades_created": 0,
                "shadow_setups_observed": 0,
                "shadow_errors": 0,
                "shadow_diagnostics": diag,
            }

        svc = ShadowTradeService(self.session, self.config)
        price_map: dict[str, float] = {}
        for row_score in ranked:
            sym = row_score.get("symbol")
            if not sym:
                continue
            ref = row_score.get("mid_price") or row_score.get("last_price")
            if ref is not None:
                price_map[sym] = float(ref)
        try:
            ShadowOutcomeService(self.session, self.config).update_open_trades(price_by_symbol=price_map)
        except Exception:
            pass

        for row_score in ranked:
            sym = row_score.get("symbol")
            if not sym:
                continue
            rows_scored += 1
            q, obs_floor, shadow_floor, quality_scale = quality_on_shadow_scale(
                float(row_score.get("trade_quality_score") or 0), self.config
            )
            max_quality = max(max_quality, q)
            if q >= obs_floor:
                rows_above_obs += 1
            if q >= shadow_floor:
                rows_above_shadow += 1

            asset_class = str(row_score.get("asset_class") or ("crypto" if "/" in sym else "stock")).lower()
            strategy_row = eligible_by_asset.get(asset_class) or (eligible_strats[0] if eligible_strats else None)
            strategy_id = (strategy_row or {}).get("strategy_id")
            blocker = (
                row_score.get("no_trade_reason")
                or row_score.get("alpha_candidate_gate")
                or ("entry_allowed" if row_score.get("entry_allowed") else "entry_not_allowed")
            )
            if not strategy_id:
                skip_counts["no_strategy"] += 1
                record_near_miss(
                    near_misses,
                    symbol=sym,
                    quality=q,
                    obs_floor=obs_floor,
                    shadow_floor=shadow_floor,
                    blocker=str(blocker),
                    shadow_skip_reason="no_strategy",
                )
                continue

            shadow_attempts += 1
            paper_blocked = (
                row_score.get("no_trade_reason")
                or row_score.get("alpha_candidate_gate")
                or (None if row_score.get("entry_allowed") else "entry_not_allowed")
            )
            try:
                shadow_res = svc.consider_setup(
                    row_score,
                    strategy_id=strategy_id,
                    paper_blocked_reason=str(paper_blocked) if paper_blocked else None,
                    paper_submitted=False,
                    cycle_run_id=cycle_run_id,
                )
                skip = str(shadow_res.get("shadow_skip_reason") or (shadow_res.get("shadow_trade") or {}).get("reason") or "unknown")
                skip_counts[skip] += 1
                if shadow_res.get("observation"):
                    shadow_observed += 1
                else:
                    record_near_miss(
                        near_misses,
                        symbol=sym,
                        quality=q,
                        obs_floor=obs_floor,
                        shadow_floor=shadow_floor,
                        blocker=str(blocker),
                        shadow_skip_reason=skip,
                    )
                st = shadow_res.get("shadow_trade") or {}
                if st.get("shadow_trade_id") and st.get("status") not in ("skipped", "exists"):
                    shadow_created += 1
            except Exception as exc:
                shadow_errors += 1
                skip_counts["exception"] += 1
                log_activity(
                    self.session,
                    "shadow_league_error",
                    f"Shadow league hook failed for {sym}",
                    {"symbol": sym, "error": type(exc).__name__, "message": str(exc)[:200]},
                    commit=False,
                )
                record_near_miss(
                    near_misses,
                    symbol=sym,
                    quality=q,
                    obs_floor=obs_floor,
                    shadow_floor=shadow_floor,
                    blocker=str(blocker),
                    shadow_skip_reason="exception",
                )

        near_misses.sort(key=lambda m: float(m.get("quality") or 0), reverse=True)
        diag = build_shadow_tick_diagnostics(
            self.config,
            rows_scored=rows_scored,
            rows_above_observation_floor=rows_above_obs,
            rows_above_shadow_floor=rows_above_shadow,
            max_setup_quality=max_quality,
            quality_scale=quality_scale,
            shadow_attempts=shadow_attempts,
            shadow_observations_created=shadow_observed,
            shadow_trades_created=shadow_created,
            shadow_errors=shadow_errors,
            near_misses=near_misses,
            skip_reason_counts=dict(skip_counts),
        )
        return {
            "shadow_trades_created": shadow_created,
            "shadow_setups_observed": shadow_observed,
            "shadow_errors": shadow_errors,
            "shadow_diagnostics": diag,
        }


def _plain_tick_summary(
    *,
    symbols_scanned: int,
    active: int,
    blocked: int,
    fresh: int,
    stale: int,
    eligible_strats: int,
    push_signals: int,
    approved: int,
    skipped: int,
    orders: int,
    reasons: Counter,
    top_symbol: Optional[str] = None,
    top_score: Optional[float] = None,
    selected: Optional[dict] = None,
) -> str:
    score_note = ""
    if top_symbol and top_score is not None:
        score_note = f" Top scored {top_symbol} (quality {top_score:.2f})."
    label_map = {
        "no_push_signal": "no push signal",
        "spread_too_wide": "spread too wide",
        "quote_currency_unfunded": "quote currency unfunded",
        "data_stale": "stale data",
        "duplicate_buy": "duplicate buy / open position",
        "blocked_other": "blocked",
        "no_eligible_strategy": "no eligible strategy",
        "no_edge_after_cost": "no edge after cost",
        "allocator_block": "allocator or validator block",
        "negative_edge_after_cost": "negative edge after cost",
        "no_stock_strategy": "no stock paper strategy",
        "no_crypto_strategy": "no crypto paper strategy",
        "adaptive_budget_blocked": "adaptive budget blocked",
        "risk_blocked": "risk blocked",
        "cooldown": "symbol/account cooldown",
        "missing_exit_plan": "missing exit plan",
    }
    if orders:
        return (
            f"Scanned {symbols_scanned} symbols ({fresh} fresh bars) — paper order submitted ({orders})."
            + score_note
        )
    if approved:
        # Approved by the portfolio gate but NO broker order was submitted — it was blocked
        # downstream at the execution cage/preflight. Do not imply a fill is pending.
        top_block = reasons.most_common(1)[0][0] if reasons else None
        block_note = (
            f" (blocked before submission: {label_map.get(top_block, top_block.replace('_', ' '))})"
            if top_block
            else " (no broker order submitted)"
        )
        return (
            f"Scanned {symbols_scanned} symbols ({fresh} fresh) — candidate passed gates but no order submitted{block_note}."
            + score_note
        )
    if selected and selected.get("symbol"):
        sel_reason = selected.get("no_trade_reason") or "gates passed but validator blocked"
        return (
            f"Scanned {symbols_scanned} symbols — best candidate {selected['symbol']} "
            f"(score {selected.get('trade_quality_score', 0):.2f}) skipped: {sel_reason}."
        )
    parts = []
    for code, n in reasons.most_common(8):
        parts.append(f"{n} {label_map.get(code, code.replace('_', ' '))}")
    detail = ", ".join(parts) if parts else "no stronger entry this tick"
    return (
        f"Scanned {symbols_scanned} symbols ({fresh} fresh, {stale} stale bars, "
        f"{eligible_strats} eligible strategies). No approved candidate: {detail}."
        + score_note
    )
