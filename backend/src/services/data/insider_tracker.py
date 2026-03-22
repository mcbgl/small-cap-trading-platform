"""
SEC EDGAR Form 4 insider trading tracker.

Monitors insider transactions via EDGAR, detects cluster buying patterns
(3+ insiders buying within 10 days = strong signal, academic alpha 4-6%).
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import httpx

from src.config import settings
from src.db import get_db_pool, get_redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transaction type codes (SEC Form 4)
# ---------------------------------------------------------------------------
TRANSACTION_CODES: dict[str, str] = {
    "P": "Open market or private purchase",
    "S": "Open market or private sale",
    "A": "Grant, award, or other acquisition",
    "D": "Disposition to the issuer",
    "F": "Payment of exercise price or tax liability by delivering securities",
    "I": "Discretionary transaction",
    "M": "Exercise or conversion of derivative security",
    "C": "Conversion of derivative security",
    "E": "Expiration of short derivative position",
    "G": "Bona fide gift",
    "H": "Expiration of long derivative position",
    "J": "Other acquisition or disposition",
    "K": "Equity swap or similar instrument",
    "L": "Small acquisition under Rule 16a-6",
    "U": "Disposition pursuant to a tender of shares in a change of control",
    "V": "Transaction voluntarily reported earlier than required",
    "W": "Acquisition or disposition by will or succession",
    "X": "Exercise of in-the-money or at-the-money derivative security",
    "Z": "Deposit into or withdrawal from voting trust",
}

# Relationship codes
RELATIONSHIP_MAP: dict[str, str] = {
    "isDirector": "Director",
    "isOfficer": "Officer",
    "isTenPercentOwner": "10% Owner",
    "isOther": "Other",
}


@dataclass
class InsiderTransaction:
    """A single parsed insider transaction from Form 4."""

    insider_name: str
    insider_role: str
    transaction_type: str  # P, S, A, etc.
    transaction_date: str  # YYYY-MM-DD
    shares: float
    price_per_share: float
    total_value: float
    shares_after: float
    form4_url: str
    cik: str = ""


@dataclass
class ClusterBuyingResult:
    """Result of cluster buying detection for a symbol."""

    symbol: str
    cluster_count: int
    insiders: list[dict]  # [{name, role, shares, value, date}]
    score: float
    confidence: float
    lookback_days: int
    has_ceo: bool = False
    has_large_purchases: bool = False


# ---------------------------------------------------------------------------
# Rate limiter — same 10 req/sec constraint as EdgarMonitor
# ---------------------------------------------------------------------------
class _RateLimiter:
    """Token-bucket rate limiter for SEC EDGAR API (10 req/sec)."""

    def __init__(self, max_per_second: float = 10.0) -> None:
        self._max_per_second = max_per_second
        self._min_interval = 1.0 / max_per_second
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = time.monotonic()


# ---------------------------------------------------------------------------
# InsiderTracker
# ---------------------------------------------------------------------------
class InsiderTracker:
    """
    Async tracker for SEC Form 4 insider transactions.

    Fetches Form 4 filings from EDGAR, parses XML to extract transaction
    details, detects cluster buying patterns, and generates insider signals.
    """

    FORM4_RSS_URL = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        "?action=getcompany&type=4&dateb=&owner=include"
        "&count=40&search_text=&action=getcompany&company=&CIK={cik}&output=atom"
    )

    def __init__(self) -> None:
        user_agent = settings.edgar_user_agent
        if not user_agent:
            raise ValueError(
                "edgar_user_agent must be set in settings "
                "(SEC requires 'CompanyName email@example.com')"
            )
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "application/atom+xml, application/xml, text/xml",
        }
        self._client: httpx.AsyncClient | None = None
        self._rate_limiter = _RateLimiter(max_per_second=10.0)

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Create the underlying httpx client."""
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
        logger.info("InsiderTracker started")

    async def close(self) -> None:
        """Shut down the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("InsiderTracker closed")

    # -- internal helpers ----------------------------------------------------

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        """Rate-limited GET request."""
        if not self._client:
            raise RuntimeError("InsiderTracker not started — call start() first")
        await self._rate_limiter.acquire()
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp

    # -- public API ----------------------------------------------------------

    async def fetch_recent_form4(self, cik: str) -> list[str]:
        """
        Get recent Form 4 filing URLs from EDGAR RSS/ATOM feed for a CIK.

        Args:
            cik: Central Index Key for the company.

        Returns:
            List of Form 4 filing document URLs.
        """
        padded_cik = cik.zfill(10)
        url = self.FORM4_RSS_URL.format(cik=padded_cik)
        resp = await self._get(url)

        # Parse ATOM feed
        namespaces = {
            "atom": "http://www.w3.org/2005/Atom",
        }

        filing_urls: list[str] = []
        try:
            root = ElementTree.fromstring(resp.text)
            entries = root.findall("atom:entry", namespaces)

            for entry in entries:
                # Each entry has a link to the filing index page
                link_el = entry.find("atom:link", namespaces)
                if link_el is not None:
                    href = link_el.get("href", "")
                    if href:
                        filing_urls.append(href)

                # Also check for content links
                content_el = entry.find("atom:content", namespaces)
                if content_el is not None and content_el.text:
                    # Extract document links from content HTML
                    import re

                    doc_links = re.findall(
                        r'href="(/Archives/edgar/data/[^"]+\.xml)"',
                        content_el.text,
                    )
                    for doc_link in doc_links:
                        full_url = f"https://www.sec.gov{doc_link}"
                        if full_url not in filing_urls:
                            filing_urls.append(full_url)

        except ElementTree.ParseError:
            logger.warning("Failed to parse ATOM feed for CIK %s", cik)

        logger.debug("Found %d Form 4 URLs for CIK %s", len(filing_urls), cik)
        return filing_urls

    def parse_form4_xml(self, xml_content: str) -> list[InsiderTransaction]:
        """
        Parse Form 4 XML to extract insider transaction details.

        SEC Form 4 XML uses the namespace:
        http://www.sec.gov/cgi-bin/viewer?action=view&cik=...

        But the ownership document schema is at:
        http://www.sec.gov/edgar/document/ownershipDocument

        Args:
            xml_content: Raw XML string of the Form 4 filing.

        Returns:
            List of InsiderTransaction objects.
        """
        transactions: list[InsiderTransaction] = []

        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError:
            logger.warning("Failed to parse Form 4 XML")
            return transactions

        # The Form 4 XML structure varies — handle with or without namespace
        # Try to find elements with common paths
        def _find_text(element: ElementTree.Element, path: str, default: str = "") -> str:
            """Find text in element, trying with and without namespace."""
            el = element.find(path)
            if el is not None and el.text:
                return el.text.strip()
            return default

        def _find_float(element: ElementTree.Element, path: str, default: float = 0.0) -> float:
            text = _find_text(element, path)
            if text:
                try:
                    return float(text.replace(",", ""))
                except ValueError:
                    pass
            return default

        # -- Reporting owner info --
        owner_name = ""
        owner_role = ""

        reporting_owner = root.find(".//reportingOwner")
        if reporting_owner is not None:
            owner_id = reporting_owner.find("reportingOwnerId")
            if owner_id is not None:
                owner_name = _find_text(owner_id, "rptOwnerName")

            relationship = reporting_owner.find("reportingOwnerRelationship")
            if relationship is not None:
                roles: list[str] = []
                for xml_key, label in RELATIONSHIP_MAP.items():
                    val = _find_text(relationship, xml_key)
                    if val in ("1", "true", "True"):
                        roles.append(label)
                # Also grab officer title
                officer_title = _find_text(relationship, "officerTitle")
                if officer_title:
                    roles.append(officer_title)
                owner_role = ", ".join(roles) if roles else "Unknown"

        # -- Issuer CIK --
        issuer = root.find(".//issuer")
        issuer_cik = ""
        if issuer is not None:
            issuer_cik = _find_text(issuer, "issuerCik")

        # -- Non-derivative transactions --
        for txn_el in root.findall(".//nonDerivativeTransaction"):
            coding = txn_el.find(".//transactionCoding")
            txn_code = ""
            if coding is not None:
                txn_code = _find_text(coding, "transactionCode")

            amounts = txn_el.find(".//transactionAmounts")
            shares = 0.0
            price = 0.0
            if amounts is not None:
                shares = _find_float(amounts, ".//transactionShares/value")
                price = _find_float(amounts, ".//transactionPricePerShare/value")

            date_el = txn_el.find(".//transactionDate")
            txn_date = ""
            if date_el is not None:
                txn_date = _find_text(date_el, "value")

            post_amounts = txn_el.find(".//postTransactionAmounts")
            shares_after = 0.0
            if post_amounts is not None:
                shares_after = _find_float(
                    post_amounts, ".//sharesOwnedFollowingTransaction/value"
                )

            total_value = shares * price

            transactions.append(
                InsiderTransaction(
                    insider_name=owner_name,
                    insider_role=owner_role,
                    transaction_type=txn_code,
                    transaction_date=txn_date,
                    shares=shares,
                    price_per_share=price,
                    total_value=total_value,
                    shares_after=shares_after,
                    form4_url="",  # Set by caller
                    cik=issuer_cik,
                )
            )

        # -- Derivative transactions --
        for txn_el in root.findall(".//derivativeTransaction"):
            coding = txn_el.find(".//transactionCoding")
            txn_code = ""
            if coding is not None:
                txn_code = _find_text(coding, "transactionCode")

            amounts = txn_el.find(".//transactionAmounts")
            shares = 0.0
            price = 0.0
            if amounts is not None:
                shares = _find_float(amounts, ".//transactionShares/value")
                price = _find_float(amounts, ".//transactionPricePerShare/value")

            date_el = txn_el.find(".//transactionDate")
            txn_date = ""
            if date_el is not None:
                txn_date = _find_text(date_el, "value")

            post_amounts = txn_el.find(".//postTransactionAmounts")
            shares_after = 0.0
            if post_amounts is not None:
                shares_after = _find_float(
                    post_amounts, ".//sharesOwnedFollowingTransaction/value"
                )

            total_value = shares * price

            transactions.append(
                InsiderTransaction(
                    insider_name=owner_name,
                    insider_role=owner_role,
                    transaction_type=txn_code,
                    transaction_date=txn_date,
                    shares=shares,
                    price_per_share=price,
                    total_value=total_value,
                    shares_after=shares_after,
                    form4_url="",
                    cik=issuer_cik,
                )
            )

        return transactions

    async def detect_cluster_buying(
        self,
        symbol: str,
        lookback_days: int = 10,
    ) -> ClusterBuyingResult | None:
        """
        Detect cluster insider buying from the database.

        A cluster = 3+ distinct insiders making open-market purchases (code 'P')
        within the lookback window. Academic research shows 4-6% alpha for
        cluster buys.

        Scoring:
            - 3 insiders = 6/10
            - 4 insiders = 7/10
            - 5+ insiders = 8/10
            - Bonus +0.5 if CEO is among buyers
            - Bonus +0.5 if any purchase exceeds $100k

        Args:
            symbol: Ticker symbol to check.
            lookback_days: Number of days to look back (default 10).

        Returns:
            ClusterBuyingResult if a cluster is detected, None otherwise.
        """
        pool = get_db_pool()
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        rows = await pool.fetch(
            """
            SELECT DISTINCT ON (it.insider_name)
                it.insider_name,
                it.insider_role,
                it.shares,
                it.total_value,
                it.transaction_date,
                it.price_per_share
            FROM insider_transactions it
            JOIN tickers t ON t.id = it.ticker_id
            WHERE t.symbol = $1
              AND it.transaction_type = 'P'
              AND it.transaction_date >= $2
            ORDER BY it.insider_name, it.total_value DESC
            """,
            symbol,
            cutoff.date(),
        )

        if len(rows) < 3:
            return None

        insiders: list[dict] = []
        has_ceo = False
        has_large_purchases = False

        for row in rows:
            role = row["insider_role"] or ""
            name = row["insider_name"] or ""
            value = float(row["total_value"] or 0)

            insiders.append(
                {
                    "name": name,
                    "role": role,
                    "shares": float(row["shares"] or 0),
                    "value": value,
                    "date": str(row["transaction_date"]),
                }
            )

            role_lower = role.lower()
            if "ceo" in role_lower or "chief executive" in role_lower:
                has_ceo = True
            if value > 100_000:
                has_large_purchases = True

        cluster_count = len(insiders)

        # Base scoring
        if cluster_count >= 5:
            score = 8.0
        elif cluster_count == 4:
            score = 7.0
        else:
            score = 6.0

        # Bonuses
        if has_ceo:
            score = min(10.0, score + 0.5)
        if has_large_purchases:
            score = min(10.0, score + 0.5)

        # Confidence based on cluster strength
        confidence = min(1.0, 0.60 + (cluster_count - 3) * 0.08)
        if has_ceo:
            confidence = min(1.0, confidence + 0.05)

        return ClusterBuyingResult(
            symbol=symbol,
            cluster_count=cluster_count,
            insiders=insiders,
            score=score,
            confidence=confidence,
            lookback_days=lookback_days,
            has_ceo=has_ceo,
            has_large_purchases=has_large_purchases,
        )

    async def scan_insider_activity(
        self,
        symbols: list[str],
        lookback_days: int = 10,
    ) -> list[ClusterBuyingResult]:
        """
        Batch scan multiple symbols for insider cluster buying.

        Args:
            symbols: List of ticker symbols to check.
            lookback_days: Number of days to look back.

        Returns:
            List of ClusterBuyingResult for symbols where clusters were detected.
        """
        results: list[ClusterBuyingResult] = []

        for symbol in symbols:
            try:
                cluster = await self.detect_cluster_buying(symbol, lookback_days)
                if cluster:
                    results.append(cluster)
                    logger.info(
                        "Insider cluster detected for %s: %d insiders, score=%.1f",
                        symbol,
                        cluster.cluster_count,
                        cluster.score,
                    )
            except Exception:
                logger.exception("Error scanning insider activity for %s", symbol)

        return results

    # -- persistence ---------------------------------------------------------

    async def store_transaction(
        self,
        txn: InsiderTransaction,
        ticker_id: int,
    ) -> int | None:
        """
        Insert an insider transaction into PostgreSQL.

        Returns the transaction id if inserted, None on conflict.
        """
        pool = get_db_pool()
        row = await pool.fetchrow(
            """
            INSERT INTO insider_transactions (
                ticker_id, cik, insider_name, insider_role,
                transaction_type, transaction_date, shares,
                price_per_share, total_value, shares_after, form4_url
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            ticker_id,
            txn.cik,
            txn.insider_name,
            txn.insider_role,
            txn.transaction_type,
            txn.transaction_date,
            txn.shares,
            txn.price_per_share,
            txn.total_value,
            txn.shares_after,
            txn.form4_url,
        )
        if row:
            logger.info(
                "Stored insider txn: %s %s %s shares of ticker_id=%d",
                txn.insider_name,
                txn.transaction_type,
                txn.shares,
                ticker_id,
            )
            return row["id"]
        return None

    async def store_cluster_signal(self, cluster: ClusterBuyingResult) -> int | None:
        """
        Store a cluster buying signal in the signals table.

        Maps cluster detection to the existing signals schema with
        signal_type='insider'.
        """
        pool = get_db_pool()

        # Resolve ticker_id from symbol
        ticker_row = await pool.fetchrow(
            "SELECT id FROM tickers WHERE symbol = $1", cluster.symbol
        )
        if not ticker_row:
            logger.warning("No ticker found for symbol %s — skipping signal", cluster.symbol)
            return None

        ticker_id = ticker_row["id"]
        metadata = json.dumps(
            {
                "cluster_count": cluster.cluster_count,
                "insiders": cluster.insiders,
                "lookback_days": cluster.lookback_days,
                "has_ceo": cluster.has_ceo,
                "has_large_purchases": cluster.has_large_purchases,
            }
        )
        reasoning = (
            f"Insider cluster buying detected: {cluster.cluster_count} distinct insiders "
            f"made open-market purchases in the last {cluster.lookback_days} days."
        )
        if cluster.has_ceo:
            reasoning += " CEO among buyers."
        if cluster.has_large_purchases:
            reasoning += " Includes purchase(s) exceeding $100k."

        row = await pool.fetchrow(
            """
            INSERT INTO signals (
                ticker_id, signal_type, score, confidence,
                model, reasoning, metadata
            )
            VALUES ($1, 'insider', $2, $3, 'insider_cluster_v1', $4, $5::jsonb)
            RETURNING id
            """,
            ticker_id,
            cluster.score,
            cluster.confidence,
            reasoning,
            metadata,
        )
        if row:
            logger.info(
                "Stored insider cluster signal id=%d for %s (score=%.1f)",
                row["id"],
                cluster.symbol,
                cluster.score,
            )
            return row["id"]
        return None

    async def publish_insider_alert(self, cluster: ClusterBuyingResult) -> None:
        """Publish an insider cluster alert to Redis channel:signals."""
        try:
            redis = get_redis()
            alert = {
                "type": "insider_cluster",
                "symbol": cluster.symbol,
                "cluster_count": cluster.cluster_count,
                "score": cluster.score,
                "confidence": cluster.confidence,
                "insiders": cluster.insiders,
                "has_ceo": cluster.has_ceo,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await redis.publish("channel:signals", json.dumps(alert))
            logger.debug("Published insider alert for %s to channel:signals", cluster.symbol)
        except Exception:
            logger.warning("Failed to publish insider alert to Redis", exc_info=True)
