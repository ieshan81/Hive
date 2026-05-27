"""Public system metadata — no secrets."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/meta")
def system_meta():
    return {
        "status": "ok",
        "service": "caged-hive-quant-api",
        "cors_origins": settings.cors_origin_list,
        "paper_trading_only": True,
    }


@router.get("/db-pool/status")
def db_pool_status_endpoint():
    from app.services.system_db_pool_service import db_pool_status

    return {"status": "ok", **db_pool_status()}
