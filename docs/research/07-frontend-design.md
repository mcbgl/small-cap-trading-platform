# Frontend Interface Design

## Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Framework | Next.js 15 (App Router) | SSR + CSR hybrid, largest ecosystem |
| Language | TypeScript (strict) | Non-negotiable for financial data |
| State | Zustand + TanStack Query | Client state + server-state with caching |
| Real-time | Native WebSocket | 93% latency reduction vs polling |
| Financial Charts | TradingView Lightweight Charts | Purpose-built, ~40KB, 60fps, candlestick/OHLC |
| General Charts | Apache ECharts | Heatmaps, treemaps, gauges, scatter plots |
| Data Grid | AG Grid Community | 100K+ rows, virtualization, inline sparklines |
| Styling | Tailwind CSS 4 + shadcn/ui | Dark mode essential for trading |
| Layout | react-mosaic | Drag-and-drop Bloomberg-style panels |
| Notifications | Sonner + Web Push API | Toast + push notifications |

## Dashboard Layout

```
+-------+------------------------------------------------------------+
| LOGO  |  [Global Search]  [Alerts 12]  [Paper/Live Toggle]  [Settings]|
+-------+------------------------------------------------------------+
|       |                                                            |
| HOME  |  Main workspace area with drag-and-drop resizable panels   |
| PORT  |  (react-mosaic for Bloomberg-style multi-panel layout)     |
| WATCH |                                                            |
| SCREEN|  Supports tiled charts, tables, alerts, AI insights        |
| FILES |  in any arrangement the user prefers                       |
| SIGNAL|                                                            |
| RISK  |  Workspace layouts can be saved and loaded                 |
| BACK  |                                                            |
| SYSTEM|                                                            |
+-------+------------------------------------------------------------+
```

## Key Tabs

### 1. Home / Command Center
- Portfolio snapshot (total value, P&L, cash, margin)
- AI Insights Feed (scrolling real-time signals)
- Active alerts with priority badges
- Top movers from watchlists
- Market context strip (S&P 500, Russell 2000, VIX)

### 2. Portfolio
- AG Grid holdings table with sparklines, conditional P&L formatting
- AI column (icon indicating current AI insight per holding)
- Treemap heat map (position size = rectangle, color = P&L)
- Sector allocation donut chart
- Click any row to expand into detailed view

### 3. Screener / Scanner
**Preset screens:**
- Distressed Asset Screener (low P/B, high D/E, 8-K flags)
- Short Squeeze Scanner (SI >20%, DTC >5, rising volume)
- Insider Buying Tracker (Form 4 cluster detection)
- AI Opportunity Scanner (multi-signal convergence)

**Features:**
- Visual filter builder + advanced SQL-like mode
- Scatter plot visualization (e.g., SI% vs DTC, bubble size = volume)
- Composite AI Score (0-10) per result

### 4. SEC Filing Monitor
- Real-time EDGAR feed via WebSocket
- AI auto-summarization (Qwen 122B for routine, Claude for complex)
- Keyword highlighting ("going concern", "covenant breach", "material weakness")
- Split-pane: raw filing left, AI analysis right
- Filter by type, ticker, AI score, keywords

### 5. Signal & Alert Center
- Three-tier priority: Red (urgent), Amber (AI signals), Blue (informational)
- Configurable alert rules ("Price crosses $5" -> notification)
- Delivery: dashboard, push, email, webhook

### 6. Risk Management Dashboard
- Portfolio VaR (95% and 99%)
- Correlation heat map between holdings
- Concentration risk bars (position limits, sector limits)
- Gauge-style risk indicators (liquidity, leverage, beta)
- Scenario analysis ("Market -10%", "Sector crash", "Squeeze event")

### 7. Backtesting
- Equity curve with benchmark overlay (Russell 2000)
- Drawdown chart (underwater equity curve)
- Monthly returns calendar heatmap
- Full trade log with filtering
- AI-generated strategy commentary

### 8. System Health
- Data feed status (green/amber/red per source)
- AI model health (GPU utilization, queue depth, accuracy drift)
- System resources (CPU, RAM, GPU, disk)
- Recent errors and warnings

## AI Integration in UI

### Model Attribution
Every AI insight shows which model generated it:
- **"Model: Qwen"** for local real-time analysis
- **"Model: Claude"** for complex deep analysis
- Confidence score (0-1) with color coding:
  - Green (0.85+): High confidence
  - Amber (0.65-0.84): Moderate
  - Grey (0.40-0.64): Low - treat as hypothesis
  - Red (<0.40): Very low - insufficient data

### AI Insight Cards
Primary surface for AI-generated insights across all tabs:
```
+------------------------------------------+
| AI DISTRESSED ALERT        Score: 7.8/10 |
| DIST Corp ($DIST) - $1.22                |
|                                          |
| [+] Debt/equity improved 4.2 -> 3.1     |
| [+] New management (8-K Mar 15)          |
| [+] Insider cluster (3 in 10 days)       |
| [-] Revenue declining (-12% YoY)         |
|                                          |
| AI: "Early-stage turnaround. Position    |
| should not exceed 2% of portfolio."      |
|                                          |
| Confidence: 0.78 | Model: Claude         |
+------------------------------------------+
```

### AI Co-Analyst Chat Panel
Collapsible right panel for natural language questions:
- "Why is ACME up 12% today?"
- "What's the risk profile of my distressed holdings?"
- "Compare ACME and BETA on distress metrics"

### Morning Briefing
Auto-generated daily summary on login:
- Portfolio overnight changes
- Key events today (earnings, fed, filings)
- AI signals generated overnight
- Risk watch items

## Mobile (PWA)

### Must-have on mobile:
- Portfolio summary (value, P&L)
- Alert feed with push notifications (killer feature)
- Watchlist with prices + sparklines
- Single-stock chart (touch-optimized)
- AI insight feed (scrollable cards)

### Desktop-only:
- Multi-panel layouts
- Complex screener filters
- Order book depth
- Backtesting interface
- Filing viewer split pane

### Breakpoints:
- Mobile: <768px (single column, card-based)
- Tablet: 768-1024px (two-column)
- Desktop: >1024px (full multi-panel workspace)

## Implementation Phases

### Phase 1 (MVP - 8-12 weeks)
- Next.js scaffolding + dark theme
- Home dashboard + portfolio tab
- Watchlist with WebSocket prices
- Basic screener (squeeze + distressed presets)
- TradingView charts
- Qwen 3.5 integration for sentiment
- Mobile-responsive layout

### Phase 2 (Weeks 12-20)
- SEC Filing Monitor with EDGAR feed
- Claude API for complex analysis
- AI Insight Cards across views
- Insider trading tracker
- Risk management dashboard
- Multi-panel workspace
- Push notifications (PWA)

### Phase 3 (Weeks 20-28)
- Backtesting visualization
- AI Co-Analyst chat panel
- Morning Briefing
- Order book visualization
- Advanced screener builder
- Cmd+K command palette
- System health monitoring
