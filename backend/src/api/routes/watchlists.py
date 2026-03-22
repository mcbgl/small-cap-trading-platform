"""
Watchlist endpoints -- manage stock watchlists for monitoring.

CRUD operations on watchlists and their items.  Items are added by ticker
symbol (with auto-resolution to ticker_id).  Watchlist item listings are
enriched with the latest signal for each ticker.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.models.schemas import WatchlistCreate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class WatchlistUpdate(BaseModel):
    """Payload for updating a watchlist's name and/or description."""

    name: str | None = None
    description: str | None = None


class WatchlistItemAdd(BaseModel):
    """Payload for adding a ticker to a watchlist by symbol."""

    symbol: str


# ---------------------------------------------------------------------------
# GET / — list all watchlists with item counts
# ---------------------------------------------------------------------------

@router.get("")
async def list_watchlists():
    """
    List all watchlists with their item counts.

    Returns watchlists ordered by creation date descending.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        return {"error": "Database not available", "watchlists": []}

    try:
        rows = await pool.fetch(
            """
            SELECT
                w.id,
                w.name,
                w.description,
                COUNT(wi.id) AS ticker_count,
                w.created_at,
                w.updated_at
            FROM watchlists w
            LEFT JOIN watchlist_items wi ON wi.watchlist_id = w.id
            GROUP BY w.id
            ORDER BY w.created_at DESC
            """
        )
        return {"watchlists": [dict(row) for row in rows]}

    except Exception:
        logger.exception("Failed to list watchlists")
        raise HTTPException(status_code=500, detail="Failed to retrieve watchlists")


# ---------------------------------------------------------------------------
# POST / — create a new watchlist
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_watchlist(body: WatchlistCreate):
    """
    Create a new watchlist.

    Accepts a name and optional description.  Returns the newly created
    watchlist with its id and timestamps.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        row = await pool.fetchrow(
            """
            INSERT INTO watchlists (name, description, created_at, updated_at)
            VALUES ($1, $2, NOW(), NOW())
            RETURNING id, name, description, created_at, updated_at
            """,
            body.name,
            body.description,
        )
        return {**dict(row), "ticker_count": 0}

    except Exception:
        logger.exception("Failed to create watchlist")
        raise HTTPException(status_code=500, detail="Failed to create watchlist")


# ---------------------------------------------------------------------------
# GET /{watchlist_id} — get watchlist with items + latest signals
# ---------------------------------------------------------------------------

@router.get("/{watchlist_id}")
async def get_watchlist(watchlist_id: int):
    """
    Get a watchlist with all its items.

    Each item is enriched with ticker details (symbol, name, sector, market_cap)
    and the latest signal for that ticker (type, score, confidence, timestamp).
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        # Fetch watchlist metadata
        wl = await pool.fetchrow(
            """
            SELECT id, name, description, created_at, updated_at
            FROM watchlists WHERE id = $1
            """,
            watchlist_id,
        )
        if wl is None:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        # Fetch items with ticker details and latest signal
        items = await pool.fetch(
            """
            SELECT
                wi.id AS item_id,
                t.id AS ticker_id,
                t.symbol,
                t.name,
                t.sector,
                t.industry,
                t.market_cap,
                t.avg_volume,
                t.exchange,
                wi.added_at,
                ls.signal_type AS latest_signal_type,
                ls.score AS latest_signal_score,
                ls.confidence AS latest_signal_confidence,
                ls.created_at AS latest_signal_at
            FROM watchlist_items wi
            JOIN tickers t ON t.id = wi.ticker_id
            LEFT JOIN LATERAL (
                SELECT s.signal_type, s.score, s.confidence, s.created_at
                FROM signals s
                WHERE s.symbol = t.symbol
                ORDER BY s.created_at DESC
                LIMIT 1
            ) ls ON true
            WHERE wi.watchlist_id = $1
            ORDER BY wi.added_at DESC
            """,
            watchlist_id,
        )

        item_list = []
        for item in items:
            d = dict(item)
            # Group latest signal into a sub-object
            if d.get("latest_signal_type"):
                d["latest_signal"] = {
                    "type": d.pop("latest_signal_type"),
                    "score": float(d.pop("latest_signal_score")),
                    "confidence": float(d.pop("latest_signal_confidence")),
                    "at": d.pop("latest_signal_at"),
                }
            else:
                d.pop("latest_signal_type", None)
                d.pop("latest_signal_score", None)
                d.pop("latest_signal_confidence", None)
                d.pop("latest_signal_at", None)
                d["latest_signal"] = None
            item_list.append(d)

        return {
            **dict(wl),
            "ticker_count": len(item_list),
            "items": item_list,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get watchlist %d", watchlist_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve watchlist")


# ---------------------------------------------------------------------------
# PUT /{watchlist_id} — update watchlist name/description
# ---------------------------------------------------------------------------

@router.put("/{watchlist_id}")
async def update_watchlist(watchlist_id: int, body: WatchlistUpdate):
    """
    Update a watchlist's name and/or description.

    Only provided fields are updated; omitted fields remain unchanged.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        # Build dynamic SET clause
        set_parts: list[str] = ["updated_at = NOW()"]
        params: list = []
        idx = 1

        if body.name is not None:
            set_parts.append(f"name = ${idx}")
            params.append(body.name)
            idx += 1

        if body.description is not None:
            set_parts.append(f"description = ${idx}")
            params.append(body.description)
            idx += 1

        if len(set_parts) == 1:
            # Only updated_at, nothing meaningful to change
            raise HTTPException(
                status_code=400,
                detail="At least one of 'name' or 'description' must be provided",
            )

        params.append(watchlist_id)
        set_clause = ", ".join(set_parts)

        row = await pool.fetchrow(
            f"""
            UPDATE watchlists
            SET {set_clause}
            WHERE id = ${idx}
            RETURNING id, name, description, created_at, updated_at
            """,
            *params,
        )

        if row is None:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        return dict(row)

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update watchlist %d", watchlist_id)
        raise HTTPException(status_code=500, detail="Failed to update watchlist")


# ---------------------------------------------------------------------------
# DELETE /{watchlist_id} — delete watchlist and its items
# ---------------------------------------------------------------------------

@router.delete("/{watchlist_id}")
async def delete_watchlist(watchlist_id: int):
    """
    Delete a watchlist and all its items.

    Items are deleted first (FK constraint), then the watchlist itself.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Delete items first
                await conn.execute(
                    "DELETE FROM watchlist_items WHERE watchlist_id = $1",
                    watchlist_id,
                )
                result = await conn.execute(
                    "DELETE FROM watchlists WHERE id = $1",
                    watchlist_id,
                )
                if result == "DELETE 0":
                    raise HTTPException(status_code=404, detail="Watchlist not found")

        return {"status": "deleted", "watchlist_id": watchlist_id}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete watchlist %d", watchlist_id)
        raise HTTPException(status_code=500, detail="Failed to delete watchlist")


# ---------------------------------------------------------------------------
# POST /{watchlist_id}/items — add ticker by symbol
# ---------------------------------------------------------------------------

@router.post("/{watchlist_id}/items", status_code=201)
async def add_watchlist_item(watchlist_id: int, body: WatchlistItemAdd):
    """
    Add a ticker to a watchlist by symbol.

    If the ticker does not exist in the tickers table, it is auto-created
    as an active ticker stub (name defaults to symbol, no sector/market_cap).
    Duplicate additions are silently ignored (ON CONFLICT DO NOTHING).
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    symbol = body.symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol must not be empty")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Verify watchlist exists
                wl = await conn.fetchval(
                    "SELECT id FROM watchlists WHERE id = $1",
                    watchlist_id,
                )
                if wl is None:
                    raise HTTPException(status_code=404, detail="Watchlist not found")

                # Resolve ticker_id -- auto-create if not found
                ticker_row = await conn.fetchrow(
                    "SELECT id, name FROM tickers WHERE symbol = $1",
                    symbol,
                )

                if ticker_row:
                    ticker_id = ticker_row["id"]
                    ticker_name = ticker_row["name"]
                else:
                    # Auto-create a stub ticker
                    new_ticker = await conn.fetchrow(
                        """
                        INSERT INTO tickers (symbol, name, is_active, created_at)
                        VALUES ($1, $1, true, NOW())
                        RETURNING id, name
                        """,
                        symbol,
                    )
                    ticker_id = new_ticker["id"]
                    ticker_name = new_ticker["name"]
                    logger.info(
                        "Auto-created stub ticker %s (id=%d) for watchlist",
                        symbol,
                        ticker_id,
                    )

                # Insert watchlist item (ignore duplicate)
                result = await conn.fetchrow(
                    """
                    INSERT INTO watchlist_items (watchlist_id, ticker_id, added_at)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (watchlist_id, ticker_id) DO NOTHING
                    RETURNING id
                    """,
                    watchlist_id,
                    ticker_id,
                )

                already_existed = result is None

        return {
            "status": "already_exists" if already_existed else "added",
            "watchlist_id": watchlist_id,
            "symbol": symbol,
            "ticker_id": ticker_id,
            "ticker_name": ticker_name,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to add %s to watchlist %d", symbol, watchlist_id
        )
        raise HTTPException(status_code=500, detail="Failed to add item to watchlist")


# ---------------------------------------------------------------------------
# DELETE /{watchlist_id}/items/{symbol} — remove ticker by symbol
# ---------------------------------------------------------------------------

@router.delete("/{watchlist_id}/items/{symbol}")
async def remove_watchlist_item(watchlist_id: int, symbol: str):
    """
    Remove a ticker from a watchlist by symbol.

    Resolves the symbol to a ticker_id and deletes the watchlist_items row.
    Returns 404 if the symbol is not in the watchlist.
    """
    try:
        from src.db import get_db_pool

        pool = get_db_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not available")

    symbol_upper = symbol.upper().strip()

    try:
        # Resolve ticker_id
        ticker_id = await pool.fetchval(
            "SELECT id FROM tickers WHERE symbol = $1",
            symbol_upper,
        )
        if ticker_id is None:
            raise HTTPException(
                status_code=404,
                detail=f"Ticker '{symbol_upper}' not found",
            )

        result = await pool.execute(
            """
            DELETE FROM watchlist_items
            WHERE watchlist_id = $1 AND ticker_id = $2
            """,
            watchlist_id,
            ticker_id,
        )

        if result == "DELETE 0":
            raise HTTPException(
                status_code=404,
                detail=f"'{symbol_upper}' is not in watchlist {watchlist_id}",
            )

        return {
            "status": "removed",
            "watchlist_id": watchlist_id,
            "symbol": symbol_upper,
            "ticker_id": ticker_id,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to remove %s from watchlist %d", symbol_upper, watchlist_id
        )
        raise HTTPException(
            status_code=500, detail="Failed to remove item from watchlist"
        )
