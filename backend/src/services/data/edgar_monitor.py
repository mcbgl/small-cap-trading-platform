"""
SEC EDGAR filing monitor.

Polls EDGAR full-text search API for filings mentioning watchlist companies.
Parses 8-K, 10-K, 10-Q, SC 13D/G filings for distress signals.
Extracts key phrases and queues for AI analysis.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from src.config import settings
from src.db import get_db_pool, get_redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Distress keywords to scan for in filing text
# ---------------------------------------------------------------------------
DISTRESS_KEYWORDS: list[str] = [
    "going concern",
    "substantial doubt",
    "material weakness",
    "covenant breach",
    "covenant waiver",
    "default",
    "forbearance",
    "restructuring",
    "impairment",
    "liquidity risk",
    "bankruptcy",
    "chapter 11",
    "going private",
    "delisting",
    "restatement",
    "late filing",
    "material misstatement",
    "auditor resignation",
    "inability to continue",
]

# ---------------------------------------------------------------------------
# 8-K item number mapping
# ---------------------------------------------------------------------------
ITEM_8K_MAP: dict[str, str] = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.04": "Triggering Events That Accelerate or Increase a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy a Continued Listing Rule",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure of Directors or Certain Officers; Election of Directors",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "5.06": "Change in Shell Company Status",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}


@dataclass
class KeywordMatch:
    """A single distress keyword found in filing text."""

    keyword: str
    context_snippet: str
    position: int


@dataclass
class FilingResult:
    """Parsed filing from EDGAR search."""

    accession_number: str
    form_type: str
    filed_date: str
    entity_name: str
    cik: str
    title: str
    url: str
    keywords_found: list[KeywordMatch] = field(default_factory=list)
    items_8k: list[dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rate limiter — SEC mandates max 10 requests/second
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
# EdgarMonitor
# ---------------------------------------------------------------------------
class EdgarMonitor:
    """
    Async monitor for SEC EDGAR filings.

    Searches the EDGAR full-text search API, downloads filing content,
    scans for distress keywords, and stores results in PostgreSQL.
    Publishes alerts to Redis for downstream consumers.
    """

    SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
    XBRL_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    def __init__(self) -> None:
        user_agent = settings.edgar_user_agent
        if not user_agent:
            raise ValueError(
                "edgar_user_agent must be set in settings "
                "(SEC requires 'CompanyName email@example.com')"
            )
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "application/json",
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
        logger.info("EdgarMonitor started")

    async def close(self) -> None:
        """Shut down the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("EdgarMonitor closed")

    # -- internal helpers ----------------------------------------------------

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        """Rate-limited GET request."""
        if not self._client:
            raise RuntimeError("EdgarMonitor not started — call start() first")
        await self._rate_limiter.acquire()
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp

    # -- public API ----------------------------------------------------------

    async def poll_filings(
        self,
        symbols: list[str],
        form_types: list[str] | None = None,
        lookback_hours: int = 24,
    ) -> list[FilingResult]:
        """
        Search EDGAR full-text search API for recent filings mentioning the
        given ticker symbols.

        Args:
            symbols: List of ticker symbols to search for.
            form_types: Filing form types to filter (default: 8-K, 10-K, 10-Q).
            lookback_hours: How far back to search (default 24h).

        Returns:
            List of FilingResult objects with parsed metadata.
        """
        if form_types is None:
            form_types = ["8-K", "10-K", "10-Q", "SC 13D", "SC 13G"]

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(hours=lookback_hours)

        all_results: list[FilingResult] = []

        for symbol in symbols:
            try:
                params = {
                    "q": f'"{symbol}"',
                    "dateRange": "custom",
                    "startdt": start_dt.strftime("%Y-%m-%d"),
                    "enddt": end_dt.strftime("%Y-%m-%d"),
                    "forms": ",".join(form_types),
                }
                resp = await self._get(self.SEARCH_URL, params=params)
                data = resp.json()

                hits = data.get("hits", {}).get("hits", [])
                for hit in hits:
                    source = hit.get("_source", {})
                    filing = FilingResult(
                        accession_number=source.get("file_num", source.get("adsh", "")),
                        form_type=source.get("form_type", source.get("file_type", "")),
                        filed_date=source.get("file_date", source.get("period_of_report", "")),
                        entity_name=source.get("entity_name", source.get("display_names", [""])[0] if source.get("display_names") else ""),
                        cik=str(source.get("entity_id", source.get("ciks", [""])[0] if source.get("ciks") else "")),
                        title=source.get("display_names", [symbol])[0] if source.get("display_names") else symbol,
                        url=self._build_filing_url(source),
                    )
                    all_results.append(filing)

                logger.debug("EDGAR search for %s returned %d hits", symbol, len(hits))

            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "EDGAR search failed for %s: HTTP %d", symbol, exc.response.status_code
                )
            except Exception:
                logger.exception("Unexpected error polling EDGAR for %s", symbol)

        return all_results

    @staticmethod
    def _build_filing_url(source: dict) -> str:
        """Build the EDGAR filing URL from search result metadata."""
        # Full-text search returns file_url or we construct from accession number
        if "file_url" in source:
            return f"https://www.sec.gov{source['file_url']}"
        adsh = source.get("adsh", "")
        if adsh:
            clean = adsh.replace("-", "")
            return f"https://www.sec.gov/Archives/edgar/data/{source.get('entity_id', '')}/{clean}/{adsh}-index.htm"
        return ""

    async def get_filing_text(self, url: str) -> str:
        """
        Download and parse filing HTML/text content.

        Returns plain text extracted from the filing HTML.
        """
        resp = await self._get(url)
        content_type = resp.headers.get("content-type", "")

        if "html" in content_type or "xml" in content_type:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove script and style elements
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)

        return resp.text

    def search_keywords(self, text: str) -> list[KeywordMatch]:
        """
        Search filing text for distress-signal keywords.

        Returns a list of KeywordMatch with keyword, surrounding context
        snippet (100 chars each side), and character position.
        """
        text_lower = text.lower()
        matches: list[KeywordMatch] = []
        seen_positions: set[int] = set()

        for keyword in DISTRESS_KEYWORDS:
            start = 0
            while True:
                pos = text_lower.find(keyword, start)
                if pos == -1:
                    break
                # Deduplicate overlapping matches at same position
                if pos not in seen_positions:
                    seen_positions.add(pos)
                    snippet_start = max(0, pos - 100)
                    snippet_end = min(len(text), pos + len(keyword) + 100)
                    context = text[snippet_start:snippet_end].strip()
                    matches.append(
                        KeywordMatch(keyword=keyword, context_snippet=context, position=pos)
                    )
                start = pos + len(keyword)

        return matches

    async def get_company_facts(self, cik: str) -> dict:
        """
        Fetch XBRL company facts for a CIK (zero-padded to 10 digits).

        Returns the raw JSON dict from the XBRL companyfacts API, which
        contains structured financial data (revenues, assets, etc.).
        """
        padded_cik = cik.zfill(10)
        url = self.XBRL_URL.format(cik=padded_cik)
        resp = await self._get(url)
        return resp.json()

    async def get_recent_filings(self, cik: str, form_type: str | None = None) -> list[dict]:
        """
        Get filing list from the EDGAR submissions API for a given CIK.

        Args:
            cik: Central Index Key (will be zero-padded).
            form_type: Optional filter for specific form type.

        Returns:
            List of filing dicts with keys: accessionNumber, form, filingDate,
            primaryDocument, etc.
        """
        padded_cik = cik.zfill(10)
        url = self.SUBMISSIONS_URL.format(cik=padded_cik)
        resp = await self._get(url)
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            return []

        filings: list[dict] = []
        accession_numbers = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])
        primary_doc_descriptions = recent.get("primaryDocDescription", [])

        for i in range(len(accession_numbers)):
            entry = {
                "accessionNumber": accession_numbers[i] if i < len(accession_numbers) else "",
                "form": forms[i] if i < len(forms) else "",
                "filingDate": filing_dates[i] if i < len(filing_dates) else "",
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
                "primaryDocDescription": (
                    primary_doc_descriptions[i]
                    if i < len(primary_doc_descriptions)
                    else ""
                ),
            }
            if form_type and entry["form"] != form_type:
                continue
            filings.append(entry)

        return filings

    def parse_8k_items(self, html: str) -> list[dict[str, str]]:
        """
        Extract 8-K item numbers and descriptions from filing HTML.

        Looks for patterns like "Item 1.01" and maps them to known descriptions.
        Returns a list of {item_number, description, matched_text} dicts.
        """
        # Match patterns like "Item 1.01", "ITEM 2.05", "Item 5.02 -" etc.
        pattern = re.compile(
            r"item\s+(\d+\.\d{2})",
            re.IGNORECASE,
        )

        items: list[dict[str, str]] = []
        seen: set[str] = set()

        for match in pattern.finditer(html):
            item_num = match.group(1)
            if item_num in seen:
                continue
            seen.add(item_num)

            description = ITEM_8K_MAP.get(item_num, "Unknown Item")
            # Grab surrounding context
            start = max(0, match.start() - 20)
            end = min(len(html), match.end() + 200)
            context = html[start:end].strip()

            items.append(
                {
                    "item_number": item_num,
                    "description": description,
                    "matched_text": context,
                }
            )

        return items

    # -- persistence ---------------------------------------------------------

    async def store_filing(self, filing: FilingResult, ticker_id: int) -> int | None:
        """
        Insert a filing record into PostgreSQL.

        Uses ON CONFLICT DO NOTHING on accession_number to avoid duplicates.
        Returns the filing id if inserted, None if it already existed.
        """
        pool = get_db_pool()
        keywords_json = json.dumps(
            [
                {
                    "keyword": m.keyword,
                    "context_snippet": m.context_snippet,
                    "position": m.position,
                }
                for m in filing.keywords_found
            ]
        )
        row = await pool.fetchrow(
            """
            INSERT INTO filings (
                ticker_id, cik, accession_number, form_type, filed_date,
                title, url, keywords_found, processed
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, false)
            ON CONFLICT (accession_number) DO NOTHING
            RETURNING id
            """,
            ticker_id,
            filing.cik,
            filing.accession_number,
            filing.form_type,
            filing.filed_date,
            filing.title,
            filing.url,
            keywords_json,
        )
        if row:
            logger.info(
                "Stored filing %s (%s) for ticker_id=%d",
                filing.accession_number,
                filing.form_type,
                ticker_id,
            )
            return row["id"]
        return None

    async def publish_filing_alert(self, filing: FilingResult, symbol: str) -> None:
        """Publish a filing alert to Redis channel:alerts."""
        try:
            redis = get_redis()
            alert = {
                "type": "filing",
                "symbol": symbol,
                "form_type": filing.form_type,
                "accession_number": filing.accession_number,
                "filed_date": filing.filed_date,
                "title": filing.title,
                "url": filing.url,
                "keywords_found": [m.keyword for m in filing.keywords_found],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await redis.publish("channel:alerts", json.dumps(alert))
            logger.debug("Published filing alert for %s to channel:alerts", symbol)
        except Exception:
            logger.warning("Failed to publish filing alert to Redis", exc_info=True)
