"""
Database connection helpers for PostgreSQL (asyncpg), QuestDB (ILP over HTTP), and Redis.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
import httpx
import redis.asyncio as aioredis

from src.config import settings

logger = logging.getLogger(__name__)

# Module-level connection pool references — initialised at app startup.
_pg_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None


# ---------------------------------------------------------------------------
# PostgreSQL (asyncpg)
# ---------------------------------------------------------------------------

async def init_pg_pool() -> asyncpg.Pool:
    """Create and return the asyncpg connection pool."""
    global _pg_pool
    _pg_pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    logger.info("PostgreSQL connection pool initialised")
    return _pg_pool


async def close_pg_pool() -> None:
    """Gracefully close the asyncpg pool."""
    global _pg_pool
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None
        logger.info("PostgreSQL connection pool closed")


def get_db_pool() -> asyncpg.Pool:
    """Return the active asyncpg pool (must be initialised first)."""
    if _pg_pool is None:
        raise RuntimeError("Database pool not initialised — call init_pg_pool() first")
    return _pg_pool


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Acquire a single connection from the pool as an async context manager."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        yield conn


# ---------------------------------------------------------------------------
# QuestDB (HTTP / ILP)
# ---------------------------------------------------------------------------

class QuestDBClient:
    """Thin wrapper for QuestDB writes via the HTTP /exec endpoint and ILP ingestion."""

    def __init__(
        self,
        http_url: str = settings.questdb_url,
        ilp_host: str = settings.questdb_ilp_host,
        ilp_port: int = settings.questdb_ilp_port,
    ):
        self.http_url = http_url
        self.ilp_host = ilp_host
        self.ilp_port = ilp_port
        self._http_client: httpx.AsyncClient | None = None

    async def init(self) -> None:
        self._http_client = httpx.AsyncClient(base_url=self.http_url, timeout=10.0)

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def query(self, sql: str) -> dict:
        """Execute a SQL query against QuestDB via HTTP."""
        if not self._http_client:
            raise RuntimeError("QuestDB client not initialised — call init() first")
        resp = await self._http_client.get("/exec", params={"query": sql})
        resp.raise_for_status()
        return resp.json()

    async def write_ilp(self, line: str) -> None:
        """Send an ILP (Influx Line Protocol) line via HTTP /write endpoint."""
        if not self._http_client:
            raise RuntimeError("QuestDB client not initialised — call init() first")
        resp = await self._http_client.post(
            "/write",
            content=line.encode(),
            headers={"Content-Type": "text/plain"},
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

async def init_redis() -> aioredis.Redis:
    """Create and return a Redis connection."""
    global _redis
    _redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    logger.info("Redis connection initialised")
    return _redis


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    """Return the active Redis connection (must be initialised first)."""
    if _redis is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _redis
