"""Phase 7 verifier: the default (latest) diagnostic bundle is read-pure.

Asserts build_latest_bundle performs no session.commit()/expire_all()/add (runtime commit-spy +
static), the default export mode is latest, forensic is explicit-only, and the forensic export is
labeled as having side effects (not read-pure) so it is not used during active cycles.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    latest_src = (BACKEND / "app/services/diagnostic_bundle_latest.py").read_text(encoding="utf-8-sig", errors="ignore")
    api_src = (BACKEND / "app/routers/api.py").read_text(encoding="utf-8-sig", errors="ignore")
    forensic_src = (BACKEND / "app/services/diagnostic_export.py").read_text(encoding="utf-8-sig", errors="ignore")

    # Latest bundle is statically read-only (no writes/commits/expire).
    for bad in ("session.commit(", ".expire_all(", "session.add("):
        assert bad not in latest_src, f"latest bundle must be read-pure — found {bad}"

    # Default mode is latest; forensic is explicit-only.
    assert 'if resolved == "forensic"' in api_src and "build_latest_bundle" in api_src, "default must be latest"
    assert 'diagnostic_export_mode", "latest"' in api_src or 'getattr(settings, "diagnostic_export_mode", "latest")' in api_src

    # Forensic export is explicitly labeled as NOT read-pure.
    assert "NOT read-pure" in forensic_src and "explicit-only" in forensic_src, "forensic export must be labeled non-read-pure"

    # Runtime commit-spy: building the latest bundle must not commit.
    from sqlmodel import Session, SQLModel

    import app.database  # noqa: F401
    from app.database import engine
    from app.services.diagnostic_bundle_latest import build_latest_bundle

    try:
        SQLModel.metadata.create_all(engine)
    except Exception:
        pass
    # Warm once so any first-run lazy default-singleton creation (cold-DB only) is already persisted.
    try:
        with Session(engine) as warm:
            build_latest_bundle(warm, config={})
            warm.commit()
    except Exception:
        pass
    # Steady-state read-purity: a build against a warm DB must emit ZERO commits.
    s = Session(engine)
    commits = {"n": 0}
    real_commit = s.commit
    s.commit = lambda *a, **k: commits.__setitem__("n", commits["n"] + 1)  # type: ignore
    try:
        build_latest_bundle(s, config={})
    finally:
        s.commit = real_commit  # type: ignore
    assert commits["n"] == 0, f"latest bundle committed {commits['n']} time(s) in steady state — not read-pure"

    print("verify_diagnostic_export_read_purity: PASS (latest bundle read-pure / 0 commits; default=latest; forensic explicit + labeled)")


if __name__ == "__main__":
    main()
