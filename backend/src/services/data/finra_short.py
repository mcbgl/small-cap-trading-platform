"""
FINRA short interest data via API.

FINRA API uses OAuth 2.0, provides consolidated short interest across all
exchanges + OTC. Updated bi-monthly (settlement dates). 5 years rolling history.
API: api.finra.org
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from src.config import settings
from src.db import get_db_pool, get_redis

logger = logging.getLogger(__name__)

OAUTH_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token"
SHORT_INTEREST_URL = (
    "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
)
CACHE_TTL_SECONDS = 43_200  # 12 hours — data only updates bi-monthly
CACHE_PREFIX = "finra:si:"


@dataclass
class ShortInterestData:
    """Parsed short interest record from FINRA."""

    symbol: str
    settlement_date: str
    current_short_interest: int
    previous_short_interest: int
    change: int
    change_pct: float
    avg_daily_volume: float | None = None
    days_to_cover: float | None = None
    si_pct_float: float | None = None


@dataclass
class ShortInterestMetrics:
    """Computed short interest metrics for signal scoring."""

    symbol: str
    si_pct: float  # short interest / shares outstanding
    days_to_cover: float  # short interest / avg daily volume
    si_change_pct: float  # settlement-over-settlement % change
    si_trend: str  # "rising", "falling", "flat"
    current_short_interest: int = 0
    settlement_date: str = ""
    raw: dict = field(default_factory=dict)


class FinraShortInterest:
    """
    Client for FINRA short interest data.

    Uses OAuth 2.0 client credentials for authentication.  Results are cached
    in Redis (12h TTL) and persisted to PostgreSQL for historical analysis.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self._client_id = client_id or settings.polygon_api_key  # reuse or set separate
        self._client_secret = client_secret or ""
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Initialise the async HTTP client."""
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"Accept": "application/json"},
        )
        logger.info("FinraShortInterest client initialised")

    async def close(self) -> None:
        """Shut down the HTTP client."""
        if self._http:
            await self._http.aclose()
            self._http = None
            logger.info("FinraShortInterest client closed")

    # ------------------------------------------------------------------
    # OAuth 2.0
    # ------------------------------------------------------------------

    async def _ensure_token(self) -> str:
        """Obtain or refresh the OAuth 2.0 access token."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        if not self._http:
            raise RuntimeError("Client not initialised — call init() first")

        logger.debug("Requesting new FINRA OAuth token")
        resp = await self._http.post(
            OAUTH_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        resp.raise_for_status()
        payload = resp.json()

        self._access_token = payload["access_token"]
        # Default to 30-min expiry if not provided
        expires_in = int(payload.get("expires_in", 1800))
        self._token_expires_at = time.time() + expires_in
        logger.info("FINRA OAuth token acquired (expires in %ds)", expires_in)
        return self._access_token

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def get_short_interest(self, symbol: str) -> ShortInterestData | None:
        """
        Fetch the latest short interest record for *symbol* from FINRA.

        Returns ``None`` if no data is available.  Checks Redis cache first.
        """
        cache_key = f"{CACHE_PREFIX}{symbol.upper()}"
        redis = get_redis()

        # --- Cache hit ---
        cached = await redis.get(cache_key)
        if cached:
            logger.debug("FINRA SI cache hit for %s", symbol)
            return self._parse_record(json.loads(cached), symbol)

        # --- API fetch ---
        if not self._http:
            raise RuntimeError("Client not initialised — call init() first")

        token = await self._ensure_token()
        resp = await self._http.post(
            SHORT_INTEREST_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "fields": [
                    "symbolCode",
                    "currentShortPositionQuantity",
                    "previousShortPositionQuantity",
                    "changePreviousNumber",
                    "changePercent",
                    "settlementDate",
                    "averageDailyVolumeQuantity",
                    "daysToCoverQuantity",
                ],
                "compareFilters": [
                    {
                        "fieldName": "symbolCode",
                        "fieldValue": symbol.upper(),
                        "compareType": "EQUAL",
                    }
                ],
                "limit": 5,
                "sortFields": ["-settlementDate"],
            },
        )
        resp.raise_for_status()
        rows = resp.json()

        if not rows:
            logger.info("No FINRA SI data for %s", symbol)
            return None

        record = rows[0]  # most recent settlement date

        # Cache the raw record
        await redis.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(record))
        logger.info(
            "FINRA SI fetched for %s — settlement %s",
            symbol,
            record.get("settlementDate"),
        )
        return self._parse_record(record, symbol)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    async def compute_metrics(
        self,
        symbol: str,
        avg_volume: float,
        shares_outstanding: float,
    ) -> ShortInterestMetrics | None:
        """
        Compute derived short-interest metrics for *symbol*.

        * SI%  = short_interest / shares_outstanding
        * DTC  = short_interest / avg_daily_volume
        * Trend = compare current vs previous settlement
        """
        data = await self.get_short_interest(symbol)
        if data is None:
            return None

        si_pct = (
            (data.current_short_interest / shares_outstanding) * 100
            if shares_outstanding > 0
            else 0.0
        )

        dtc = (
            data.current_short_interest / avg_volume
            if avg_volume > 0
            else 0.0
        )

        change_pct = data.change_pct

        if change_pct > 2.0:
            trend = "rising"
        elif change_pct < -2.0:
            trend = "falling"
        else:
            trend = "flat"

        return ShortInterestMetrics(
            symbol=symbol.upper(),
            si_pct=round(si_pct, 2),
            days_to_cover=round(dtc, 2),
            si_change_pct=round(change_pct, 2),
            si_trend=trend,
            current_short_interest=data.current_short_interest,
            settlement_date=data.settlement_date,
            raw={
                "current": data.current_short_interest,
                "previous": data.previous_short_interest,
                "change": data.change,
                "avg_daily_volume": data.avg_daily_volume,
            },
        )

    # ------------------------------------------------------------------
    # Batch scanner
    # ------------------------------------------------------------------

    async def scan_squeeze_candidates(
        self,
        symbols: list[str],
        min_si_pct: float = 10.0,
    ) -> list[ShortInterestMetrics]:
        """
        Batch-scan *symbols* for squeeze candidates.

        Returns the subset with SI% >= *min_si_pct*, sorted descending by SI%.
        Requires shares_outstanding & avg_volume from the tickers table.
        """
        pool = get_db_pool()
        results: list[ShortInterestMetrics] = []

        for symbol in symbols:
            try:
                row = await pool.fetchrow(
                    """
                    SELECT avg_volume, market_cap
                    FROM tickers
                    WHERE symbol = $1 AND is_active = true
                    """,
                    symbol.upper(),
                )
                if not row or not row["market_cap"]:
                    continue

                # Rough shares outstanding estimate: market_cap / last_price
                # In production, pull from a fundamentals table.
                avg_vol = float(row["avg_volume"] or 0)
                shares_out = float(row["market_cap"])  # placeholder — refine later

                metrics = await self.compute_metrics(symbol, avg_vol, shares_out)
                if metrics and metrics.si_pct >= min_si_pct:
                    results.append(metrics)
            except Exception:
                logger.exception("Error scanning squeeze candidate %s", symbol)

        results.sort(key=lambda m: m.si_pct, reverse=True)
        logger.info(
            "Squeeze scan complete: %d/%d symbols above %.1f%% SI",
            len(results),
            len(symbols),
            min_si_pct,
        )
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def store(self, data: ShortInterestData) -> None:
        """Upsert a short-interest record into PostgreSQL."""
        pool = get_db_pool()
        await pool.execute(
            """
            INSERT INTO short_interest (
                symbol, settlement_date, current_short_interest,
                previous_short_interest, change, change_pct,
                avg_daily_volume, days_to_cover, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (symbol, settlement_date) DO UPDATE SET
                current_short_interest = EXCLUDED.current_short_interest,
                previous_short_interest = EXCLUDED.previous_short_interest,
                change = EXCLUDED.change,
                change_pct = EXCLUDED.change_pct,
                avg_daily_volume = EXCLUDED.avg_daily_volume,
                days_to_cover = EXCLUDED.days_to_cover,
                updated_at = NOW()
            """,
            data.symbol,
            data.settlement_date,
            data.current_short_interest,
            data.previous_short_interest,
            data.change,
            data.change_pct,
            data.avg_daily_volume,
            data.days_to_cover,
        )
        logger.debug("Stored SI for %s (%s)", data.symbol, data.settlement_date)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_record(record: dict, symbol: str) -> ShortInterestData:
        """Parse a raw FINRA API row into a ``ShortInterestData``."""
        current = int(record.get("currentShortPositionQuantity", 0))
        previous = int(record.get("previousShortPositionQuantity", 0))
        change = int(record.get("changePreviousNumber", 0))
        change_pct = float(record.get("changePercent", 0.0))
        settlement = record.get("settlementDate", "")
        avg_vol = record.get("averageDailyVolumeQuantity")
        dtc = record.get("daysToCoverQuantity")

        return ShortInterestData(
            symbol=symbol.upper(),
            settlement_date=settlement,
            current_short_interest=current,
            previous_short_interest=previous,
            change=change,
            change_pct=change_pct,
            avg_daily_volume=float(avg_vol) if avg_vol is not None else None,
            days_to_cover=float(dtc) if dtc is not None else None,
        )
