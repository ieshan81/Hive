#!/usr/bin/env python3
"""Verify DB-backed diagnostic export jobs do not duplicate running jobs."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

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

    fake_bundle = {"bundle_manifest.json": {"status": "ok"}, "system_health.json": {"status": "ok"}}
    fake_zip = b"PK\x05\x06" + (b"\x00" * 18)
    with patch("app.services.diagnostic_export.export_diagnostic_bundle_safe", lambda _session: fake_bundle), patch(
        "app.services.diagnostic_export.bundle_dict_as_zip_bytes", lambda _bundle: fake_zip
    ), patch("app.services.diagnostic_export.diagnostic_bundle_filename", lambda _session: "verify.zip"):
        first = jobs.start_export_job()
        second = jobs.start_export_job()
        for _ in range(40):
            status = jobs.export_job_status()
            if not status.get("export_in_progress"):
                break
            time.sleep(0.05)

    assert first.get("job_id")
    assert second.get("export_in_progress") or second.get("job_id") == first.get("job_id")
    status = jobs.export_job_status()
    assert "export_in_progress" in status
    assert status.get("last_completed") or status.get("current_job")
    print("verify_diagnostics_export_job: PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("verify_diagnostics_export_job: FAIL", exc)
        sys.exit(1)
