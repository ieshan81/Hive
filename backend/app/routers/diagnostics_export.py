"""Async diagnostic export job API."""

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import Response
from sqlmodel import Session

from app.database import get_session
from app.services.diagnostic_export_job_service import (
    export_job_status,
    get_job_download,
    start_export_job,
)
from app.services.operator_auth import require_operator_token

router = APIRouter(prefix="/api/diagnostics/export", tags=["diagnostics-export"])


@router.post("/run")
def run_export(
    body: Optional[dict[str, Any]] = Body(default=None),
    _op: str = Depends(require_operator_token),
):
    """OPERATOR ACTION: background export. Default mode=latest (small current-run). Use mode=forensic for full history."""
    mode = str((body or {}).get("mode") or "latest").strip().lower()
    return start_export_job(mode=mode)


@router.get("/status")
def status(session: Session = Depends(get_session)):
    """READ ONLY: returns persisted diagnostic job metadata only."""
    return export_job_status(session)


@router.get("/download/{job_id}")
def download(job_id: str):
    data, filename, reason = get_job_download(job_id)
    if reason == "job_not_found":
        return {"status": "error", "message": "Job not found"}
    if reason == "not_ready":
        return {"status": "pending", "message": "Export not ready yet"}
    if reason in ("file_unavailable_after_restart", "download_unavailable"):
        return {
            "status": "error",
            "message": "Diagnostic metadata exists, but the ZIP file is unavailable after restart or storage cleanup.",
            "reason": reason,
            "filename": filename,
        }
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
