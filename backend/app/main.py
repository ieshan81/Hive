import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import api, strategy_registry
from app.services.startup import bootstrap_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hive")

app = FastAPI(
    title="Caged Hive Quant API",
    description="AI-managed quant trading under strict survival rules. Paper trading only.",
    version="1.0.2",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.router)
app.include_router(strategy_registry.router)


@app.on_event("startup")
def on_startup():
    logger.info("Starting Caged Hive Quant API")
    init_db()
    bootstrap_database()
    if not settings.alpaca_configured:
        logger.warning("ALPACA_API_KEY / ALPACA_SECRET_KEY not set — broker sync unavailable")
    if not settings.gemini_configured:
        logger.warning("GEMINI_API_KEY not set — AI reviews unavailable")
    if not settings.database_configured:
        logger.warning("DATABASE_URL not set — using fallback")
    logger.info("Paper trading only. Live trading disabled.")


@app.get("/health")
def root_health():
    warnings = []
    if not settings.alpaca_configured:
        warnings.append("Alpaca credentials missing")
    if not settings.gemini_configured:
        warnings.append("Gemini API key missing")
    return {
        "status": "ok",
        "service": "caged-hive-quant",
        "paper_trading_only": True,
        "warnings": warnings,
    }
