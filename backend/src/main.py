"""
FastAPI application entry point for the small-cap trading platform.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import (
    filings,
    orders,
    portfolio,
    risk,
    screener,
    signals,
    system,
    tickers,
    watchlists,
)
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

    # ------------------------------------------------------------------
    # Start background workers
    # ------------------------------------------------------------------
    from src.workers.market_data import start_market_data_worker, stop_market_data_worker
    from src.workers.edgar_worker import start_edgar_worker, stop_edgar_worker
    from src.workers.signal_scanner import start_signal_scanner
    from src.workers.health_check import start_health_monitor, stop_health_monitor
    from src.workers.ai_worker import start_ai_worker, stop_ai_worker

    # Signal scanner task reference (needed for cleanup)
    signal_scanner_task: asyncio.Task | None = None

    try:
        await start_market_data_worker()
    except Exception:
        logger.warning("Failed to start market data worker — continuing without it")

    try:
        await start_edgar_worker()
    except Exception:
        logger.warning("Failed to start EDGAR worker — continuing without it")

    try:
        signal_scanner_task = asyncio.create_task(
            start_signal_scanner(), name="signal-scanner"
        )
    except Exception:
        logger.warning("Failed to start signal scanner — continuing without it")

    try:
        await start_health_monitor()
    except Exception:
        logger.warning("Failed to start health monitor — continuing without it")

    try:
        await start_ai_worker()
    except Exception:
        logger.warning("Failed to start AI worker — continuing without it")

    yield

    # ------------------------------------------------------------------
    # Shutdown background workers
    # ------------------------------------------------------------------
    logger.info("Shutting down — stopping background workers")

    try:
        await stop_ai_worker()
    except Exception:
        logger.warning("Error stopping AI worker")

    try:
        await stop_health_monitor()
    except Exception:
        logger.warning("Error stopping health monitor")

    if signal_scanner_task and not signal_scanner_task.done():
        signal_scanner_task.cancel()
        try:
            await signal_scanner_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Error stopping signal scanner")

    try:
        await stop_edgar_worker()
    except Exception:
        logger.warning("Error stopping EDGAR worker")

    try:
        await stop_market_data_worker()
    except Exception:
        logger.warning("Error stopping market data worker")

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
app.include_router(risk.router)
app.include_router(screener.router)
app.include_router(system.router)
app.include_router(filings.router)
app.include_router(watchlists.router)
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
