"""Verify Top-1 portfolio gate defers extra entries with TOP_N_LIMIT."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.default_config import DEFAULT_CONFIG
from app.services.portfolio_gate import ApprovedCandidate, PortfolioGate, compute_ranking_score


class FakeSession:
    def add(self, _):
        pass


def test_top_n_defer():
    config = DEFAULT_CONFIG
    gate = PortfolioGate(FakeSession(), config, alpaca=None)
    cycle_id = "test-cycle"
    cands = []
    for i, sym in enumerate(["ARB/USD", "UNI/USDC", "SUSHI/USDT", "LINK/USDT"]):
        cands.append(
            ApprovedCandidate(
                signal_id=i + 1,
                symbol=sym,
                side="buy",
                signal_type="entry",
                meta={"momentum_1h": 0.01 - i * 0.001},
                strength=1.0 - i * 0.1,
                confidence=0.8,
                spread_pct=0.001,
                liquidity_score=80,
                edge_over_cost=2.5 - i * 0.2,
                expected_move_pct=1.0,
                position_qty=0.1,
                entry_price=10.0,
                stop_loss=9.5,
                atr14=0.2,
                tier="TIER_ALT",
                cost_evidence={},
                sizing_evidence={},
            )
        )
    result = gate.run(
        cycle_id,
        cands,
        equity=200,
        cash=120,
        buying_power=200,
        positions=[],
        open_order_symbols=set(),
        promotion_stage="PAPER",
    )
    selected = [d for d in result.decisions if d.selected_for_execution]
    deferred = [d for d in result.decisions if d.portfolio_reason_code == "TOP_N_LIMIT"]
    assert len(selected) == 1, f"expected 1 selected, got {len(selected)}"
    assert len(deferred) == 3, f"expected 3 deferred TOP_N, got {len(deferred)}"
    print("verify_portfolio_gate_top1: PASS")


if __name__ == "__main__":
    test_top_n_defer()
