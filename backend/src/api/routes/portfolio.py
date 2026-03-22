"""
Portfolio endpoints — summary, positions, value history, performance, and
broker reconciliation.  DB-backed with graceful fallbacks.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from src.config import settings

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_pool():
    """Return the asyncpg pool or None if unavailable."""
    try:
        from src.db import get_db_pool
        return get_db_pool()
    except RuntimeError:
        return None


def _get_redis():
    """Return the Redis client or None if unavailable."""
    try:
        from src.db import get_redis
        return get_redis()
    except RuntimeError:
        return None


# ---------------------------------------------------------------------------
# GET /summary — portfolio overview
# ---------------------------------------------------------------------------

@router.get("/summary")
async def portfolio_summary():
    """
    Portfolio overview: total value, cash, invested, unrealised/realised P&L,
    daily P&L, position count, open order count, and portfolio utilisation.
    """
    pool = _get_pool()

    if pool is None:
        # Graceful degradation — return zeros so the frontend renders
        return {
            "total_value": 0.0,
            "cash": 0.0,
            "invested": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "daily_pnl": 0.0,
            "daily_pnl_pct": 0.0,
            "position_count": 0,
            "open_order_count": 0,
            "portfolio_utilization_pct": 0.0,
            "paper_mode": settings.paper_mode,
            "shadow_mode": settings.shadow_mode,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Database unavailable — showing default values",
        }

    try:
        # Positions aggregate
        pos_row = await pool.fetchrow(
            """
            SELECT
                count(*)                              AS position_count,
                coalesce(sum(qty * current_price), 0) AS positions_value,
                coalesce(sum(qty * (current_price - avg_entry_price)), 0) AS unrealized_pnl
            FROM positions
            WHERE qty > 0
            """
        )

        position_count = int(pos_row["position_count"]) if pos_row else 0
        positions_value = float(pos_row["positions_value"]) if pos_row else 0.0
        unrealized_pnl = float(pos_row["unrealized_pnl"]) if pos_row else 0.0

        # Open orders count
        order_row = await pool.fetchrow(
            """
            SELECT count(*) AS cnt
            FROM orders
            WHERE status IN ('created', 'risk_checked', 'submitted')
            """
        )
        open_order_count = int(order_row["cnt"]) if order_row else 0

        # Realised P&L: sum of closed trade profits
        rpnl_row = await pool.fetchrow(
            """
            SELECT coalesce(sum(realized_pnl), 0) AS rpnl
            FROM trade_history
            """
        )
        realized_pnl = float(rpnl_row["rpnl"]) if rpnl_row else 0.0

        # Latest snapshot for cash / total value
        snap = await pool.fetchrow(
            """
            SELECT total_value, cash, snapshot_at
            FROM portfolio_snapshots
            ORDER BY snapshot_at DESC
            LIMIT 1
            """
        )

        if snap:
            total_value = float(snap["total_value"])
            cash = float(snap["cash"])
            updated_at = snap["snapshot_at"].isoformat() if snap["snapshot_at"] else datetime.now(timezone.utc).isoformat()
        else:
            # No snapshots yet — estimate from positions + a default starting cash
            cash = 100_000.0  # default paper account
            total_value = cash + positions_value
            updated_at = datetime.now(timezone.utc).isoformat()

        invested = positions_value

        # Daily P&L: difference from today's first snapshot
        daily_row = await pool.fetchrow(
            """
            SELECT total_value
            FROM portfolio_snapshots
            WHERE snapshot_at >= date_trunc('day', now())
            ORDER BY snapshot_at ASC
            LIMIT 1
            """
        )
        if daily_row:
            start_of_day = float(daily_row["total_value"])
            daily_pnl = total_value - start_of_day
            daily_pnl_pct = round(
                (daily_pnl / start_of_day * 100) if start_of_day > 0 else 0.0, 4
            )
        else:
            daily_pnl = 0.0
            daily_pnl_pct = 0.0

        portfolio_utilization_pct = round(
            (invested / total_value * 100) if total_value > 0 else 0.0, 2
        )

        return {
            "total_value": round(total_value, 2),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "realized_pnl": round(realized_pnl, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": daily_pnl_pct,
            "position_count": position_count,
            "open_order_count": open_order_count,
            "portfolio_utilization_pct": portfolio_utilization_pct,
            "paper_mode": settings.paper_mode,
            "shadow_mode": settings.shadow_mode,
            "updated_at": updated_at,
        }

    except Exception as exc:
        logger.error("portfolio_summary query failed: %s", exc)
        return {
            "total_value": 0.0,
            "cash": 0.0,
            "invested": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "daily_pnl": 0.0,
            "daily_pnl_pct": 0.0,
            "position_count": 0,
            "open_order_count": 0,
            "portfolio_utilization_pct": 0.0,
            "paper_mode": settings.paper_mode,
            "shadow_mode": settings.shadow_mode,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# GET /positions — all positions with current prices
# ---------------------------------------------------------------------------

@router.get("/positions")
async def list_positions():
    """
    All open positions with current prices, unrealised P&L, weight,
    stop loss info. Sorted by value descending.
    """
    pool = _get_pool()
    if pool is None:
        return []

    try:
        # Get portfolio total value for weight calculation
        snap = await pool.fetchrow(
            "SELECT total_value FROM portfolio_snapshots ORDER BY snapshot_at DESC LIMIT 1"
        )
        portfolio_value = float(snap["total_value"]) if snap else 0.0

        rows = await pool.fetch(
            """
            SELECT
                p.id,
                p.ticker_id,
                t.symbol,
                t.name,
                t.sector,
                t.is_otc,
                p.side,
                p.qty,
                p.avg_entry_price,
                p.current_price,
                p.stop_loss,
                p.trailing_stop_pct,
                p.opened_at,
                p.updated_at,
                (p.qty * p.current_price)                               AS market_value,
                (p.qty * (p.current_price - p.avg_entry_price))         AS unrealized_pnl,
                CASE
                    WHEN p.avg_entry_price > 0
                    THEN ((p.current_price - p.avg_entry_price) / p.avg_entry_price) * 100
                    ELSE 0
                END                                                      AS pnl_pct,
                CASE
                    WHEN p.current_price > 0 AND p.stop_loss > 0
                    THEN ((p.current_price - p.stop_loss) / p.current_price) * 100
                    ELSE NULL
                END                                                      AS distance_to_stop_pct
            FROM positions p
            JOIN tickers t ON t.id = p.ticker_id
            WHERE p.qty > 0
            ORDER BY (p.qty * p.current_price) DESC
            """
        )

        positions = []
        for r in rows:
            market_value = float(r["market_value"]) if r["market_value"] else 0.0
            weight = (market_value / portfolio_value * 100) if portfolio_value > 0 else 0.0

            positions.append({
                "id": r["id"],
                "ticker_id": r["ticker_id"],
                "symbol": r["symbol"],
                "name": r["name"],
                "sector": r["sector"],
                "is_otc": r["is_otc"],
                "side": r["side"],
                "qty": float(r["qty"]),
                "avg_entry_price": float(r["avg_entry_price"]),
                "current_price": float(r["current_price"]) if r["current_price"] else None,
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(float(r["unrealized_pnl"]), 2) if r["unrealized_pnl"] else 0.0,
                "pnl_pct": round(float(r["pnl_pct"]), 2) if r["pnl_pct"] else 0.0,
                "weight_pct": round(weight, 2),
                "stop_loss": float(r["stop_loss"]) if r["stop_loss"] else None,
                "trailing_stop_pct": float(r["trailing_stop_pct"]) if r["trailing_stop_pct"] else None,
                "distance_to_stop_pct": round(float(r["distance_to_stop_pct"]), 2) if r["distance_to_stop_pct"] else None,
                "opened_at": r["opened_at"].isoformat() if r["opened_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            })

        return positions

    except Exception as exc:
        logger.error("list_positions query failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# GET /positions/{symbol} — single position detail
# ---------------------------------------------------------------------------

@router.get("/positions/{symbol}")
async def position_detail(symbol: str):
    """
    Single position detail with related orders, signals, stop loss info,
    and current risk metrics.
    """
    pool = _get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    symbol_upper = symbol.upper()

    try:
        # Position data
        pos = await pool.fetchrow(
            """
            SELECT
                p.id, p.ticker_id, t.symbol, t.name, t.sector, t.is_otc,
                p.side, p.qty, p.avg_entry_price, p.current_price,
                p.stop_loss, p.trailing_stop_pct,
                p.opened_at, p.updated_at,
                (p.qty * p.current_price) AS market_value,
                (p.qty * (p.current_price - p.avg_entry_price)) AS unrealized_pnl
            FROM positions p
            JOIN tickers t ON t.id = p.ticker_id
            WHERE upper(t.symbol) = $1 AND p.qty > 0
            """,
            symbol_upper,
        )

        if pos is None:
            raise HTTPException(
                status_code=404, detail=f"No open position for {symbol_upper}"
            )

        ticker_id = pos["ticker_id"]

        # Related orders (recent 20)
        order_rows = await pool.fetch(
            """
            SELECT id, side, qty, price, order_type, status,
                   filled_qty, filled_avg_price, submitted_at, filled_at, created_at
            FROM orders
            WHERE ticker_id = $1
            ORDER BY created_at DESC
            LIMIT 20
            """,
            ticker_id,
        )

        orders = [
            {
                "id": o["id"],
                "side": o["side"],
                "qty": float(o["qty"]),
                "price": float(o["price"]) if o["price"] else None,
                "order_type": o["order_type"],
                "status": o["status"],
                "filled_qty": float(o["filled_qty"]) if o["filled_qty"] else 0.0,
                "filled_avg_price": float(o["filled_avg_price"]) if o["filled_avg_price"] else None,
                "submitted_at": o["submitted_at"].isoformat() if o["submitted_at"] else None,
                "filled_at": o["filled_at"].isoformat() if o["filled_at"] else None,
                "created_at": o["created_at"].isoformat() if o["created_at"] else None,
            }
            for o in order_rows
        ]

        # Related signals (recent 10)
        signal_rows = await pool.fetch(
            """
            SELECT id, signal_type, score, confidence, model, reasoning, created_at
            FROM signals
            WHERE ticker_id = $1
            ORDER BY created_at DESC
            LIMIT 10
            """,
            ticker_id,
        )

        signals = [
            {
                "id": s["id"],
                "signal_type": s["signal_type"],
                "score": float(s["score"]),
                "confidence": float(s["confidence"]),
                "model": s["model"],
                "reasoning": s["reasoning"],
                "created_at": s["created_at"].isoformat() if s["created_at"] else None,
            }
            for s in signal_rows
        ]

        # Portfolio value for weight
        snap = await pool.fetchrow(
            "SELECT total_value FROM portfolio_snapshots ORDER BY snapshot_at DESC LIMIT 1"
        )
        portfolio_value = float(snap["total_value"]) if snap else 0.0
        market_value = float(pos["market_value"]) if pos["market_value"] else 0.0
        weight = (market_value / portfolio_value * 100) if portfolio_value > 0 else 0.0

        return {
            "position": {
                "id": pos["id"],
                "ticker_id": pos["ticker_id"],
                "symbol": pos["symbol"],
                "name": pos["name"],
                "sector": pos["sector"],
                "is_otc": pos["is_otc"],
                "side": pos["side"],
                "qty": float(pos["qty"]),
                "avg_entry_price": float(pos["avg_entry_price"]),
                "current_price": float(pos["current_price"]) if pos["current_price"] else None,
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(float(pos["unrealized_pnl"]), 2) if pos["unrealized_pnl"] else 0.0,
                "weight_pct": round(weight, 2),
                "stop_loss": float(pos["stop_loss"]) if pos["stop_loss"] else None,
                "trailing_stop_pct": float(pos["trailing_stop_pct"]) if pos["trailing_stop_pct"] else None,
                "opened_at": pos["opened_at"].isoformat() if pos["opened_at"] else None,
                "updated_at": pos["updated_at"].isoformat() if pos["updated_at"] else None,
            },
            "orders": orders,
            "signals": signals,
            "risk": {
                "portfolio_weight_pct": round(weight, 2),
                "max_position_pct": settings.max_position_pct,
                "headroom_pct": round(settings.max_position_pct - weight, 2),
                "stop_loss": float(pos["stop_loss"]) if pos["stop_loss"] else None,
                "distance_to_stop_pct": (
                    round(
                        ((float(pos["current_price"]) - float(pos["stop_loss"])) / float(pos["current_price"])) * 100,
                        2,
                    )
                    if pos["current_price"] and pos["stop_loss"] and float(pos["current_price"]) > 0
                    else None
                ),
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("position_detail query failed for %s: %s", symbol, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# GET /history — portfolio value time series
# ---------------------------------------------------------------------------

@router.get("/history")
async def portfolio_history(
    period: str = Query(default="1W", description="1D, 1W, 1M, 3M, 6M, 1Y"),
    resolution: str = Query(default="1hour", description="5min, 1hour, 1day"),
):
    """
    Portfolio value time series from the portfolio_snapshots table.
    Returns array of {timestamp, value, pnl}.
    """
    pool = _get_pool()
    if pool is None:
        return {"period": period, "resolution": resolution, "data_points": [], "note": "Database unavailable"}

    # Map period to interval string
    interval_map = {
        "1D": "1 day",
        "1W": "7 days",
        "1M": "30 days",
        "3M": "90 days",
        "6M": "180 days",
        "1Y": "365 days",
    }
    interval = interval_map.get(period.upper(), "7 days")

    # Map resolution to a bucket width for time_bucket-like grouping
    # We'll use date_trunc or generate_series depending on resolution
    trunc_map = {
        "5min": "5 minutes",
        "1hour": "1 hour",
        "1day": "1 day",
    }
    bucket = trunc_map.get(resolution, "1 hour")

    try:
        # Use date_trunc for hourly/daily, custom for 5min
        if resolution == "5min":
            # Round snapshot_at to nearest 5 minutes
            rows = await pool.fetch(
                f"""
                SELECT
                    date_trunc('hour', snapshot_at)
                        + interval '5 min' * floor(extract(minute from snapshot_at) / 5) AS bucket_time,
                    avg(total_value)  AS value,
                    avg(daily_pnl)    AS pnl
                FROM portfolio_snapshots
                WHERE snapshot_at >= now() - interval '{interval}'
                GROUP BY bucket_time
                ORDER BY bucket_time ASC
                """
            )
        elif resolution == "1day":
            rows = await pool.fetch(
                f"""
                SELECT
                    date_trunc('day', snapshot_at) AS bucket_time,
                    avg(total_value)               AS value,
                    avg(daily_pnl)                 AS pnl
                FROM portfolio_snapshots
                WHERE snapshot_at >= now() - interval '{interval}'
                GROUP BY bucket_time
                ORDER BY bucket_time ASC
                """
            )
        else:
            # Default: 1 hour buckets
            rows = await pool.fetch(
                f"""
                SELECT
                    date_trunc('hour', snapshot_at) AS bucket_time,
                    avg(total_value)                AS value,
                    avg(daily_pnl)                  AS pnl
                FROM portfolio_snapshots
                WHERE snapshot_at >= now() - interval '{interval}'
                GROUP BY bucket_time
                ORDER BY bucket_time ASC
                """
            )

        data_points = [
            {
                "timestamp": r["bucket_time"].isoformat() if r["bucket_time"] else None,
                "value": round(float(r["value"]), 2) if r["value"] else 0.0,
                "pnl": round(float(r["pnl"]), 2) if r["pnl"] else 0.0,
            }
            for r in rows
        ]

        return {
            "period": period,
            "resolution": resolution,
            "data_points": data_points,
            "count": len(data_points),
        }

    except Exception as exc:
        logger.error("portfolio_history query failed: %s", exc)
        return {
            "period": period,
            "resolution": resolution,
            "data_points": [],
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# GET /performance — performance metrics
# ---------------------------------------------------------------------------

@router.get("/performance")
async def portfolio_performance():
    """
    Performance metrics: total return, daily/weekly/monthly returns,
    Sharpe ratio (if enough data), max drawdown, win rate.
    """
    pool = _get_pool()
    if pool is None:
        return {
            "total_return_pct": 0.0,
            "daily_return_pct": 0.0,
            "weekly_return_pct": 0.0,
            "monthly_return_pct": 0.0,
            "sharpe_ratio": None,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "note": "Database unavailable",
        }

    try:
        # Total return: (latest value - earliest value) / earliest value
        first_last = await pool.fetchrow(
            """
            SELECT
                (SELECT total_value FROM portfolio_snapshots ORDER BY snapshot_at ASC  LIMIT 1) AS first_value,
                (SELECT total_value FROM portfolio_snapshots ORDER BY snapshot_at DESC LIMIT 1) AS last_value
            """
        )

        first_val = float(first_last["first_value"]) if first_last and first_last["first_value"] else 0.0
        last_val = float(first_last["last_value"]) if first_last and first_last["last_value"] else 0.0
        total_return_pct = round(
            ((last_val - first_val) / first_val * 100) if first_val > 0 else 0.0, 4
        )

        # Period returns
        async def _period_return(interval: str) -> float:
            row = await pool.fetchrow(
                f"""
                SELECT total_value
                FROM portfolio_snapshots
                WHERE snapshot_at >= now() - interval '{interval}'
                ORDER BY snapshot_at ASC
                LIMIT 1
                """
            )
            if row and row["total_value"] and last_val > 0:
                start = float(row["total_value"])
                return round(((last_val - start) / start * 100) if start > 0 else 0.0, 4)
            return 0.0

        daily_return = await _period_return("1 day")
        weekly_return = await _period_return("7 days")
        monthly_return = await _period_return("30 days")

        # Max drawdown: look at daily snapshots
        dd_row = await pool.fetchrow(
            """
            WITH daily_vals AS (
                SELECT
                    date_trunc('day', snapshot_at) AS day,
                    avg(total_value) AS value
                FROM portfolio_snapshots
                GROUP BY day
                ORDER BY day
            ),
            running AS (
                SELECT
                    day,
                    value,
                    max(value) OVER (ORDER BY day) AS peak
                FROM daily_vals
            )
            SELECT
                min((value - peak) / NULLIF(peak, 0) * 100) AS max_drawdown_pct
            FROM running
            """
        )
        max_drawdown_pct = round(
            abs(float(dd_row["max_drawdown_pct"])) if dd_row and dd_row["max_drawdown_pct"] else 0.0, 4
        )

        # Win rate from trade_history
        wr_row = await pool.fetchrow(
            """
            SELECT
                count(*) AS total_trades,
                count(*) FILTER (WHERE realized_pnl > 0) AS winning_trades
            FROM trade_history
            """
        )
        total_trades = int(wr_row["total_trades"]) if wr_row else 0
        winning_trades = int(wr_row["winning_trades"]) if wr_row else 0
        win_rate_pct = round(
            (winning_trades / total_trades * 100) if total_trades > 0 else 0.0, 2
        )

        # Sharpe ratio (annualised) from daily returns
        sharpe_row = await pool.fetchrow(
            """
            WITH daily_vals AS (
                SELECT
                    date_trunc('day', snapshot_at) AS day,
                    avg(total_value) AS value
                FROM portfolio_snapshots
                GROUP BY day
                ORDER BY day
            ),
            daily_returns AS (
                SELECT
                    (value - lag(value) OVER (ORDER BY day)) / NULLIF(lag(value) OVER (ORDER BY day), 0) AS ret
                FROM daily_vals
            )
            SELECT
                avg(ret)    AS mean_return,
                stddev(ret) AS std_return,
                count(*)    AS n_days
            FROM daily_returns
            WHERE ret IS NOT NULL
            """
        )

        sharpe_ratio = None
        if sharpe_row and sharpe_row["std_return"] and float(sharpe_row["std_return"]) > 0:
            n_days = int(sharpe_row["n_days"])
            if n_days >= 5:
                mean_r = float(sharpe_row["mean_return"])
                std_r = float(sharpe_row["std_return"])
                # Annualise: Sharpe = (mean_daily / std_daily) * sqrt(252)
                sharpe_ratio = round((mean_r / std_r) * (252 ** 0.5), 4)

        return {
            "total_return_pct": total_return_pct,
            "daily_return_pct": daily_return,
            "weekly_return_pct": weekly_return,
            "monthly_return_pct": monthly_return,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": max_drawdown_pct,
            "win_rate_pct": win_rate_pct,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
        }

    except Exception as exc:
        logger.error("portfolio_performance query failed: %s", exc)
        return {
            "total_return_pct": 0.0,
            "daily_return_pct": 0.0,
            "weekly_return_pct": 0.0,
            "monthly_return_pct": 0.0,
            "sharpe_ratio": None,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# POST /reconcile — trigger position reconciliation with broker
# ---------------------------------------------------------------------------

@router.post("/reconcile")
async def reconcile_positions():
    """
    Trigger a position reconciliation between the local DB and the broker
    (Alpaca).  Returns a summary of mismatches found and corrective actions.
    """
    pool = _get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Try the OMS reconciliation method first
    try:
        from src.services.execution.oms import get_oms
        oms = get_oms()
        if oms is not None:
            result = await oms.reconcile_positions()
            return result
    except Exception:
        logger.debug("OMS reconcile unavailable, performing manual comparison")

    # Fallback: compare local positions with broker positions
    try:
        from src.services.execution.alpaca_broker import get_alpaca_broker
        broker = get_alpaca_broker()
        if broker is None:
            raise HTTPException(
                status_code=503, detail="Broker connection unavailable"
            )

        broker_positions = await broker.get_positions()
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Broker module not available — reconciliation requires the execution service",
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Broker error: {exc}")

    # Fetch local positions
    try:
        local_rows = await pool.fetch(
            """
            SELECT t.symbol, p.qty, p.avg_entry_price
            FROM positions p
            JOIN tickers t ON t.id = p.ticker_id
            WHERE p.qty > 0
            """
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DB error: {exc}")

    local_by_symbol = {r["symbol"]: r for r in local_rows}
    broker_by_symbol = {p["symbol"]: p for p in broker_positions}

    mismatches: list[dict] = []
    all_symbols = set(local_by_symbol.keys()) | set(broker_by_symbol.keys())

    for sym in sorted(all_symbols):
        local = local_by_symbol.get(sym)
        broker = broker_by_symbol.get(sym)

        if local and not broker:
            mismatches.append({
                "symbol": sym,
                "type": "local_only",
                "local_qty": float(local["qty"]),
                "broker_qty": 0,
                "action": "Position exists locally but not at broker",
            })
        elif broker and not local:
            mismatches.append({
                "symbol": sym,
                "type": "broker_only",
                "local_qty": 0,
                "broker_qty": float(broker.get("qty", 0)),
                "action": "Position exists at broker but not locally",
            })
        elif local and broker:
            local_qty = float(local["qty"])
            broker_qty = float(broker.get("qty", 0))
            if abs(local_qty - broker_qty) > 0.001:
                mismatches.append({
                    "symbol": sym,
                    "type": "qty_mismatch",
                    "local_qty": local_qty,
                    "broker_qty": broker_qty,
                    "action": "Quantity mismatch between local and broker",
                })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_local": len(local_by_symbol),
        "total_broker": len(broker_by_symbol),
        "mismatches": mismatches,
        "mismatch_count": len(mismatches),
        "status": "clean" if len(mismatches) == 0 else "discrepancies_found",
    }
