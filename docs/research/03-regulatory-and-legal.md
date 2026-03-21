# Regulatory & Legal Considerations

## Registration Requirements

### Trading Your Own Money
- **Generally NO registration required** for proprietary automated trading
- SEC expanded dealer definition (April 2025) - but primarily targets liquidity providers
- Safe harbor: If taking directional positions only (not market-making), you're exempt

### If Managing Others' Money
- Broker-dealer registration: $100K-$300K+ first year
- FINRA membership required
- Series 57 exam for algo developers ($210)

## Key Regulations

### Pattern Day Trader (PDT) Rule
- **Current**: $25,000 minimum equity for 4+ day trades in 5 business days
- **Pending change**: FINRA filed SR-FINRA-2025-017 (Dec 2025) to eliminate PDT entirely
- Replace with risk-based intraday margin. SEC approval pending as of March 2026

### Penny Stock Rules (SEC 15g-1 through 15g-9)
- Apply to <$5/share OTC stocks
- Per-transaction suitability requirements
- Written risk disclosure required
- Adds compliance friction for automated trading

### Rule 15c2-11 (OTC Markets)
- Requires current public disclosure for public quotation
- 2,000+ companies moved to Expert Market (accredited investors only)
- Many small-cap OTC securities now "dark"

### FINRA Algo Developer Registration
- Series 57 required for persons primarily responsible for algo design/modification
- Must be sponsored by FINRA member firm
- Applies since January 2017

## Market Manipulation - Active Enforcement

SEC and FINRA enforcement priorities in 2025-2026:
- **Microcap manipulation** = top examination priority
- Spoofing, layering, wash trades, prearranged trades
- Marking the close
- Pump-and-dump via social media
- AI-generated trades treated identically to human decisions

**Must have**: Robust surveillance systems + audit trails demonstrating non-manipulative intent

## Distressed Asset Regulations

### Trading Around Bankruptcy
- Chapter 11 debtors routinely seek NOL preservation orders
- Can restrict equity trading above ~4.75% ownership threshold
- 90-day advance notice requirements possible
- Must monitor court orders for each bankruptcy holding

### Insider Trading Near Restructuring
- MNPI liability extends to debt claims and creditor committee members
- "Big boy" letters do NOT provide safe harbor from SEC enforcement
- SEC specifically watching debt trading around restructuring announcements
- Rule 10b5-1 plans tightened (Dec 2022 amendments)

## Data Licensing

- Exchange data for algorithmic (non-display) use requires separate licensing
- NYSE/NASDAQ fees can reach $10K-$100K+/month depending on scope
- **Workaround**: Use broker-provided data (IBKR, Alpaca) which includes exchange licenses

## AI in Trading - Regulatory Stance

- **No new AI-specific rules** as of March 2026
- Existing framework fully applies (anti-fraud, best execution, supervision)
- FINRA rules are "technology neutral"
- SEC AI task force launched August 2025
- **Requirements**: Model governance, explainability logs, books & records
- All AI-generated trading decisions must have audit trail
- Model risk management expected (validation, version control, drift monitoring)

## Tax Considerations

### Section 475(f) Mark-to-Market Election
- **Critical**: File before first live trading year
- Eliminates wash sale rule (which can create phantom tax liabilities)
- All gains/losses treated as ordinary income
- No $3,000 capital loss limitation
- Data feeds, servers, software become deductible business expenses
- Must elect by April 15 of applicable tax year

### Wash Sale Rule (Without 475(f))
- 30-day lookback/lookahead window
- Can create phantom tax liabilities (documented: $72K taxes on $30K profit)
- Especially dangerous for high-frequency algo traders
