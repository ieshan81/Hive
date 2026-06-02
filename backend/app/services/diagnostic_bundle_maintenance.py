"""DiagnosticBundleMaintenanceService — keep the diagnostics folder small & fast.

Compresses old on-disk diagnostic exports into per-run archives, dedupes, keeps the latest N
uncompressed, and writes cleanup_summary.json. It only ever touches files under the diagnostics
directory — it NEVER deletes DB rows (broker/trade/outcome/risk/memory audit truth is untouched).
Safe to run on startup or on a periodic schedule; a no-op when there is nothing to archive.
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session

try:
    from app.config import BACKEND_ROOT, settings
except Exception:  # pragma: no cover
    BACKEND_ROOT = Path(__file__).resolve().parents[2]
    settings = None


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _cfg_int(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default) or default)
    except (TypeError, ValueError):
        return default


class DiagnosticBundleMaintenanceService:
    def __init__(self, session: Optional[Session] = None, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}
        self.root: Path = Path(BACKEND_ROOT) / "diagnostics"
        self.latest_dir = self.root / "latest"
        self.archives_dir = self.root / "archives"
        self.keep_latest = _cfg_int("diagnostic_keep_latest_bundles", 5)
        self.archive_after_hours = _cfg_int("diagnostic_archive_after_hours", 12)
        self.max_default_mb = _cfg_int("diagnostic_max_default_bundle_mb", 10)

    # ---- read-only summary (embedded in the latest bundle) ----
    def manifest_summary(self) -> dict[str, Any]:
        archives: list[dict[str, Any]] = []
        total_mb = 0.0
        if self.archives_dir.exists():
            for manifest in sorted(self.archives_dir.glob("**/manifest.json")):
                try:
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                    archives.append({
                        "archive_id": m.get("archive_id"),
                        "validation_run_id": m.get("validation_run_id"),
                        "date_range": m.get("date_range"),
                        "files_included": len(m.get("files_included") or []),
                        "compressed_size_mb": m.get("compressed_size_mb"),
                        "created_at": m.get("created_at"),
                    })
                    total_mb += float(m.get("compressed_size_mb") or 0)
                except Exception:
                    continue
        return {
            "status": "ok",
            "generated_at": _now(),
            "archive_count": len(archives),
            "total_compressed_mb": round(total_mb, 2),
            "archives": archives,
            "note": "Summary only — full archives live under diagnostics/archives/ and via ?mode=forensic.",
        }

    # ---- maintenance (safe; only touches diagnostics files, never DB) ----
    def run_maintenance(self, *, reason: str = "scheduled") -> dict[str, Any]:
        t0 = time.time()
        actions: list[str] = []
        archived: list[str] = []
        if not self.latest_dir.exists():
            summary = {
                "status": "ok",
                "reason": reason,
                "generated_at": _now(),
                "nothing_to_do": True,
                "message": "No diagnostics/latest directory — nothing to archive.",
                "audit_critical_db_untouched": True,
                "config": self._config_echo(),
            }
            self._write_cleanup_summary(summary)
            return summary

        run_id = self._current_run_id()
        cutoff = time.time() - self.archive_after_hours * 3600
        exports = sorted(self.latest_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)

        # Keep the newest N uncompressed; archive the rest if older than the window.
        to_archive = [p for p in exports[self.keep_latest:] if p.stat().st_mtime < cutoff]
        if to_archive:
            dest = self.archives_dir / (run_id or "unassigned")
            dest.mkdir(parents=True, exist_ok=True)
            stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            archive_path = dest / f"historical_{stamp}.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in to_archive:
                    zf.write(p, arcname=p.name)
            for p in to_archive:
                try:
                    p.unlink()
                    archived.append(p.name)
                except OSError:
                    pass
            self._write_manifest(dest, archive_path, run_id, archived)
            actions.append(f"archived {len(archived)} old export(s) -> {archive_path.name}")

        # Dedupe identical-size+name duplicates in latest (cheap heuristic).
        seen: set[tuple[str, int]] = set()
        deduped = 0
        for p in self.latest_dir.glob("*.zip"):
            key = (p.name, p.stat().st_size)
            if key in seen:
                try:
                    p.unlink(); deduped += 1
                except OSError:
                    pass
            else:
                seen.add(key)
        if deduped:
            actions.append(f"removed {deduped} duplicate export(s)")

        summary = {
            "status": "ok",
            "reason": reason,
            "generated_at": _now(),
            "nothing_to_do": not actions,
            "actions": actions,
            "archived_files": archived,
            "kept_latest": self.keep_latest,
            "duration_seconds": round(time.time() - t0, 2),
            "audit_critical_db_untouched": True,  # this service never deletes DB rows
            "config": self._config_echo(),
        }
        self._write_cleanup_summary(summary)
        return summary

    # ---- helpers ----
    def _current_run_id(self) -> Optional[str]:
        if not self.session:
            return None
        try:
            from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch

            epoch = get_latest_reset_epoch(self.session) or {}
            return epoch.get("validation_run_id") or (PAPER_VALIDATION_RUN_ID if epoch else None)
        except Exception:
            return None

    def _write_manifest(self, dest: Path, archive_path: Path, run_id: Optional[str], files: list[str]) -> None:
        size_mb = round(archive_path.stat().st_size / (1024 * 1024), 3) if archive_path.exists() else 0.0
        manifest = {
            "archive_id": archive_path.stem,
            "validation_run_id": run_id,
            "reset_epoch": run_id,
            "date_range": {"archived_at": _now()},
            "files_included": files,
            "row_counts": {"note": "file-level archive (not DB rows)"},
            "compressed_size_mb": size_mb,
            "reason_archived": "older than DIAGNOSTIC_ARCHIVE_AFTER_HOURS",
            "created_at": _now(),
        }
        (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _write_cleanup_summary(self, summary: dict) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "cleanup_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _config_echo(self) -> dict[str, Any]:
        return {
            "DIAGNOSTIC_KEEP_LATEST_BUNDLES": self.keep_latest,
            "DIAGNOSTIC_ARCHIVE_AFTER_HOURS": self.archive_after_hours,
            "DIAGNOSTIC_MAX_DEFAULT_BUNDLE_MB": self.max_default_mb,
            "DIAGNOSTIC_EXPORT_MODE": getattr(settings, "diagnostic_export_mode", "latest"),
        }


def run_if_due(session: Session, *, min_interval_hours: int = 6) -> dict[str, Any]:
    """Safe periodic entrypoint (scheduler/startup). Runs maintenance at most every N hours,
    tracked via a marker file under the diagnostics dir. Never raises."""
    try:
        svc = DiagnosticBundleMaintenanceService(session)
        marker = svc.root / ".last_maintenance"
        now = time.time()
        if marker.exists() and (now - marker.stat().st_mtime) < min_interval_hours * 3600:
            return {"status": "skipped", "reason": "within_min_interval"}
        out = svc.run_maintenance(reason="run_if_due")
        try:
            svc.root.mkdir(parents=True, exist_ok=True)
            marker.write_text(_now(), encoding="utf-8")
        except OSError:
            pass
        return out
    except Exception as exc:  # never break the caller
        return {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
