"""A hypothesis memory cannot influence trading until it has a linked backtest.

Hypothesis (no backtest) -> cannot influence trading. A backtest-class memory with a backtest link
-> may influence. This enforces RawEvent→Hypothesis→Backtest→Paper ordering: ideas must be tested.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import LessonNode  # noqa: E402
from app.services.memory_governance_service import MemoryGovernanceService as MG  # noqa: E402


def lz(memory_type, related_type=None, related_id=None, evidence=None):
    return LessonNode(memory_type=memory_type, title="t", summary="s",
                      related_entity_type=related_type, related_entity_id=related_id,
                      evidence_json=evidence or {})


def main() -> None:
    # Hypothesis classified as hypothesis; never influences trading.
    h = lz("hypothesis_momentum_idea")
    assert MG.classify(h) == "hypothesis", MG.classify(h)
    assert MG.has_backtest_link(h) is False
    assert MG.can_influence_trading(h) is False, "hypothesis without backtest must not influence trading"

    # A hypothesis that *claims* a backtest link is still a hypothesis class -> still cannot trade
    # directly; it must first become a backtest/validated memory.
    h2 = lz("hypothesis_momentum_idea", evidence={"backtest_run_id": "bt1"})
    assert MG.can_influence_trading(h2) is False, "hypothesis class never trades; must be promoted to backtest/validated"

    # Backtest-class memory with a backtest link -> may influence (the gate opens after testing).
    b = lz("backtest_result_memory", evidence={"backtest_run_id": "bt1"})
    assert MG.classify(b) == "backtest", MG.classify(b)
    assert MG.has_backtest_link(b) is True
    assert MG.can_influence_trading(b) is True, "evidence-linked backtest memory may influence ranking"

    # Backtest-class memory WITHOUT a link -> cannot influence (no proof).
    b2 = lz("backtest_result_memory")
    assert MG.can_influence_trading(b2) is False
    print("verify_memory_hypothesis_requires_backtest: PASS (hypothesis gated; backtest evidence opens the gate)")


if __name__ == "__main__":
    main()
