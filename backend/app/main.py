import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import (
    account_eligibility,
    api,
    autonomous_paper_learning,
    capital_allocator,
    candle_lab,
    confidence,
    fast_training,
    hive_brain,
    live_promotion,
    market_meme,
    memory_brain,
    paper_learning,
    settings_brain,
    strategy_proposals,
    strategy_registry,
    system_meta,
)
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
app.include_router(paper_learning.router)
app.include_router(memory_brain.router)
app.include_router(hive_brain.router)
app.include_router(fast_training.router)
app.include_router(candle_lab.router)
app.include_router(market_meme.router)
app.include_router(settings_brain.router)
app.include_router(autonomous_paper_learning.router)
app.include_router(capital_allocator.router)
app.include_router(confidence.router)
app.include_router(account_eligibility.router)
app.include_router(strategy_proposals.router)
app.include_router(live_promotion.router)
app.include_router(system_meta.router)


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
