# Data Sources & APIs

## Market Data

| Provider | Cost | Best For | OTC Coverage |
|---|---|---|---|
| **Polygon.io/Massive** | $29-500/mo | Primary data backbone | Excellent - all OTC included |
| **Alpaca** | $9/mo SIP feed | Bundled with execution | Listed small caps only |
| **Finnhub** | Free-$100/mo | Alt data (FDA, congressional trading) | Moderate |
| **EODHD** | ~$20/mo | 30+ year history, bulk download | Good |
| **Tiingo** | $7-29/mo | Clean EOD, quant research | Moderate |
| **Twelve Data** | $29-329/mo | Global coverage, WebSocket | Moderate |
| **Alpha Vantage** | Free-$250/mo | Budget fundamentals | Moderate |

### Recommended: Polygon.io/Massive
- OTC data included at no extra cost (covers Pink Sheets, OTCQB, OTCQX)
- Direct fiber cross-connects to exchanges
- Tick-level data on Advanced tier ($500/mo)
- Real-time WebSocket on paid plans

## Execution Brokers

### Interactive Brokers (Primary - OTC/Distressed)
- **Commission**: $0.0005-$0.005/share (tiered), min $1
- **OTC access**: Best in class - supports all OTC Markets tiers
- **API**: TWS API (C++, C#, Java, Python), Client Portal REST API
- **Short locates**: Programmatic via tick type 46
- **Account minimum**: $0 (no minimum)

### Alpaca (Secondary - Listed/Development)
- **Commission**: $0 for US equities
- **API**: REST + WebSocket, modern architecture
- **Paper trading**: Free, $100K simulated balance
- **Limitation**: Limited OTC/penny stock support

## Alternative Data Sources (Free/Low-Cost)

### SEC EDGAR (Free)
- Submissions API: <1 second delay
- XBRL financials: Structured data from all public filings
- Full-text search: `efts.sec.gov`
- Rate limit: 10 req/s (User-Agent header required)
- **Critical for**: 8-K material events, Form 4 insider trades, going concern opinions

### FINRA Short Interest (Free)
- API: `api.finra.org` with OAuth 2.0
- Consolidated short interest across all exchanges + OTC
- Updated bi-monthly (settlement dates)
- 5 years rolling history

### CourtListener / PACER (Free / $0.10/page)
- Bankruptcy docket metadata (free via CourtListener)
- RECAP Search Alerts (2025) - Google Alerts for federal courts
- PACER docs: $0.10/page, cap $3/document
- **Critical for**: Chapter 11 filings, DIP financing, restructuring plans

### OTC Markets Disclosure API (Launched Sept 2025)
- 45,000+ filings for OTC issuers
- Data not available through any other platform
- Covers Alternative Reporting Standard filings

## Paid Enhancements

| Source | Cost | Value |
|---|---|---|
| **sec-api.io** | $55/mo | Real-time filing stream (<300ms), full-text search 18M+ filings |
| **Fintel** | $15-95/mo | Short interest, squeeze scores, insider clusters, cost to borrow |
| **ORTEX** | Enterprise | Real-time intra-day short interest estimates |
| **Financial Modeling Prep** | $19-99/mo | Pre-calculated ratios for 70K+ companies |
| **Unusual Whales** | $250/mo | Options flow, dark pool, 100+ API endpoints |
| **Quiver Quant** | $10-75/mo | Reddit mentions, congressional trading |

## Recommended Stack

**Minimum viable**: IB free data + Polygon Starter + SEC EDGAR = ~$30/mo
**Solid operation**: Polygon Business + sec-api.io + FMP + Fintel = ~$400/mo
