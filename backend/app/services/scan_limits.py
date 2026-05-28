"""Shared scan/evaluate limits — 0 or negative means unlimited."""

from __future__ import annotations

from typing import Any

from app.services.engine_config import cfg_get


def zero_means_unlimited(value: Any) -> bool:
    try:
        return int(value) <= 0
    except (TypeError, ValueError):
        return False


def scan_limit(config: dict, path: str, default: int = 0) -> int:
    raw = cfg_get(config, path, default)
    if zero_means_unlimited(raw):
        return 9999
    return max(1, int(raw))


def slice_limit(items: list, limit: int) -> list:
    if limit <= 0 or limit >= len(items):
        return items
    return items[:limit]
