"""Signal evaluation pipeline — tier, cost, ATR, risk, portfolio, execution."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.database import StrategySignal
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.atr_sizing import evaluate_atr_sizing
from app.services.cost_edge_gate import evaluate_cost_edge
from app.services.cooldown_service import CooldownService
from app.services.crypto_push_pull import broker_position_qty
from app.services.engine_config import cfg_get, current_promotion_stage
from app.services.execution_policy import ExecutionPolicy
from app.services.kill_switch_service import KillSwitchService
from app.services.portfolio_gate import ApprovedCandidate, PortfolioGate
from app.services.risk_engine import RiskEngine, TradeProposal
from app.services.symbol_tier_service import EngineBoundaryBlocked, SymbolTierService
from app.services.portfolio_gate import _stage_portfolio_value


def _quote_symbol(sig: StrategySignal, asset_class: str) -> str:
    if asset_class == "crypto":
        return normalize_crypto_symbol(sig.symbol)
    return sig.symbol.split("/")[0]


class SignalPipeline:
    def __init__(self, session: Session, config: dict, alpaca: AlpacaAdapter, risk: RiskEngine):
        self.session = session
        self.config = config
        self.alpaca = alpaca
        self.risk = risk
        self.tiers = SymbolTierService(config)
        self.cooldowns = CooldownService(session, config)
        self.kills = KillSwitchService(session, config)

    def evaluate_tradeable(
        self,
        sig: StrategySignal,
        *,
        cycle_run_id: str,
        session_state,
        account,
        equity: float,
        cash: float,
        buckets,
        candidates,
        positions,
        daily_pl_pct: float = 0,
        drawdown_pct: float = 0,
    ) -> tuple[Optional[ApprovedCandidate], str, Optional[dict]]:
        """Returns (candidate, final_status, meta) or (None, blocked_status, meta)."""
        asset_class = sig.asset_class or "crypto"
        signal_type = (sig.signal_type or "entry").lower()
        meta = dict(sig.signal_metadata or {})

        try:
            tier_info = self.tiers.classify(sig.symbol)
            if signal_type == "entry" and not tier_info.trade_eligible:
                return None, "blocked", {
                    "block_reason_code": "ENGINE_BOUNDARY_BLOCKED",
                    "invalidation_reason": tier_info.watch_only_reason,
                }
        except EngineBoundaryBlocked as exc:
            return None, "blocked", {"block_reason_code": "ENGINE_BOUNDARY_BLOCKED", "invalidation_reason": str(exc)}

        tier = tier_info.tier
        meta["tier"] = tier

        ok, cd_reason, _ = self.cooldowns.check_symbol(sig.symbol)
        if not ok and signal_type == "entry":
            return None, "blocked", {"block_reason_code": "SYMBOL_COOLDOWN_ACTIVE", "invalidation_reason": cd_reason}
        ok_acct, acct_reason, _ = self.cooldowns.check_account()
        if not ok_acct and signal_type == "entry":
            return None, "blocked", {"block_reason_code": "ACCOUNT_COOLDOWN_ACTIVE", "invalidation_reason": acct_reason}

        entries_ok, kills = self.kills.evaluate(equity=equity, daily_pl_pct=daily_pl_pct, drawdown_pct=drawdown_pct)
        if not entries_ok and signal_type == "entry":
            return None, "blocked", {
                "block_reason_code": "KILL_SWITCH_ACTIVE",
                "invalidation_reason": kills[0].get("message") if kills else "Kill switch active",
            }

        quote_sym = _quote_symbol(sig, asset_class)
        quote = self.alpaca.get_quote(quote_sym, asset_class)
        is_exit = signal_type == "exit"
        if is_exit or sig.side == "sell":
            entry = quote["bid"] if quote else None
        elif sig.side in ("buy", "buy_spread"):
            entry = quote["ask"] if quote else None
        else:
            entry = quote.get("mid") if quote else None
        if entry is None:
            return None, "blocked", {"block_reason_code": "DATA_MISSING", "invalidation_reason": "No quote"}

        spread_pct = meta.get("spread_pct")
        candidate_row = next((c for c in candidates if c.symbol == sig.symbol), None)
        if spread_pct is None and candidate_row:
            spread_pct = candidate_row.spread_pct
        if spread_pct is None and quote:
            spread_pct = quote.get("spread_pct")

        expected_move = meta.get("expected_move_pct")
        if expected_move is None and meta.get("expected_edge") is not None:
            expected_move = abs(float(meta["expected_edge"])) * 100
        if expected_move is None and meta.get("momentum_1h") is not None:
            expected_move = abs(float(meta["momentum_1h"])) * 100

        cost = evaluate_cost_edge(
            self.config,
            expected_move_pct=expected_move,
            spread_pct=spread_pct,
            tier=tier,
        )
        meta["cost_edge"] = cost.evidence
        if not cost.passed and signal_type == "entry":
            return None, "blocked", {
                "block_reason_code": cost.block_reason_code,
                "invalidation_reason": cost.human_reason,
                "evidence": cost.evidence,
            }

        bars = self.alpaca.get_crypto_bars(quote_sym, timeframe="1Hour", limit=20) if asset_class == "crypto" else []
        reserve_pct = _stage_portfolio_value(self.config, "reserve_cash_pct", 60.0)
        crypto_remaining = buckets.crypto_night_bucket if hasattr(buckets, "crypto_night_bucket") else equity * 0.3
        pos_qty = broker_position_qty(positions, sig.symbol)
        total_crypto = sum(abs(p.market_value or 0) for p in positions if p.symbol)

        sizing = evaluate_atr_sizing(
            self.config,
            equity=equity,
            entry_price=entry,
            side="buy" if "buy" in sig.side else "sell",
            tier=tier,
            bars=bars,
            spread_pct=spread_pct,
            crypto_bucket_remaining=crypto_remaining,
            buying_power=account.buying_power if account else 0,
            reserve_cash_pct=reserve_pct,
            total_crypto_exposure=total_crypto,
        )
        if not sizing.passed and signal_type == "entry":
            return None, "blocked", {
                "block_reason_code": sizing.block_reason_code,
                "invalidation_reason": sizing.human_reason,
                "evidence": sizing.evidence,
            }

        stop = sizing.stop_loss_price or sig.stop_loss or (entry * 0.985)
        qty = sizing.position_qty if not is_exit else min(sizing.position_qty or pos_qty, pos_qty)
        if is_exit:
            qty = pos_qty

        proposal = TradeProposal(
            symbol=sig.symbol,
            side="buy" if "buy" in sig.side else "sell",
            quantity=qty or 0,
            entry_price=entry,
            stop_loss=stop,
            take_profit=sig.take_profit,
            strategy=sig.strategy,
            spread_pct=spread_pct,
            liquidity_score=candidate_row.liquidity_score if candidate_row else None,
            asset_class=asset_class,
            signal_id=sig.id,
            signal_confidence=sig.confidence,
            cycle_run_id=cycle_run_id,
            signal_type=signal_type,
            broker_position_qty=pos_qty,
            expected_edge=cost.edge_over_cost,
            volatility=meta.get("volatility"),
        )
        decision = self.risk.evaluate(proposal, session_state=session_state)
        if not decision.approved:
            return None, "blocked", {
                "block_reason_code": decision.block_reason_code,
                "invalidation_reason": decision.human_reason,
            }

        cand = ApprovedCandidate(
            signal_id=sig.id,
            symbol=sig.symbol,
            side=proposal.side,
            signal_type=signal_type,
            meta=meta,
            strength=sig.strength,
            confidence=sig.confidence,
            spread_pct=spread_pct,
            liquidity_score=candidate_row.liquidity_score if candidate_row else None,
            edge_over_cost=cost.edge_over_cost,
            expected_move_pct=expected_move,
            position_qty=qty or 0,
            entry_price=entry,
            stop_loss=stop,
            atr14=sizing.atr14,
            tier=tier,
            cost_evidence=cost.evidence,
            sizing_evidence=sizing.evidence,
        )
        return cand, "risk_approved", {"cost": cost.evidence, "sizing": sizing.evidence}
