"""Paper account quote-currency and symbol pair eligibility before broker submit."""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountSnapshot, ExecutionLog, SymbolCandidate
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.broker_safety import is_paper_broker_url
from app.services.lesson_memory_service import LessonMemoryService
from app.services.session_engine import CRYPTO_STRATEGIES, STOCK_STRATEGIES, SessionEngine


def parse_quote_currency(symbol: str) -> str:
    s = (symbol or "").upper().replace("USD", "USD").replace("USDT", "USDT")
    if "/" in symbol:
        return symbol.split("/")[-1].upper()
    for q in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if symbol.upper().endswith(q) and len(symbol) > len(q):
            return q
    return "USD"


class AccountPairEligibilityService:
    MIN_BALANCE = 0.01

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}
        self.alpaca = AlpacaAdapter(session)

    def _quote_balances(self) -> dict[str, float]:
        balances: dict[str, float] = {"USD": 0.0, "USDC": 0.0, "USDT": 0.0}
        snap = self.session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()
        if snap:
            balances["USD"] = max(balances["USD"], float(snap.cash or 0), float(snap.buying_power or 0))
        try:
            client = self.alpaca._get_trading_client()
            if client:
                account = client.get_account()
                balances["USD"] = max(balances["USD"], float(getattr(account, "cash", 0) or 0))
        except Exception:
            pass
        return balances

    def supported_quote_currencies(self) -> list[dict[str, Any]]:
        bal = self._quote_balances()
        out = []
        for cur, amount in bal.items():
            out.append(
                {
                    "currency": cur,
                    "available": round(amount, 4),
                    "tradeable": amount >= self.MIN_BALANCE,
                }
            )
        return out

    def classify_symbol(self, symbol: str, *, asset_class: str = "crypto") -> dict[str, Any]:
        quote = parse_quote_currency(symbol)
        bal = self._quote_balances()
        session = SessionEngine().detect()
        if asset_class == "stock" or symbol.endswith("USD") and "/" not in symbol and len(symbol) < 8:
            if not session.stock_trading_allowed:
                reason = session.us_stock_close_reason or "U.S. stock market is closed"
                return {
                    "symbol": symbol,
                    "quote_currency": quote,
                    "status": "blocked",
                    "reason": reason,
                    "category": "market_session",
                }
        available = bal.get(quote, 0.0)
        if available < self.MIN_BALANCE:
            return {
                "symbol": symbol,
                "quote_currency": quote,
                "status": "blocked",
                "reason": f"No {quote} balance in paper account. This pair is not currently tradeable.",
                "category": "account_pair_eligibility",
            }
        return {
            "symbol": symbol,
            "quote_currency": quote,
            "status": "eligible",
            "reason": f"{quote} balance available for paper trading.",
            "category": "ok",
        }

    def summary(self, symbols: Optional[list[str]] = None) -> dict[str, Any]:
        if symbols is None:
            rows = self.session.exec(select(SymbolCandidate).limit(40)).all()
            symbols = [r.symbol for r in rows if r.symbol]
        eligible, blocked = [], []
        for sym in symbols:
            ac = "crypto" if "/" in sym or "USD" in sym.upper() else "stock"
            row = self.classify_symbol(sym, asset_class=ac)
            if row["status"] == "eligible":
                eligible.append(row)
            else:
                blocked.append(row)
        return {
            "status": "ok",
            "paper_broker": is_paper_broker_url(),
            "supported_quote_currencies": self.supported_quote_currencies(),
            "eligible": eligible,
            "blocked": blocked,
            "eligible_count": len(eligible),
            "blocked_count": len(blocked),
        }

    def preflight_block(self, symbol: str, side: str = "buy", strategy_id: str = "") -> Optional[tuple[str, str]]:
        if side.lower() != "buy":
            return None
        ac = "crypto"
        if strategy_id in STOCK_STRATEGIES:
            ac = "stock"
        elif strategy_id in CRYPTO_STRATEGIES:
            ac = "crypto"
        row = self.classify_symbol(symbol, asset_class=ac)
        if row["status"] == "blocked":
            return row["category"], row["reason"]
        return None

    def record_broker_balance_reject_lesson(self, symbol: str, broker_message: str) -> None:
        if not broker_message:
            return
        low = broker_message.lower()
        if "insufficient" not in low and "balance" not in low and "available" not in low:
            return
        LessonMemoryService(self.session, self.config).upsert_lesson(
            memory_type="account_pair_eligibility",
            title=f"Pair not tradeable: {symbol}",
            summary=f"Broker rejected order — account/pair eligibility, not strategy failure. {broker_message[:200]}",
            detailed_lesson=broker_message[:500],
            symbol=symbol,
            source="broker_reject",
            can_influence_ranking=True,
            visible_to_ai=True,
            pattern_key=f"eligibility|{symbol}|balance|{__import__('datetime').datetime.utcnow().date()}",
        )
