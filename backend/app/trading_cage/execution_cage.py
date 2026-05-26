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
            return ExecutionCageResult(
                False,
                "kill_switch",
                "KILL_SWITCH_ACTIVE",
                switches[0].get("message") if switches else "Kill switch active",
                evidence={**evidence, "switches": switches},
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
