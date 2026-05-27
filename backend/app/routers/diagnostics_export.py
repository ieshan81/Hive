"""Async diagnostic export job API."""

from fastapi import APIRouter, Depends
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
def run_export(_op: str = Depends(require_operator_token)):
    return start_export_job()


@router.get("/status")
def status():
    return export_job_status()


@router.get("/download/{job_id}")
def download(job_id: str):
    data, filename, reason = get_job_download(job_id)
    if reason == "job_not_found":
        return {"status": "error", "message": "Job not found"}
    if reason == "not_ready":
        return {"status": "pending", "message": "Export not ready yet"}
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
