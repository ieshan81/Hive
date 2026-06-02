"""Phase 3 verifier: paper_trade_protections fails CLOSED on missing context (entries only).

Proves: a DB/context read failure (or no session) marks the context degraded, and run_all_protections
then BLOCKS new entries with PROTECTIONS_DEGRADED_FAIL_CLOSED (codes include DB_CONTEXT_UNAVAILABLE /
PAPER_PROTECTION_CONTEXT_UNAVAILABLE). A clean context still passes (entries not over-blocked), and
the degraded state is visible in diagnostics. Exits are never gated by this module.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.paper_trade_protections import (  # noqa: E402
    ProtectionContext,
    collect_protection_context,
    run_all_protections,
)


class _RaisingSession:
    def exec(self, *a, **k):
        raise RuntimeError("simulated DB read failure")


def main() -> None:
    # 1) Degraded context -> entries blocked, fail-closed, with visible diagnostics.
    ctx = ProtectionContext(symbol="BTC/USD", degraded=True, degraded_reason="DB_CONTEXT_UNAVAILABLE:OperationalError")
    res = run_all_protections(ctx, {})
    assert res.blocked and res.code == "PROTECTIONS_DEGRADED_FAIL_CLOSED", f"degraded ctx not fail-closed: {res.code}"
    assert res.evidence.get("protections_degraded") is True, "degraded not visible in diagnostics"
    assert "DB_CONTEXT_UNAVAILABLE" in res.evidence.get("blocker_codes", []), "missing DB_CONTEXT_UNAVAILABLE code"
    assert res.evidence.get("exits_allowed") is True, "exits must remain allowed"

    # 2) collect_protection_context with a failing session -> degraded (intended fail-closed path).
    ctx2 = collect_protection_context(_RaisingSession(), {}, symbol="BTC/USD")
    assert ctx2.degraded is True and "DB_CONTEXT_UNAVAILABLE" in (ctx2.degraded_reason or ""), \
        f"DB read failure not degraded: {ctx2.degraded_reason}"
    assert run_all_protections(ctx2, {}).blocked, "degraded-from-DB-failure must block entries"

    # 3) No session -> context unavailable -> degraded.
    ctx3 = collect_protection_context(None, {}, symbol="X")
    assert ctx3.degraded is True, "missing session must degrade (fail-closed)"

    # 4) Clean (non-degraded) context with no issues -> NOT blocked (entries not over-blocked).
    clean = ProtectionContext(symbol="BTC/USD")
    assert not run_all_protections(clean, {}).blocked, "clean context must pass (entries allowed)"

    # 5) Configurable: fail_closed_on_degraded=False -> degraded does NOT block (proves it's the new gate).
    cfg_off = {"autonomous_paper_learning": {"protections": {"fail_closed_on_degraded": False}}}
    assert not run_all_protections(ctx, cfg_off).blocked, "fail_closed_on_degraded=False should not block"

    print("verify_paper_trade_protections_fail_closed: PASS (degraded->entries blocked; exits allowed; clean passes; configurable)")


if __name__ == "__main__":
    main()
