"""HTTP client for optional FinBERT microservice."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional


def finbert_service_url() -> Optional[str]:
    url = (os.environ.get("FINBERT_SERVICE_URL") or "").strip().rstrip("/")
    return url or None


def finbert_health() -> dict[str, Any]:
    url = finbert_service_url()
    if not url:
        return {"configured": False, "status": "inactive", "reason": "FINBERT_SERVICE_URL not set"}
    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        return {"configured": True, "status": data.get("status", "ok"), **data}
    except Exception as exc:
        return {"configured": True, "status": "unavailable", "error": str(exc)[:200]}


def classify_batch(items: list[dict[str, Any]], *, timeout: float = 15.0) -> list[dict[str, Any]]:
    """items: [{id, symbol, source, text}, ...]"""
    base = finbert_service_url()
    if not base or not items:
        return []
    payload = json.dumps({"items": items[:64]}).encode()
    req = urllib.request.Request(
        f"{base}/sentiment/batch",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return list(data.get("items") or [])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
