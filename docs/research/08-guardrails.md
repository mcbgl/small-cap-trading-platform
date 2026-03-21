# Guardrails & Safety Mechanisms

## Three-Tier Configuration Model

### Tier 1: Hardcoded (Never Overridable)
```python
HARDCODED_LIMITS = {
    "absolute_max_position_pct":       10.0,    # No position > 10% NAV
    "absolute_max_drawdown_pct":       20.0,    # Total shutdown at 20%
    "absolute_max_order_value":        500_000, # No order > $500K
    "kill_switch_always_available":     True,
    "audit_logging_always_on":         True,
    "stop_loss_required":              True,    # Every position must have a stop
    "wash_sale_check_always_on":       True,
}
```

### Tier 2: Configurable with Bounds
```python
CONFIGURABLE = {
    "max_position_pct":     {"default": 5.0,  "min": 1.0,  "max": 10.0},
    "daily_drawdown_pct":   {"default": 3.0,  "min": 1.0,  "max": 5.0},
    "weekly_drawdown_pct":  {"default": 5.0,  "min": 2.0,  "max": 8.0},
    "fixed_stop_loss_pct":  {"default": 8.0,  "min": 3.0,  "max": 15.0},
    "ai_confidence_min":    {"default": 0.70, "min": 0.50, "max": 0.95},
    "orders_per_day":       {"default": 200,  "min": 10,   "max": 500},
}
```

### Tier 3: Freely Configurable (No Safety Impact)
- Alert recipients, display timezone, color scheme, report timing

---

## 1. Financial Risk Guardrails

### Position Sizing
| Parameter | Default | Alert | Hard Block |
|---|---|---|---|
| Per-trade capital | 2% of NAV | 1.5% | 2% |
| Per-sector exposure | 15% of NAV | 12% | 15% |
| Per-strategy allocation | 25% of NAV | 20% | 25% |
| Single-name concentration | 5% of NAV | 4% | 5% |
| Correlated cluster (r>0.7) | 20% of NAV | 15% | 20% |
| OTC total | 15% of NAV | 12% | 15% |
| Distressed total | 20% of NAV | 15% | 20% |

### Drawdown Circuit Breakers
| Timeframe | Threshold | Action | Reset |
|---|---|---|---|
| Intraday | -3% | Flatten all, halt | Manual review |
| Weekly | -5% | Halt remainder of week | Monday review |
| Monthly | -8% | Halt, full strategy review | Owner meeting |
| All-time peak | -15% | Complete shutdown | Formal audit |

**Velocity trigger**: -1.5% in under 10 minutes = immediate halt.

### Liquidity Checks
- Max order: 5% of 20-day ADV
- Max daily participation: 10% of ADV across all orders per name
- Minimum ADV: 10,000 shares or $50K dollar volume
- Max spread: 5% of mid price (skip if wider)

### Stop-Loss Enforcement (Non-Overridable by AI)
| Type | Default | Range |
|---|---|---|
| Fixed stop | -8% from entry | 3-15% |
| Trailing stop | -5% from high | 2-10% |
| Time-based | Close if >10 days with <2% gain | Configurable |
| Volatility stop | 2x ATR below entry | 1.5-3x ATR |

---

## 2. Execution Guardrails

### Order Validation (Fat Finger Protection)
- Price: Reject if >10% from last trade or >15% from VWAP
- Size: Max $50,000 per order, max 100,000 shares
- Notional rate: Max $200,000 per minute
- Duplicates: Same ticker+side+size within 5s = duplicate
- Market orders: Blocked in pre/post market

### Rate Limiting
| Limit | Default |
|---|---|
| Orders per minute | 10 |
| Orders per hour | 60 |
| Orders per day | 200 |
| Cancels per minute | 20 |
| Cancel-to-fill ratio alert | >10:1 |

### Kill Switch (Three-Tier)
1. **Strategy-level**: Disable one strategy, flatten its positions
2. **Account-level**: Halt all trading for one account
3. **System-level**: Halt everything across all accounts

Triggerable: manually (single button), automatically (circuit breakers), remotely (SMS command).
**Test weekly** in simulated environment.

### Slippage Monitoring
- Expected: 20 bps for small caps
- Warn: >50 bps
- Halt strategy: >200 bps
- Track rolling 20-trade average, pause if avg >40 bps

---

## 3. AI/ML Guardrails

### Confidence Thresholds
```python
AI_CONFIDENCE = {
    # Qwen 3.5 122B (local)
    "min_to_act":        0.70,   # Don't trade below 70%
    "high_confidence":   0.85,   # Can auto-execute small positions

    # Claude Opus (complex decisions)
    "required_above":    10_000, # Positions > $10K need Opus
    "required_distressed": True, # All distressed trades need Opus

    # Consensus
    "require_agreement":  True,  # Both models must agree on direction
    "max_divergence":     0.30,  # Alert if models diverge > 30%
}
```

### Human-in-the-Loop
| Decision | Requirement |
|---|---|
| Position < $5K, high confidence | Auto-execute, notify after |
| Position $5K-$25K | Queue for approval, 5-min timeout |
| Position > $25K | Mandatory human approval |
| New strategy deployment | Mandatory human approval |
| Distressed/bankruptcy trade | Mandatory human review |
| First trade in new ticker | Human approval |
| Any short sale | Human approval |

### Model Drift Detection
- Halt if Sharpe drops below 0.5 (rolling 30 days)
- Alert if win rate drops below 40%
- Population Stability Index > 0.20 = investigate
- Check feature distributions daily
- Alert if confidence rises without performance improvement

### Hallucination Detection
- Verify all ticker symbols exist
- Cross-check LLM-cited prices against market data
- Validate financial metrics (P/E, market cap) against data feeds
- Reject future-dated claims
- Require source citations
- Cross-check factual claims between Qwen and Claude

### Fallback to Rule-Based Logic
- Qwen timeout: 30s, Claude timeout: 120s
- After 3 consecutive AI failures: switch to conservative rules
- Fallback: block new positions, tighten stops 50%, cancel pending orders
- Retry AI every 5 minutes

### Audit Trail
Every AI recommendation logged with:
- Model ID and version, timestamp
- Input prompt hash + data snapshot
- Full raw output + parsed signal + confidence
- Action taken (executed/rejected/queued/overridden)
- Human override flag
- Execution result if applicable
- **Retention: 7 years** (SEC requirement)

### A/B Testing
- New models: 30-day shadow mode minimum, 100+ simulated trades
- Champion/challenger: 90/10 split
- Challenger gets 50% of normal position sizing
- Auto-rollback if challenger underperforms by 2%+

### Prompt Injection Prevention
- Strip HTML/script tags from scraped content
- Max input length: 50,000 chars
- Reject known injection patterns
- Wrap scraped data in XML tags (structural isolation)
- Constrain output to structured JSON schema

---

## 4. Data Quality Guardrails

### Stale Data Detection
- Max quote age: 30s (120s extended hours)
- Max bar delay: 5 minutes
- Heartbeat check every 10s
- Action on stale data: halt new orders

### Data Validation
- Flag if price moves >20% in 1 minute (possible bad data)
- Reject $0 or negative prices
- Flag volume >50x average
- OHLC sanity checks (high > low, close between H and L)

### Source Cross-Referencing
- Compare prices across broker feed + Polygon + Yahoo
- Alert if sources diverge >1%
- Require 2+ sources to confirm before acting

### Corporate Action Handling
- Check daily pre-market: splits, reverse splits, dividends, ticker changes
- Auto-adjust stops and targets post-split
- Halt trading during action until adjustments confirmed
- Flag reverse splits as potential distress signal

### Halt Detection
- Monitor Nasdaq halt feed + broker events
- On halt: cancel open orders, prevent new orders, alert user
- On resume: wait 30s, revalidate signals, check for price gaps

---

## 5. Operational Guardrails

### System Health
- Broker API ping every 10s
- Database health every 30s
- Qwen model test every 60s
- Claude API check every 5 min
- Alert if queue >100, RAM >85%, GPU >90%, disk <10GB

### Disaster Recovery
- Hot standby broker connection
- Position reconciliation every 5 minutes
- All state persisted to durable storage
- On restart: reconcile -> cancel stale -> re-evaluate stops -> conservative mode
- Daily database backup including AI audit logs

### Alert Escalation
1. **Info**: Dashboard + log
2. **Warning**: + email + push notification
3. **Critical**: + SMS (escalate after 5 min if unacknowledged)
4. **Emergency**: + phone call + auto kill switch

### Version Control
- All strategy parameters in Git
- Parameter changes require PR review
- Backtest required before deploy
- 7-day canary period with reduced sizing

---

## 6. Regulatory Compliance

### Wash Sale Prevention
- 30-day lookback/lookahead
- Check substantially identical securities (options count)
- Check across accounts (IRA purchases trigger wash sale)
- **Cannot be overridden**

### PDT Monitoring
- Track day trades rolling 5 days
- Warn at 3, block at 4 round-trips
- Enforce $25K minimum if PDT triggered

### Market Manipulation Detection
- Spoofing detection (large orders quickly cancelled)
- Wash trade detection (simultaneous buy/sell same name)
- Marking the close detection (unusual last 5 min activity)
- Cancel-to-fill ratio monitoring
- Minimum order duration: 1 second

### Record Retention
| Record | Retention |
|---|---|
| Orders, fills, AI outputs | 6 years |
| Risk check logs | 6 years |
| Strategy parameter changes | 6 years (Git + DB) |
| System logs | 3 years |

---

## 7. Small-Cap / Distressed Specific

### Penny Stock Checks
- Threshold: <$5/share + not exchange-listed
- Max 2% of portfolio per penny stock
- Max 10% total in penny stocks
- No margin for penny stocks
- Require Claude Opus review for all penny stock trades

### OTC Access Verification
- Check 15c2-11 compliance before trading
- OTCQX/OTCQB: allowed
- Pink Current: allowed with limits
- Pink No Info / Expert Market / Grey: blocked

### Bankruptcy NOL Monitoring
- Track Chapter 11 filings via PACER
- Check for trading injunctions
- Default ownership cap: 4.75% (standard NOL preservation)
- All bankruptcy trades require human review

### Thin Market Detection
- Pause if bid-ask spread >5% of mid
- Require minimum 100 shares on each side
- Minimum 5 trades in last hour
- Cut position size 50% in thin markets

---

## Default Conservative Settings (Initial Deployment)

```python
CONSERVATIVE_DEFAULTS = {
    "max_portfolio_utilization_pct":  50,      # Only use 50% of capital
    "max_position_pct":               2,       # 2% per position
    "max_daily_drawdown_pct":         2,       # Very tight daily stop
    "max_orders_per_day":             50,      # Start slow
    "ai_confidence_threshold":        0.80,    # High bar
    "human_approval_above_usd":       5000,    # Low threshold
    "shadow_mode_first_30_days":      True,    # Paper trade first month
    "limit_orders_only":              True,    # No market orders
    "no_extended_hours":              True,    # Regular hours only
    "min_market_cap_usd":             50_000_000,  # No micro-caps initially
    "min_adv_shares":                 50_000,
    "max_spread_pct":                 2.0,
}
```

Gradually loosen as system proves itself over 3-6 months.
