"""Paper canary order gate — shadow evidence → paper candidate → caged broker paper order.

PAPER ONLY. Live trading stays locked. Never bypasses alpha, cage, freshness, or duplicate guards.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import AlphaScorecard, PositionSnapshot, SettingsActionAudit, ShadowTrade
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService
from app.services.autonomous_alpha_promotion_service import PAPER_ALLOWED_VERDICTS, AutonomousAlphaPromotionService
from app.services.broker_safety import broker_base_url, is_paper_broker_url, live_lock_status
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch
from app.services.order_ledger_service import classify_asset
from app.services.research_cost_model import COST_MODEL_VERSION, round_trip_cost_pct
from app.services.shadow_league_constants import LEVEL_SHADOW_TRADE, STATUS_CLOSED

CANARY_COID_TAG = "CANARY"
CANARY_AUDIT_KEY = "paper_canary_audit"
EXCLUDED_EXIT_REASONS = frozenset({"missing_price_data", "max_open_cap_release", "missing_entry_price"})
INVALID_PRICE_SOURCES = frozenset({None, "", "missing", "entry_fallback"})
SUBMITTED_STATUSES = ("paper_order_submitted", "paper_order_filled", "paper_order_partially_filled")


def _norm(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").strip()


def _canary_cfg(config: dict) -> dict[str, Any]:
    sl = (config or {}).get("shadow_league") or {}
    return dict(sl.get("paper_canary") or {})


def _enabled(config: dict) -> bool:
    return bool(_canary_cfg(config).get("enabled", True))


def _validation_run_id(session: Session) -> str:
    return (get_latest_reset_epoch(session) or {}).get("validation_run_id") or PAPER_VALIDATION_RUN_ID


def is_qualified_shadow_close(row: ShadowTrade, config: Optional[dict] = None) -> tuple[bool, str]:
    """Single closed shadow trade qualifies as positive paper-canary evidence."""
    if row.status != STATUS_CLOSED:
        return False, "not_closed"
    if row.promotion_level < LEVEL_SHADOW_TRADE:
        return False, "below_shadow_trade_level"
    oj = row.outcome_json or {}
    ej = row.evidence_json or {}
    reason = str(oj.get("exit_reason") or "")
    if reason in EXCLUDED_EXIT_REASONS:
        return False, f"excluded_exit:{reason}"
    if ej.get("legacy") or oj.get("legacy"):
        return False, "legacy_shadow_close"
    entry = row.entry_reference_price
    exit_px = row.exit_reference_price
    if entry is None or exit_px is None or float(entry) <= 0 or float(exit_px) <= 0:
        return False, "missing_entry_or_exit_price"
    price_source = oj.get("price_source")
    if price_source in INVALID_PRICE_SOURCES:
        return False, "missing_price_source"
    min_hold = float(((config or {}).get("shadow_league") or {}).get("min_hold_seconds", 90))
    hold = float(oj.get("hold_seconds") or 0)
    if hold < min_hold:
        return False, "hold_below_minimum"
    if row.simulated_pnl_bps is None:
        return False, "missing_simulated_pnl"
    return True, "qualified"


def list_qualified_shadow_closes(session: Session, config: Optional[dict] = None) -> tuple[list[ShadowTrade], dict[str, Any]]:
    """All qualified closes for the active validation run, plus exclusion counts."""
    cfg = config or {}
    run_id = _validation_run_id(session)
    rows = list(
        session.exec(
            select(ShadowTrade).where(
                ShadowTrade.validation_run_id == run_id,
                ShadowTrade.status == STATUS_CLOSED,
                ShadowTrade.promotion_level >= LEVEL_SHADOW_TRADE,
            )
        ).all()
    )
    qualified: list[ShadowTrade] = []
    excluded_missing_price = 0
    excluded_cap_release = 0
    excluded_other: dict[str, int] = {}
    for r in rows:
        oj = r.outcome_json or {}
        reason = str(oj.get("exit_reason") or "")
        if reason == "missing_price_data":
            excluded_missing_price += 1
            continue
        if reason == "max_open_cap_release":
            excluded_cap_release += 1
            continue
        ok, why = is_qualified_shadow_close(r, cfg)
        if ok:
            qualified.append(r)
        else:
            excluded_other[why] = excluded_other.get(why, 0) + 1
    return qualified, {
        "validation_run_id": run_id,
        "total_closed": len(rows),
        "qualified_count": len(qualified),
        "excluded_missing_price": excluded_missing_price,
        "excluded_cap_release": excluded_cap_release,
        "excluded_other": excluded_other,
    }


def _pnl_after_cost_bps(row: ShadowTrade, config: dict) -> float:
    raw = float(row.simulated_pnl_bps or 0)
    cm = round_trip_cost_pct(row.symbol, config)
    return raw - float(cm.get("round_trip_bps") or 0)


def compute_aggregate_metrics(closes: list[ShadowTrade], config: dict) -> dict[str, Any]:
    pnls = [_pnl_after_cost_bps(r, config) for r in closes]
    wins = [p for p in pnls if p > 0.5]
    losses = [abs(p) for p in pnls if p < -0.5]
    zero_pnl = sum(1 for p in pnls if abs(p) < 0.5)
    gross_win = sum(wins)
    gross_loss = sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    win_rate = (len(wins) / len(closes)) if closes else 0.0
    avg_pnl = (sum(pnls) / len(pnls)) if pnls else 0.0
    return {
        "qualified_closes": len(closes),
        "avg_pnl_bps_after_cost": round(avg_pnl, 2),
        "profit_factor": round(pf, 3),
        "win_rate": round(win_rate, 4),
        "zero_pnl_count": zero_pnl,
        "zero_pnl_fraction": round(zero_pnl / len(closes), 4) if closes else 0.0,
        "wins": len(wins),
        "losses": len([p for p in pnls if p < -0.5]),
    }


def evaluate_aggregate_gate(metrics: dict[str, Any], config: dict) -> dict[str, Any]:
    cc = _canary_cfg(config)
    min_closes = int(cc.get("min_qualified_closes", 30))
    min_pf = float(cc.get("min_profit_factor", 1.10))
    min_wr = float(cc.get("min_win_rate", 0.45))
    min_avg = float(cc.get("min_avg_pnl_bps_after_cost", 0.0))
    max_zero_frac = float(cc.get("max_zero_pnl_fraction", 0.50))
    failures: list[str] = []
    n = int(metrics.get("qualified_closes") or 0)
    if n < min_closes:
        failures.append(f"need_{min_closes}_qualified_closes_have_{n}")
    if float(metrics.get("avg_pnl_bps_after_cost") or 0) <= min_avg:
        failures.append("avg_pnl_bps_after_cost_not_positive")
    if float(metrics.get("profit_factor") or 0) < min_pf:
        failures.append("profit_factor_below_threshold")
    if float(metrics.get("win_rate") or 0) < min_wr:
        failures.append("win_rate_below_threshold")
    if float(metrics.get("zero_pnl_fraction") or 0) > max_zero_frac:
        failures.append("zero_pnl_dominates")
    passed = not failures
    return {
        "aggregate_gate_passed": passed,
        "gate_failures": failures,
        "thresholds": {
            "min_qualified_closes": min_closes,
            "min_profit_factor": min_pf,
            "min_win_rate": min_wr,
            "min_avg_pnl_bps_after_cost": min_avg,
            "max_zero_pnl_fraction": max_zero_frac,
        },
    }


def _best_symbol_group(closes: list[ShadowTrade], config: dict) -> Optional[dict[str, Any]]:
    """Pick symbol+strategy with strongest qualified shadow track record."""
    buckets: dict[tuple[str, str], list[ShadowTrade]] = {}
    for r in closes:
        sid = str(r.strategy_id or "crypto_push_pull_baseline")
        buckets.setdefault((r.symbol, sid), []).append(r)
    if not buckets:
        return None
    ranked = []
    for (sym, sid), grp in buckets.items():
        m = compute_aggregate_metrics(grp, config)
        gate = evaluate_aggregate_gate(m, config)
        ranked.append({
            "symbol": sym,
            "strategy_id": sid,
            "asset_class": r.asset_class if (r := grp[0]) else classify_asset(sym),
            "metrics": m,
            "per_symbol_gate_passed": gate["aggregate_gate_passed"],
            "score": float(m.get("avg_pnl_bps_after_cost") or 0) * float(m.get("profit_factor") or 0),
        })
    ranked.sort(key=lambda x: (x["per_symbol_gate_passed"], x["score"]), reverse=True)
    return ranked[0] if ranked else None


class PaperCanaryGateService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.promotion = AutonomousAlphaPromotionService(session, self.config)
        self.alpha = AutonomousAlphaFactoryService(session, self.config)

    def evaluate_and_promote(self, *, operator: str = "paper_canary") -> dict[str, Any]:
        """Shadow qualified closes → paper_candidate scorecard when aggregate gate passes."""
        if not _enabled(self.config):
            return {"status": "skipped", "reason": "paper_canary_disabled", "orders_created": 0}
        qualified, exclusion = list_qualified_shadow_closes(self.session, self.config)
        metrics = compute_aggregate_metrics(qualified, self.config)
        gate = evaluate_aggregate_gate(metrics, self.config)
        best = _best_symbol_group(qualified, self.config) if gate["aggregate_gate_passed"] else None
        promoted = False
        candidate_symbol: Optional[str] = None
        if best and best.get("per_symbol_gate_passed"):
            promoted = self._upsert_scorecard_from_shadow(best["symbol"], best["strategy_id"], metrics, best["metrics"])
            candidate_symbol = best["symbol"]
        audit = self._build_audit(
            qualified=qualified,
            exclusion=exclusion,
            metrics=metrics,
            gate=gate,
            best=best,
            promoted=promoted,
            candidate_symbol=candidate_symbol,
            order_result=None,
        )
        self._persist_audit(audit, operator=operator)
        return {
            "status": "ok",
            "aggregate_gate_passed": gate["aggregate_gate_passed"],
            "paper_candidate_promoted": promoted,
            "candidate_symbol": candidate_symbol,
            "metrics": metrics,
            "exclusion": exclusion,
            "gate": gate,
            "audit": audit,
            "orders_created": 0,
        }

    def _upsert_scorecard_from_shadow(
        self,
        symbol: str,
        strategy_id: str,
        aggregate_metrics: dict[str, Any],
        symbol_metrics: dict[str, Any],
    ) -> bool:
        family = self.alpha._family_for(strategy_id)
        row = self.alpha._find_scorecard(symbol, strategy_id=strategy_id)
        n = int(symbol_metrics.get("qualified_closes") or aggregate_metrics.get("qualified_closes") or 0)
        wr = float(symbol_metrics.get("win_rate") or 0)
        pf = float(symbol_metrics.get("profit_factor") or 0)
        avg_bps = float(symbol_metrics.get("avg_pnl_bps_after_cost") or 0)
        expectancy = avg_bps / 10000.0
        cm = round_trip_cost_pct(symbol, self.config)
        if not row:
            row = AlphaScorecard(
                symbol=symbol,
                normalized_symbol=_norm(symbol),
                asset_class=classify_asset(symbol) if classify_asset(symbol) != "unknown" else "crypto",
                strategy_family=family,
                strategy_id=strategy_id,
            )
        row.sample_size = n
        row.backtest_count = max(int(row.backtest_count or 0), 1)
        row.win_rate = wr
        row.profit_factor = pf
        row.expectancy = expectancy
        row.edge_after_cost_bps = avg_bps
        row.cost_bps = cm.get("round_trip_bps")
        row.data_freshness_status = row.data_freshness_status or "unknown"
        row.scorecard_json = {
            **(row.scorecard_json or {}),
            "shadow_canary_source": True,
            "shadow_evidence_closes": n,
            "aggregate_metrics": aggregate_metrics,
            "symbol_metrics": symbol_metrics,
            "cost_model_version": COST_MODEL_VERSION,
        }
        row.promotion_reason = (
            f"Paper canary: {n} qualified shadow closes with PF {pf:.2f}, "
            f"win rate {wr * 100:.1f}%, avg after-cost {avg_bps:.1f} bps."
        )
        row.blocker_reasons_json = []
        row.verdict = "paper_candidate"
        row.current_stage = "paper_candidate"
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        self.promotion._sync_registry(row)
        self.session.flush()
        return True

    def status(self) -> dict[str, Any]:
        qualified, exclusion = list_qualified_shadow_closes(self.session, self.config)
        metrics = compute_aggregate_metrics(qualified, self.config)
        gate = evaluate_aggregate_gate(metrics, self.config)
        best = _best_symbol_group(qualified, self.config)
        cards = list(
            self.session.exec(
                select(AlphaScorecard).where(AlphaScorecard.verdict.in_(tuple(PAPER_ALLOWED_VERDICTS)))
            ).all()
        )
        shadow_candidates = [c for c in cards if (c.scorecard_json or {}).get("shadow_canary_source")]
        last_audit = self._load_last_audit()
        open_positions = int(
            self.session.exec(
                select(func.count()).select_from(PositionSnapshot).where(PositionSnapshot.qty > 0)
            ).one()
            or 0
        )
        return {
            "status": "ok",
            "paper_canary_enabled": _enabled(self.config),
            "aggregate_gate_passed": gate["aggregate_gate_passed"],
            "gate_failures": gate.get("gate_failures") or [],
            "metrics": metrics,
            "exclusion": exclusion,
            "best_shadow_symbol": (best or {}).get("symbol"),
            "best_shadow_strategy_id": (best or {}).get("strategy_id"),
            "shadow_paper_candidate_count": len(shadow_candidates),
            "paper_candidate_symbols": [c.symbol for c in shadow_candidates[:10]],
            "open_positions": open_positions,
            "max_open_positions": int(_canary_cfg(self.config).get("max_open_positions", 1)),
            "max_new_orders_per_tick": int(_canary_cfg(self.config).get("max_new_orders_per_tick", 1)),
            "crypto_only": bool(_canary_cfg(self.config).get("crypto_only", True)),
            "block_stock_broker_entries": bool(_canary_cfg(self.config).get("block_stock_broker_entries", True)),
            "last_audit": last_audit,
            "live_trading_locked": True,
            "broker_mode": "paper" if is_paper_broker_url() else "live_or_unknown",
            "broker_base_url": broker_base_url(),
            **live_lock_status(self.config),
        }

    def try_submit_canary_order(self, *, operator: str = "paper_canary", cycle_run_id: Optional[str] = None) -> dict[str, Any]:
        """At most one tiny crypto paper order per tick when all gates pass."""
        if not _enabled(self.config):
            return self._blocked("paper_canary_disabled", operator=operator)
        if not is_paper_broker_url():
            return self._blocked("broker_not_paper", operator=operator)
        if bool(cfg_get(self.config, "execution.live_orders_enabled", False)):
            return self._blocked("live_orders_must_stay_off", operator=operator)
        if not bool(cfg_get(self.config, "execution.paper_orders_enabled", False)):
            return self._blocked("paper_orders_disabled", operator=operator)
        if self._orders_this_tick() >= int(_canary_cfg(self.config).get("max_new_orders_per_tick", 1)):
            return self._blocked("max_new_orders_per_tick", operator=operator)
        open_n = int(
            self.session.exec(
                select(func.count()).select_from(PositionSnapshot).where(PositionSnapshot.qty > 0)
            ).one()
            or 0
        )
        if open_n >= int(_canary_cfg(self.config).get("max_open_positions", 1)):
            return self._blocked("max_open_positions", operator=operator, open_positions=open_n)

        promo = self.evaluate_and_promote(operator=operator)
        if not promo.get("aggregate_gate_passed"):
            return self._blocked(
                "aggregate_gate_failed",
                operator=operator,
                gate_failures=promo.get("gate", {}).get("gate_failures"),
                audit=promo.get("audit"),
            )
        sym = promo.get("candidate_symbol")
        if not sym:
            return self._blocked("no_candidate_symbol", operator=operator, audit=promo.get("audit"))
        if bool(_canary_cfg(self.config).get("crypto_only", True)) and classify_asset(sym) != "crypto":
            return self._blocked("crypto_only", operator=operator, symbol=sym)
        if bool(_canary_cfg(self.config).get("block_stock_broker_entries", True)) and classify_asset(sym) == "stock":
            return self._blocked("stock_broker_blocked", operator=operator, symbol=sym)

        strategy_id = (promo.get("audit") or {}).get("candidate_strategy_id") or "crypto_push_pull_baseline"
        alpha_gate = self.alpha.can_trade_paper(sym, strategy_id=strategy_id)
        if not alpha_gate.get("allowed"):
            return self._blocked(
                alpha_gate.get("reason") or "alpha_not_ready",
                operator=operator,
                symbol=sym,
                alpha_gate=alpha_gate,
            )

        try:
            from app.services.exposure_truth_service import ExposureTruthService

            dupe = ExposureTruthService(self.session, self.config).duplicate_buy_decision(sym)
            if dupe.get("blocked"):
                return self._blocked("duplicate_buy", operator=operator, symbol=sym, exposure=dupe)
        except Exception:
            pass

        try:
            from app.services.quote_freshness_service import QuoteFreshnessService

            chk = QuoteFreshnessService(self.session, self.config).check(sym, asset_class="crypto")
            if not chk.get("fresh"):
                return self._blocked("quote_not_fresh", operator=operator, symbol=sym, quote=chk)
        except Exception as exc:
            return self._blocked(f"freshness_check_error:{type(exc).__name__}", operator=operator, symbol=sym)

        from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
        from app.services.portfolio_gate import ApprovedCandidate
        from app.services.paper_execution_service import PaperExecutionService
        from app.services.cycle_context import current_cycle_run_id

        alpaca = AlpacaAdapter(self.session)
        account = alpaca.get_account()
        equity = float(getattr(account, "equity", 0) or getattr(account, "portfolio_value", 0) or 200)
        max_pct = float(_canary_cfg(self.config).get("max_notional_pct_equity", 5.0))
        cap_usd = max(1.0, equity * (max_pct / 100.0))
        quote = alpaca.get_quote(normalize_crypto_symbol(sym), "crypto") or {}
        px = float(quote.get("mid") or quote.get("ask") or 0)
        if px <= 0:
            return self._blocked("no_quote_price", operator=operator, symbol=sym)
        notional = min(cap_usd, cap_usd)
        qty = notional / px
        stop_pct = 0.01
        stop_loss = round(px * (1 - stop_pct), 8)
        take_profit = round(px * (1 + stop_pct * 1.5), 8)
        coid = f"{CANARY_COID_TAG}-{_norm(sym)}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        cand = ApprovedCandidate(
            signal_id=0,
            symbol=sym,
            side="buy",
            signal_type="entry",
            meta={
                "paper_canary_probe": True,
                "strategy_id": strategy_id,
                "client_order_id": coid,
                "dynamic_exit_levels": {
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "invalidation_price": stop_loss,
                },
                "cost_model_version": COST_MODEL_VERSION,
                "shadow_canary_source": True,
            },
            strength=0.5,
            confidence=0.5,
            position_qty=qty,
            entry_price=px,
            stop_loss=stop_loss,
            tier="TIER_ALT",
            sizing_evidence={"paper_canary_max_notional_usd": round(notional, 4), "equity_pct_cap": max_pct},
        )
        run_id = cycle_run_id or current_cycle_run_id.get() or f"canary-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        positions = list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
        paper = PaperExecutionService(self.session, self.config)
        log_row = paper.submit_candidate(
            cand,
            cycle_run_id=run_id,
            portfolio_decision=None,
            account=account,
            positions=positions,
            open_order_symbols=set(),
        )
        submitted = str(getattr(log_row, "status", "") or "") in SUBMITTED_STATUSES
        cage_passed = str(getattr(log_row, "status", "")) not in ("preflight_blocked", "paper_order_rejected")
        result = {
            "status": "ok" if submitted else "blocked",
            "submitted": submitted,
            "symbol": sym,
            "gate_result": "passed" if cage_passed else "blocked",
            "broker_result": getattr(log_row, "status", None),
            "reject_reason": getattr(log_row, "reject_reason", None),
            "notional_usd": round(qty * px, 4),
            "risk_pct_equity_cap": max_pct,
            "human_reason": getattr(log_row, "human_reason", None) or getattr(log_row, "reject_reason", None),
            "orders_created": 1 if submitted else 0,
            "live_trading_locked": True,
            "broker_mode": "paper",
        }
        audit = self._build_audit(
            qualified=[],
            exclusion=promo.get("exclusion") or {},
            metrics=promo.get("metrics") or {},
            gate=promo.get("gate") or {},
            best=None,
            promoted=True,
            candidate_symbol=sym,
            order_result=result,
            candidate_strategy_id=strategy_id,
        )
        audit["alpha_gate"] = alpha_gate
        self._persist_audit(audit, operator=operator)
        self._mark_tick_order_attempt()
        return {**result, "audit": audit}

    def run_tick_phase(self, *, operator: str = "cron", cycle_run_id: Optional[str] = None) -> dict[str, Any]:
        """Promote from shadow then attempt one canary order (paper-only)."""
        promo = self.evaluate_and_promote(operator=operator)
        if not promo.get("aggregate_gate_passed"):
            return {**promo, "order_attempted": False, "order_submitted": False}
        order = self.try_submit_canary_order(operator=operator, cycle_run_id=cycle_run_id)
        return {
            **promo,
            "order_attempted": True,
            "order_submitted": bool(order.get("submitted")),
            "order": order,
        }

    def build_bundle_audit(self) -> dict[str, Any]:
        return self._load_last_audit() or self.status()

    def _blocked(self, reason: str, *, operator: str, **extra: Any) -> dict[str, Any]:
        out = {
            "status": "blocked",
            "submitted": False,
            "gate_result": "blocked",
            "block_reason": reason,
            "orders_created": 0,
            "live_trading_locked": True,
            "broker_mode": "paper" if is_paper_broker_url() else "unknown",
            **extra,
        }
        audit = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "gate_result": "blocked",
            "block_reason": reason,
            **extra,
        }
        self._persist_audit(audit, operator=operator)
        return out

    def _build_audit(
        self,
        *,
        qualified: list[ShadowTrade],
        exclusion: dict[str, Any],
        metrics: dict[str, Any],
        gate: dict[str, Any],
        best: Optional[dict[str, Any]],
        promoted: bool,
        candidate_symbol: Optional[str],
        order_result: Optional[dict[str, Any]],
        candidate_strategy_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "symbol": candidate_symbol or (best or {}).get("symbol"),
            "candidate_strategy_id": candidate_strategy_id or (best or {}).get("strategy_id"),
            "gate_result": "passed" if gate.get("aggregate_gate_passed") else "failed",
            "gate_failures": gate.get("gate_failures") or [],
            "reason": None if gate.get("aggregate_gate_passed") else ", ".join(gate.get("gate_failures") or []),
            "qualified_shadow_closes": metrics.get("qualified_closes"),
            "avg_pnl_bps_after_cost": metrics.get("avg_pnl_bps_after_cost"),
            "profit_factor": metrics.get("profit_factor"),
            "win_rate": metrics.get("win_rate"),
            "excluded_missing_price": exclusion.get("excluded_missing_price"),
            "excluded_cap_release": exclusion.get("excluded_cap_release"),
            "paper_candidate_promoted": promoted,
            "notional_usd": (order_result or {}).get("notional_usd"),
            "risk_pct_equity_cap": (order_result or {}).get("risk_pct_equity_cap"),
            "broker_result": (order_result or {}).get("broker_result"),
            "order_submitted": (order_result or {}).get("submitted"),
            "reject_reason": (order_result or {}).get("reject_reason"),
            "live_trading_locked": True,
            "broker_mode": "paper" if is_paper_broker_url() else "unknown",
            "counts_as_broker_evidence": bool((order_result or {}).get("submitted")),
        }

    def _persist_audit(self, audit: dict[str, Any], *, operator: str) -> None:
        self.session.add(
            SettingsActionAudit(
                action=CANARY_AUDIT_KEY,
                actor=operator,
                broker_mode="paper",
                paper_broker=is_paper_broker_url(),
                live_trading_locked=True,
                live_orders_enabled=False,
                details_json=audit,
            )
        )

    def _load_last_audit(self) -> Optional[dict[str, Any]]:
        rows = list(
            self.session.exec(
                select(SettingsActionAudit).where(SettingsActionAudit.action == CANARY_AUDIT_KEY)
            ).all()
        )
        row = max(rows, key=lambda r: r.created_at or datetime.min, default=None) if rows else None
        return dict(row.details_json) if row and row.details_json else None

    def _tick_day_key(self) -> str:
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _orders_this_tick(self) -> int:
        key = f"paper_canary_tick|{self._tick_day_key()}"
        row = self.session.exec(
            select(SettingsActionAudit)
            .where(SettingsActionAudit.action == key)
            .order_by(SettingsActionAudit.created_at.desc())
        ).first()
        if not row or not row.details_json:
            return 0
        ts = row.created_at
        if ts and (datetime.utcnow() - ts.replace(tzinfo=None)).total_seconds() > 120:
            return 0
        return int(row.details_json.get("orders_this_tick") or 0)

    def _mark_tick_order_attempt(self) -> None:
        key = f"paper_canary_tick|{self._tick_day_key()}"
        self.session.add(
            SettingsActionAudit(
                action=key,
                actor="paper_canary",
                broker_mode="paper",
                paper_broker=True,
                live_trading_locked=True,
                details_json={"orders_this_tick": 1, "at": datetime.utcnow().isoformat() + "Z"},
            )
        )


def is_paper_canary_probe(config: dict, cand) -> bool:
    """True for marked shadow-canary paper probes (cage applies hard notional cap)."""
    meta = getattr(cand, "meta", None) or {}
    execution = config.get("execution") or {}
    live_orders = bool(execution.get("live_orders_enabled", False)) or bool(config.get("live_trading_enabled", False))
    cc = _canary_cfg(config)
    return (
        bool(meta.get("paper_canary_probe"))
        and bool(cc.get("enabled", True))
        and bool(cc.get("live_forbidden", True))
        and not live_orders
    )


def paper_canary_max_notional_usd(config: dict, equity: float) -> float:
    cc = _canary_cfg(config)
    pct = float(cc.get("max_notional_pct_equity", 5.0))
    return max(1.0, float(equity or 200) * (pct / 100.0))
