"""
Verify: export_diagnostic_bundle_safe() does NOT return emergency-only for
a normal local DB state, includes system_summary.md, includes
diagnostic_export_errors.json, includes API snapshot metadata, and screenshot
failures are non-fatal.

This script runs without Alpaca creds against the local sqlite DB.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

import logging

logging.disable(logging.CRITICAL)

from sqlmodel import Session

from app.database import engine
from app.services.diagnostic_export import (
    bundle_dict_as_zip_bytes,
    export_diagnostic_bundle_safe,
)


def main() -> int:
    failures: list[str] = []
    # Manually manage the session so a teardown race in the bundle export
    # cannot mask the verifier's own assertions.
    session = Session(engine)
    try:
        bundle = export_diagnostic_bundle_safe(session)
    finally:
        try:
            session.close()
        except Exception:
            pass

    # 1. Not emergency-only
    if bundle.get("emergency_bundle_only") is True:
        failures.append("bundle.emergency_bundle_only=True (Phase 1 fix did not hold)")

    # 2. system_summary.md present
    if "system_summary.md" not in bundle:
        failures.append("system_summary.md missing")

    # 3. diagnostic_export_errors.json present (even if empty list)
    if "diagnostic_export_errors.json" not in bundle:
        failures.append("diagnostic_export_errors.json missing")

    # 4. API snapshots manifest present
    if "api_snapshots/_manifest.json" not in bundle:
        failures.append("api_snapshots/_manifest.json missing")
    else:
        manifest = bundle["api_snapshots/_manifest.json"]
        if not isinstance(manifest, dict) or manifest.get("snapshot_count", 0) < 5:
            failures.append("api_snapshots manifest missing entries")

    # 5. Screenshot subsystem must NOT crash; either a manifest or an
    #    unavailability marker is acceptable.
    has_screens = "screenshots/screenshot_manifest.json" in bundle
    has_unavail = "screenshots/screenshots_unavailable.json" in bundle
    if not (has_screens or has_unavail):
        failures.append("screenshots subsystem produced neither manifest nor unavailable.json")

    # 6. PaperExperimentDecision regression: paper_experiment_decisions.json should be present
    if "paper_experiment_decisions.json" not in bundle:
        failures.append("paper_experiment_decisions.json missing (PaperExperimentDecision regression)")

    # 7. ZIP packer must accept the bundle (binary screenshots tolerated)
    try:
        zip_bytes = bundle_dict_as_zip_bytes(bundle)
        if len(zip_bytes) < 1024:
            failures.append("bundle zip suspiciously small")
    except Exception as exc:
        failures.append(f"bundle_dict_as_zip_bytes raised: {exc}")

    if failures:
        print("FAIL: verify_diagnostic_bundle_full_export")
        for f in failures:
            print("  -", f)
        return 1

    print("PASS: verify_diagnostic_bundle_full_export")
    print(f"  bundle keys = {len(bundle)}")
    print(f"  zip size    = {len(zip_bytes)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
