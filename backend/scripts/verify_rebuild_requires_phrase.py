"""Phase 1 verifier: /api/rebuild is phrase-protected and validation-run-guarded.

Proves: rebuild without phrase / wrong phrase is refused; during an active validation run it is
refused unless a valid override is supplied; and DangerZoneService.nuke_everything() is NOT called
on any refused request. No live flags changed, no orders submitted.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    import app.services.rebuild_guard as rg

    PHRASE = rg.REBUILD_CONFIRMATION_PHRASE

    # --- decision logic (session unused once _active_validation_run is stubbed) ---
    rg._active_validation_run = lambda s: None  # no active run
    assert not rg.evaluate_rebuild_request(None, confirmation_phrase="")["allowed"], "empty phrase must refuse"
    assert "CONFIRMATION_PHRASE_REQUIRED" in rg.evaluate_rebuild_request(None, confirmation_phrase="")["refusal_codes"]
    assert not rg.evaluate_rebuild_request(None, confirmation_phrase="wrong")["allowed"], "wrong phrase must refuse"
    assert rg.evaluate_rebuild_request(None, confirmation_phrase=PHRASE)["allowed"], "correct phrase, no run -> allowed"

    rg._active_validation_run = lambda s: "paper_validation_run_001"  # active validation run
    r = rg.evaluate_rebuild_request(None, confirmation_phrase=PHRASE)  # phrase ok but no override
    assert not r["allowed"] and "REBUILD_BLOCKED_DURING_VALIDATION" in r["refusal_codes"], "active run must block w/o override"
    assert "VALIDATION_RUN_OVERRIDE_REQUIRED" in r["refusal_codes"]
    r = rg.evaluate_rebuild_request(None, confirmation_phrase=PHRASE,
                                    validation_run_override_reason="external audit rebuild", engines_stopped_ack=True)
    assert r["allowed"], "valid override during run must be allowed"
    # override reason without engines-stopped ack is NOT valid
    assert not rg.evaluate_rebuild_request(None, confirmation_phrase=PHRASE,
                                           validation_run_override_reason="x", engines_stopped_ack=False)["allowed"]

    # --- full_rebuild must NOT reach nuke_everything on refusal ---
    import app.services.danger_zone_service as dz
    calls = {"n": 0}
    real = dz.DangerZoneService.nuke_everything

    def _fake_nuke(self, *a, **k):
        calls["n"] += 1
        return {"status": "ok", "mocked": True}

    dz.DangerZoneService.nuke_everything = _fake_nuke
    try:
        from sqlmodel import Session

        from app.database import engine
        from app.v2 import rebuild as rb

        rg._active_validation_run = lambda s: None  # default: no run (sqlite empty)
        with Session(engine) as s:
            out = rb.full_rebuild(s, confirmation_phrase="")  # no phrase
        assert out.get("status") == "refused", f"no-phrase rebuild not refused: {out.get('status')}"
        assert out.get("nuke_called") is False and out.get("orders_created") == 0
        assert out.get("live_trading_locked") is True, "refusal must keep live locked"
        assert calls["n"] == 0, "nuke_everything was called on a refused (no-phrase) rebuild!"

        rg._active_validation_run = lambda s: "paper_validation_run_001"  # active run
        with Session(engine) as s:
            out2 = rb.full_rebuild(s, confirmation_phrase=PHRASE)  # phrase ok, no override
        assert out2.get("status") == "refused" and "REBUILD_BLOCKED_DURING_VALIDATION" in out2.get("refusal_codes", [])
        assert calls["n"] == 0, "nuke_everything was called during a refused validation-run rebuild!"
    finally:
        dz.DangerZoneService.nuke_everything = real

    print("verify_rebuild_requires_phrase: PASS (refused without phrase / during run; nuke_everything not called; live locked; 0 orders)")


if __name__ == "__main__":
    main()
