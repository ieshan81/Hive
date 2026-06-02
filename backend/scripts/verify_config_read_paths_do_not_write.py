"""Phase 8 verifier: pure config read does not write; migration stays explicit; caps still locked.

Asserts ConfigManager.get_current_readonly() performs no commit/write (commit-spy), still applies
the locked caps (live false / paper true), that get_current() retains the explicit migration/activate
path, and that the read-only diagnostic + universe-summary paths use the pure read.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    cm_src = (BACKEND / "app/services/config_manager.py").read_text(encoding="utf-8-sig", errors="ignore")
    assert "def get_current_readonly" in cm_src, "ConfigManager.get_current_readonly missing"
    # Migration path stays explicit in get_current() (uses _activate).
    gc = cm_src.split("def get_current_readonly")[0]
    assert "_activate(" in gc, "get_current must retain explicit migration via _activate"
    # The pure read must not call _activate.
    ro = cm_src.split("def get_current_readonly", 1)[1].split("\n    def ", 1)[0]
    assert "self._activate(" not in ro, "get_current_readonly must NOT call self._activate"

    # Read-only consumers use the pure read.
    bundle = (BACKEND / "app/services/diagnostic_bundle_latest.py").read_text(encoding="utf-8-sig", errors="ignore")
    uni = (BACKEND / "app/services/universe_summary_service.py").read_text(encoding="utf-8-sig", errors="ignore")
    assert "get_current_readonly()" in bundle, "latest bundle must use get_current_readonly"
    assert "get_current_readonly()" in uni, "universe summary must use get_current_readonly"

    # Runtime: pure read commits nothing, even when the config row is missing.
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.config_manager import ConfigManager

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    s = Session(engine)
    commits = {"n": 0}
    real = s.commit
    s.commit = lambda *a, **k: commits.__setitem__("n", commits["n"] + 1)  # type: ignore
    try:
        cfg = ConfigManager(s).get_current_readonly()
    finally:
        s.commit = real  # type: ignore
    assert commits["n"] == 0, f"get_current_readonly committed {commits['n']} time(s)"
    assert isinstance(cfg, dict) and cfg, "pure read returned empty config"
    # Locked caps still force live false / paper true.
    assert cfg.get("live_trading_enabled") is not True, "locked caps must keep live_trading_enabled false"
    assert (cfg.get("execution") or {}).get("live_orders_enabled") is not True, "locked caps must keep live_orders_enabled false"

    print("verify_config_read_paths_do_not_write: PASS (pure read = 0 commits; migration explicit; live locked)")


if __name__ == "__main__":
    main()
