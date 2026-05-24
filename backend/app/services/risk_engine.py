"""Risk engine — final authority. Strategy cannot bypass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import BlockedTrade, PositionSnapshot, RiskEvent, TradeRecord
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.config_manager import ConfigManager
from app.services.risk_codes import CHECK_TO_CODE, CHECK_TO_RULE, primary_block_code
from app.services.session_engine import SessionState


@dataclass
class TradeProposal:
    symbol: str
    side: str
    quantity: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strategy: Optional[str] = None
    expected_edge: Optional[float] = None
    spread_pct: Optional[float] = None
    liquidity_score: Optional[float] = None
    fractionable_required: bool = False
    asset_class: str = "stock"
    signal_id: Optional[int] = None
    signal_confidence: Optional[float] = None
    cycle_run_id: Optional[str] = None


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    block_reason_code: Optional[str] = None
    human_reason: Optional[str] = None
    risk_rule: Optional[str] = None


class RiskEngine:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)

    def _quote_symbol(self, proposal: TradeProposal) -> str:
        if proposal.asset_class == "crypto":
            return normalize_crypto_symbol(proposal.symbol)
        if "/" in proposal.symbol and proposal.strategy == "mean_reversion_pairs":
            return proposal.symbol.split("/")[0]
        return proposal.symbol.split("/")[0]

    def log_block(
        self,
        symbol: str,
        strategy: Optional[str],
        side: str,
        reason: str,
        check_name: str,
        *,
        signal_id: Optional[int] = None,
        cycle_run_id: Optional[str] = None,
        evidence: Optional[dict] = None,
    ) -> None:
        code = CHECK_TO_CODE.get(check_name, "RISK_BLOCKED")
        proposal = TradeProposal(
            symbol=symbol,
            side=side,
            quantity=0,
            strategy=strategy,
            signal_id=signal_id,
            cycle_run_id=cycle_run_id,
        )
        checks = {check_name: False}
        self._log_blocked(
            proposal,
            [reason],
            checks,
            block_reason_code=code,
            human_reason=reason,
            risk_rule=CHECK_TO_RULE.get(check_name, check_name),
            evidence=evidence or {},
        )

    def evaluate(
        self,
        proposal: TradeProposal,
        session_state: Optional[SessionState] = None,
    ) -> RiskDecision:
        reasons: list[str] = []
        checks: dict[str, bool] = {}

        def fail(check: str, reason: str) -> None:
            checks[check] = False
            reasons.append(reason)

        def pass_check(check: str) -> None:
            checks[check] = True

        if session_state and not session_state.stock_trading_allowed and proposal.asset_class == "stock":
            fail("market_session", "US stock market closed for this asset class")
            return self._finalize(proposal, reasons, checks)

        if session_state and not session_state.crypto_trading_allowed and proposal.asset_class == "crypto":
            fail("market_session", "Crypto trading not allowed in current session")
            return self._finalize(proposal, reasons, checks)

        if self.config.get("kill_switch_active"):
            fail("kill_switch", "Kill switch is active")
            return self._finalize(proposal, reasons, checks)

        if self.config.get("live_trading_enabled"):
            fail("live_trading", "Live trading is disabled in MVP")

        if self.config.get("stop_loss_required") and proposal.stop_loss is None:
            fail("stop_loss", "Stop-loss required on all positions")

        if proposal.take_profit is None and self.config.get("take_profit_required"):
            fail("exit_logic", "Exit logic (take profit) required")

        min_conf = self.config.get("confidence_threshold", 0.6)
        if proposal.signal_confidence is not None and proposal.signal_confidence < min_conf:
            fail(
                "confidence",
                f"Signal confidence {proposal.signal_confidence:.3f} below threshold {min_conf}",
            )

        quote_sym = self._quote_symbol(proposal)
        quote = self.alpaca.get_quote(quote_sym, proposal.asset_class)
        if quote is None or quote.get("bid") is None or quote.get("ask") is None:
            fail("no_quote", "No quote available")
            return self._finalize(proposal, reasons, checks)
        pass_check("no_quote")

        spread = proposal.spread_pct if proposal.spread_pct is not None else quote.get("spread_pct")
        max_spread = self.config.get("max_spread_pct", 0.005)
        if spread is None:
            fail("spread", "Cannot compute spread")
        elif spread > max_spread:
            fail("spread", f"Spread too wide: {spread:.4f} > {max_spread:.4f}")
        else:
            pass_check("spread")

        min_liq = self.config.get("min_liquidity_score", 40)
        if proposal.liquidity_score is not None and proposal.liquidity_score < min_liq:
            fail("liquidity", f"Liquidity too low: {proposal.liquidity_score} < {min_liq}")
        else:
            pass_check("liquidity")

        account = self.alpaca.sync_account()
        if account is None:
            fail("alpaca_connection", "Alpaca connection unstable or not configured")
            return self._finalize(proposal, reasons, checks)
        pass_check("alpaca_connection")

        if proposal.entry_price and account.buying_power < proposal.entry_price * proposal.quantity:
            fail("buying_power", "Insufficient buying power")
        else:
            pass_check("buying_power")

        max_pos_pct = self.config.get("max_position_size_pct", 0.25)
        if proposal.entry_price and proposal.quantity > 0:
            pos_value = proposal.entry_price * proposal.quantity
            if account.equity > 0 and pos_value / account.equity > max_pos_pct:
                fail("position_size", f"Max position size exceeded ({max_pos_pct:.0%})")
            else:
                pass_check("position_size")

        open_positions = len(
            self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()
        )
        max_open = self.config.get("max_open_positions", 2)
        if open_positions >= max_open:
            fail("max_open_positions", f"Max open positions ({max_open}) reached")
        else:
            pass_check("max_open_positions")

        daily_limit = self.config.get("daily_loss_limit_pct", 0.02) * account.equity
        if account.daily_pl < 0 and abs(account.daily_pl) >= daily_limit:
            fail("daily_loss_limit", "Daily loss limit exceeded")
        else:
            pass_check("daily_loss_limit")

        weekly_limit = self.config.get("weekly_loss_limit_pct", 0.05) * account.equity
        if self._weekly_loss() >= weekly_limit:
            fail("weekly_loss_limit", "Weekly loss limit exceeded")
        else:
            pass_check("weekly_loss_limit")

        max_dd = self.config.get("max_drawdown_limit_pct", 0.15)
        if account.drawdown_pct / 100 >= max_dd:
            fail("drawdown_limit", "Drawdown limit exceeded")
        else:
            pass_check("drawdown_limit")

        if proposal.strategy:
            from app.database import StrategyState

            state = self.session.exec(
                select(StrategyState).where(StrategyState.strategy == proposal.strategy)
            ).first()
            if state and state.status == "inactive":
                fail("strategy_inactive", f"Strategy {proposal.strategy} is inactive: {state.status_reason or ''}")
            elif state and state.status == "cooling_down":
                fail("strategy_cooling", f"Strategy {proposal.strategy} is cooling down")

        if self._loss_streak(proposal.strategy) >= self.config.get("max_loss_streak", 5):
            fail("loss_streak", "Loss streak too high")
        else:
            pass_check("loss_streak")

        assets = self.alpaca.get_tradable_assets(asset_class=proposal.asset_class, limit=500)
        sym = quote_sym.replace("/", "")
        asset_map = {a["symbol"]: a for a in assets}
        asset_map.update({a["symbol"].replace("/", ""): a for a in assets})
        lookup = proposal.symbol if proposal.symbol in asset_map else sym
        if assets and lookup not in asset_map and proposal.symbol not in asset_map:
            fail("tradable", f"Symbol {proposal.symbol} not tradable")
        elif lookup in asset_map and not asset_map[lookup].get("tradable"):
            fail("tradable", f"Symbol {proposal.symbol} not tradable")
        else:
            pass_check("tradable")

        if (
            proposal.fractionable_required
            and lookup in asset_map
            and not asset_map[lookup].get("fractionable")
        ):
            fail("fractionable", f"Symbol {proposal.symbol} not fractionable")

        approved = len(reasons) == 0
        if not approved:
            return self._finalize(proposal, reasons, checks)
        return RiskDecision(approved=True, reasons=[], checks=checks)

    def _finalize(
        self,
        proposal: TradeProposal,
        reasons: list[str],
        checks: dict[str, bool],
    ) -> RiskDecision:
        failed = [k for k, v in checks.items() if not v]
        primary = failed[0] if failed else "unknown"
        code = primary_block_code(failed)
        human = "; ".join(reasons) if reasons else "Blocked by risk engine"
        rule = CHECK_TO_RULE.get(primary, primary)
        self._log_blocked(
            proposal,
            reasons,
            checks,
            block_reason_code=code,
            human_reason=human,
            risk_rule=rule,
            evidence={"failed_checks": failed, "quote_symbol": self._quote_symbol(proposal)},
        )
        return RiskDecision(
            approved=False,
            reasons=reasons,
            checks=checks,
            block_reason_code=code,
            human_reason=human,
            risk_rule=rule,
        )

    def _weekly_loss(self) -> float:
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(days=7)
        trades = self.session.exec(
            select(TradeRecord).where(TradeRecord.closed_at >= cutoff)
        ).all()
        return abs(sum(t.pl_dollars or 0 for t in trades if (t.pl_dollars or 0) < 0))

    def _loss_streak(self, strategy: Optional[str]) -> int:
        q = select(TradeRecord).where(TradeRecord.status == "closed").order_by(TradeRecord.closed_at.desc())
        if strategy:
            q = q.where(TradeRecord.strategy == strategy)
        trades = self.session.exec(q.limit(20)).all()
        streak = 0
        for t in trades:
            if (t.pl_dollars or 0) < 0:
                streak += 1
            else:
                break
        return streak

    def _log_blocked(
        self,
        proposal: TradeProposal,
        reasons: list[str],
        checks: dict[str, bool],
        *,
        block_reason_code: str,
        human_reason: str,
        risk_rule: str,
        evidence: Optional[dict] = None,
    ) -> None:
        failed_checks = [k for k, v in checks.items() if not v]
        engine_result: dict[str, Any] = {
            "approved": False,
            "reasons": reasons,
            "checks": checks,
            "block_reason_code": block_reason_code,
            "human_reason": human_reason,
            "risk_rule": risk_rule,
        }
        evidence_payload = {
            **(evidence or {}),
            "strategy": proposal.strategy,
            "signal_id": proposal.signal_id,
            "cycle_run_id": proposal.cycle_run_id,
            "symbol": proposal.symbol,
            "side": proposal.side,
            "quantity": proposal.quantity,
            "spread_pct": proposal.spread_pct,
            "liquidity_score": proposal.liquidity_score,
            "asset_class": proposal.asset_class,
        }
        row = BlockedTrade(
            symbol=proposal.symbol,
            strategy=proposal.strategy,
            side=proposal.side,
            reason=human_reason,
            block_reason_code=block_reason_code,
            human_reason=human_reason,
            risk_rule=risk_rule,
            evidence_json=evidence_payload,
            risk_engine_result=engine_result,
            risk_checks_failed=failed_checks,
            proposed_qty=proposal.quantity,
            signal_id=proposal.signal_id,
            cycle_run_id=proposal.cycle_run_id,
        )
        self.session.add(row)
        self.session.add(
            RiskEvent(
                event_type="trade_blocked",
                severity="warning",
                message=f"{block_reason_code}: blocked {proposal.side} {proposal.symbol} — {human_reason}",
                details={
                    "block_reason_code": block_reason_code,
                    "human_reason": human_reason,
                    "risk_rule": risk_rule,
                    "risk_engine_result": engine_result,
                    "evidence": evidence_payload,
                },
            )
        )
        self.session.commit()
