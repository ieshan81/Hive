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

    @property
    def cap_max_usd(self) -> float:
        return float(self._cfg("exploration_cap_max_usd", 25.0) or 25.0)

    # ---- operator: set exploration notional cap (paper-only, audited) ---
    def set_exploration_cap(self, usd: Any, *, operator: str = "operator") -> dict[str, Any]:
        """Set alpha_factory.paper_exploration.exploration_max_notional_usd within (0, cap_max].
        Paper-only: never touches live flags, standard paper-entry safety, or the kill switch, and
        submits NO order. The change is activated + audited through ConfigManager."""
        from app.services.config_manager import ConfigManager

        cap_max = self.cap_max_usd
        try:
            requested = float(usd)
        except (TypeError, ValueError):
            return {"status": "rejected", "ok": False, "reason": "invalid_cap_value",
                    "safe_human_message": f"Cap must be a number between 0 and ${cap_max:.0f}.",
                    "orders_created": 0}
        if requested <= 0 or requested > cap_max:
            return {"status": "rejected", "ok": False, "reason": "cap_out_of_range",
                    "requested_usd": requested, "max_allowed_usd": cap_max,
                    "safe_human_message": f"Cap ${requested:.2f} rejected — must be > 0 and <= ${cap_max:.0f}.",
                    "orders_created": 0}

        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        af = dict(cur.get("alpha_factory") or {})
        pe = dict(af.get("paper_exploration") or {})
        previous = pe.get("exploration_max_notional_usd")
        pe["exploration_max_notional_usd"] = requested
        af["paper_exploration"] = pe
        merged = {**cur, "alpha_factory": af}
        # Hard invariant: this endpoint must NEVER alter live-trading flags.
        merged["live_trading_enabled"] = bool(cur.get("live_trading_enabled", False))
        merged.setdefault("execution", {})
        merged["execution"] = {**(cur.get("execution") or {}),
                               "live_orders_enabled": bool((cur.get("execution") or {}).get("live_orders_enabled", False))}
        cfg_mgr._activate(merged, changed_by=operator, reason="paper_exploration_set_cap")
        self.config = cfg_mgr.get_current()
        self.factory = AutonomousAlphaFactoryService(self.session, self.config)
        self.factory._audit("paper_exploration_set_cap", operator, {
            "previous_usd": previous, "new_usd": requested, "max_allowed_usd": cap_max,
            "live_trading_enabled": bool(self.config.get("live_trading_enabled", False)),
            "orders_created": 0,
        })
        return {
            "status": "ok", "ok": True, "orders_created": 0,
            "exploration_max_notional_usd": requested,
            "previous_usd": previous,
            "max_allowed_usd": cap_max,
            "broker_min_notional_usd": float(cfg_get(self.config, "execution.alpaca_crypto_min_notional_usd", 10.0) or 10.0),
            "live_trading_enabled": bool(self.config.get("live_trading_enabled", False)),
            "real_money_entries_allowed": False,
            "safe_human_message": f"Paper exploration cap set to ${requested:.0f} (paper-only; live trading untouched).",
        }

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
        bv = self.broker_validity(nm)
        return {
            "exploration_eligible": eligible,
            "exploration_score": score,
            "exploration_stage": EXPLORATION_STAGE if eligible else None,
            "exploration_blockers": blockers,
            "broker_valid_for_exploration": bv["broker_valid"],
            "broker_valid_blockers": bv["broker_valid_blockers"],
            "min_required_notional_usd": bv["min_required_notional_usd"],
            "exploration_next_action": (
                "Eligible for a tiny capped paper-exploration probe through the cage."
                if eligible and bv["broker_valid"]
                else f"Resolve: {', '.join(blockers + bv['broker_valid_blockers']) or 'broker sizing'}."
            ),
        }

    def broker_validity(self, nm: dict[str, Any]) -> dict[str, Any]:
        """Can this candidate be VALIDLY submitted under the exploration cap at the broker minimum?
        The cap is never raised silently — if it is below the broker minimum the candidate is
        marked invalid so no invalid broker order is ever attempted."""
        min_notional = float(cfg_get(self.config, "execution.alpaca_crypto_min_notional_usd", 10.0) or 10.0)
        buffer = float(self._cfg("broker_min_buffer_pct", 2.0) or 0.0) / 100.0
        required = round(min_notional * (1.0 + buffer), 2)
        cap = self.max_notional_usd
        allow_raise = bool(self._cfg("allow_cap_raise_to_broker_min", False))
        skip_if_exceeds = bool(self._cfg("skip_candidate_if_min_notional_exceeds_cap", True))
        blockers: list[str] = []
        if cap < required and not allow_raise and skip_if_exceeds:
            blockers.append("broker_min_notional_exceeds_cap")
        return {
            "broker_valid": not blockers,
            "broker_valid_blockers": blockers,
            "min_required_notional_usd": required,
            "exploration_cap_usd": cap,
            "broker_min_notional_usd": min_notional,
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
        """Highest-score near-miss that is BOTH eligible and broker-valid under the cap."""
        return self.select_candidate_detailed()["selected"]

    def select_candidate_detailed(self) -> dict[str, Any]:
        """Pick the best broker-valid eligible candidate; record why higher-scored ones were skipped."""
        skipped: list[dict[str, Any]] = []
        selected: Optional[dict[str, Any]] = None
        for nm in self.near_misses(limit=50):  # already sorted: eligible first, then score desc
            if not nm.get("exploration_eligible"):
                continue
            if not nm.get("broker_valid_for_exploration"):
                skipped.append({
                    "symbol": nm.get("symbol"),
                    "exploration_score": nm.get("exploration_score"),
                    "skipped_reason": (nm.get("broker_valid_blockers") or ["broker_min_notional_exceeds_cap"])[0],
                    "min_required_notional_usd": nm.get("min_required_notional_usd"),
                })
                continue
            selected = nm
            break
        return {
            "selected": selected,
            "skipped_broker_invalid": skipped,
            "no_broker_valid_candidate": selected is None,
        }

    # ---- status + decision-state (PHASE 6) -----------------------------
    def status(self) -> dict[str, Any]:
        perm = self.permission()
        sel = self.select_candidate_detailed()
        cand = sel["selected"]
        # The top-scored eligible near-miss even if broker-invalid (for visibility/UI truth).
        top = next((n for n in self.near_misses(limit=50) if n.get("exploration_eligible")), None)
        return {
            "paper_exploration_enabled": self.enabled,
            "paper_exploration_allowed": perm["paper_exploration_allowed"],
            "paper_exploration_block_reason": perm["paper_exploration_block_reason"],
            "current_exploration_candidate": None if not top else {
                "symbol": top.get("symbol"),
                "strategy_family": top.get("strategy_family"),
                "best_session": top.get("best_session"),
                "exploration_score": top.get("exploration_score"),
                "edge_after_cost_bps": self._eff_edge(top),
                "sample_size": max(int(top.get("sample_size") or 0), int(top.get("session_sample_size") or 0)),
                "verdict": top.get("verdict"),
                "stage": EXPLORATION_STAGE,
                "broker_valid_for_exploration": top.get("broker_valid_for_exploration"),
                "min_required_notional_usd": top.get("min_required_notional_usd"),
            },
            "broker_valid_candidate": None if not cand else {
                "symbol": cand.get("symbol"),
                "best_session": cand.get("best_session"),
                "exploration_score": cand.get("exploration_score"),
                "min_required_notional_usd": cand.get("min_required_notional_usd"),
            },
            "no_broker_valid_candidate": sel["no_broker_valid_candidate"],
            "skipped_broker_invalid": sel["skipped_broker_invalid"],
            "exploration_entries_today": perm["exploration_entries_today"],
            "exploration_open_position": perm["exploration_open_positions"] > 0,
            "exploration_max_notional_usd": perm["max_notional_usd"],
            "broker_min_notional_usd": float(cfg_get(self.config, "execution.alpaca_crypto_min_notional_usd", 10.0) or 10.0),
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
        # Broker-valid selection: never attempt an invalid (below broker-min) order.
        sel = self.select_candidate_detailed()
        nm = sel["selected"]
        if not nm:
            any_eligible_invalid = bool(sel["skipped_broker_invalid"])
            return {
                "status": "blocked",
                "submitted": False,
                "orders_created": 0,
                "block_reason": "no_broker_valid_exploration_candidate" if any_eligible_invalid else "no_eligible_near_miss",
                "execution_status": "preflight_blocked",
                "error_stage": None,
                "safe_human_message": (
                    "Eligible near-miss(es) exist but none can be validly submitted under the "
                    f"${self.max_notional_usd:.0f} exploration cap (broker minimum notional exceeds the cap)."
                    if any_eligible_invalid
                    else "No eligible near-miss candidate for paper exploration right now."
                ),
                "skipped_broker_invalid": sel["skipped_broker_invalid"],
                "permission": perm,
            }

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
