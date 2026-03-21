# Small-Cap & Distressed Asset Automated Trading Platform

An automated trading platform focused on up-and-coming small-cap stocks and distressed assets, combining established monitoring metrics with AI-powered analysis.

## Architecture

- **Backend**: Python (QuantConnect LEAN, async workers)
- **Frontend**: Next.js 15 + TypeScript + TradingView Lightweight Charts
- **AI**: Hybrid local (Qwen 3.5 122B via Ollama) + cloud (Claude Opus/Sonnet)
- **Data**: QuestDB (time-series) + PostgreSQL (relational) + Redis (real-time state)
- **Event Bus**: Kafka (durable log) + Redis Streams (low-latency)

## Key Features

- Real-time small-cap screener (short squeeze, distressed, insider buying)
- SEC filing monitor with AI-powered analysis
- Distressed asset identification (Altman Z-Score, covenant monitoring)
- Multi-source sentiment analysis (news, social, filings)
- Comprehensive risk management with circuit breakers
- Backtesting with survivorship-bias-free data
- AI co-analyst with confidence-scored recommendations

## Research Documents

See [`docs/research/`](docs/research/) for comprehensive research:

1. [Data Sources & APIs](docs/research/01-data-sources-and-apis.md)
2. [Architecture & Trading Signals](docs/research/02-architecture-and-signals.md)
3. [Regulatory & Legal](docs/research/03-regulatory-and-legal.md)
4. [Local LLM vs Cloud (Qwen 3.5 vs Claude)](docs/research/04-local-llm-vs-cloud.md)
5. [Testing & Backtesting Strategy](docs/research/05-testing-and-backtesting.md)
6. [Startup Capital Requirements](docs/research/06-startup-capital.md)
7. [Frontend Interface Design](docs/research/07-frontend-design.md)
8. [Guardrails & Safety Mechanisms](docs/research/08-guardrails.md)

## Getting Started

*Coming soon - implementation in progress*

## License

Private - All rights reserved
