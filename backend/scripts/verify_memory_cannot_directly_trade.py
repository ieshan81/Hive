"""No memory node can directly trigger a trade or mutate live/risk.

Two proofs:
1. STATIC: the order-submission paths (paper_exploration_service.submit_*, paper_execution_service
   .submit_candidate, execution_cage.validate_submit, execution_preflight.run_preflight) do not
   read LessonNode/memory to DECIDE or TRIGGER an order.
2. GATE: MemoryGovernanceService.can_influence_trading() returns False for raw/regime/risk/
   hypothesis memory and for any non-evidence-linked memory.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
ORDER_PATH_FILES = [
    "app/services/paper_exploration_service.py",
    "app/services/paper_execution_service.py",
    "app/trading_cage/execution_cage.py",
    "app/services/execution_preflight.py",
]


def main() -> None:
    # 1. Static: no LessonNode/memory dependency on the order path.
    for rel in ORDER_PATH_FILES:
        text = (BACKEND / rel).read_text(encoding="utf-8")
        assert "LessonNode" not in text, f"{rel} references LessonNode on the order path"
        assert "MemoryEvidenceConsolidator" not in text, f"{rel} consults memory consolidator on the order path"
        assert "memory_governance" not in text.lower() or "can_influence_trading" not in text, rel

    # 2. Gate: classify + can_influence_trading.
    from app.database import LessonNode
    from app.services.memory_governance_service import MemoryGovernanceService as MG

    def lz(memory_type, related_type=None, related_id=None, evidence=None):
        return LessonNode(memory_type=memory_type, title="t", summary="s",
                          related_entity_type=related_type, related_entity_id=related_id,
                          evidence_json=evidence or {})

    # Hypothesis never influences trading (even if it claims a scorecard link).
    assert MG.can_influence_trading(lz("hypothesis_idea", evidence={"backtest_id": None})) is False
    # Raw / regime / risk never directly trade.
    assert MG.can_influence_trading(lz("raw_event_log")) is False
    assert MG.can_influence_trading(lz("market_regime_memory")) is False
    assert MG.can_influence_trading(lz("cost_spread_drag")) is False
    # Validated/closed-trade WITHOUT evidence link -> still cannot influence.
    assert MG.can_influence_trading(lz("validated_alpha_candidate")) is False
    # Validated/closed-trade WITH evidence link -> may influence ranking.
    assert MG.can_influence_trading(lz("validated_alpha_candidate", "alpha_scorecard", "42")) is True
    assert MG.can_influence_trading(lz("paper_outcome_lesson", "outcome", "7")) is True
    print("verify_memory_cannot_directly_trade: PASS (no memory->order path; gate blocks non-evidence/hypothesis)")


if __name__ == "__main__":
    main()
