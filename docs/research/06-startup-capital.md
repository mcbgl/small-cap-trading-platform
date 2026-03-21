# Startup Capital Requirements

## Scenario A: Bootstrapped Solo Trader (Minimum Viable)

| Category | Cost |
|---|---|
| **Trading capital** | $30,000-50,000 (PDT minimum + buffer) |
| VPS hosting | $60-100/mo |
| Market data (IB free + Polygon starter) | $30-50/mo |
| Software (open-source stack) | $20/mo |
| Backtesting data (Norgate Platinum) | $53/mo ($630/yr) |
| GPU hardware (if running 122B locally) | $4,000-10,000 one-time |
| Legal (initial compliance review) | $500-1,500 one-time |
| CPA (trader tax specialist) | $2,000-4,000/yr |
| **Monthly burn** | **~$210-370/mo** |
| **Total Year 1** | **~$37,000-62,000** |

## Scenario B: Serious Operation (2-3 people)

| Category | Cost |
|---|---|
| **Trading capital** | $100,000-250,000 |
| Team salaries | $228,000-336,000/yr |
| Cloud infrastructure | $500-1,500/mo |
| Premium data stack | $400-800/mo |
| GPU hardware (2x RTX 4090 or H100) | $8,000-12,000 one-time |
| Legal (entity + compliance) | $5,000-15,000 one-time |
| **Monthly burn** | **~$21,000-34,000/mo** |
| **Total Year 1** | **~$370,000-690,000** |

## Scenario C: Funded Startup / Small Fund

| Category | Cost |
|---|---|
| **Trading capital (AUM)** | $1,000,000-5,000,000 |
| Team (3-5 people) | $480,000-840,000/yr |
| Fund formation (legal) | $25,000-75,000 one-time |
| Bloomberg/premium data | $3,000-6,000/mo |
| **Monthly burn** | **~$55,000-108,000/mo** |
| **Total Year 1** | **~$1.7M-6.5M** |

## Trading Capital Requirements

### Pattern Day Trader Rule
- Current: $25,000 minimum equity for day trading
- Pending: FINRA filed to eliminate (Dec 2025), SEC review ongoing
- Until changed: $30,000-50,000 practical minimum (buffer above $25K)

### Diversification
- 10 positions at $5,000 each = $50,000
- 20 positions at $5,000 each = $100,000
- **Recommended minimum for diversified small-cap: $75,000-$150,000**

### Distressed Assets
- Distressed equity: $50,000-$100,000 minimum
- Distressed bonds: $250,000-$500,000 (most desks want $25K-$100K per trade)
- Accessible alternative: Distressed debt ETFs with $10,000-$50,000

### Short Selling Small Caps
- Reg T: 150% of short sale value as margin
- Hard-to-borrow fees: Average 30%+ annually for sub-$100M market cap
- Extreme cases: 1,000%+ annual borrow rates
- Many brokers won't short stocks under $3-$5

## Commission/Fee Impact

| Capital | 200 Trades/Mo (IB Tiered) | Annual Fee Drag |
|---|---|---|
| $25,000 | $140-200/mo | 6.7-9.6% |
| $50,000 | $140-200/mo | 3.4-4.8% |
| $100,000 | $140-200/mo | 1.7-2.4% |
| $250,000 | $140-200/mo | 0.7-1.0% |

Commissions become negligible (<1% drag) at ~$200,000+.
Alternative: Alpaca commission-free API eliminates this entirely.

## Break-Even Analysis

| Capital | Annual Costs | Return to Break Even |
|---|---|---|
| $50,000 | ~$5,000 | **10%** |
| $100,000 | ~$6,000 | **6%** |
| $250,000 | ~$7,000 | **2.8%** |
| $500,000 | ~$10,000 | **2%** |

## Realistic Return Expectations

| Strategy Type | Annual Return | Sharpe |
|---|---|---|
| Momentum / trend following | 15-30% | 1.0-1.8 |
| Mean reversion | 10-25% | 1.2-2.0 |
| Event-driven (earnings, filings) | 15-40% | 0.8-1.5 |
| Distressed equity | 15-50% | 0.5-1.2 |

## Timeline to Profitability

| Phase | Timeline |
|---|---|
| Strategy research & backtesting | 2-8 weeks |
| Paper trading validation | 4-12 weeks |
| Small-scale live testing | 4-12 weeks |
| Full deployment | Month 4-8 |
| Strategy maturation | Month 6-18 |

**Realistic: 6-18 months from first code to consistent profitability.**

## Funding Options

### Prop Trading Firms
| Firm | Capital | Profit Split |
|---|---|---|
| FTMO | Up to $200K | 80-90% |
| Apex Trader Funding | Up to $300K | 90% |
| Alpha Capital Group | Up to $2M | 80% |
| The5ers | Up to $4M | 80% |

Note: Most focus on forex/futures. US equity prop firms for algo trading are less common.

### Incubator Fund Path
1. Form incubator fund ($3,000 setup)
2. Trade own capital 6-12 months, build audited track record
3. Convert to full hedge fund ($12,000-$20,000 legal)
4. Accept accredited investor capital under Reg D
