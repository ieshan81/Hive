"""Operator token guard for mutating API endpoints."""

from __future__ import annotations

import os

from fastapi import Header, HTTPException

from app.config import settings


def require_operator_token(
    x_operator_token: str | None = Header(default=None, alias="X-Operator-Token"),
) -> str:
    secret = (settings.operator_secret or "").strip()
    if not secret:
        if os.environ.get("HIVE_ALLOW_UNAUTHENTICATED_DEV") == "1":
            return "dev-bypass"
        raise HTTPException(
            status_code=503,
            detail={
                "status": "blocked",
                "message": "Operator secret not configured — mutating actions disabled.",
                "action_required": "Set OPERATOR_SECRET on Railway backend and matching token in frontend.",
            },
        )
    if not x_operator_token or x_operator_token.strip() != secret:
        raise HTTPException(
            status_code=403,
            detail={
                "status": "forbidden",
                "message": "Invalid or missing operator token.",
            },
        )
    return x_operator_token.strip()
