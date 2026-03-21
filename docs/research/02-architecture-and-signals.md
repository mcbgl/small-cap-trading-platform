# Architecture & Trading Signals

## Recommended Tech Stack

```
Time-Series DB:   QuestDB (6-13x faster than TimescaleDB, ASOF JOINs, nanosecond timestamps)
Relational DB:    PostgreSQL (orders, positions, fundamentals, reference data)
Event Bus:        Redis Streams (sub-ms latency) + Kafka (durable log, audit trail)
Framework:        QuantConnect LEAN (production-grade, multi-asset, 180+ contributors)
Language:         Python (signal generation, ML) + LEAN C#/Python bridge
Deployment:       Docker on cloud VM (8-16 cores, 32-64GB RAM)
```

## Architecture Diagram

```
Data Sources (Polygon.io, SEC EDGAR, FINRA, PACER, Fintel)
    -> Kafka / Redis Streams (event bus)
        -> Signal Engine (Python async workers)
            -> Qwen 3.5 122B (local sentiment, filing classification)
            -> Claude Opus (complex analysis, distressed evaluation)
        -> Risk Engine (pre-trade checks, guardrails)
        -> Order Management System
            -> IBKR (OTC execution) / Alpaca (listed execution)
        -> QuestDB (tick/OHLCV data)
        -> PostgreSQL (portfolio state, orders, config)
        -> Next.js Dashboard (real-time WebSocket)
```

## Database Architecture

### QuestDB (Time-Series)
- Tick data, OHLCV bars, order book snapshots
- 6-13x faster ingestion than TimescaleDB
- Native ASOF JOINs (critical for financial time-alignment)
- Multi-tier storage: WAL -> native -> Parquet on object storage
- Used by Tier 1 banks and major exchanges

### PostgreSQL (Relational)
- Portfolio state, orders, positions
- Fundamental data (Z-scores, financial ratios)
- AI audit logs, strategy configurations
- Reference data (tickers, sectors, corporate actions)

### Redis
- Real-time position state and P&L
- Inter-service pub/sub messaging
- Rate limiting and caching
- WebSocket session management

## Key Trading Signals

### Small-Cap Signals

**Volume Anomalies**
- RVOL (Relative Volume): Current / 20-day average. >2-3x = actionable
- Volume preceded price in GME squeeze - earliest detectable signal
- Use Isolation Forest for ML-based anomaly detection across universe

**Short Squeeze Setup**
- Short float >20% + Days to Cover >5 + RSI <20 + rising volume
- Cost to borrow rising = squeeze pressure building
- FINRA short interest (bi-monthly, lagging) + Fintel/ORTEX (real-time estimates)

**Insider Cluster Buying**
- Multiple Form 4 open-market purchases within short window
- Academic research: 4-6% annual alpha from cluster buying signals
- Most predictive in small caps where information asymmetry is highest
- Monitor via EDGAR Form 4 RSS, OpenInsider, sec-api.io

**Technical Convergence**
- Bollinger lower band + RSI <30 + MACD bullish crossover = high-confidence long
- Band squeeze (narrow bandwidth) precedes explosive small-cap moves

**Catalyst Monitors**
- 8-K filings (material events): Real-time via EDGAR RSS or sec-api.io
- Earnings surprises: >10% beat in small caps = multi-day momentum
- FDA approvals / PDUFA dates: Binary events for biotech small caps
- Contract wins: Especially impactful when >10% of company revenue

### Distressed Asset Metrics

**Altman Z-Score**
```
Z = 1.2(Working Capital/Total Assets) + 1.4(Retained Earnings/Total Assets)
  + 3.3(EBIT/Total Assets) + 0.6(Market Cap/Total Liabilities)
  + 1.0(Revenue/Total Assets)

Z < 1.81 = Distress zone (80-90% accurate 1yr ahead)
1.81-2.99 = Grey zone
Z > 2.99 = Safe zone
```
Compute weekly from EDGAR XBRL data.

**Interest Coverage Ratio**
- EBIT / Interest Expense
- < 1.5x = can't service debt (strong distress signal)
- < 1.0x = operations cannot cover interest

**CDS Spreads**
- > 1,000bp over Treasuries = definitively distressed
- CDS markets lead equity by 1-3 days in pricing distress
- CoreWeave example: CDS hit 700bp in Dec 2025 (screaming signal)

**Going Concern Opinions**
- Search 10-K filings for "substantial doubt" / "going concern"
- Lagging indicator but high precision
- Going concern in Q4 -> restructuring within 12 months

**Covenant Violations**
- Search 10-Q/10-K footnotes for "covenant" + "waiver"
- Covenant violations trigger acceleration clauses
- EDGAR XBRL doesn't capture this - requires full-text search

**Chapter 11 Patterns (2025-2026)**
- 10-year high for filings in 2025
- PE-backed companies = 54% of large bankruptcies
- Marathon Asset Management: "richest distressed opportunity set in a long time"

## Automated Signal Pipeline

1. Daily EDGAR scrape for 8-K mentioning covenant violations / going concern
2. Weekly Z-Score recomputation from latest quarterly XBRL financials
3. Real-time Form 4 monitoring for insider buying clusters
4. Short interest + borrow rate tracking via FINRA + Fintel
5. Volume anomaly scanning across universe (Isolation Forest)
6. CDS spread monitoring for held positions
7. Catalyst calendar monitoring (earnings, FDA, contract announcements)

## Risk Management

### Position Sizing
- Max 1-2% of capital per trade
- Max 1-5% of average daily volume
- Half-Kelly criterion for optimal sizing
- Volatility-adjusted via ATR

### Execution
- Limit orders only (never market orders for small caps)
- Budget 2-5% slippage for sub-$1M ADV stocks
- TWAP for larger fills
- Square-root market impact model: `impact = sigma * sqrt(Q/V)`

### Circuit Breakers
- Daily loss limit: -3% -> halt all trading
- Weekly: -5% -> halt for remainder of week
- All-time: -15% -> complete shutdown + audit
- Per-strategy kill at 5-7% drawdown

### Concentration
- Max 5% per position
- Max 25% per sector
- Max 20% in correlated cluster (r > 0.7)
- Max 15% in OTC names
- Max 20% in distressed names
