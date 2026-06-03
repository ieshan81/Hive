#!/usr/bin/env python3
"""Background diagnostic export jobs must default to the small latest bundle, not forensic."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

tmp_db = Path(tempfile.gettempdir()) / f"hive_export_job_verify_{os.getpid()}.db"
try:
    tmp_db.unlink()
except FileNotFoundError:
    pass
os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db.as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from app.database import DiagnosticExportJob, engine, init_db
from app.services import diagnostic_export_job_service as jobs


def main() -> int:
    init_db()
    with Session(engine) as session:
        for row in session.exec(select(DiagnosticExportJob)).all():
            session.delete(row)
        session.commit()

    captured: dict = {}

    def _fake_latest_zip(session, config=None):
        captured["called"] = True
        return b"PK\x05\x06" + (b"\x00" * 18)

    with patch(
        "app.services.diagnostic_bundle_latest.latest_bundle_as_zip",
        _fake_latest_zip,
    ), patch(
        "app.services.diagnostic_bundle_latest.latest_bundle_filename",
        lambda: "latest_bundle_test.zip",
    ), patch(
        "app.services.diagnostic_bundle_latest.build_latest_bundle",
        lambda session, config=None: {
            "README_FIRST.json": {"bundle_mode": "latest"},
            "bundle_meta.json": {"bundle_mode": "latest", "section_errors": []},
        },
    ), patch(
        "app.services.diagnostic_export.export_diagnostic_bundle_safe",
        lambda _session: (_ for _ in ()).throw(AssertionError("forensic must not run for default export")),
    ):
        jobs.start_export_job()
        for _ in range(60):
            status = jobs.export_job_status()
            if not status.get("export_in_progress"):
                break
            time.sleep(0.05)

    assert captured.get("called"), "latest_bundle_as_zip must be used for default export job"
    last = jobs.export_job_status().get("last_completed") or {}
    assert last.get("filename", "").startswith("latest_bundle"), last
    print("verify_diagnostics_export_job_uses_latest: PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("verify_diagnostics_export_job_uses_latest: FAIL", exc)
        sys.exit(1)
