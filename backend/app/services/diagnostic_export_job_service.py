"""Durable diagnostic bundle export jobs.

Status reads are DB-backed so a browser refresh does not lose the last
completed/failed export. The bundle ZIP is stored in DB when reasonably small;
large bundles are written to a local storage path and reported honestly if the
file is unavailable after a restart/redeploy.
"""

from __future__ import annotations

import io
import logging
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from app.config import BACKEND_ROOT
from app.database import DiagnosticExportJob, engine

logger = logging.getLogger(__name__)

_JOB_LOCK = threading.Lock()
_MAX_DB_ZIP_BYTES = 12 * 1024 * 1024
_EXPORT_DIR = BACKEND_ROOT / "diagnostic_exports"


def _public_job(job: DiagnosticExportJob | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress_pct": job.progress_pct,
        "current_step": getattr(job, "current_step", None),
        "last_completed_file": getattr(job, "last_completed_file", None),
        "started_at": job.started_at.isoformat() + "Z" if job.started_at else None,
        "completed_at": job.completed_at.isoformat() + "Z" if job.completed_at else None,
        "filename": job.filename,
        "file_count": job.file_count,
        "failed_sections": job.failed_sections or [],
        "error": job.error,
        "zip_size_bytes": job.zip_size_bytes,
        "download_available": bool(job.zip_bytes or job.storage_path),
        "storage": "db_blob" if job.zip_bytes else "local_path" if job.storage_path else None,
    }


def export_job_status(session: Session | None = None) -> dict[str, Any]:
    """READ ONLY: DB metadata only, no export work."""

    owns = session is None
    db = session or Session(engine)
    try:
        current = db.exec(
            select(DiagnosticExportJob)
            .where(DiagnosticExportJob.status.in_(["queued", "running"]))
            .order_by(DiagnosticExportJob.started_at.desc())
        ).first()
        last_done = db.exec(
            select(DiagnosticExportJob)
            .where(DiagnosticExportJob.status == "complete")
            .order_by(DiagnosticExportJob.completed_at.desc())
        ).first()
        jobs = list(
            db.exec(
                select(DiagnosticExportJob)
                .order_by(DiagnosticExportJob.started_at.desc())
                .limit(8)
            ).all()
        )
        return {
            "status": "ok",
            "export_in_progress": bool(current),
            "current_job": _public_job(current),
            "last_completed": _public_job(last_done),
            "jobs": [_public_job(j) for j in jobs],
        }
    finally:
        if owns:
            db.close()


def _update_job(job_id: str, **fields: Any) -> None:
    with Session(engine) as session:
        job = session.get(DiagnosticExportJob, job_id)
        if not job:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        session.add(job)
        session.commit()


def _resolve_export_mode(mode: str | None) -> str:
    from app.config import settings

    resolved = (mode or getattr(settings, "diagnostic_export_mode", "latest") or "latest").lower()
    return resolved if resolved in ("latest", "forensic") else "latest"


def start_export_job(mode: str | None = None) -> dict[str, Any]:
    """OPERATOR ACTION: starts diagnostic export worker (default = small latest bundle)."""

    from datetime import datetime

    export_mode = _resolve_export_mode(mode)

    with _JOB_LOCK:
        with Session(engine) as session:
            running = session.exec(
                select(DiagnosticExportJob)
                .where(DiagnosticExportJob.status.in_(["queued", "running"]))
                .order_by(DiagnosticExportJob.started_at.desc())
            ).first()
            if running:
                return {
                    "status": "ok",
                    "job_id": running.job_id,
                    "export_in_progress": True,
                    "message": "Export already running",
                }
            job_id = str(uuid.uuid4())[:12]
            session.add(
                DiagnosticExportJob(
                    job_id=job_id,
                    status="running",
                    progress_pct=0,
                    started_at=datetime.utcnow(),
                    current_step=f"queued_{export_mode}",
                )
            )
            session.commit()

    def _worker() -> None:
        from datetime import datetime

        try:
            _update_job(job_id, progress_pct=5, current_step=f"starting_{export_mode}")
            with Session(engine) as session:
                if export_mode == "forensic":
                    from app.services.diagnostic_export import (
                        bundle_dict_as_zip_bytes,
                        diagnostic_bundle_filename,
                        export_diagnostic_bundle_safe,
                    )

                    _update_job(job_id, progress_pct=15, current_step="collecting_db_truth")
                    bundle = export_diagnostic_bundle_safe(session)
                    _update_job(job_id, progress_pct=55, current_step="collecting_api_snapshots", last_completed_file="api_snapshots/_manifest.json")
                    _update_job(job_id, progress_pct=65, current_step="capturing_screenshots")
                    failed = []
                    errors = bundle.get("diagnostic_export_errors.json")
                    if isinstance(errors, list):
                        failed = [e.get("section") for e in errors if isinstance(e, dict) and e.get("section")]
                    _update_job(job_id, progress_pct=80, failed_sections=failed[:20], current_step="writing_zip")
                    zip_bytes = bundle_dict_as_zip_bytes(bundle)
                    filename = diagnostic_bundle_filename(session)
                else:
                    from app.services.diagnostic_bundle_latest import (
                        build_latest_bundle,
                        latest_bundle_as_zip,
                        latest_bundle_filename,
                    )

                    _update_job(job_id, progress_pct=25, current_step="building_latest_bundle")
                    bundle = build_latest_bundle(session)
                    failed = []
                    section_errors = (bundle.get("bundle_meta.json") or {}).get("section_errors")
                    if isinstance(section_errors, list):
                        failed = [e.get("section") for e in section_errors if isinstance(e, dict) and e.get("section")]
                    _update_job(job_id, progress_pct=70, failed_sections=failed[:20], current_step="writing_zip", last_completed_file="README_FIRST.json")
                    zip_bytes = latest_bundle_as_zip(session)
                    filename = latest_bundle_filename()

                file_count = len(zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()) if zip_bytes else 0

            _update_job(job_id, progress_pct=92, current_step="persisting_zip")
            storage_path = None
            stored_bytes: bytes | None = zip_bytes if len(zip_bytes) <= _MAX_DB_ZIP_BYTES else None
            if stored_bytes is None:
                _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
                path = _EXPORT_DIR / f"{job_id}-{filename}"
                path.write_bytes(zip_bytes)
                storage_path = str(path)

            _update_job(
                job_id,
                status="complete",
                progress_pct=100,
                current_step="complete",
                completed_at=datetime.utcnow(),
                filename=filename,
                file_count=file_count,
                last_completed_file=filename,
                zip_size_bytes=len(zip_bytes),
                zip_bytes=stored_bytes,
                storage_path=storage_path,
            )
        except Exception as exc:
            logger.exception("diagnostic export job failed: %s", exc)
            _update_job(
                job_id,
                status="failed",
                progress_pct=100,
                current_step="failed",
                completed_at=datetime.utcnow(),
                error=str(exc)[:500],
            )

    threading.Thread(target=_worker, daemon=True, name=f"diag-export-{job_id}").start()
    return {"status": "ok", "job_id": job_id, "export_in_progress": True, "message": "Export started"}


def get_job_download(job_id: str) -> tuple[Optional[bytes], Optional[str], str]:
    """Return ZIP bytes, filename, reason."""

    with Session(engine) as session:
        job = session.get(DiagnosticExportJob, job_id)
        if not job:
            return None, None, "job_not_found"
        if job.status != "complete":
            return None, None, "not_ready"
        if job.zip_bytes:
            return job.zip_bytes, job.filename or "caged-hive-diagnostic.zip", "ok"
        if job.storage_path:
            path = Path(job.storage_path)
            if path.exists():
                return path.read_bytes(), job.filename or path.name, "ok"
            return None, job.filename, "file_unavailable_after_restart"
        return None, job.filename, "download_unavailable"
