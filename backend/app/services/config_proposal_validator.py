"""Validate AI config proposals — locked keys rejected."""

from __future__ import annotations

from typing import Any

from app.services.engine_config import LOCKED_CONFIG_KEYS, cfg_get


ALLOWED_RANGES: dict[str, tuple[float, float]] = {
    "portfolio.signal_score_min": (0.0, 1.0),
    "cost.edge_multiplier_paper": (1.0, 5.0),
    "ranking.w_signal_strength": (0.0, 1.0),
}


def validate_proposal(config: dict, patch: dict) -> dict[str, Any]:
    rejected: list[dict] = []
    accepted: list[dict] = []

    def walk(prefix: str, obj: dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(path, v)
            else:
                if (
                    path in LOCKED_CONFIG_KEYS
                    or path.startswith("promotion.")
                    or path.startswith("execution.live")
                    or path == "execution.paper_orders_enabled"
                ):
                    rejected.append({"key": path, "reason": "locked_key"})
                    continue
                rng = ALLOWED_RANGES.get(path)
                if rng and isinstance(v, (int, float)):
                    lo, hi = rng
                    if not (lo <= float(v) <= hi):
                        rejected.append({"key": path, "reason": "out_of_range", "range": rng})
                        continue
                accepted.append({"key": path, "proposed_value": v})

    walk("", patch if isinstance(patch, dict) else {})
    return {
        "status": "pending_human_review" if accepted and not rejected else "rejected",
        "accepted": accepted,
        "rejected": rejected,
        "locked_keys": list(LOCKED_CONFIG_KEYS),
    }
