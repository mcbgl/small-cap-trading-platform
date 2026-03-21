# Testing & Backtesting Strategy

## Testing Pipeline (5 Stages)

```
Stage 1: Backtest (2-4 weeks)
  -> Stage 2: Walk-Forward Validation (1-2 weeks)
    -> Stage 3: Shadow Mode (2-4 weeks)
      -> Stage 4: Paper Trading (3-6 months)
        -> Stage 5: Staged Live Rollout (3-6 months)
```

## Stage 1: Backtesting

### Framework Comparison

| Framework | Best For | Status |
|---|---|---|
| **QuantConnect LEAN** | Production-grade, survivorship-bias-free data | Active, recommended |
| **VectorBT Pro** | Rapid parameter sweeps (1M orders in 70-100ms) | Active, complementary |
| **Backtrader** | Local prototyping, custom logic | Maintenance slowed |

### Data Requirements
- **Minimum 15-20 years** covering dot-com crash, GFC, COVID, rising rates
- **Must be survivorship-bias-free** - datasets missing delisteds overstate returns ~5%/yr
- Best sources: QuantConnect (free, 1998+), Norgate Data ($630/yr, 1950+)

### Small-Cap Backtesting Rules
- **Volume participation**: Max 5-10% of ADV per simulated fill
- **Non-linear slippage**: `slippage = base_bps + alpha * (order_size / ADV)^0.5`
- **Budget 2-5% slippage** round-trip for illiquid names
- **Minimum 200-500 trades** spanning multiple market regimes

### Statistical Validation
- **Walk-forward optimization**: Rolling IS/OOS windows (3-5x IS vs OOS ratio)
- **Monte Carlo simulation**: Shuffle trades, skip 10-20%, randomize slippage
- **Deflated Sharpe Ratio**: Correct for multiple testing (discount backtest Sharpe ~50%)
- **Bonferroni correction**: p < 0.05/N where N = strategies tested
- **Live Sharpe typically 30-50% lower than backtest**

### Market Regimes to Cover
- Bull market (2013-2019, 2023-2024)
- Bear market / crash (2008-2009, Q1 2020, 2022)
- Sideways/choppy (2015-2016)
- Rising rate (2022-2023)
- Low volatility (2017)
- High volatility (Q4 2018, 2020)

## Stage 2: Shadow Mode (2-4 weeks)

- Generate signals alongside real markets WITHOUT executing
- Log orders with timestamps, compare against actual market prices
- No broker simulation artifacts
- Validates signal generation and timing quality

## Stage 3: Paper Trading (3-6 months)

### Brokers
- **Alpaca**: Free, clean API, but top-of-book fill simulation only
- **IBKR**: Free with account, broadest small-cap/OTC coverage

### Key Metrics to Track
- Execution quality: Signal price vs fill price (slippage per market-cap bucket)
- Fill rate: % of orders that fill (track per liquidity bucket)
- Sharpe/Sortino/max drawdown vs backtest expectations (within 20-30%)
- Trade frequency: Generating expected number of signals?
- System uptime: Any missed signals from technical issues?

### Duration
- Minimum 3-6 months for small-cap strategies
- Must cover at least one volatility spike
- Need 50-100+ trades for statistical meaning
- Apply post-hoc slippage adjustment of 0.5-2% per trade

## Stage 4: Staged Live Rollout

| Phase | Capital | Duration | Goal |
|---|---|---|---|
| Micro live | 10-25% | 1-3 months | Validate real execution, actual slippage |
| Partial live | 50% | 1-3 months | Confirm results track paper trading |
| Full live | 100% | Ongoing | Scale only after confirmation |

### Position Sizing During Ramp-Up
- Start 0.5-1% risk per trade (half eventual target)
- Max 2% of stock's ADV during initial phase
- Increase by 25% increments every 2-4 weeks if on track

### Kill Switch Framework

| Level | Trigger | Action |
|---|---|---|
| Yellow | Drawdown = 50% of historical max | Daily review, increase monitoring |
| Orange | Drawdown = 75% of historical max | Reduce positions 50% |
| Red | Drawdown > 1.25x historical max | Halt completely, return to paper |

Also halt if: live Sharpe < 50% of backtest for 3+ months, slippage exceeds model by >50%.

## Performance Thresholds

| Metric | Minimum (Backtest) | Target (Backtest) | Expect (Live) |
|---|---|---|---|
| Sharpe Ratio | 1.0 | 1.5-2.0 | 0.7-1.2 |
| Sortino Ratio | 1.5 | 2.0+ | 1.0-1.5 |
| Max Drawdown | <30% | <20% | 25-40% |
| Profit Factor | 1.3 | 1.8+ | 1.2-1.5 |
| Win Rate | >40% | >50% | 35-50% |

### Red Flags (Not Ready)
- Backtest Sharpe < 1.0 after deflation
- Max drawdown > 40% in any window
- Profit factor < 1.3 after realistic costs
- Walk-forward OOS degrades >50% from in-sample
- Monte Carlo 5th percentile terminal wealth is negative

## Survivorship-Bias-Free Data Sources

| Provider | Coverage | Delisted? | Resolution | Annual Cost |
|---|---|---|---|---|
| Norgate Data Platinum | US stocks from 1950 | Yes, complete | EOD | ~$630/yr |
| QuantConnect | US stocks from 1998 | Yes | Minute | Free |
| CRSP via WRDS | US stocks from 1926 | Yes | EOD | $10,000+/yr |
| Sharadar / Nasdaq | US stocks | Partial | EOD | $500-2,000/yr |

**Best value**: QuantConnect (free) + Norgate Data Platinum ($630/yr)
