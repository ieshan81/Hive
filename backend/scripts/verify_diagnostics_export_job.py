#!/usr/bin/env python3
"""Verify diagnostic export job does not duplicate running jobs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import diagnostic_export_job_service as jobs


def main() -> int:
    jobs._JOBS.clear()
    jobs._CURRENT_JOB_ID = None
    a = jobs.start_export_job()
    b = jobs.start_export_job()
    assert a.get("job_id")
    assert b.get("export_in_progress") or b.get("job_id") == a.get("job_id")
    st = jobs.export_job_status()
    assert "export_in_progress" in st
    print("verify_diagnostics_export_job: OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("verify_diagnostics_export_job: FAIL", exc)
        sys.exit(1)
