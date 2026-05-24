"""Memory penalty lowers ranking score but cannot unblock portfolio-blocked trades."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import LessonNode, init_db, engine
from app.services.default_config import DEFAULT_CONFIG
from app.services.lesson_memory_service import LessonMemoryService
from app.services.portfolio_gate import ApprovedCandidate, PortfolioGate, compute_ranking_score
from sqlmodel import Session


class FakePosition:
    def __init__(self, symbol: str, qty: float = 100.0, market_value: float = 30.0):
        self.symbol = symbol
        self.qty = qty
        self.market_value = market_value


class FakeSession:
    def __init__(self, real_session):
        self._real = real_session

    def add(self, obj):
        self._real.add(obj)

    def exec(self, *a, **k):
        return self._real.exec(*a, **k)

    def flush(self):
        self._real.flush()


def test():
    init_db()
    with Session(engine) as session:
        svc = LessonMemoryService(session, DEFAULT_CONFIG)
        for _ in range(5):
            svc.upsert_lesson(
                memory_type="blocked_trade_pattern",
                title="Spread block",
                summary="blocked",
                detailed_lesson="test",
                severity="CRITICAL",
                symbol="DOGE/USD",
                pattern_key="risk_block|DOGE/USD|SPREAD_TOO_WIDE",
                aggregate=True,
            )
        session.commit()
        pen = svc.symbol_memory_penalty("DOGE/USD")
        assert pen > 0

        cand = ApprovedCandidate(
            signal_id=1,
            symbol="DOGE/USD",
            side="buy",
            signal_type="entry",
            meta={"momentum_1h": 0.05},
            strength=1.0,
            confidence=0.95,
            spread_pct=0.001,
            liquidity_score=90,
            edge_over_cost=5.0,
            expected_move_pct=2.0,
            position_qty=10,
            entry_price=0.1,
            stop_loss=0.09,
            atr14=0.01,
            tier="TIER_ALT",
            cost_evidence={},
            sizing_evidence={},
        )
        score_no_pen, _ = compute_ranking_score(DEFAULT_CONFIG, cand, memory_penalty=0)
        score_pen, _ = compute_ranking_score(DEFAULT_CONFIG, cand, memory_penalty=pen)
        assert score_pen < score_no_pen

        gate = PortfolioGate(FakeSession(session), DEFAULT_CONFIG, alpaca=None)
        result = gate.run(
            "test-cycle",
            [cand],
            equity=500,
            cash=400,
            buying_power=500,
            positions=[FakePosition("DOGE/USD")],
            open_order_symbols=set(),
            promotion_stage="PAPER",
        )
        decision = result.decisions[0]
        assert decision.portfolio_reason_code == "DUPLICATE_SYMBOL_POSITION"
        assert not decision.selected_for_execution
        print("verify_memory_does_not_bypass_risk: PASS")


if __name__ == "__main__":
    test()
