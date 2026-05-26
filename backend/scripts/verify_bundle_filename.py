"""Verify diagnostic bundle filename has no duplicate reset- prefix."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_filename_no_duplicate_reset():
    from app.services.diagnostic_export import diagnostic_bundle_filename

    class FakeSession:
        pass

    from app.services import diagnostic_export as de

    orig = de.get_latest_reset_epoch if hasattr(de, "get_latest_reset_epoch") else None
    import app.services.nuke_epoch_service as nes

    old = nes.get_latest_reset_epoch
    nes.get_latest_reset_epoch = lambda s: {"reset_epoch_id": "reset-20260526T055727"}
    try:
        name = diagnostic_bundle_filename(FakeSession())
        assert "reset-reset" not in name, name
        assert name.endswith("-reset-20260526T055727.zip"), name
        assert name.startswith("caged-hive-diagnostic-"), name
    finally:
        nes.get_latest_reset_epoch = old


if __name__ == "__main__":
    test_filename_no_duplicate_reset()
    print("OK verify_bundle_filename")
