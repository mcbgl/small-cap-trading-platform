"""
FastAPI application entry point for the small-cap trading platform.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import orders, portfolio, screener, signals, system, tickers
from src.api.ws import router as ws_router
from src.config import settings
from src.db import close_pg_pool, close_redis, init_pg_pool, init_redis

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle manager."""
    logger.info("Starting up — initialising connections")
    try:
        await init_pg_pool()
    except Exception:
        logger.warning("PostgreSQL not available — running without database")

    try:
        await init_redis()
    except Exception:
        logger.warning("Redis not available — running without cache")

    yield

    logger.info("Shutting down — closing connections")
    await close_pg_pool()
    await close_redis()


app = FastAPI(
    title="Small-Cap Trading Platform",
    version="0.1.0",
    description="AI-driven small-cap stock trading platform with risk guardrails",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(tickers.router)
app.include_router(signals.router)
app.include_router(orders.router)
app.include_router(portfolio.router)
app.include_router(screener.router)
app.include_router(system.router)
app.include_router(ws_router)


# ---------------------------------------------------------------------------
# Root health check
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "small-cap-trading-platform",
        "version": "0.1.0",
        "paper_mode": settings.paper_mode,
        "shadow_mode": settings.shadow_mode,
    }
