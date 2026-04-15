# TradingAgents v2.0 — Comprehensive Audit & Bloomberg Terminal Plan

> Prepared for Jane Street delivery review | 2026-04-04

---

## Part 1: Full Audit Report

### Executive Summary

The TradingAgents platform has a **solid backend architecture** (13 data connectors, 6 analyst agents, divergence engine, backtesting, paper trading) but the **frontend is non-functional** — every page has API contract mismatches that prevent end-to-end operation. The API layer is a simulation stub that never calls real agents. Production build fails. Test coverage claims are unverifiable.

**Verdict: NOT ready for delivery. Requires significant work across all layers.**

---

### A. Critical Bugs (App-Breaking)

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| 1 | CRITICAL | **Analysis pipeline is a simulation** — `_run_analysis()` loops agent names, emits fake events, returns hardcoded `HOLD/0.5`. Never instantiates `TradingAgentsGraph` or calls LLMs. | `api/routes/analysis.py:141-172` |
| 2 | CRITICAL | **Portfolio endpoint is hardcoded** — always returns `{cash: 100000, positions: []}`. `PaperBroker` has full implementation but is never wired. | `api/routes/analysis.py:68-77` |
| 3 | CRITICAL | **Backtest runs with empty data** — `engine.run(signals=[], prices={})` returns zero metrics regardless of input. | `api/routes/backtest.py:25-26` |
| 4 | CRITICAL | **Production build FAILS** — TypeScript compile errors: `Property 'composite_score' does not exist on type 'DivergenceData'`. | `frontend/src/app/divergence/page.tsx:47` |
| 5 | CRITICAL | **"710 tests passed" is false** — only 419 collected, 16 fail to import. System Python is 3.9 but project requires 3.10+. No venv exists. Core deps (`langchain_core`) not installed. | `pyproject.toml`, system env |

### B. Frontend-Backend Contract Mismatches

| Page | Frontend Sends/Expects | Backend Returns | Impact |
|------|----------------------|-----------------|--------|
| **Analysis** | `{ticker, num_steps}` | Expects `{ticker, trade_date, selected_analysts, debate_rounds}` | 422 on every submit |
| **Analysis** | Reads `response.id` | Returns `response.analysis_id` | `undefined` → all subsequent calls fail |
| **Analysis** | SSE `onmessage` handler | Backend sends named events (`agent_start`) | No events received |
| **Analysis** | Checks `status === "completed"` | Backend sets `status = "complete"` | Polling never detects completion |
| **Divergence** | `data.overall_score` | Returns `composite_score` | `undefined` → crash |
| **Divergence** | `data.dimensions` as `Array<{bull_score, bear_score}>` | Returns `Object<{value, confidence}>` | `.map()` crash |
| **Backtest** | `result.total_return` (flat) | Returns `{metrics: {total_return}}` (nested) | All metrics `undefined` |
| **Dashboard** | `d.overall_score` | Returns `composite_score` | Quick divergence crash (fixed) |

### C. Security Issues

| # | Severity | Finding |
|---|----------|---------|
| 1 | CRITICAL | **Zero authentication** on all endpoints — anyone can trigger LLM calls ($$$) |
| 2 | CRITICAL | **Zero rate limiting** — no throttle on `/api/analyze` |
| 3 | HIGH | **CORS `allow_origins=["*"]` + `allow_credentials=True`** — allows cross-origin authenticated requests |
| 4 | HIGH | **Config PUT accepts arbitrary unvalidated input** — can inject any key/value |
| 5 | HIGH | **Stack traces leak to clients** — no exception handling in any route |
| 6 | MEDIUM | **No input validation** — ticker, dates, capital accept any value |
| 7 | **CRITICAL** | **Hardcoded Capital IQ DB password** — `os.environ.get("CAPITALIQ_PASSWORD", "3lGzwDY0G8")` in `capitaliq_connector.py:29`. Production credential for $70K-80K dataset baked into source. **ROTATE IMMEDIATELY.** |
| 8 | HIGH | SQL injection pattern — f-string table names in `persistence.py` and `_capitaliq_provider.py` |
| 9 | MEDIUM | SQLite databases unencrypted at rest (audit.db, costs.db, memories.db) |
| 10 | MEDIUM | No TLS — Docker serves plain HTTP, no reverse proxy |
| 11 | LOW | `.env` template is clean — no other secrets in code/git |

### D. Backend Code Quality

| # | Severity | Finding |
|---|----------|---------|
| 1 | CRITICAL | **`_analyses` + `_analysis_events` grow forever** — unbounded memory leak |
| 2 | CRITICAL | **`asyncio.get_event_loop().create_task()`** — deprecated, may silently fail on 3.10+ |
| 3 | HIGH | **Sync blocking in async handlers** — `DivergenceAggregator.compute()` blocks event loop |
| 4 | HIGH | **Thread-unsafe shared state** — `_analyses`, `_runtime_config` mutated without locks |
| 5 | HIGH | **DuckDB/SQLite connections never closed** — resource leak on shutdown |
| 6 | HIGH | **`_run_analysis` has no error recovery** — failure leaves record stuck in "running" forever |
| 7 | HIGH | **Hardcoded `created_at`** — all analyses show `"2026-04-03T00:00:00Z"` |
| 8 | HIGH | **Health endpoint claims `tests_passed=662`** — fabricated number |
| 9 | MEDIUM | **`DivergenceRequest` model is dead code** — defined but never used |
| 10 | MEDIUM | **No consistent error envelope** — mix of Pydantic models and raw dicts |

### E. Missing Features (Backend Exists, No UI)

| # | Feature | Backend Support | Frontend |
|---|---------|-----------------|----------|
| 1 | LLM Provider Selection | 6 providers | No UI |
| 2 | Runtime Config Management | `GET/PUT /api/config` | No page |
| 3 | Multi-language Output | `output_language` field | No UI |
| 4 | Data Vendor Selection | yfinance/AV/CapitalIQ | No UI |
| 5 | Memory Backend Config | BM25/hybrid | No UI |
| 6 | LLM Gateway / Budget Control | Tiered routing + limit | No UI |
| 7 | Trade Date Selection | Required by backend | No date picker |
| 8 | Agent Debate Visualization | Bull/Bear/Risk debate | No UI |
| 9 | Trade Execution (Buy/Sell) | PaperBroker ready | No buttons |
| 10 | Trade History | PaperBroker tracks | No page |
| 11 | Real-time Price Charts | `lightweight-charts` installed | Not used |
| 12 | Equity Curve | Backtest engine has data | No chart |
| 13 | Portfolio Risk Metrics | Risk module exists | No UI |
| 14 | Export/Download | Data available | No buttons |
| 15 | Hedge Fund Holdings | CapitalIQ connector | No UI |
| 16 | Options Flow / Put-Call | CBOE connector | No UI |
| 17 | Macro Indicators Dashboard | FRED connector | No UI |

---

## Part 2: TradingAgents Existing Capabilities

### What the codebase CAN do (if properly wired):

**Data Sources (13 connectors)**:
- YFinance — OHLCV, fundamentals, news (free)
- Alpha Vantage — technicals, forex, crypto
- S&P Capital IQ — 22M+ companies, institutional data ($70K-80K dataset)
- Finnhub — company news, insider trades
- SEC EDGAR — official filings
- FRED — Federal Reserve economic data
- CBOE — options volatility (VIX)
- Fear & Greed Index — market sentiment
- ApeWisdom — retail sentiment (WSB)
- AAII — individual investor survey

**Agent Pipeline**:
1. 6 Analyst Agents → parallel data collection
2. Bull/Bear Researchers → debate
3. Research Manager → synthesis
4. Trader Agent → decision
5. Risk Management → 3-tier debate (aggressive/neutral/conservative)
6. Portfolio Manager → final approval

**Infrastructure**:
- Hybrid memory (BM25 + vector embeddings)
- Multi-LLM support (GPT-5.4, Gemini 3.1, Claude 4.6, Grok 4.x)
- DuckDB caching with TTL
- Backtesting engine (Backtrader)
- Paper trading (PaperBroker)
- 5-dimensional divergence scoring

---

## Part 3: Bloomberg Terminal-Inspired Redesign Plan

### Bloomberg Terminal Key Concepts

Bloomberg Terminal is organized around **functions** (commands) that provide specific data views. Key functions relevant to our platform:

| Bloomberg Cmd | What It Does | Our Equivalent |
|---------------|-------------|----------------|
| `DES` | Company description + financials | Fundamentals Analyst |
| `HP` | Historical prices | YFinance connector |
| `FA` | Financial analysis templates | Fundamentals + Backtest |
| `OMON` | Option monitor (calls/puts) | CBOE + Options Analyst |
| `GIP` | Intraday price chart | lightweight-charts |
| `TOP/CN` | Top news / company news | News Analyst + Finnhub |
| `HDS` | Hedge fund holdings | CapitalIQ + SEC EDGAR |
| `OVME` | Options pricing model | Options Analyst |
| `PORT` | Portfolio analytics | PaperBroker + Risk module |

### Proposed UI Layout (Bloomberg-Style)

```
┌─────────────────────────────────────────────────────────────────────┐
│  TradingAgents Terminal              [AAPL ▼]  [Search...]   [⚙]  │
├─────────┬───────────────────────────────────────────┬───────────────┤
│         │                                           │               │
│  WATCH  │  MAIN PANEL (switches based on function)  │  NEWS FEED    │
│  LIST   │                                           │               │
│         │  ┌─ Price Chart (lightweight-charts) ───┐ │  • Breaking   │
│  SPY    │  │                                      │ │  • Earnings   │
│  AAPL   │  │  Real-time candlestick + volume      │ │  • Macro      │
│  TSLA   │  │  Overlays: SMA, MACD, RSI            │ │  • Insider    │
│  NVDA   │  │                                      │ │               │
│  MSFT   │  └──────────────────────────────────────┘ │  Each with    │
│         │                                           │  sentiment    │
│  Each   │  ┌─ Agent Analysis Panel ───────────────┐ │  score and    │
│  shows: │  │  Bull Case │ Bear Case │ Risk View   │ │  relevance    │
│  Price  │  │  ─────────   ─────────   ──────────  │ │               │
│  Change │  │  Agents debate in real-time           │ │               │
│  Signal │  │  Final: BUY | HOLD | SELL             │ │               │
│  Score  │  └──────────────────────────────────────┘ │               │
│         │                                           │               │
├─────────┼───────────────────────────────────────────┼───────────────┤
│         │                                           │               │
│  HEDGE  │  OPTIONS FLOW                             │  DIVERGENCE   │
│  FUND   │                                           │  HEATMAP      │
│  HOLD-  │  Put/Call Ratio: 0.82                     │               │
│  INGS   │  IV Rank: 65%                             │  Inst: +0.4   │
│         │  Unusual Activity: 3 alerts               │  Opts: -0.2   │
│  Top    │                                           │  Price: +0.1  │
│  holders│  ┌─ Options Chain ──────────────────────┐ │  News: +0.3   │
│  with   │  │ Strike │ Call Bid/Ask │ Put Bid/Ask  │ │  Retail: -0.1 │
│  changes│  │  180   │  5.20/5.40  │  2.10/2.30   │ │               │
│  +/-    │  │  185   │  3.10/3.30  │  3.80/4.00   │ │  Regime:      │
│         │  └────────────────────────────────────────│  RISK_ON      │
└─────────┴───────────────────────────────────────────┴───────────────┘
│  Status Bar: 6 agents active | GPT-5.4 | yfinance | 15ms latency   │
└─────────────────────────────────────────────────────────────────────┘
```

### Integrated Plan: 3 Goals Combined

#### Goal 1: Fix TradingAgents Core (from audit)
> Make what exists actually work.

1. **Wire real agent pipeline** — connect `_run_analysis()` to `TradingAgentsGraph`
2. **Fix all API contracts** — align frontend types with backend Pydantic models
3. **Wire PaperBroker** — connect portfolio endpoint to real execution engine
4. **Wire backtest** — fetch real price data for ticker/date range
5. **Add auth + rate limiting** — API key middleware, per-key rate limits
6. **Fix memory leak** — TTL-based eviction for `_analyses` store
7. **Fix production build** — resolve all TypeScript errors
8. **Set up proper venv** — Python 3.12, all deps installed, tests passing

#### Goal 2: Your Previous Discussion Goals
> Real-time investment intelligence.

1. **Real-time news aggregation** — stream from Finnhub, Google News, SEC EDGAR
2. **Stock-to-news correlation** — show which news affects which stocks
3. **Investment recommendations** — BUY/SELL/HOLD with confidence + reasoning
4. **Hedge fund positioning** — who's buying, who's selling (CapitalIQ + 13F)
5. **Options market signals** — put/call ratios, unusual activity, IV surface
6. **Multi-dimensional divergence** — institutional vs retail vs options vs price action

#### Goal 3: Bloomberg Terminal UX (new)
> Professional-grade financial workstation.

1. **Multi-panel layout** — resizable panels like Bloomberg Launchpad
2. **Ticker-centric navigation** — type ticker, see everything about it
3. **Real-time price charts** — candlestick with technical overlays (using `lightweight-charts`)
4. **Live news feed** — streaming sidebar with sentiment scoring
5. **Options chain view** — OMON-style put/call grid
6. **Holdings tracker** — HDS-style institutional ownership changes
7. **Agent debate visualization** — watch Bull/Bear/Risk agents reason in real-time
8. **Dark theme with data density** — Bloomberg's trademark high-information-density UI
9. **Keyboard-first navigation** — function keys, command bar (like Bloomberg's `<GO>`)
10. **Status bar** — active agents, LLM provider, data source, latency

### Implementation Phases

**Phase 1: Foundation (fix what's broken)**
- Fix all API contracts (frontend ↔ backend alignment)
- Wire real agent pipeline to API
- Wire PaperBroker and backtest engine
- Add auth, rate limiting, error handling
- Fix TypeScript build
- Set up venv + CI

**Phase 2: Bloomberg Core Layout**
- Multi-panel responsive layout
- Ticker search + command bar
- Real-time price chart (lightweight-charts)
- Live news feed with sentiment
- Agent analysis with debate visualization

**Phase 3: Institutional Features**
- Options chain view (OMON equivalent)
- Hedge fund holdings tracker (HDS equivalent)
- Divergence heatmap (enhanced, cross-ticker)
- Portfolio with trade execution controls
- Macro dashboard (FRED data)

**Phase 4: Polish & Delivery**
- Keyboard shortcuts
- Export/download functionality
- Performance optimization
- Security hardening
- Full test coverage (real 80%+)
- Documentation

---

## Appendix: Audit Statistics

| Metric | Value |
|--------|-------|
| Total critical bugs | 11 |
| Total high-severity issues | 12+ |
| Frontend-backend mismatches | 8 |
| Missing features (backend exists) | 17 |
| Security vulnerabilities | 11 (incl. hardcoded DB password) |
| Production build | FAILS |
| Claimed test count | 710 |
| Actual collectable tests | 419 |
| Tests that pass import | ~403 |
| Python version mismatch | 3.9 vs 3.10+ required |
| npm vulnerabilities | 0 |
| Hardcoded/stub endpoints | 3 of 5 routes |
