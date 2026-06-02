"""
Unified execution cage — single validator facade before Alpaca submit.

Orchestrates: paper guard → risk → freshness → cost → crypto metadata → allocation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlmodel import Session

from app.services.alpaca_adapter import AlpacaAdapter
from app.services.alpaca_crypto_order_validator import AlpacaCryptoOrderValidator
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.config_manager import ConfigManager
from app.services.cooldown_service import CooldownService
from app.services.engine_config import cfg_get
from app.services.execution_preflight import PreflightResult, run_preflight
from app.services.kill_switch_service import KillSwitchService
from app.services.portfolio_gate import ApprovedCandidate
from app.trading_cage.cost_model import evaluate_edge_after_cost_bps
from app.trading_cage.micro_cap_allocator import MicroCapAllocator
from app.trading_cage.paper_guard import PaperGuardViolation, assert_paper_only


def _paper_exploration_cost_override(config: dict, cand: ApprovedCandidate) -> bool:
    meta = cand.meta or {}
    nested_score = meta.get("push_pull_score") or {}
    exp = config.get("exploration") or {}
    promotion = (config.get("promotion") or {}).get("current_stage", "PAPER")
    execution = config.get("execution") or {}
    live_orders = bool(execution.get("live_orders_enabled", False)) or bool(config.get("live_trading_enabled", False))
    levels = meta.get("dynamic_exit_levels") or nested_score.get("dynamic_exit_levels") or {}
    has_exit_truth = all(levels.get(k) is not None for k in ("stop_loss", "take_profit", "trailing_stop", "invalidation_price"))
    marked_probe = bool(
        meta.get("paper_exploration_probe")
        or nested_score.get("paper_exploration_probe")
        or meta.get("paper_exploration")
        or nested_score.get("paper_exploration")
    )
    return promotion == "PAPER" and bool(exp.get("enabled", True)) and not live_orders and marked_probe and has_exit_truth


def _is_near_miss_exploration_probe(config: dict, cand: ApprovedCandidate) -> bool:
    """A near-miss paper-exploration probe (Alpha Factory lane). Paper-only, never live."""
    meta = cand.meta or {}
    execution = config.get("execution") or {}
    live_orders = bool(execution.get("live_orders_enabled", False)) or bool(config.get("live_trading_enabled", False))
    af_exp = (config.get("alpha_factory") or {}).get("paper_exploration") or {}
    return (
        bool(meta.get("near_miss_exploration_probe"))
        and bool(af_exp.get("allow_paper_exploration_near_misses", True))
        and bool(af_exp.get("exploration_live_forbidden", True))
        and not live_orders
    )


# Switches that block even a tiny paper-exploration probe (mirrors KillSwitchService).
_CATASTROPHIC_SWITCHES = frozenset({"manual_master", "max_drawdown", "system_health", "weekly_drawdown"})


def _exploration_kill_switch_override(config: dict, cand: ApprovedCandidate, switches: list) -> bool:
    """Allow a marked near-miss probe past the kill switch ONLY when paper-only and the active
    switches are non-catastrophic (e.g. daily_drawdown alone). Real money is never affected."""
    if not _is_near_miss_exploration_probe(config, cand):
        return False
    active = {str(s.get("switch_name")) for s in (switches or [])}
    return not (active & _CATASTROPHIC_SWITCHES)


def _exploration_max_notional(config: dict) -> float:
    af_exp = (config.get("alpha_factory") or {}).get("paper_exploration") or {}
    try:
        return float(af_exp.get("exploration_max_notional_usd", 5.0) or 5.0)
    except (TypeError, ValueError):
        return 5.0


@dataclass
class ExecutionCageResult:
    passed: bool
    stage: str
    block_reason_code: Optional[str] = None
    human_reason: Optional[str] = None
    preflight: Optional[PreflightResult] = None
    crypto_validation: Optional[dict] = None
    allocation: Optional[dict] = None
    cost_model: Optional[dict] = None
    evidence: dict[str, Any] = field(default_factory=dict)


class ExecutionCage:
    """Deterministic gate — no bypass."""

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)

    def validate_submit(
        self,
        *,
        cand: ApprovedCandidate,
        cycle_run_id: str,
        portfolio_decision,
        account,
        positions: list,
        open_order_symbols: set[str],
        quote: dict,
        signal_row=None,
    ) -> ExecutionCageResult:
        evidence: dict[str, Any] = {"cycle_run_id": cycle_run_id, "symbol": cand.symbol}

        try:
            assert_paper_only(self.config, alpaca_configured=self.alpaca.configured, context="execution_cage")
        except PaperGuardViolation as exc:
            return ExecutionCageResult(False, "paper_guard", exc.code, exc.message, evidence=evidence)

        ks = KillSwitchService(self.session, self.config)
        entries_ok, switches = ks.evaluate(
            equity=account.equity if account else 0,
            daily_pl_pct=account.daily_pl_pct if account else 0,
            drawdown_pct=account.drawdown_pct if account else 0,
        )
        if not entries_ok and cand.signal_type == "entry":
            from app.trading_cage.paper_exploration_guard import (
                can_override_kill_switch_for_paper_exploration,
                is_marked_probe,
            )

            if not is_marked_probe(cand):
                # Standard paper entries block exactly as before — no exploration override.
                return ExecutionCageResult(
                    False,
                    "kill_switch",
                    "KILL_SWITCH_ACTIVE",
                    switches[0].get("message") if switches else "Kill switch active",
                    evidence={**evidence, "switches": switches},
                )
            decision = can_override_kill_switch_for_paper_exploration(switches, cand, self.config, account)
            if decision["allowed"]:
                # Paper-only near-miss probe past a NON-catastrophic switch (e.g. daily drawdown).
                # Real money stays locked; standard entries stay blocked; exits unaffected.
                evidence["paper_exploration_kill_switch_override"] = {
                    "overridden_switch": decision.get("overridden_switch"),
                    "active_switches": decision.get("active_switches"),
                    "standard_entries_still_blocked": True,
                    "real_money_still_locked": True,
                    "exits_allowed": True,
                    "exploration_probe_validated": True,
                }
            else:
                # SPECIFIC reason — never an opaque KILL_SWITCH_ACTIVE for a marked probe.
                return ExecutionCageResult(
                    False,
                    "kill_switch",
                    decision["denied_reason"],
                    f"Paper exploration override denied: {decision['denied_reason']} "
                    f"({decision.get('catastrophic_switches') or decision.get('probe_blockers')})",
                    evidence={
                        **evidence,
                        "switches": switches,
                        "exploration_override_denied_reason": decision["denied_reason"],
                        "exploration_override_decision": decision,
                    },
                )

        cd = CooldownService(self.session, self.config)
        ok, reason, cd_ev = cd.check_symbol(cand.symbol)
        if not ok:
            return ExecutionCageResult(
                False, "cooldown", "SYMBOL_COOLDOWN_ACTIVE", reason, evidence={**evidence, **(cd_ev or {})}
            )

        max_drift_bps = float(cfg_get(self.config, "risk.reconciliation_drift_halt_bps", 5.0))
        try:
            recon = BrokerReconciliationService(self.session, self.config).exit_only_reconciliation_status()
            drift = float(recon.get("max_drift_bps") or recon.get("drift_bps") or 0)
            if drift > max_drift_bps:
                return ExecutionCageResult(
                    False,
                    "reconciliation",
                    "RECONCILIATION_DRIFT",
                    f"Reconciliation drift {drift:.2f} bps > {max_drift_bps} bps — entries halted",
                    evidence={**evidence, "reconciliation": recon},
                )
        except Exception:
            pass

        quote_age = quote.get("quote_age_seconds")
        max_quote = int(cfg_get(self.config, "execution.quote_max_age_seconds", 30))
        if quote_age is not None and quote_age > max_quote:
            return ExecutionCageResult(
                False, "stale_quote", "STALE_QUOTE", f"Quote age {quote_age}s > {max_quote}s", evidence=evidence
            )

        cost = evaluate_edge_after_cost_bps(
            self.config,
            expected_move_pct=cand.expected_move_pct,
            spread_pct=quote.get("spread_pct") or cand.spread_pct,
            tier=cand.tier or "TIER_ALT",
        )
        if not cost.passed and cand.signal_type == "entry":
            if _paper_exploration_cost_override(self.config, cand):
                evidence["paper_exploration_cost_override"] = {
                    "original_block_reason_code": cost.block_reason_code,
                    "human_reason": cost.human_reason,
                    "mode": "paper_probe_dynamic_exit_truth",
                }
            else:
                return ExecutionCageResult(
                    False,
                    "cost_model",
                    cost.block_reason_code,
                    cost.human_reason,
                    cost_model=cost.evidence,
                    evidence=evidence,
                )

        if cand.signal_type == "entry" and account:
            alloc = MicroCapAllocator(self.session, self.config).compute_entry_notional(
                equity=account.equity,
                buying_power=float(
                    (getattr(account, "raw_payload", None) or {}).get("non_marginable_buying_power")
                    or account.buying_power
                ),
                symbol=cand.symbol,
                open_positions=positions,
            )
            if not alloc.allowed:
                return ExecutionCageResult(
                    False,
                    "allocator",
                    alloc.reason_code,
                    alloc.human_reason,
                    allocation=alloc.evidence,
                    evidence=evidence,
                )
            meta = cand.meta or {}
            req_notional = cand.position_qty * cand.entry_price if cand.entry_price else 0
            if req_notional < alloc.notional_usd * 0.9:
                cand.position_qty = alloc.notional_usd / max(cand.entry_price, quote.get("mid") or quote.get("ask") or 1)
                meta["allocator_notional"] = alloc.notional_usd
                cand.meta = meta

        # Hard notional cap for near-miss exploration probes — tiny, capped, paper-only.
        if cand.signal_type == "entry" and _is_near_miss_exploration_probe(self.config, cand):
            cap = _exploration_max_notional(self.config)
            px = cand.entry_price or quote.get("mid") or quote.get("ask") or 0
            req_notional = (cand.position_qty or 0) * (px or 0)
            if px and req_notional > cap:
                cand.position_qty = cap / px  # shrink to the cap; never expand
            evidence["exploration_notional_cap_usd"] = cap
            evidence["exploration_notional_usd"] = round((cand.position_qty or 0) * (px or 0), 6)
            if not px or (cand.position_qty or 0) <= 0:
                return ExecutionCageResult(
                    False, "exploration_notional", "EXPLORATION_NOTIONAL_INVALID",
                    "Exploration probe requires a positive price and tiny capped notional.",
                    evidence=evidence,
                )

        pf = run_preflight(
            self.session,
            self.config,
            cand=cand,
            cycle_run_id=cycle_run_id,
            portfolio_decision=portfolio_decision,
            account=account,
            positions=positions,
            open_order_symbols=open_order_symbols,
            alpaca=self.alpaca,
            quote=quote,
            signal_row=signal_row,
        )
        if not pf.passed:
            return ExecutionCageResult(
                False,
                "preflight",
                pf.block_reason_code,
                pf.human_reason,
                preflight=pf,
                evidence={**evidence, "preflight_evidence": pf.evidence},
            )

        recipe = str(cfg_get(self.config, "execution.crypto_paper_recipe", "limit_ioc_qty"))
        v = AlpacaCryptoOrderValidator(self.session, self.alpaca, self.config).validate_for_candidate(
            symbol=cand.symbol,
            side=cand.side,
            qty=cand.position_qty,
            limit_price=pf.limit_price or cand.entry_price,
            client_order_id=pf.client_order_id,
            account=account,
            open_order_symbols=open_order_symbols,
            recipe=recipe,
        )
        if not v.valid:
            return ExecutionCageResult(
                False,
                "crypto_validator",
                v.reject_code or "CRYPTO_VALIDATOR_BLOCK",
                "; ".join(v.validator_reasons),
                crypto_validation={
                    "validator_reasons": v.validator_reasons,
                    "asset_metadata": v.asset_metadata,
                    "normalized_payload": v.normalized_payload,
                    "precision_adjustments": v.precision_adjustments,
                },
                evidence=evidence,
            )

        return ExecutionCageResult(
            passed=True,
            stage="ready_to_submit",
            preflight=pf,
            crypto_validation={
                "normalized_payload": v.normalized_payload,
                "asset_metadata": v.asset_metadata,
                "recipe": recipe,
            },
            cost_model=cost.evidence,
            evidence=evidence,
        )
