"""Async diagnostic bundle export — one job at a time, no blocking download."""

from __future__ import annotations

import io
import logging
import threading
import uuid
import zipfile
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.database import engine

logger = logging.getLogger(__name__)

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_CURRENT_JOB_ID: Optional[str] = None


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def export_job_status() -> dict[str, Any]:
    with _JOB_LOCK:
        current = _JOBS.get(_CURRENT_JOB_ID) if _CURRENT_JOB_ID else None
        last_done = None
        for j in _JOBS.values():
            if j.get("status") == "complete":
                if not last_done or (j.get("completed_at") or "") > (last_done.get("completed_at") or ""):
                    last_done = j
        return {
            "status": "ok",
            "export_in_progress": bool(current and current.get("status") == "running"),
            "current_job": {k: current[k] for k in ("job_id", "status", "progress_pct", "started_at") if current and k in current},
            "last_completed": {
                "job_id": last_done.get("job_id"),
                "filename": last_done.get("filename"),
                "file_count": last_done.get("file_count"),
                "completed_at": last_done.get("completed_at"),
                "failed_sections": last_done.get("failed_sections") or [],
            }
            if last_done
            else None,
        }


def start_export_job() -> dict[str, Any]:
    global _CURRENT_JOB_ID
    with _JOB_LOCK:
        if _CURRENT_JOB_ID:
            cur = _JOBS.get(_CURRENT_JOB_ID)
            if cur and cur.get("status") == "running":
                return {
                    "status": "ok",
                    "job_id": _CURRENT_JOB_ID,
                    "export_in_progress": True,
                    "message": "Export already running",
                }
        job_id = str(uuid.uuid4())[:12]
        _CURRENT_JOB_ID = job_id
        _JOBS[job_id] = {
            "job_id": job_id,
            "status": "running",
            "progress_pct": 0,
            "started_at": _now(),
            "filename": None,
            "zip_bytes": None,
            "file_count": 0,
            "failed_sections": [],
        }

    def _worker() -> None:
        try:
            from app.services.diagnostic_export import (
                bundle_as_zip_bytes_safe,
                diagnostic_bundle_filename,
                export_diagnostic_bundle_safe,
            )

            with _JOB_LOCK:
                _JOBS[job_id]["progress_pct"] = 10
            with Session(engine) as session:
                bundle = export_diagnostic_bundle_safe(session)
                failed = []
                if isinstance(bundle.get("diagnostic_export_errors.json"), list):
                    failed = [e.get("section") for e in bundle["diagnostic_export_errors.json"] if e.get("section")]
                with _JOB_LOCK:
                    _JOBS[job_id]["progress_pct"] = 70
                    _JOBS[job_id]["failed_sections"] = failed[:20]
                zip_bytes = bundle_as_zip_bytes_safe(session)
                fname = diagnostic_bundle_filename(session)
            with _JOB_LOCK:
                _JOBS[job_id].update(
                    {
                        "status": "complete",
                        "progress_pct": 100,
                        "completed_at": _now(),
                        "filename": fname,
                        "zip_bytes": zip_bytes,
                        "file_count": len(zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()) if zip_bytes else 0,
                    }
                )
        except Exception as exc:
            logger.exception("diagnostic export job failed: %s", exc)
            with _JOB_LOCK:
                _JOBS[job_id].update(
                    {
                        "status": "failed",
                        "progress_pct": 100,
                        "completed_at": _now(),
                        "error": str(exc)[:300],
                    }
                )

    threading.Thread(target=_worker, daemon=True, name=f"diag-export-{job_id}").start()
    return {"status": "ok", "job_id": job_id, "export_in_progress": True, "message": "Export started"}


def get_job_download(job_id: str) -> tuple[Optional[bytes], Optional[str], str]:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None, None, "job_not_found"
        if job.get("status") != "complete":
            return None, None, "not_ready"
        return job.get("zip_bytes"), job.get("filename"), "ok"
