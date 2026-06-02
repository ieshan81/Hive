"""Paper-exploration lane for near-miss alpha candidates.

A strict PAPER-ONLY learning lane that sits BELOW paper_candidate. It lets the bot learn from
the best near-misses with tiny, capped, cage-approved paper orders. It can NEVER:
  - enable or place a live/real-money order (live is hard-forbidden here),
  - bypass the execution cage, broker truth, position/notional limits, or exit rules,
  - promote a near-miss directly to paper_candidate (that needs real closed evidence),
  - act on a session signal alone (the normal evidence gates still apply).

The exploration lane may proceed while standard paper entries are blocked by a *daily-drawdown*
kill switch — but only in paper mode, only when no CATASTROPHIC switch is active, and only with a
tiny capped probe. Real money stays locked at all times.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.database import PaperExperimentOutcome, PositionSnapshot, SettingsActionAudit
from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService
from app.services.autonomous_alpha_promotion_service import PAPER_ALLOWED_VERDICTS
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.kill_switch_service import KillSwitchService

EXPLORATION_STAGE = "paper_exploration_candidate"
EXPLORATION_COID_TAG = "EXPLORATION"

# A probe counts as submitted ONLY when PaperExecutionService reports a real broker submit/fill.
# PaperExecutionService emits paper_order_* statuses (never the literal "submitted").
SUBMITTED_STATUSES = ("paper_order_submitted", "paper_order_filled", "paper_order_partially_filled")


def _norm(symbol: str) -> str:
    return str(symbol or "").upper().replace("/", "").replace("-", "").strip()


class PaperExplorationService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.factory = AutonomousAlphaFactoryService(session, self.config)

    # ---- config helpers -------------------------------------------------
    def _cfg(self, key: str, default: Any) -> Any:
        return cfg_get(self.config, f"alpha_factory.paper_exploration.{key}", default)

    @property
    def enabled(self) -> bool:
        return bool(self._cfg("allow_paper_exploration_near_misses", True))

    @property
    def max_notional_usd(self) -> float:
        return float(self._cfg("exploration_max_notional_usd", 5.0) or 5.0)

    @property
    def max_positions(self) -> int:
        return int(self._cfg("exploration_max_positions", 1) or 1)

    @property
    def max_entries_per_day(self) -> int:
        return int(self._cfg("exploration_max_entries_per_day", 3) or 3)

    # ---- broker / cap truth --------------------------------------------
    def entries_today(self) -> int:
        """Count submitted exploration probes today via the audit trail (the submit path writes
        a 'paper_exploration_order' audit with submitted=True)."""
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = self.session.exec(
            select(SettingsActionAudit).where(
                SettingsActionAudit.action == "paper_exploration_order",
                SettingsActionAudit.created_at >= start,
            )
        ).all()
        return sum(1 for r in rows if bool((r.details_json or {}).get("submitted")))

    def open_exploration_symbols(self) -> set[str]:
        """Open broker positions (paper). Exploration shares the paper account, so any open
        position counts conservatively against the same-symbol block and the position cap."""
        rows = self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()
        return {_norm(r.symbol) for r in rows}

    # ---- permission (PHASE 2) ------------------------------------------
    def permission(self) -> dict[str, Any]:
        ks = KillSwitchService(self.session, self.config)
        snap = ks._latest_account()
        lanes = ks.evaluate_paper_exploration(
            equity=float(snap.equity or 0) if snap else 0,
            daily_pl_pct=float(snap.daily_pl_pct or 0) if snap else 0,
            drawdown_pct=float(snap.drawdown_pct or 0) if snap else 0,
        )
        block = lanes.get("paper_exploration_block_reason")
        allowed = bool(lanes.get("paper_exploration_allowed"))
        # Layer per-entry caps on top of the kill-switch lanes.
        entries = self.entries_today()
        open_syms = self.open_exploration_symbols()
        if allowed and entries >= self.max_entries_per_day:
            allowed, block = False, f"exploration_daily_entry_cap:{entries}>={self.max_entries_per_day}"
        if allowed and len(open_syms) >= self.max_positions:
            allowed, block = False, f"exploration_max_positions:{len(open_syms)}>={self.max_positions}"
        return {
            "real_money_entries_allowed": lanes["real_money_entries_allowed"],
            "paper_entries_allowed": lanes["paper_entries_allowed"],
            "paper_exploration_allowed": allowed,
            "exit_management_allowed": lanes["exit_management_allowed"],
            "paper_exploration_block_reason": block,
            "exploration_entries_today": entries,
            "exploration_open_positions": len(open_syms),
            "max_notional_usd": self.max_notional_usd,
            "max_entries_per_day": self.max_entries_per_day,
            "max_positions": self.max_positions,
            "live_forbidden": bool(self._cfg("exploration_live_forbidden", True)),
        }

    # ---- eligibility (PHASE 1) -----------------------------------------
    def _eff_edge(self, nm: dict[str, Any]) -> Optional[float]:
        se = nm.get("session_edge_after_cost_bps")
        return se if se is not None else nm.get("edge_after_cost_bps")

    def evaluate(self, nm: dict[str, Any]) -> dict[str, Any]:
        """Return exploration eligibility + score + blockers + next action for one near-miss."""
        min_sample = int(self._cfg("exploration_min_sample_size", 50) or 50)
        min_edge = float(self._cfg("exploration_min_edge_after_cost_bps", -5.0))
        require_session = bool(self._cfg("exploration_required_session_metrics", True))
        blockers: list[str] = []

        if nm.get("verdict") in PAPER_ALLOWED_VERDICTS:
            blockers.append("already_paper_candidate")  # never re-explore a real candidate
        sample = max(int(nm.get("sample_size") or 0), int(nm.get("session_sample_size") or 0))
        if sample < min_sample:
            blockers.append("insufficient_sample")
        edge = self._eff_edge(nm)
        if edge is None or edge < min_edge:
            blockers.append("edge_below_exploration_floor")
        if not (nm.get("cost_bps") or nm.get("spread_bps") or nm.get("fee_bps")):
            blockers.append("missing_cost_model")
        if (nm.get("data_freshness_status") or "fresh") not in ("fresh",):
            blockers.append("stale_data")
        if nm.get("recent_loss_cooldown_until"):
            blockers.append("recent_loss_cooldown")
        if require_session and not nm.get("session_metrics_available"):
            blockers.append("session_metrics_unavailable")
        if _norm(nm.get("symbol", "")) in self.open_exploration_symbols():
            blockers.append("open_broker_position_same_symbol")

        eligible = not blockers
        score = self.score(nm)
        return {
            "exploration_eligible": eligible,
            "exploration_score": score,
            "exploration_stage": EXPLORATION_STAGE if eligible else None,
            "exploration_blockers": blockers,
            "exploration_next_action": (
                "Eligible for a tiny capped paper-exploration probe through the cage."
                if eligible else f"Resolve: {', '.join(blockers)}."
            ),
        }

    # ---- scoring (PHASE 3) ---------------------------------------------
    def score(self, nm: dict[str, Any]) -> float:
        """Deterministic exploration score in [0,1]. Higher = better learning candidate.
        Weighted: session edge, sample size, cost quality, cooldown, stability(PF), drawdown, freshness."""
        edge = self._eff_edge(nm)
        edge_c = 0.0 if edge is None else max(0.0, min(1.0, (edge + 10.0) / 20.0))  # -10bps->0, +10bps->1
        sample = max(int(nm.get("sample_size") or 0), int(nm.get("session_sample_size") or 0))
        sample_c = min(1.0, sample / 200.0)
        cost = nm.get("cost_bps")
        cost_c = 1.0 if cost is None else max(0.0, 1.0 - min(1.0, float(cost) / 150.0))
        cooldown_c = 0.0 if nm.get("recent_loss_cooldown_until") else 1.0
        pf = nm.get("profit_factor")
        pf_c = 0.0 if not pf else min(1.0, float(pf) / 1.5)
        dd = nm.get("max_drawdown_pct")
        dd_c = 1.0 if dd is None else max(0.0, 1.0 - min(1.0, float(dd) / 35.0))
        fresh_c = 1.0 if (nm.get("data_freshness_status") or "fresh") == "fresh" else 0.0
        sess_c = 1.0 if nm.get("session_metrics_available") else 0.0
        score = (
            0.30 * edge_c + 0.18 * sample_c + 0.15 * cost_c + 0.10 * cooldown_c
            + 0.12 * pf_c + 0.08 * dd_c + 0.04 * fresh_c + 0.03 * sess_c
        )
        return round(score, 4)

    # ---- near-misses + selection (PHASE 3/6) ---------------------------
    def near_misses(self, *, limit: int = 25) -> list[dict[str, Any]]:
        rows = self.factory.get_near_misses(limit=limit).get("near_misses", [])
        out = []
        for nm in rows:
            out.append({**nm, **self.evaluate(nm)})
        out.sort(key=lambda c: (0 if c["exploration_eligible"] else 1, -c["exploration_score"]))
        return out

    def select_candidate(self) -> Optional[dict[str, Any]]:
        for nm in self.near_misses(limit=50):
            if nm["exploration_eligible"]:
                return nm
        return None

    # ---- status + decision-state (PHASE 6) -----------------------------
    def status(self) -> dict[str, Any]:
        perm = self.permission()
        cand = self.select_candidate()
        return {
            "paper_exploration_enabled": self.enabled,
            "paper_exploration_allowed": perm["paper_exploration_allowed"],
            "paper_exploration_block_reason": perm["paper_exploration_block_reason"],
            "current_exploration_candidate": None if not cand else {
                "symbol": cand.get("symbol"),
                "strategy_family": cand.get("strategy_family"),
                "best_session": cand.get("best_session"),
                "exploration_score": cand.get("exploration_score"),
                "edge_after_cost_bps": self._eff_edge(cand),
                "sample_size": max(int(cand.get("sample_size") or 0), int(cand.get("session_sample_size") or 0)),
                "verdict": cand.get("verdict"),
                "stage": EXPLORATION_STAGE,
            },
            "exploration_entries_today": perm["exploration_entries_today"],
            "exploration_open_position": perm["exploration_open_positions"] > 0,
            "exploration_max_notional_usd": perm["max_notional_usd"],
            "real_money_entries_allowed": perm["real_money_entries_allowed"],
            "standard_paper_entries_allowed": perm["paper_entries_allowed"],
            "exit_management_allowed": perm["exit_management_allowed"],
            "orders_authority": "cage_only",
        }

    def decision_state(self) -> dict[str, Any]:
        perm = self.permission()
        cand = self.select_candidate()
        return {
            "standard_entries_allowed": perm["paper_entries_allowed"],
            "paper_exploration_allowed": perm["paper_exploration_allowed"],
            "selected_exploration_candidate": None if not cand else {
                "symbol": cand.get("symbol"),
                "best_session": cand.get("best_session"),
                "exploration_score": cand.get("exploration_score"),
                "stage": EXPLORATION_STAGE,
            },
            "exploration_order_submitted": False,  # set true only by submit_exploration_order
            "exploration_block_reason": perm["paper_exploration_block_reason"],
        }

    # ---- micro paper order path (PHASE 4) ------------------------------
    def build_probe_candidate(self, nm: dict[str, Any], *, price: float):
        """Build a tiny, capped, exit-planned, paper-only exploration probe ApprovedCandidate.
        It is marked so the cage applies the exploration overrides + hard notional cap, and uses
        an EXPLORATION client_order_id. Long-bias (buy) only; never live."""
        from app.services.portfolio_gate import ApprovedCandidate
        from app.services.research_cost_model import COST_MODEL_VERSION

        price = float(price)
        notional = min(self.max_notional_usd, self.max_notional_usd)  # tiny by construction
        qty = (notional / price) if price > 0 else 0.0
        # Conservative synthetic exit plan (exit truth required by the cage probe override).
        stop_pct = 0.01
        target_pct = stop_pct * 1.5
        stop_loss = round(price * (1 - stop_pct), 8)
        take_profit = round(price * (1 + target_pct), 8)
        exit_levels = {
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_stop": round(stop_pct, 6),
            "invalidation_price": stop_loss,
        }
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        coid = f"{EXPLORATION_COID_TAG}-{_norm(nm.get('symbol', ''))}-{ts}"
        meta = {
            "near_miss_exploration_probe": True,
            "paper_exploration_probe": True,
            "paper_exploration": True,
            "strategy_id": nm.get("strategy_id"),
            "scorecard_id": nm.get("id"),
            "best_session": nm.get("best_session"),
            "dynamic_exit_levels": exit_levels,
            "client_order_id": coid,
            "exploration_stage": EXPLORATION_STAGE,
            "exploration_reason": "near_miss_paper_exploration",
            "cost_model_version": COST_MODEL_VERSION,
            "exploration_score": nm.get("exploration_score"),
        }
        return ApprovedCandidate(
            signal_id=0,
            symbol=str(nm.get("symbol")),
            side="buy",
            signal_type="entry",
            meta=meta,
            strength=float(nm.get("exploration_score") or 0.0),
            confidence=float(nm.get("exploration_score") or 0.0),
            spread_pct=nm.get("spread_bps") and float(nm["spread_bps"]) / 10000.0,
            liquidity_score=None,
            edge_over_cost=self._eff_edge(nm),
            expected_move_pct=None,
            position_qty=qty,
            entry_price=price,
            stop_loss=stop_loss,
            atr14=None,
            tier=nm.get("tier") or "TIER_ALT",
            cost_evidence={"cost_model_version": COST_MODEL_VERSION},
            sizing_evidence={"exploration_max_notional_usd": self.max_notional_usd, "notional_usd": round(qty * price, 6)},
        )

    def _evidence(self, nm: dict[str, Any], approved) -> dict[str, Any]:
        from app.services.research_cost_model import COST_MODEL_VERSION

        return {
            "near_miss_id": nm.get("id"),
            "scorecard_id": nm.get("id"),
            "symbol": nm.get("symbol"),
            "strategy_id": nm.get("strategy_id"),
            "session": nm.get("best_session"),
            "exploration_reason": "near_miss_paper_exploration",
            "exploration_score": nm.get("exploration_score"),
            "risk_limits": {
                "max_notional_usd": self.max_notional_usd,
                "max_entries_per_day": self.max_entries_per_day,
                "max_positions": self.max_positions,
            },
            "client_order_id": (approved.meta or {}).get("client_order_id"),
            "dynamic_exit_levels": (approved.meta or {}).get("dynamic_exit_levels"),
            "cost_model_version": COST_MODEL_VERSION,
            "stage": EXPLORATION_STAGE,
        }

    def submit_exploration_order(self, *, operator: str = "paper_exploration", dry_run: bool = False,
                                 price: Optional[float] = None) -> dict[str, Any]:
        """Submit ONE tiny paper-exploration probe through the official cage. Never live, never
        forced. Returns blocked + reason if any gate fails; writes evidence either way."""
        perm = self.permission()
        if not perm["paper_exploration_allowed"]:
            return {"status": "blocked", "submitted": False, "orders_created": 0,
                    "block_reason": perm["paper_exploration_block_reason"], "permission": perm}
        nm = self.select_candidate()
        if not nm:
            return {"status": "no_candidate", "submitted": False, "orders_created": 0,
                    "block_reason": "no_eligible_near_miss", "permission": perm}

        # --- stage: quote_fetch (live price) ---
        px = price
        if px is None and not dry_run:
            try:
                from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol

                q = AlpacaAdapter(self.session).get_quote(normalize_crypto_symbol(str(nm["symbol"])), "crypto") or {}
                px = q.get("mid") or q.get("ask")
            except Exception as exc:  # never 500 — structured blocked response
                return self._submit_error(
                    stage="quote_fetch", exc=exc, perm=perm, nm=nm, status="blocked",
                    block_reason="quote_fetch_failed",
                    human="Paper exploration order was not submitted. Live quote fetch failed.",
                )
        if not px:
            if dry_run:
                px = 1.0  # planning only — no order is placed in dry_run
            else:
                return {"status": "blocked", "submitted": False, "orders_created": 0,
                        "block_reason": "no_quote", "error_stage": "quote_fetch",
                        "safe_human_message": "Paper exploration order was not submitted. No usable quote price.",
                        "permission": perm}

        # --- stage: build_probe_candidate ---
        try:
            approved = self.build_probe_candidate(nm, price=float(px))
            evidence = self._evidence(nm, approved)
        except Exception as exc:
            return self._submit_error(
                stage="build_probe_candidate", exc=exc, perm=perm, nm=nm, status="error",
                block_reason="build_probe_failed",
                human="Paper exploration order was not submitted. Candidate build failed.",
            )

        if dry_run:
            return {"status": "planned", "submitted": False, "orders_created": 0,
                    "planned_candidate": {"symbol": approved.symbol, "side": approved.side,
                                          "position_qty": approved.position_qty,
                                          "notional_usd": round(approved.position_qty * float(px), 6),
                                          "client_order_id": (approved.meta or {}).get("client_order_id")},
                    "evidence": evidence, "permission": perm}

        # --- stage: account/positions (soft — a missing account is not fatal; the cage gates) ---
        account = None
        try:
            from app.services.alpaca_adapter import AlpacaAdapter

            account = AlpacaAdapter(self.session).sync_account_cached()
        except Exception:
            account = None
        try:
            positions = list(self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all())
        except Exception:
            positions = []
        open_syms = {p.symbol for p in positions}

        # --- stage: paper_execution_submit (official cage-gated path ONLY) ---
        try:
            from app.services.paper_execution_service import PaperExecutionService

            log = PaperExecutionService(self.session, self.config).submit_candidate(
                approved, cycle_run_id=f"exploration_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                portfolio_decision=None, account=account, positions=positions, open_order_symbols=open_syms,
            )
        except Exception as exc:
            return self._submit_error(
                stage="paper_execution_submit", exc=exc, perm=perm, nm=nm, approved=approved, evidence=evidence,
                status="error", block_reason="paper_execution_exception",
                human="Paper exploration order was not submitted. Server caught execution exception.",
            )

        log_status = getattr(log, "status", None)
        # Submitted ONLY when the broker actually accepted/filled — never faked.
        submitted = log_status in SUBMITTED_STATUSES

        # --- stage: audit_write + commit (best-effort, never fatal) ---
        try:
            self.factory._audit("paper_exploration_order", operator, {
                **evidence, "submitted": submitted, "execution_status": log_status,
                "reject_reason": getattr(log, "reject_reason", None),
            })
            self.session.commit()
        except Exception:
            try:
                self.session.rollback()
            except Exception:
                pass

        return {
            "status": "submitted" if submitted else "blocked",
            "submitted": submitted,
            "orders_created": 1 if submitted else 0,
            "execution_status": log_status,
            "execution_log_id": getattr(log, "id", None),
            "block_reason": None if submitted else (getattr(log, "reject_reason", None) or log_status),
            "error_stage": None,
            "safe_human_message": (
                "Tiny paper exploration probe submitted through the cage."
                if submitted
                else "Paper exploration order was not submitted; the cage/broker did not accept it."
            ),
            "evidence": evidence,
            "permission": perm,
        }

    def _submit_error(self, *, stage: str, exc: Exception, perm: dict[str, Any], status: str,
                      block_reason: str, human: str, nm: Optional[dict[str, Any]] = None,
                      approved: Any = None, evidence: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Build a structured (never-500) error response and write a debug-safe audit row.
        Rolls back first so no partial/half-submitted order state is persisted (no fake submit)."""
        try:
            self.session.rollback()  # clear any partial flush from the failed stage
        except Exception:
            pass
        exception_type = type(exc).__name__
        coid = (approved.meta or {}).get("client_order_id") if approved is not None else None
        try:
            self.factory._audit("paper_exploration_submit_error", "paper_exploration", {
                "error_stage": stage,
                "exception_type": exception_type,
                "message": str(exc)[:300],  # no secrets — message text only, truncated
                "symbol": (nm or {}).get("symbol"),
                "strategy_id": (nm or {}).get("strategy_id"),
                "client_order_id": coid,
                "dry_run": False,
            })
            self.session.commit()
        except Exception:
            try:
                self.session.rollback()
            except Exception:
                pass
        out: dict[str, Any] = {
            "status": status,
            "submitted": False,
            "orders_created": 0,
            "block_reason": block_reason,
            "error_stage": stage,
            "exception_type": exception_type,
            "safe_human_message": human,
            "permission": perm,
        }
        if nm is not None:
            out["candidate"] = {"symbol": nm.get("symbol"), "strategy_id": nm.get("strategy_id"),
                                "best_session": nm.get("best_session")}
        if evidence is not None:
            out["evidence"] = evidence
        return out

    def run_exploration_cycle(self, *, operator: str = "operator", dry_run: bool = False) -> dict[str, Any]:
        """Operator-triggered exploration tick. Submits at most one tiny probe; never live."""
        return self.submit_exploration_order(operator=operator, dry_run=dry_run)

    # ---- promotion gate (PHASE 5) --------------------------------------
    def can_promote_from_exploration(self, symbol: str, strategy_id: str) -> dict[str, Any]:
        """Exploration -> paper_candidate requires REAL closed exploration evidence.
        A near-miss is NEVER promoted to paper_candidate by exploration eligibility alone."""
        min_closed = int(self._cfg("exploration_promote_min_closed_trades", 20) or 20)
        min_pf = float(self._cfg("exploration_promote_min_profit_factor", 1.10))
        max_dd = float(self._cfg("exploration_promote_max_drawdown_pct", 35.0))
        outcomes = list(
            self.session.exec(
                select(PaperExperimentOutcome).where(
                    PaperExperimentOutcome.symbol == symbol,
                    PaperExperimentOutcome.strategy_id == strategy_id,
                    PaperExperimentOutcome.realized_pnl != None,  # noqa: E711
                )
            ).all()
        )
        closed = len(outcomes)
        pnls = [float(o.realized_pnl) for o in outcomes if o.realized_pnl is not None]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        pf = (gross_win / gross_loss) if gross_loss > 0 else (None if not wins else float("inf"))
        expectancy = (sum(pnls) / closed) if closed else None
        reasons: list[str] = []
        if closed < min_closed:
            reasons.append(f"need_{min_closed}_closed_trades_have_{closed}")
        if expectancy is None or expectancy <= 0:
            reasons.append("expectancy_not_positive")
        if pf is None or pf < min_pf:
            reasons.append(f"profit_factor_below_{min_pf}")
        can = not reasons
        return {
            "can_promote": can,
            "closed_trades": closed,
            "expectancy": expectancy,
            "profit_factor": None if pf in (None, float("inf")) else round(pf, 4),
            "min_closed_required": min_closed,
            "reasons": reasons,
            "note": "Promotion still runs through normal promotion.evaluate evidence gates; this only unlocks eligibility.",
        }
