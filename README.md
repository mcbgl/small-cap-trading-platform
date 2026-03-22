# Small-Cap & Distressed Asset Automated Trading Platform

An automated trading platform focused on up-and-coming small-cap stocks and distressed assets, combining real-time market monitoring, AI-powered analysis (hybrid local Qwen 3.5 122B + Claude), and paper trading execution.

## Architecture

```
Data Sources (Polygon.io, SEC EDGAR, FINRA, Form 4)
    → Signal Engine (Python async workers)
        → AI Analysis (Qwen 3.5 local / Claude cloud)
        → Risk Engine (pre-trade checks, circuit breakers)
        → Order Management → Alpaca Paper Trading
    → QuestDB (tick/OHLCV time-series)
    → PostgreSQL (portfolio, orders, audit log)
    → Redis (real-time state, WebSocket pub/sub)
    → Next.js Dashboard (real-time WebSocket)
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, asyncpg, WebSockets |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS 4 |
| Time-Series DB | QuestDB 8.2 (OHLCV, ticks, signal scores) |
| Relational DB | PostgreSQL 16 (orders, positions, audit log) |
| Cache/PubSub | Redis 7 (real-time prices, WebSocket relay) |
| AI (Local) | Qwen 3.5 122B via Ollama |
| AI (Cloud) | Claude Opus/Sonnet via Anthropic API |
| Charts | TradingView Lightweight Charts, Apache ECharts |
| Data Grid | AG Grid Community |
| Broker | Alpaca (paper trading), IBKR (future) |

## Key Features

- **Real-time screener** — Short squeeze, distressed assets, insider buying, AI opportunity presets
- **SEC filing monitor** — EDGAR feed with AI-powered analysis and keyword highlighting
- **Signal engine** — Volume anomalies, short squeeze detection, insider clusters, technical convergence, distressed metrics
- **AI analysis** — Confidence-based routing: Qwen for routine, Claude for complex/distressed
- **Risk management** — Three-tier guardrails, circuit breakers, kill switch, wash sale prevention
- **Paper trading** — Alpaca integration with full order lifecycle and audit trail
- **Dark theme dashboard** — Bloomberg-style panels with real-time WebSocket updates

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Node.js 22+ (for local frontend dev)
- Python 3.12+ (for local backend dev)

### Quick Start (Docker)

```bash
# Clone and configure
cp .env.example .env
# Edit .env with your API keys (Polygon, Anthropic, Alpaca, etc.)

# Start infrastructure + services
docker compose up -d

# With Ollama/Qwen (requires NVIDIA GPU):
docker compose --profile gpu up -d
```

Services will be available at:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **QuestDB Console**: http://localhost:9000

### Local Development

```bash
# Backend
cd backend
pip install -e ".[dev]"
uvicorn src.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Database Setup

```bash
# Run migrations (requires PostgreSQL running)
cd backend
alembic upgrade head
```

## Project Structure

```
small-cap-trading-platform/
├── docker-compose.yml          # PostgreSQL, QuestDB, Redis, Ollama
├── .env.example                # Configuration template
├── backend/
│   ├── pyproject.toml          # Python dependencies
│   ├── src/
│   │   ├── main.py             # FastAPI app + lifespan
│   │   ├── config.py           # Three-tier guardrails config
│   │   ├── db.py               # asyncpg + QuestDB + Redis clients
│   │   ├── models/schemas.py   # Pydantic models
│   │   ├── api/
│   │   │   ├── routes/         # REST endpoints (tickers, signals, orders, portfolio, screener, system)
│   │   │   └── ws.py           # WebSocket hub (prices, alerts, signals)
│   │   ├── services/
│   │   │   ├── data/           # Market data ingestion (Polygon, EDGAR, FINRA, Form 4)
│   │   │   ├── signals/        # Signal generation (volume, squeeze, insider, technical, distressed)
│   │   │   ├── ai/             # AI router (Qwen/Claude), clients
│   │   │   ├── execution/      # OMS, Alpaca broker
│   │   │   ├── risk/           # Risk engine, position limits, compliance
│   │   │   └── screener/       # Preset screens
│   │   └── workers/            # Background tasks
│   ├── alembic/                # Database migrations
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── app/                # Next.js pages (home, portfolio, screener, filings, signals, risk, backtest, system)
│   │   ├── components/         # Layout, charts, data-grid, AI, common
│   │   ├── lib/                # API client, WebSocket, Zustand stores
│   │   └── types/              # Shared TypeScript types
│   └── public/
└── docs/research/              # 8 research documents
```

## Risk & Safety

The platform implements a **three-tier guardrails model**:

1. **Hardcoded (never overridable)** — Max 10% per position, 20% max drawdown, stop-loss required, wash sale checks always on
2. **Configurable with bounds** — Position sizing (1-10%), drawdown limits (1-5%), AI confidence thresholds (0.50-0.95)
3. **Free config** — Display preferences, alert recipients, timezone

**Conservative defaults for initial deployment**: 50% capital utilization, 2% per position, shadow mode first 30 days, limit orders only, no extended hours.

See [docs/research/08-guardrails.md](docs/research/08-guardrails.md) for the full safety specification.

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

## Implementation Roadmap

- [x] **Phase 1**: Foundation — Docker, backend scaffold, frontend scaffold, DB schema
- [x] **Phase 2**: Data Pipeline — Polygon WebSocket, EDGAR monitor, FINRA short interest, signal engine
- [x] **Phase 3**: AI Integration — Claude router (Qwen-ready), screener presets, filing/watchlist APIs
- [x] **Phase 4**: Execution — OMS, Alpaca paper trading, risk engine (13 checks), compliance
- [ ] **Phase 5**: Frontend Dashboard — Charts, AG Grid, WebSocket live data, all tabs
- [ ] **Phase 6**: Backtesting & Polish — VectorBT, morning briefings, command palette

## License

Private - All rights reserved
