"""Verify diagnostic export status is DB-backed and top-level last_completed."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session

from app.database import DiagnosticExportJob, engine, init_db
from app.services.diagnostic_export_job_service import export_job_status, get_job_download


JOB_ID = "verify_diag_contract"


def main() -> None:
    init_db()
    with Session(engine) as session:
        session.exec(delete(DiagnosticExportJob).where(DiagnosticExportJob.job_id == JOB_ID))
        session.add(
            DiagnosticExportJob(
                job_id=JOB_ID,
                status="complete",
                progress_pct=100,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                filename="verify.zip",
                file_count=2,
                failed_sections=[],
                zip_bytes=b"not-a-real-zip-but-download-bytes",
                zip_size_bytes=30,
            )
        )
        session.commit()
        status = export_job_status(session)
        assert status["status"] == "ok"
        assert status["last_completed"]["job_id"] == JOB_ID
        assert "jobs" in status

    data, filename, reason = get_job_download(JOB_ID)
    assert reason == "ok"
    assert filename == "verify.zip"
    assert data

    with Session(engine) as session:
        session.exec(delete(DiagnosticExportJob).where(DiagnosticExportJob.job_id == JOB_ID))
        session.commit()
    print("verify_diagnostic_export_status_contract: PASS")


if __name__ == "__main__":
    main()
