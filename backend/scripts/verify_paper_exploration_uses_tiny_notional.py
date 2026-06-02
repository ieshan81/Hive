"""Exploration probes are tiny: notional never exceeds the configured cap, and the cage
recognises the probe so it applies the hard notional cap."""

from _alpha_factory_verify_common import session_with_config  # noqa: E402

from app.trading_cage.execution_cage import _exploration_max_notional, _is_near_miss_exploration_probe  # noqa: E402
from app.services.paper_exploration_service import PaperExplorationService  # noqa: E402
from verify_near_miss_can_be_paper_exploration_candidate import nm  # noqa: E402


def main() -> None:
    session, cfg = session_with_config()
    svc = PaperExplorationService(session, cfg)
    cap = svc.max_notional_usd
    assert 0 < cap <= svc.cap_max_usd, f"exploration cap must stay within the operator ceiling, got {cap}"
    assert svc.cap_max_usd <= 25.0, f"cap ceiling must stay tiny, got {svc.cap_max_usd}"

    for price in (1.0, 100.0, 65000.0):
        cand = svc.build_probe_candidate(nm(), price=price)
        notional = cand.position_qty * price
        assert 0 < notional <= cap + 1e-9, (price, notional, cap)

    cand = svc.build_probe_candidate(nm(), price=100.0)
    assert _is_near_miss_exploration_probe(cfg, cand) is True, "cage must recognise the probe to cap it"
    assert _exploration_max_notional(cfg) == cap, (_exploration_max_notional(cfg), cap)
    print(f"verify_paper_exploration_uses_tiny_notional: PASS (cap ${cap})")


if __name__ == "__main__":
    main()
