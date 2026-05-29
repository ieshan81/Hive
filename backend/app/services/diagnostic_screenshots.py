"""
Optional best-effort UI screenshots for the diagnostic bundle.

This module is GUARANTEED NEVER TO CRASH the export. On any failure path it
emits `screenshots/screenshots_unavailable.json` explaining why and returns
an empty screenshot set.

Rules (Phase 3 spec):
  - Best effort only. Browser tooling may not be installed on Railway.
  - 2–5 second post-load wait before snapshot.
  - Never click dangerous buttons. Never run a cycle. Never trigger
    operator POST endpoints. Never include secrets.
  - On unavailability, screenshots_unavailable.json is written and the
    bundle export continues normally.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SCREENSHOT_DIR = "screenshots"
_DEFAULT_WAIT_S = 3.0
_PAGES: list[tuple[str, str]] = [
    ("cockpit.png", "/cockpit"),
    ("universe.png", "/universe"),
    ("portfolio.png", "/portfolio"),
    ("tradingview.png", "/tradingview"),
    ("reports.png", "/reports"),
    ("ai_manager.png", "/ai-manager"),
    ("settings.png", "/settings"),
]


def _frontend_origin() -> str:
    """Best guess for where the cockpit UI is running."""
    for env in (
        "FRONTEND_PUBLIC_URL",
        "NEXT_PUBLIC_FRONTEND_URL",
        "VERCEL_URL",
        "DIAG_SCREENSHOTS_ORIGIN",
    ):
        v = os.environ.get(env)
        if v:
            if not v.startswith("http"):
                return f"https://{v.lstrip('/')}"
            return v.rstrip("/")
    return "http://localhost:3000"


def _unavailable_payload(reason: str, *, page_targets: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "captured_at_utc": datetime.utcnow().isoformat() + "Z",
        "available": False,
        "reason": reason,
        "page_targets": page_targets,
        "remediation": "Install Playwright + Chromium in the bundle worker, "
                       "set FRONTEND_PUBLIC_URL, and ensure the cockpit UI is reachable.",
    }


def _try_playwright() -> Optional[Any]:
    """Return playwright.sync_api module if importable, else None."""
    try:
        from playwright import sync_api  # noqa: F401
        return sync_api
    except Exception as exc:
        logger.debug("playwright not available: %s", exc)
        return None


def collect_screenshots() -> dict[str, Any]:
    """
    Returns dict of bundle entries:
      {"screenshots/cockpit.png": <bytes>, ..., "screenshots/screenshot_manifest.json": {...}}
    OR (if browser unavailable):
      {"screenshots/screenshots_unavailable.json": {...}}
    """
    page_targets = [p for _, p in _PAGES]
    sync_api = _try_playwright()
    if sync_api is None:
        return {
            f"{_SCREENSHOT_DIR}/screenshots_unavailable.json": _unavailable_payload(
                "playwright_not_installed", page_targets=page_targets,
            ),
        }

    origin = _frontend_origin()
    out: dict[str, Any] = {}
    manifest_entries: list[dict[str, Any]] = []

    try:
        with sync_api.sync_playwright() as pw:  # type: ignore[attr-defined]
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception as exc:
                return {
                    f"{_SCREENSHOT_DIR}/screenshots_unavailable.json": _unavailable_payload(
                        f"chromium_launch_failed: {exc}", page_targets=page_targets,
                    )
                }
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            for filename, path in _PAGES:
                target_url = f"{origin}{path}"
                started = time.time()
                entry: dict[str, Any] = {
                    "file": f"{_SCREENSHOT_DIR}/{filename}",
                    "url": target_url,
                    "captured_at_utc": datetime.utcnow().isoformat() + "Z",
                }
                try:
                    page.goto(target_url, wait_until="networkidle", timeout=12_000)
                    time.sleep(_DEFAULT_WAIT_S)  # let lazy content settle
                    png_bytes = page.screenshot(full_page=False)
                    out[f"{_SCREENSHOT_DIR}/{filename}"] = png_bytes
                    entry["status"] = "ok"
                    entry["size_bytes"] = len(png_bytes)
                except Exception as exc:
                    entry["status"] = "error"
                    entry["error"] = str(exc)[:300]
                entry["elapsed_ms"] = int((time.time() - started) * 1000)
                manifest_entries.append(entry)

            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
    except Exception as exc:
        return {
            f"{_SCREENSHOT_DIR}/screenshots_unavailable.json": _unavailable_payload(
                f"playwright_runtime_error: {exc}", page_targets=page_targets,
            )
        }

    out[f"{_SCREENSHOT_DIR}/screenshot_manifest.json"] = {
        "schema_version": 1,
        "captured_at_utc": datetime.utcnow().isoformat() + "Z",
        "origin": origin,
        "wait_s": _DEFAULT_WAIT_S,
        "viewport": {"width": 1440, "height": 900},
        "entries": manifest_entries,
        "success_count": sum(1 for e in manifest_entries if e.get("status") == "ok"),
        "failure_count": sum(1 for e in manifest_entries if e.get("status") == "error"),
        "rules": [
            "no_clicks",
            "no_form_input",
            "no_POST",
            "no_cycle_run",
            "no_secrets",
        ],
    }
    return out
