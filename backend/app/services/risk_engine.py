"""Risk engine — final authority. Strategy cannot bypass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, select

from app.database import BlockedTrade, PositionSnapshot, RiskEvent, TradeRecord
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.config_manager import ConfigManager


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


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)


class RiskEngine:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.alpaca = AlpacaAdapter(session)

    def evaluate(self, proposal: TradeProposal) -> RiskDecision:
        reasons: list[str] = []
        checks: dict[str, bool] = {}

        def fail(check: str, reason: str) -> None:
            checks[check] = False
            reasons.append(reason)

        def pass_check(check: str) -> None:
            checks[check] = True

        if self.config.get("kill_switch_active"):
            fail("kill_switch", "Kill switch is active")
            return RiskDecision(approved=False, reasons=reasons, checks=checks)

        if self.config.get("live_trading_enabled"):
            fail("live_trading", "Live trading is disabled in MVP")

        if self.config.get("stop_loss_required") and proposal.stop_loss is None:
            fail("stop_loss", "Stop-loss required on all positions")

        if proposal.take_profit is None and self.config.get("take_profit_required"):
            fail("exit_logic", "Exit logic (take profit) required")

        quote = self.alpaca.get_latest_quote(proposal.symbol)
        spread = proposal.spread_pct
        if quote and quote.get("spread_pct") is not None:
            spread = quote["spread_pct"]
        max_spread = self.config.get("max_spread_pct", 0.005)
        if spread is not None and spread > max_spread:
            fail("spread", f"Spread too wide: {spread:.4f} > {max_spread:.4f}")
        else:
            pass_check("spread")

        liquidity = proposal.liquidity_score
        min_liq = self.config.get("min_liquidity_score", 40)
        if liquidity is not None and liquidity < min_liq:
            fail("liquidity", f"Liquidity too low: {liquidity} < {min_liq}")
        else:
            pass_check("liquidity")

        account = self.alpaca.sync_account()
        if account is None:
            fail("alpaca_connection", "Alpaca connection unstable or not configured")
            return RiskDecision(approved=False, reasons=reasons, checks=checks)
        pass_check("alpaca_connection")

        if proposal.entry_price and account.buying_power < proposal.entry_price * proposal.quantity:
            fail("buying_power", "Insufficient buying power")
        else:
            pass_check("buying_power")

        max_pos_pct = self.config.get("max_position_size_pct", 0.25)
        if proposal.entry_price:
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
        weekly_loss = self._weekly_loss()
        if weekly_loss >= weekly_limit:
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
            if state and state.status == "cooling_down":
                fail("strategy_cooling", f"Strategy {proposal.strategy} is cooling down")

        loss_streak = self._loss_streak(proposal.strategy)
        max_streak = self.config.get("max_loss_streak", 5)
        if loss_streak >= max_streak:
            fail("loss_streak", f"Loss streak ({loss_streak}) too high")
        else:
            pass_check("loss_streak")

        assets = self.alpaca.get_tradable_assets()
        asset_map = {a["symbol"]: a for a in assets}
        asset = asset_map.get(proposal.symbol)
        if assets and asset is None:
            fail("tradable", f"Symbol {proposal.symbol} not tradable")
        elif asset and not asset.get("tradable"):
            fail("tradable", f"Symbol {proposal.symbol} not tradable")
        else:
            pass_check("tradable")

        if proposal.fractionable_required and asset and not asset.get("fractionable"):
            fail("fractionable", f"Symbol {proposal.symbol} not fractionable")

        if not proposal.entry_price or not proposal.stop_loss:
            if "stop_loss" not in checks:
                pass_check("data_complete")
        else:
            pass_check("data_complete")

        approved = len(reasons) == 0
        if not approved:
            self._log_blocked(proposal, reasons, checks)
        return RiskDecision(approved=approved, reasons=reasons, checks=checks)

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

    def _log_blocked(self, proposal: TradeProposal, reasons: list[str], checks: dict) -> None:
        row = BlockedTrade(
            symbol=proposal.symbol,
            strategy=proposal.strategy,
            side=proposal.side,
            reason="; ".join(reasons),
            risk_checks_failed=[k for k, v in checks.items() if not v],
            proposed_qty=proposal.quantity,
        )
        self.session.add(row)
        event = RiskEvent(
            event_type="trade_blocked",
            severity="warning",
            message=f"Blocked {proposal.side} {proposal.symbol}: {'; '.join(reasons)}",
            details={"checks": checks},
        )
        self.session.add(event)
        self.session.commit()
