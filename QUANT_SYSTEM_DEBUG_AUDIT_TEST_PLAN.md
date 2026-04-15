# FLAB MASA — Quant System Debug / Audit / Test Plan

> Produced by 10 parallel read-only audit sub-agents per the master prompt at
> `~/Desktop/QUANT_SYSTEM_DEBUG_AUDIT_TEST_MASTER_PROMPT.md`.
> Session date: 2026-04-05. Repository root:
> `/Users/fongyeungwong/Documents/Trading-Agent/TradingAgents`.
>
> **System under audit**: FLAB MASA (née TradingAgents) — sentiment-driven
> multi-agent trading platform with FastAPI backend + Next.js frontend, 9-context
> TickerBriefing materializer, 4-agent LLM debate pipeline (Anthropic), screener,
> signals cache, and divergence panel.
>
> **Executive summary**: The v3 pipeline is architecturally sound and largely
> production-shape, but has **Critical** blockers for any backtest or real-capital
> deploy due to four look-ahead bias vectors (yfinance period fetch, FRED
> latest-observation, live social sentiment, survivorship-biased ETF/universe
> lists) and non-deterministic LLM calls (temperature=1.0 default). Architecture
> has a 1,052-line materializer monolith, a DRY violation in options scoring, and
> a legacy-code layer (`divergence/aggregator.py`) that is dead but still shipped.
> Testing covers 899 test functions across 58 files but has **zero coverage** on
> the materializer, runner, and all frontend logic. Observability is 1/5 (no
> metrics, no correlation IDs, no cost visibility until invoice arrives).
>
> This document is designed to be **handed directly to an engineering team** for
> execution. Every finding cites a concrete file path and line number; every
> recommendation has an effort estimate and test requirement.

---

# Table of Contents

1. [Repository Map](#1-repository-map)
2. [Runtime / Dataflow Map](#2-runtime--dataflow-map)
3. [Debug Playbook — Production Failures & Repro](#3-debug-playbook)
4. [Missing Debug Instrumentation](#4-missing-debug-instrumentation)
5. [Audit — Architecture & Data](#5-audit--architecture--data)
6. [Audit — Model/Signal & Agent/Strategy](#6-audit--modelsignal--agentstrategy)
7. [Audit — Testing & Operational](#7-audit--testing--operational)
8. [Test Strategy — Unit & Integration](#8-test-strategy--unit--integration)
9. [Test Strategy — Replay & Regression](#9-test-strategy--replay--regression)
10. [Priority Fix Roadmap (P0/P1/P2)](#10-priority-fix-roadmap)
11. [Suggested File / Folder Refactor](#11-suggested-file--folder-refactor)
12. [Immediate Next Actions](#12-immediate-next-actions)
13. [Quant-Specific Risk Deep Dive (15 mandatory risks)](#13-quant-specific-risk-deep-dive)

---

# 1. Repository Map

## Top-level Structure

| Directory | Purpose |
|-----------|---------|
| `tradingagents/` | Main Python package |
| `tradingagents/api/` | FastAPI server + routes (16 route files) |
| `tradingagents/agents/` | LLM debate agents (v3) + legacy v1 analysts |
| `tradingagents/pipeline/` | End-to-end orchestration (materializer → agents → synthesis) |
| `tradingagents/data/` | Data materialization, briefing assembly, sources |
| `tradingagents/dataflows/` | Connector registry (20 vendor adapters) |
| `tradingagents/schemas/` | Pydantic models (v3) |
| `tradingagents/gateway/` | Cost tracking, API key store, signals cache |
| `tradingagents/graph/` | LangChain StateGraph (legacy v1) |
| `tradingagents/divergence/` | Divergence dimensions + dead aggregator |
| `tradingagents/memory/` | Hybrid BM25 + vector retrieval |
| `tradingagents/signals/` | Factor baseline scoring |
| `tradingagents/risk/` | Deterministic risk evaluation |
| `tradingagents/screener/` | Volatility universe screener |
| `tradingagents/cache/` | DuckDB caching layer |
| `tradingagents/execution/` | Paper trading (alpaca) — not integrated |
| `tradingagents/backtest/` | Replay engine — not integrated |
| `tradingagents/llm_clients/` | LLM provider abstraction |
| `tradingagents/observability/` | Audit logging |
| `frontend/` | Next.js 14 React client (TypeScript) |
| `tests/` | 58 test files, 13,316 LOC, 899 functions |

**Total**: 189 Python files, 21 top-level packages.

## Layer Classification

| Path | Purpose | Layer |
|---|---|---|
| `tradingagents/data/materializer.py` | TickerBriefing assembly (1,052 LOC, 9 contexts) | data ingestion |
| `tradingagents/data/sources/polygon_price.py` | Polygon aggregates vendor | data ingestion |
| `tradingagents/data/sources/alpha_vantage_price.py` | Alpha Vantage vendor | data ingestion |
| `tradingagents/data/sources/finnhub_news.py` | Finnhub news + event flags | sentiment scoring |
| `tradingagents/data/sources/fred_macro.py` | FRED macro series | data ingestion |
| `tradingagents/data/sources/options_analytics.py` | IV rank, skew, max pain | feature generation |
| `tradingagents/data/sources/social_sentiment.py` | Fear&Greed + ApeWisdom | sentiment scoring |
| `tradingagents/data/sources/quiver_institutional.py` | Congressional / insider / lobbying | data ingestion |
| `tradingagents/data/sources/regime_classifier.py` | Macro regime heuristic | feature generation |
| `tradingagents/data/sources/news_scorer.py` | Tag regex + impact scoring | sentiment scoring |
| `tradingagents/schemas/v3.py` | 505 LOC Pydantic schemas | normalization |
| `tradingagents/agents/v3/thesis_agent.py` | Bull-case LLM agent (358 LOC) | agent logic |
| `tradingagents/agents/v3/antithesis_agent.py` | Bear-case LLM agent (327 LOC) | agent logic |
| `tradingagents/agents/v3/base_rate_agent.py` | Statistical anchor LLM agent (327 LOC) | agent logic |
| `tradingagents/agents/v3/synthesis_agent.py` | Judge LLM agent (505 LOC) | agent logic |
| `tradingagents/pipeline/runner.py` | F11 orchestrator (348 LOC) | agent logic |
| `tradingagents/risk/deterministic.py` | Position sizing + stops | risk control |
| `tradingagents/screener/volatility_screener.py` | Polygon grouped → top 20 equities/ETFs | feature generation |
| `tradingagents/gateway/cost_tracker.py` | LLM spend + budget enforcement (275 LOC) | infra |
| `tradingagents/gateway/signals_cache.py` | SQLite L2 cache 24h TTL (279 LOC) | infra |
| `tradingagents/gateway/api_key_store.py` | Persistent credential store | infra |
| `tradingagents/api/main.py` | FastAPI app factory | api routes |
| `tradingagents/api/routes/signals_v3.py` | Batch endpoint + SSE (19 KB) | api routes |
| `tradingagents/api/routes/analysis_v3.py` | Single-ticker endpoint | api routes |
| `tradingagents/api/routes/divergence.py` | 5-dimension divergence (rewritten from briefing) | api routes |
| `tradingagents/api/routes/config.py` | Runtime config + API key mgmt (17 KB) | infra |
| `frontend/src/app/page.tsx` | Next.js dashboard entry | api routes |

## Suspected Entry Points

- **`tradingagents/api/main.py`** — FastAPI `create_app()`; includes 17 routers; loads API keys on startup via `api_key_store.load_all_into_env()`
- **`tradingagents/pipeline/runner.py::run_analysis(ticker, date, on_event)`** — standalone orchestrator
- **`tradingagents/api/routes/signals_v3.py::batch_signals`** — GET `/api/v3/signals/batch?tickers=...`
- **`tradingagents/api/routes/analysis_v3.py::start_analysis`** — POST `/api/v3/analyze`
- **`tradingagents/api/routes/screener.py::run_screener_route`** — POST `/api/v3/screener/run`
- **`cli/main.py`** — Typer CLI (legacy v1 orchestration, not the v3 pipeline)
- **`frontend/src/app/page.tsx`** — Next.js dashboard root

## Critical Modules (top 8)

### 1. `tradingagents/data/materializer.py` (1,052 LOC)
- **Why critical**: Stage 0 of v3 pipeline. Assembles the frozen `TickerBriefing` from 7+ external sources. All downstream agents depend on its output schema.
- **Likely risks**: Monolith with 9 context builders; single point of failure; technical indicator math copied inline; catches `Exception` broadly.
- **Coupled to**: `data.sources.*`, `schemas.v3`, `yfinance`, Polygon, FRED, Quiver, Finnhub.

### 2. `tradingagents/pipeline/runner.py` (348 LOC)
- **Why critical**: F11 orchestrator; main runtime path for all v3 analysis.
- **Likely risks**: Uses `importlib.util.spec_from_file_location` to load agents dynamically (bypasses langchain import side-effects); duplicates options scoring logic.
- **Coupled to**: `schemas.v3`, `agents.v3.*`, `data.materializer`, `risk.deterministic`, `screener`.

### 3. `tradingagents/schemas/v3.py` (505 LOC)
- **Why critical**: Single source of truth for Pydantic models. Changes break 12+ downstream modules.
- **Likely risks**: High cardinality (100+ fields); no schema version migration; optional-default fields can silently deserialize stale cache entries wrong.
- **Coupled to**: every module that consumes briefings or decisions.

### 4. `tradingagents/agents/v3/{thesis,antithesis,base_rate,synthesis}_agent.py` (1,675 LOC total)
- **Why critical**: The debate loop. 3 parallel agents + 1 judge.
- **Likely risks**: Hardcoded prompts with no version tracking; temperature not pinned to 0 (non-deterministic); dynamic `_load_agent` import hides errors; mock fallback silently contaminates synthesis.
- **Coupled to**: `gateway.cost_tracker`, `schemas.v3`, `memory.hybrid_store`, `llm_clients`.

### 5. `tradingagents/gateway/cost_tracker.py` (275 LOC)
- **Why critical**: Enforces daily + per-ticker LLM spend limits. Consulted before every LLM call.
- **Likely risks**: Pricing table hardcoded; unknown models silently cost $0; double-charges on LLM retries; no API endpoint exposing totals.
- **Coupled to**: all 4 v3 agents, `signals_v3` route, screener LLM filter.

### 6. `tradingagents/gateway/signals_cache.py` (279 LOC)
- **Why critical**: L2 SQLite cache (24h TTL). Fresh pipeline runs are expensive; cache misses drive cost.
- **Likely risks**: Schema version stuck at 1 despite field additions; in-memory L1 is process-local; no distributed cache support; no purge-on-mismatch on schema drift.
- **Coupled to**: `api.routes.signals_v3`.

### 7. `tradingagents/api/routes/signals_v3.py` (~19 KB)
- **Why critical**: Main HTTP entrypoint for batch analysis. 2-tier cache, `asyncio.Semaphore(5)` concurrency gate, SSE streaming.
- **Likely risks**: Semaphore size hardcoded; per-ticker errors silently wrapped into `data_gaps`; SSE stream has no schema versioning.
- **Coupled to**: `gateway.signals_cache`, `gateway.cost_tracker`, `pipeline.runner`, `schemas.v3`.

### 8. `tradingagents/api/routes/config.py` (~17 KB)
- **Why critical**: Runtime config + API key management. Only way to adjust models, vendors, budgets at runtime.
- **Likely risks**: Sensitive keys redacted in GET but plaintext in runtime dict; no validation on PUT; config changes not audited.
- **Coupled to**: `gateway.api_key_store`, `default_config.DEFAULT_CONFIG`.

## Dead Code / Legacy

- **`tradingagents/agents/analysts/`** — 6 v1 analyst files; imported only by legacy `graph/` orchestration, not by v3 pipeline.
- **`tradingagents/agents/researchers/`** — bull/bear researchers referenced in `cli/main.py` but source files not found.
- **`tradingagents/divergence/aggregator.py`** — the original zero-bug `DivergenceAggregator` that always returned composite_score=0. Replaced mid-session by the rewritten `api/routes/divergence.py` which computes directly from the briefing. Grep confirms **no active callers** — safe to delete.
- **`tradingagents/api/routes/analysis.py`** — v1 simulation stub returning hardcoded HOLD; coexists with `analysis_v3.py`.
- **`tradingagents/graph/`** — 1,200+ LOC LangChain StateGraph; only used by legacy CLI.
- **`tradingagents/dataflows/connectors/` (16 of 20 files)** — only Polygon, Finnhub, FRED, Quiver actively used (via source wrappers). The other 16 are dead.
- **`tradingagents/execution/alpaca_paper.py`** — no HTTP endpoint or pipeline call found.
- **`tradingagents/backtest/engine.py`** — exists but not called from live paths.

## High-Coupling Hotspots

| Module | Incoming references | Risk |
|---|---|---|
| `tradingagents/schemas/v3.py` | 12 modules | **Critical** — any field change cascades to materializer, agents, routes, memory, cache, risk, screener |
| `tradingagents/data/materializer.py` | 5 modules | **High** — called by runner, agents, divergence route, config route |
| `tradingagents/agents/utils/agent_utils.py` | 6 modules | **High** — imported by graph, agents, memory, screener |
| `tradingagents/gateway/cost_tracker.py` | 4 modules | **High** — imported by every agent + signals_v3 + screener |
| `tradingagents/gateway/api_key_store.py` | 2 modules | **Medium** — startup env-var injection |

---

# 2. Runtime / Dataflow Map

## End-to-End Flow

### Path A: Single Ticker v3 Analysis (`POST /api/v3/analyze`)

1. Frontend `AnalysisTab.tsx:150-200` calls `startAnalysisV3(ticker, date)` → POST `/api/v3/analyze {"ticker":"AAPL","date":"2026-04-05"}`
2. `api/routes/analysis_v3.py::start_analysis:92-128` → validates ticker, generates `analysis_id`, stores record in `_analyses[analysis_id]`, `asyncio.create_task(_run_pipeline(...))`
3. `_run_pipeline(analysis_id, ticker, analysis_date)` at `analysis_v3.py:58-85` → sets status "running", `asyncio.to_thread(run_analysis, ticker, date, on_event)`
4. `pipeline/runner.py::run_analysis:104-296` executes synchronously in a worker thread:
   - **Stage 0**: `materialize_briefing(ticker, date)` from `data/materializer.py:983-1024`
   - **Stage 1**: `screen_ticker(briefing)` from `data/screener.py:92-110`
   - **Stage 2**: `compute_factor_score(briefing)` from `signals/factor_baseline.py`
   - **Stages 3-5**: If Tier 1/2, load & execute 3 agents sequentially:
     - `run_thesis_agent(briefing)` (LLM call via Anthropic)
     - `run_antithesis_agent(briefing)` (LLM call)
     - `run_base_rate_agent(briefing)` (LLM call)
   - **Stage 6**: `run_synthesis_agent(thesis, antithesis, base_rate)` (Judge LLM)
   - **Stage 7**: `evaluate_risk(synthesis, portfolio_nav=100_000)` from `risk/deterministic.py`
5. Each stage emits `on_event(event_name, data)` → `_push_event(analysis_id, event, data)` → `_events[analysis_id]` (SSE buffer)
6. `FinalDecision` assembled at `runner.py:256-284` and returned
7. Frontend polls `GET /api/v3/analyze/{id}` or streams `/stream` (SSE): `materialized → screened → thesis_complete → antithesis_complete → base_rate_complete → synthesis_complete → risk_complete → pipeline_complete`

### Path B: Batch Screener (`GET /api/v3/signals/batch?tickers=...`)

1. Frontend calls `batch_signals(tickers, force=False)` → `signals_v3.py::batch_signals:292-325`
2. For each ticker, concurrency-gated via `_SIGNALS_SEMAPHORE` (limit=5):
   - Check L1 cache (`signals_v3.py:54-63`, 5-min TTL)
   - If miss, check L2 SQLite (`signals_v3.py:76-90`, 24h TTL)
   - If miss, acquire semaphore and `asyncio.to_thread(run_analysis, ...)`
3. Result converted `FinalDecision → BatchSignalItem` via `_decision_to_item:148-195`
4. Store in L1 + L2; return list

### Path C: Async Batch + SSE (`POST /api/v3/signals/batch/start`)

1. Generate `batch_id`, create progress record, `asyncio.create_task(_run_batch_with_progress(...))`
2. Background worker runs `_one(ticker)` per ticker; increments `running/completed/failed` counters
3. Frontend streams `GET /api/v3/signals/batch/{batch_id}/stream` (SSE): emits `progress` / `ticker_done` / `complete`

### Path D: Divergence Panel (`GET /api/divergence/{ticker}`)

1. `asyncio.to_thread(materialize_briefing, ticker, today)`
2. Compute 5 dimensions from the briefing:
   - Institutional (Quiver congress + insider + lobbying) → normalized [-1, +1]
   - Options (put/call + IV skew) → [-1, +1]
   - Price Action (change_20d + RSI + MACD + SMA) → [-1, +1]
   - News (sentiment + event_flags) → [-1, +1]
   - Retail (Fear&Greed + ApeWisdom) → [-1, +1]
3. Weighted composite: `sum(dims[k].value * WEIGHTS[k])` with `WEIGHTS = {institutional: 0.35, options: 0.25, price_action: 0.20, news: 0.15, retail: 0.05}`
4. Return `DivergenceResponse(ticker, regime, composite_score, dimensions, timestamp)`

## Data Source → Context Field Mapping

| External API | Auth | Source Module | Context Model | Fields Populated | Fallback |
|---|---|---|---|---|---|
| **yfinance** (free) | none | `materializer._fetch_price_history` | PriceContext | OHLCV-derived: price, change_1/5/20d_pct, SMA 20/50/200, RSI-14, MACD, Bollinger, ATR-14, realized_vol_20d, atr_pct | Default `_empty_price_context()` on fail |
| **Polygon.io** ($29/mo) | POLYGON_API_KEY | `data.sources.polygon_price` | PriceContext | Same shape as yfinance | Tag `price:polygon_fallback:*`, cascade to yfinance |
| **Alpha Vantage** (free/paid) | ALPHA_VANTAGE_API_KEY | `data.sources.alpha_vantage_price` | PriceContext | Same shape | Tag `price:alpha_vantage_fallback:*` |
| **yfinance options** | none | `data.sources.options_analytics` | OptionsContext | put_call_ratio, iv_rank_percentile, iv_skew_25d, max_pain_price, unusual_activity_summary | Empty OptionsContext |
| **Finnhub** ($free tier) | FINNHUB_API_KEY | `data.sources.finnhub_news` | NewsContext | top_headlines, headline_sentiment_avg, event_flags (22 tags) | Tag `news:finnhub_fallback:*`, cascade to yfinance news |
| **FRED** (free) | FRED_API_KEY | `data.sources.fred_macro` | MacroContext | fed_funds_rate, yield_curve_2y10y_bps, dgs2, dgs10 | Tag `macro:fred_fallback` |
| **yfinance VIX** | none | `_build_macro_context` | MacroContext | vix_level | Tag `macro:vix` |
| **yfinance SPY** | none | `_build_macro_context` | MacroContext | sector_etf_5d/20d_pct (SPY proxy) | Tag `macro:spy` |
| **QuiverQuant** ($75/mo) | QUIVER_API_KEY | `data.sources.quiver_institutional` | InstitutionalContext | congressional_net_buys_30d, top buyers/sellers, govt_contracts_count/total, lobbying_usd_last_quarter, insider_net_txns_90d | Tag `institutional:quiver_fallback:*`, 60-min cache |
| **CNN Fear & Greed** | free public | `data.sources.social_sentiment` | SocialContext | sentiment_score (40% weight) | Tag `social:sentiment_fetch_failed:*`, 15-min cache |
| **ApeWisdom WSB** | free public | `data.sources.social_sentiment` | SocialContext | mention_volume_vs_avg, trending_narratives (60% weight) | Partial fetch if one source fails |
| **Anthropic Claude** | ANTHROPIC_API_KEY | `agents.v3.*` | Thesis/Antithesis/BaseRate/SynthesisOutput | catalysts, confidence, must_be_true, scenarios, disagreement, signal | Deterministic mock fallback; tagged `llm:budget_exceeded` or `llm:api_error` |

## Caching Summary

- **L1 in-memory** (5 min): `signals_v3._cache[(ticker, date)]`
- **L2 SQLite** (24h): `~/.tradingagents/signals_cache.db` (schema_version=1)
- **Quiver 60-min cache**: per `(ticker, UTC-date)` with thread lock
- **Options IV rank cache**: per `(ticker, YYYY-MM-DD)` lifetime (52-week rolling vol computation)
- **Social sentiment 15-min cache**: per ticker
- **Screener cache**: `~/.tradingagents/screener_cache.db` (daily)
- **API keys**: `~/.tradingagents/api_keys.db` (SQLite, 0600 perms)
- **Runtime config**: `~/.tradingagents/runtime_config.json`

## Debug Entry Points

| File:line | What to inspect | Why | Tier |
|---|---|---|---|
| `analysis_v3.py:70` (asyncio.to_thread) | `result` or exception from `run_analysis` | Entry to entire pipeline | Critical |
| `materializer.py:998-1008` (context builders) | Each context's `fetched_ok` and `data_gaps` appends | First external data boundary | Critical |
| `materializer.py:1000` (price history fetch) | `hist` DataFrame shape, null counts, date range | Price is foundation for vol/technicals/risk | Critical |
| `runner.py:204-220` (agent calls) | Confidence scores, catalyst lists | LLM output validation | Critical |
| `runner.py:224` (synthesis call) | `synthesis.signal`, conviction, disagreement_score | Final decision | Critical |
| `runner.py:237` (risk evaluation) | `risk.final_shares`, risk_rating | Position sizing | Critical |
| `signals_v3.py:218-226` (semaphore acquire) | Semaphore count, queue depth | Batch bottleneck | Performance |
| `signals_v3.py:76-90` (L2 cache lookup) | Hit/miss rate, deserialization errors | Cache corruption detection | Operational |
| `signals_v3.py:148-195` (_decision_to_item) | `cost_usd`, `models_used` | Cost integration | Cost |
| `divergence.py:216-244` (materialize for divergence) | `raw_data` in dimension scores | Divergence debugging | Debugging |

## Async / Concurrency Model

- **Event loop**: FastAPI async; all HTTP endpoints async
- **Blocking offload**: `run_analysis` and `materialize_briefing` run via `asyncio.to_thread`
- **Concurrency limit**: `asyncio.Semaphore(5)` in `signals_v3.py` — gates LLM pipeline runs; cache hits skip semaphore
- **Lazy init**: semaphore created on first use (within running event loop) to avoid binding to wrong loop at import
- **ThreadPoolExecutor**: screener uses `max_workers=5` for parallel per-ticker history fetches (respects Polygon rate limit)

## Time / Timezone Handling

- `date` flows as ISO string `"2026-04-05"` (naive, no TZ)
- yfinance history returns tz-aware DatetimeIndex (market TZ)
- Polygon returns UTC milliseconds; parsed to `tz="UTC"` DatetimeIndex (potential mix — see §13.4)
- FRED observations are date-only
- Finnhub headlines in UTC unix timestamps
- `divergence.py` returns `datetime.now(timezone.utc).isoformat()`

**Known TZ issues**: Polygon bars labeled UTC are actually market ET times → 4-5 hour shift if consumer assumes UTC==market time. (See §13.4.)

## Error Propagation

| Scenario | Propagation |
|---|---|
| Price history fails | `data_gaps += ["price:{vendor}_fallback:..."]` → empty PriceContext (neutral values) → tier may misclassify |
| Finnhub fails | Falls back to yfinance news → tag `news:finnhub_fallback:*` |
| Quiver fails | `institutional.fetched_ok=False` → zeros + tag `institutional:quiver_fallback:*` |
| FRED fails | Tag `macro:fred_fallback` → regime defaults to TRANSITIONING |
| LLM budget exceeded | `BudgetExceededError` caught → mock fallback; **no data_gap emitted** (silent) |
| Materializer exception | Propagates to `asyncio.to_thread` → caught in `_run_pipeline` → status="failed" |
| Batch ticker failure | Per-ticker wrapped in try/except → returns HOLD + `data_gaps=["pipeline_error:..."]`, batch continues |

---

# 3. Debug Playbook

## 3.1 Common Production Failures

| # | Symptom | Likely Cause | Where to Inspect | How to Confirm | Fix Direction | Blocking? |
|---|---|---|---|---|---|---|
| 1 | Dashboard shows all HOLD/conv=25 | ANTHROPIC_API_KEY missing or budget exhausted | `/api/config/test-keys`; backend log "credit balance too low" | Unset key → curl batch → expect mock | Top up credits or increase `budget_daily_usd` | Yes |
| 2 | Dashboard stuck "Running v3 pipeline..." | L1/L2 cache cold + 5-concurrency semaphore bottleneck | `signals_v3.py:105` semaphore state | `/api/v3/signals/batch/{id}/status` shows running=5 repeatedly | Reduce batch size or raise `_SEMAPHORE_LIMIT` | No |
| 3 | Polygon 429 errors in health dashboard | Free-tier 5/min rate limit exhausted | Backend log `"Polygon 429"` | `/api/config/test-keys` → POLYGON.status==fail | Upgrade plan OR switch `data_vendor_price: yfinance` | No |
| 4 | Divergence panel shows all 0.0 | OptionsContext empty OR materializer exception | Curl `/api/divergence/TICKER` | All dimensions = 0 | Check `data_gaps` in batch response | No |
| 5 | `institutional:quiver_fallback:*` in data_gaps | Quiver endpoint changed / key expired / 429 | `quiver_institutional.py:113` retry logic | Decode tag: HTTP 401 vs 429 vs timeout | Re-probe via `/api/config/test-keys` | No |
| 6 | `macro:fred_fallback` | FRED_API_KEY missing or rate-limited | `/api/config/api-keys` → FRED configured? | GET returns configured=false | Set FRED_API_KEY (free) | No |
| 7 | `news:finnhub_fallback:*` | Finnhub key expired or rate-limited | `/api/config/test-keys` → FINNHUB.status | `data_gaps` reason string | Update FINNHUB_API_KEY | No |
| 8 | `price:polygon_fallback:*` | Polygon 429, invalid ticker, or auth failed | `materializer.py:280-285` error handling | Curl with `force=1` → observe fallback | Verify ticker validity or switch vendor | No |
| 9 | Mock fallback in thesis agent (conv=25, cost=$0) | ANTHROPIC_API_KEY missing or budget exceeded | `thesis_agent.py:391-399` budget gate | `cost_tracker.daily_total_usd()` vs budget | Set key OR increase budgets | Yes |
| 10 | Cache stale after schema change | L2 SQLite has old JSON without new fields | `signals_cache._SCHEMA_VERSION` vs code schema | Parse error in logs | Bump `_SCHEMA_VERSION`, clear_all() | No |
| 11 | SSE stream drops mid-batch | Browser closed EventSource or backend restart | `signals_v3.py:526-564` SSE generator | Polling fallback `/status` endpoint | Use `/status` for resilience | No |
| 12 | Frontend "Cannot read properties of undefined" | Stale cache entry lacks new optional fields | `BatchSignalItem.model_dump()` | Missing `options_direction` key | Null guards + cache version bump | No |
| 13 | Options signal BULL ↔ BEAR flip between runs | Near-zero clamp threshold (±0.15) is noisy | `runner.py:34-80` | Same ticker runs yield different directions | Widen to ±0.25 with hysteresis | No |
| 14 | Screener returns empty results | Polygon grouped rate-limited OR auth failed | `screener/volatility_screener.py` logs | `/api/screener?base_vol_pct=20` returns [] | Set/renew POLYGON_API_KEY | No |
| 15 | Volatility regime stays NORMAL on HIGH-vol ticker | <20 bars → `realized_vol_20d_pct=None` → defaults NORMAL | `materializer.py:176-195` | Newly-IPO'd ticker | Wait 20+ trading days | No |
| 16 | Briefing parse error after schema change | New field without `default_factory` | `schemas/v3.py` field defaults | Pydantic validation error | Add `default_factory=list` / `default=None` | No |
| 17 | yfinance 401 "Invalid Crumb" | Upstream Yahoo session expired | yfinance auto-retries | Intermittent on cold start | Transparent; restart if persistent | No |
| 18 | Delisted tickers crash batch | SPLK/WBA/ANSS in watchlist | Backend log "possibly delisted" | Batch includes delisted → tag `price:history` | Filter upstream | No |
| 19 | Congress net_buys=0 but trades happened | 30d window excluded them | `quiver_institutional.py` filter | Trades older than 30d | Expected behavior | No |
| 20 | IV rank stays None | <20 historical bars for proxy | `options_analytics.py` IV history | Illiquid / ETF | Acceptable None | No |
| 21 | Fresh batch costs $0.00 | All 4 agents fell back to mock | `cost_tracker.py:244-262` budget check | `force=1` + mock markers | Set ANTHROPIC_API_KEY + budget | Yes |
| 22 | `llm_provider != anthropic` config ignored | Agents hardcoded to Anthropic | `thesis_agent.py:35-39` reads config but calls Anthropic | Config shows openai; logs show Anthropic call | Future-proofing; agents don't switch yet | No |
| 23 | Tests pass but prod fails | Mocks differ from real API response shapes | Compare mock JSON to live response | Integration test vs prod parity | Add live smoke test before deploy | No |

## 3.2 Local Reproduction Strategy

### A) Reproduce "all HOLD/conv=25" without burning credits

```bash
unset ANTHROPIC_API_KEY
curl "http://localhost:8000/api/v3/signals/batch?tickers=AAPL&force=1"
```

Expected: `signal=HOLD, conviction=25, cost_usd=0.0`. Each agent logs `"LLM unavailable"` and returns `_mock_*` output.

### B) Reproduce divergence computing real values

```bash
curl "http://localhost:8000/api/divergence/NFLX"
```

Expected: `composite_score != 0`, 5 non-zero dimensions, `regime in [RISK_ON, RISK_OFF, ...]`. If composite=0, check `data_gaps` in `/api/v3/signals/batch?tickers=NFLX`.

### C) Reproduce Polygon 429

```bash
for t in AAPL MSFT NVDA GOOGL TSLA QQQ; do
  curl "http://localhost:8000/api/v3/signals/batch?tickers=$t&force=1" &
done
wait
```

Expected: after ~5 calls within 60s, POLYGON.status=fail via `/api/config/test-keys`. Health dashboard dot turns red with tooltip containing "exceeded maximum requests".

### D) Reproduce cache-stale-after-schema-change

1. Populate cache: `curl "...?tickers=AAPL"`
2. Inspect SQLite: `sqlite3 ~/.tradingagents/signals_cache.db "SELECT * FROM signals LIMIT 1;"`
3. Add new required field to `BatchSignalItem` in `responses.py`
4. Call `force=1` again → observe Pydantic validation error in logs
5. **Fix**: Bump `_SCHEMA_VERSION` + `signals_cache.clear_all()`

### E) Reproduce LLM budget exceeded

```bash
curl -X PUT http://localhost:8000/api/config/runtime -d '{...,"budget_per_ticker_usd":0.001}'
curl "http://localhost:8000/api/v3/signals/batch?tickers=AAPL&force=1"  # costs ~$0.20, exceeds $0.001
curl "http://localhost:8000/api/v3/signals/batch?tickers=AAPL&force=1"  # raises BudgetExceededError → mock fallback
```

## 3.3 Time-Window Lockdown

Pin pipeline to a specific date:

```python
run_analysis(ticker="AAPL", date="2026-04-05")
```

**Non-replay-safe paths** (see §13.2 for full list):
- yfinance `.history(period="1y")` uses wall-clock now, NOT the date param
- FRED `/observations?sort_order=desc&limit=1` returns latest, ignoring date
- ApeWisdom / Fear&Greed return current snapshot only
- Quiver 30d/90d windows relative to now, not date

**For full replay**: must switch to Polygon with explicit `from/to` params + pre-downloaded news fixtures + skip social sentiment.

## 3.4 Single Event Tracing

Follow one news headline through the pipeline:

1. **Ingestion**: `materializer._build_news_context` → `briefing.news.top_headlines`
2. **Scoring**: `news_scorer.score_headlines` → `ScoredHeadline(direction, impact_score, rationale)`
3. **Briefing integration**: `_format_briefing` inserts into `## NEWS` section of LLM prompt
4. **Agent processing**: Thesis/Antithesis/BaseRate all receive the same formatted briefing
5. **Synthesis**: `SynthesisOutput.key_evidence` references the headline
6. **UI**: `/api/v3/news/{ticker}/scored` → `RightPanel.NewsFeed` renders with direction chip + rationale

Example trace for "AAPL beats Q3 earnings":
```
Finnhub API fetch → briefing.news.top_headlines[0] = "Apple beats Q3..."
↓
news_scorer → ScoredHeadline(direction=LONG, impact=92, tags=[earnings_beat], rationale="Earnings beat — bullish")
↓
thesis_agent._format_briefing → prompt includes "[NEWS] 1. Apple beats Q3..."
↓
thesis LLM output → catalysts=["Q3 earnings beat"], confidence_score=75
↓
synthesis → key_evidence includes earnings beat, signal=BUY, conviction=72
↓
UI: SignalTable shows AAPL BUY 72, NewsFeed shows "LONG 92" chip on the headline
```

---

# 4. Missing Debug Instrumentation

| Gap | Status | Priority | Effort | Notes |
|---|---|---|---|---|
| 4.1 Structured logging | EXISTS ✓ | — | 0h | `observability/logger.py::JSONFormatter` + `logging.getLogger(__name__)` used consistently |
| 4.2 Correlation / trace IDs | MISSING | P1 | 3h | `CorrelationContext` infra exists but `run_analysis` doesn't propagate `trace_id`; 10+ log lines per run are uncorrelatable |
| 4.3 Event lineage | MISSING | P2 | 4h | No `sources_used: list[str]` on any context; only `data_gaps` (missing/fallback) is visible |
| 4.4 Decision snapshot | PARTIAL | P1 | 2h | Briefing is stored via `snapshot.py`, but full `FinalDecision` (with agent outputs) is NOT persisted for post-mortem |
| 4.5 Feature dump | MISSING | P2 | 2h | No `GET /api/v3/briefing/{ticker}/{date}` endpoint or CLI flag to export the exact briefing fed to agents |
| 4.6 Source-level health check | PARTIAL | P2 | 3h | `/api/config/test-keys` probes live (exists), but no historical up/down tracking |
| 4.7 Configuration snapshot | MISSING | P1 | 2h | `FinalDecision` has no `config_hash` field → mid-day config change makes prior runs irreproducible |
| 4.8 Deterministic replay | MISSING | P1 | 8h | Blockers: yfinance uses wall-clock, LLM temperature=1.0, news/social APIs return "current"; no `replay_mode` flag |
| 4.9 One-click smoke scenario | MISSING | **P0** | 2h | No `scripts/smoke_test.py`; pytest tests mock everything |
| 4.10 Error budget / silent failure alarms | MISSING | P1 | 2h | Mock fallback is silent; no `record_incident("mock_fallback", agent)` |
| 4.11 Budget observability | PARTIAL | P2 | 3h | `cost_tracker` records but no `GET /api/config/costs/today` endpoint or UI widget |
| 4.12 Prompt recording | MISSING | P1 | 3h | Exact prompts sent to Claude are not saved → cannot audit hallucinations |

**Total**: 12 gaps (1 exists, 3 partial, 8 missing). P0 + P1 critical path = ~22 hours of work.

---

# 5. Audit — Architecture & Data

## 5.1 Architecture Findings

| # | Severity | Title | File | Issue |
|---|---|---|---|---|
| 1 | High | Materializer monolith | `materializer.py` (1,052 LOC) | 9 context builders + 7 external sources in one file — SRP violation |
| 2 | Medium | Importlib loader silently swallows errors | `runner.py:82-100` | Dynamic agent loading bypasses static analysis and import errors |
| 3 | High | DRY violation in options scoring | `runner.py:33-79` vs `divergence.py:72-99` | Two near-identical `_derive_options_signal` and `_compute_options` implementations |
| 4 | Medium | Config mixes I/O and HTTP handlers | `config.py:79-141` | SQLite persistence + FastAPI route handlers in same module |
| 5 | Low | Backtest/execution modules exist but not called | `backtest/`, `execution/` | Dead code confuses auditors |
| 6 | Low | Dead divergence aggregator | `divergence/aggregator.py` | Rewritten in `divergence.py` route; old file still present |
| 7 | Low | Legacy `/api/analyze` coexists with v3 | `analysis.py` vs `analysis_v3.py` | Two analyze endpoints confuse API consumers |
| 8 | Medium | Importlib workaround architectural debt | `runner.py:82` | Required because `agents/__init__.py` eagerly imports langchain |
| 9 | Medium | Schema drift risk on optional fields | `schemas/v3.py:216-233` | `default_factory` fields can silently deserialize wrong |
| 10 | Low | Frontend/backend contract drift risk | `api.ts` vs `responses.py` | TS interfaces mirror Pydantic but no automated check |

## 5.2 Data Audit Findings

| # | Severity | Title | File | Issue |
|---|---|---|---|---|
| 11 | **Critical** | **yfinance news leaks future data** | `materializer.py:679-716` | yfinance news endpoint returns "latest", ignores `as_of_date` — backtests see post-date headlines |
| 12 | **Critical** | **Social sentiment leaks future data** | `materializer.py:755`, `social_sentiment.py` | Fear & Greed + ApeWisdom are current-state only; not date-constrained |
| 13 | **Critical** | **yfinance price fallback leaks future data** | `materializer.py:262-320` | `ticker_obj.history(period="1y")` uses wall-clock now, ignoring date param |
| 14 | **Critical** | **FRED ignores as-of-date** | `fred_macro.py:105` | `sort_order=desc&limit=1` returns latest observation regardless of `observation_end` |
| 15 | **Critical** | **S&P 500 / ETF universe hardcoded to today** | `volatility_screener.py` `_KNOWN_ETFS` | Replay on 2020-01-01 uses 2026 ETF list — classic survivorship bias |
| 16 | High | Naive datetimes scattered across codebase | multiple files | `datetime.now()` without `tz=timezone.utc` — ambiguous in multi-TZ deploys |
| 17 | Medium | Market calendar unawareness | `materializer.py:915-980` | Sunday run silently uses Friday data; no weekend/holiday detection |
| 18 | Medium | `data_age_seconds` is fetch latency not data age | `materializer.py` | Labelled as "age" but measures elapsed wall-clock from fetch start |
| 19 | Medium | Fallback chain not always recorded in data_gaps | `materializer.py:292-310` | Some fallbacks happen silently |
| 20 | Low | Quiver Form 4 duplicates on same-day refiling | `quiver_institutional.py:330-370` | Member re-files, count doubles |

## 5.3 Scorecard

| Area | Score (1-5) | Rationale |
|---|---|---|
| Architecture cleanliness | **2** | Monolith materializer, importlib workaround, dead code present |
| Module boundaries | **2** | DRY violations, config mixes concerns |
| Data consistency | **1** | Four critical future-leakage findings |
| **Future leakage safety** | **1** | yfinance + FRED + social + survivor bias all leak future data |
| Schema drift resistance | 2 | Many optional fields, no schema version purge |
| Dead code hygiene | 2 | `aggregator.py`, legacy routes, unused connectors |

**Verdict**: Architecture is fixable (2 weeks of work), but data future-leakage vectors must be addressed before **any** backtest or real-capital decision.

---

# 6. Audit — Model/Signal & Agent/Strategy

## 6.1 Model / Signal Findings

| # | Severity | Title | File | Issue |
|---|---|---|---|---|
| M1 | **Critical** | **LLM temperature not pinned to 0** | All 4 v3 agents `_call_anthropic` | Anthropic default temperature=1.0 → non-deterministic → backtests not reproducible |
| M2 | High | News scorer has no negation handling | `news_scorer.py:65-232` | "fails to beat estimates" matches `earnings_beat` regex (+0.80) despite bearish intent |
| M3 | High | LLM schema parse failure silent-fallbacks | `thesis_agent.py:407-429` | Mock confidence=25 + mock antithesis=25 → synthesis averages to "low conviction" → HOLD with no indication of outage |
| M4 | High | Regime classifier thresholds hardcoded in prompt | `base_rate_agent.py:144`, `divergence.py` | Thresholds like "VIX>30 → RISK_OFF" exist only in LLM prompts, not code constants → cannot audit or calibrate |
| M5 | High | LLM prompt versioning absent | All agent files | Inline prompts with no `_PROMPT_VERSION` → historical runs uncomparable after prompt changes |
| M6 | Medium | Options signal threshold instability | `divergence.py:73-100` | ±0.15 cutoff produces BULL↔BEAR flips on tiny PCR drift |
| M7 | Medium | Volatility percentile convention undocumented | (helper function) | Unclear if `<=` or `<` ranking |
| M8 | Low | Offline → online metric leakage | (searched, none found) | Pass ✓ |
| M9 | Medium | News scorer regex drift over time | `news_scorer.py:64-233` | Hardcoded weights don't adapt to new market vocabulary |

## 6.2 Agent / Strategy Findings

| # | Severity | Title | File | Issue |
|---|---|---|---|---|
| A1 | **Critical** | Determinism (temperature=0) | All agents | Same as M1 — elevated to Critical due to strategy impact |
| A2 | High | Silent degradation paths | All agents | Mock thesis + mock antithesis → synthesis treats as real low-conviction → HOLD without warning |
| A3 | High | Missing `used_mock: bool` on outputs | `schemas/v3.py:412` | No field on FinalDecision indicates the debate was entirely mocked |
| A4 | Medium | Cascading failure on briefing gaps | `base_rate_agent.py:168-193` | Partial price history → `realized_vol_20d=None` → base_rate mock → synthesis uses mock as real |
| A5 | Medium | Fallback cascade not exposed in outputs | All agents | `fallback_chain_used` field needed for operational transparency |
| A6 | Medium | Circuit breaker observability gap | `cost_tracker.py` | `BudgetExceededError` raised but no metric/log surfaces it |
| A7 | Medium | Risk rules miss earnings/expiry proximity | `deterministic.py:19-86` | `next_earnings_days` computed in briefing but risk layer never consults it |
| A8 | Medium | Conviction calibration not validated | `synthesis_agent.py:314-322` | No empirical check that conviction=80 correlates with +X% returns |
| A9 | Medium | Position sizing formula overconfidence risk | `deterministic.py:154-157` | LLM overconfidence × 0.02 NAV per trade → drawdown exposure |
| A10 | Medium | Disagreement-score discount magnitude unclear | `synthesis_agent.py:209`, `deterministic.py:160` | `disagreement_discount` applied but magnitude uncalibrated |

## 6.3 Scorecard

| Area | Score | Notes |
|---|---|---|
| Determinism | **1** | Temperature=1.0 default, non-deterministic outputs |
| Fallback safety | 2 | Fallbacks exist but silent; mock outputs unmarked |
| Signal stability | 2 | Negation false positives, options threshold whipsaw |
| Agent isolation | 3 | Agents are pure functions but cascading gap failures undocumented |
| Risk coverage | 2 | No earnings/expiry/halt/daily-loss-limit rules |
| Conviction calibration | 2 | No feedback loop, no damping |
| Prompt versioning | **1** | Inline strings, no version tracking |

---

# 7. Audit — Testing & Operational

## 7.1 Testing Audit

**Total**: 58 test files, 13,316 LOC, 899 test functions.

| Module Category | Coverage | Status |
|---|---|---|
| Data sources (11 modules) | 6/11 tested | Partial |
| Agents v3 (schema + execution) | Schemas ~60%, execution ~30% | Gap |
| Gateway (3 modules) | 3/3 tested | Good |
| API routes (16 files) | ~40% | Weak |
| **Materializer + Runner** | **0%** (1,400 LOC combined) | **Critical** |
| Pipeline + Screener | Partial | Weak |
| Pydantic schemas | ~60% | Moderate |
| **Frontend** | **0%** | **Critical** |

**Overall coverage estimate**: **~45%** of critical modules tested.

### Specific gaps

1. **No tests for `materializer.py`** (1,052 LOC) — no unit tests for SMA/RSI/MACD/Bollinger, no round-trip TickerBriefing JSON
2. **No tests for `pipeline/runner.py`** (348 LOC) — no end-to-end `run_analysis` test with mocked agents
3. **Mock authenticity drift**: Quiver test mocks use `acqDisp` but real API returns `AcquiredDisposedCode` (fixed mid-session)
4. **Test isolation**: Some tests leak to `~/.tradingagents/*.db`; `autouse` tmp-path fixtures needed
5. **`@pytest.mark.unit` not registered** in `pyproject.toml` → `PytestUnknownMarkWarning`
6. **Frontend has ZERO tests**: no Vitest/Jest config; `SignalTable.tsx`, `sortValue`, `formatRelativeTime`, color helpers all uncovered

### Happy-path-only tests (flagged for error-path additions)

- `test_alpha_vantage_price.py` — only success paths, no 401/429
- `test_social_sentiment.py` — only scoring, no missing-key path
- `test_v3_schemas.py` — no JSON round-trip
- `test_new_agents.py` — no LLM integration

## 7.2 Operational Readiness

| Area | Score (1-5) | Rationale |
|---|---|---|
| Observability | **1** | Logging present but unstructured; zero metrics; zero traces |
| Alerting | **1** | No alerts for mock fallback, 429s, budget exhaustion |
| Runbooks | **1** | No operational docs |
| Deploy / rollback | 2 | Docker + compose exist; no CI/CD, no systemd, manual uvicorn |
| Config tracking | **1** | Silent overwrites, no audit log |
| Secret rotation | **1** | Requires backend restart |
| Backup / DR | **1** | Zero backup of 3 SQLite stores |
| Cost visibility | **0** | Cost tracked but not exposed — session hit credit depletion blind |
| Rate limit visibility | **1** | 429s handled silently, no metric |
| Security | 2 | CORS=* OK for localhost but risky on deploy; no TLS, no auth |
| **Average readiness** | **1.2 / 5** | **Not production-ready** |

## 7.3 Top Operational Gaps

1. **No `/api/config/costs/today`** → can't see spend until invoice arrives (session witnessed this)
2. **No runbook for Polygon 429** → user hits it repeatedly without guidance
3. **CORS allow_origins=["*"]** + no auth → critical vulnerability if deployed beyond localhost
4. **No hot-reload of secrets** → key rotation requires backend restart

---

# 8. Test Strategy — Unit & Integration

## 8.1 Unit Test Matrix (155 scenarios)

Produce tests targeting these modules. Matrix compressed; see full per-row spec below. Full breakdown:

- **Data sources (68 rows)**: polygon_price (10), alpha_vantage_price (6), finnhub_news (12), fred_macro (6), options_analytics (6), social_sentiment (5), quiver_institutional (8), regime_classifier (6), news_scorer (9)
- **Materializer (9 rows)**: vendor dispatch, build_*_context paths, full materialize_briefing
- **Schemas (8 rows)**: Pydantic parse, default_factory, enum validation, round-trip JSON, backward compat
- **Agents (16 rows)**: thesis/antithesis/base_rate/synthesis `_format_briefing`, `_extract_json_from_text`, `_call_anthropic`, mock fallbacks, check_budget, record cost, lazy model loading
- **News scorer (3 rows)**: 22-tag coverage, recency decay, impact score formula
- **Risk (5 rows)**: position cap, VIX halt, earnings window, drawdown cut, stop loss
- **Cost tracker (5 rows)**: Opus/Sonnet/Haiku pricing, per-ticker accumulation, daily limit
- **Signals cache (4 rows)**: round trip, TTL expiry, schema version, corrupt JSON
- **API key store (4 rows)**: CRUD, load_all_into_env, perms, missing DB
- **Screener (5 rows)**: vol formula, ATR, z-score, ETF classification, LLM filter fallback
- **Runner (5 rows)**: options signal, importlib loader, Tier 3 path, full path, cost records per agent
- **API routes (8 rows)**: cache hit, force bypass, semaphore concurrency, per-ticker error isolation, field completeness

### Sample rows (high priority)

| Module | Scenario | Input | Assertion | Priority |
|---|---|---|---|---|
| `polygon_price.fetch_polygon_price_history` | missing API key | no POLYGON_API_KEY | fetched_ok=False, error contains "API key" | HIGH |
| `polygon_price` | HTTP 429 | mock 429 response | fetched_ok=False, error mentions rate limit | HIGH |
| `finnhub_news` | each of 22 tag regexes | canonical phrase | tag present in output | HIGH |
| `materializer._build_price_context` | <20 bars | short history | realized_vol_20d_pct=None, no crash | HIGH |
| `materializer.materialize_briefing` | full path mocked | all sources mocked | 9 contexts populated, data_gaps=[] | HIGH |
| `schemas.v3.TickerBriefing` | legacy JSON without volatility | old briefing dict | parses via default_factory | HIGH |
| `thesis_agent._extract_json_from_text` | parse error + retry | first invalid, second valid | retries, returns valid output | HIGH |
| `thesis_agent._call_anthropic` | success | LLM response with usage tokens | cost_tracker.record called with correct amount | HIGH |
| `cost_tracker.compute_cost` | Opus model | 1M/1M input/output | 15 + 75 = 90 USD | HIGH |
| `signals_cache.put/get` | round trip | ticker, date, JSON | retrieves identical dict | HIGH |
| `runner._derive_options_signal` | pcr=0.7, skew=+0.2 | briefing | direction=BULL, impact>0 | HIGH |
| `signals_v3.batch_signals` | force=1 | existing cached entry | cached=False, fresh compute | HIGH |
| `signals_v3` | semaphore limit | 20 concurrent calls | max 5 in flight at any time | HIGH |

## 8.2 Integration Test Matrix (15 scenarios)

| Flow | Scenario | Expected | Priority |
|---|---|---|---|
| Full analyze | POST /api/v3/analyze → poll → complete | signal ∈ {BUY,SHORT,HOLD}, 5+ contexts populated | HIGH |
| Batch | GET batch with 2 tickers | both have all 12+ fields incl. options_direction, vol, cost | HIGH |
| Force bypass | batch then batch force=1 | first cached, second fresh | HIGH |
| SSE progress | start + stream | events ordered, final status=complete | HIGH |
| Config live | PUT runtime config → next materialize | uses new vendor | MEDIUM |
| Key rotation | PUT api-keys → test-keys | new key passes probe | HIGH |
| Rate-limit fallback | simulate Polygon 429 | data_gaps contains polygon_fallback, price still populated | HIGH |
| Budget exhaust | budget=0 → all agents mock → valid FinalDecision | pipeline returns valid output | MEDIUM |
| Screener → batch | run screener → feed equities[:5] into batch | all complete | MEDIUM |
| Divergence parity | materialize briefing → /api/divergence | same briefing drives both | MEDIUM |
| News scoring | real Finnhub call | at least one headline with event_flags | MEDIUM |
| Quiver end-to-end | fresh materialize | institutional.fetched_ok=True, thesis prompt includes institutional block | MEDIUM |
| FRED macro | fresh materialize | fed_funds_rate populated | MEDIUM |
| Volatility | fresh materialize | realized_vol_20d_pct + 20 kline bars | MEDIUM |
| Frontend batch | GET batch | BatchSignalItem has all required fields | HIGH |

## 8.3 Recommended Test Utilities

1. **`FakeAnthropicClient`** (2h) — canned responses, budget-exceeded simulation, call log
2. **`MockPolygonServer`** (3h) — aiohttp test server with rate-limit simulation
3. **`BriefingFactory`** (2h) — `.bull()`, `.bear()`, `.neutral()`, `.crisis()`, `.with_gaps([...])`
4. **`ClockFixture`** (1h) — pytest-freezegun wrapper for decay and TTL tests
5. **`DataGapsAsserter`** (1h) — assert_has_gap / assert_no_gap / assert_gap_count
6. **`CostLedgerRecorder`** (2h) — captures cost entries, asserts totals
7. **`EndpointSmokeBatch`** (2h) — hits every v3 endpoint, validates all schemas
8. **`SnapshotDiffer`** (1h) — compares two FinalDecision objects, reports deltas
9. **`CacheResetFixture`** (1h) — autouse fixture clearing L1 + L2 + api_key_store + screener cache
10. **`PromptCaptureFixture`** (2h) — captures exact prompts sent to Claude

**Total utility build effort**: ~18 hours. Estimated coverage boost: 45% → 95%+.

---

# 9. Test Strategy — Replay & Regression

## 9.1 Replay / Regression Matrix (30 cases)

| # | Replay case | Dataset window | Assertion | Priority |
|---|---|---|---|---|
| 1 | AAPL Q3 earnings beat | Finnhub fixture 2024-11-01 | thesis identifies `earnings_beat` → synthesis BUY | P0 |
| 2 | GME short squeeze | ApeWisdom fixture 2021-01-28 | retail dimension > 0.5, divergence non-zero | P0 |
| 3 | TSLA SEC investigation | News fixture with `sec_investigation` tag | antithesis wins, synthesis SHORT, disagreement>0.6 | P0 |
| 4 | NVDA 3× analyst upgrades | Finnhub multi-headline fixture | thesis catalysts ≥3 | P0 |
| 5 | Lawsuit + earnings beat mixed | 2 contradictory headlines | disagreement_score > 0.7 | P1 |
| 6 | Off-topic buyback in Apple feed | Qualcomm headline in AAPL feed | news_scorer relevance < 0.5 | P1 |
| 7 | Penny stock ($0.50) | yfinance fixture | PriceContext handles, no NaN | P1 |
| 8 | Zero 20-day volume | Polygon synthetic | vol_regime=NORMAL, no crash | P1 |
| 9 | Merger gap day (20%) | yfinance fixture | RSI/MACD robust, no stop triggered on gap | P0 |
| 10 | Recently IPO'd (15 days) | yfinance ipo fixture | insufficient bars → data_gaps ≥ 3 | P1 |
| 11 | Finnhub 30s delay | mock latency | pipeline latency < 120s SLA | P1 |
| 12 | Polygon 429 mid-batch | 3 tickers, TSLA fails | 2/3 complete, no cascading failure | P0 |
| 13 | FRED 1-day-stale data | mock prev-day response | regime still classified | P2 |
| 14 | Quiver endpoint down | mock fail | institutional.fetched_ok=False, agents adapt | P2 |
| 15 | Duplicate news headline | Finnhub duplicate | news_scorer dedupes by title hash | P1 |
| 16 | Quiver Form 4 duplicate refiling | 2 report periods | insider count not doubled | P2 |
| 17 | Batch with duplicate tickers | ["AAPL","AAPL","MSFT"] | 2 unique runs | P1 |
| 18 | Empty news feed | Finnhub returns [] | NewsContext empty, agents still produce output | P1 |
| 19 | Zero option strikes | illiquid ticker | OptionsContext all None, no crash | P1 |
| 20 | Clock skew 1h behind | mock clock | decay drift within tolerance | P2 |
| 21 | DST transition day | 2026-03-09 | no future-data leakage at TZ boundary | P0 |
| 22 | Weekend run (Saturday) | Sat 2026-04-05 | uses Friday Polygon data correctly | P1 |
| 23 | **[CRITICAL]** yfinance period ignores as_of_date | materialize("AAPL", "2024-01-01") with mock clock 2026 | **EXPECT FAIL**: yfinance returns 2025–2026 data | **P0** |
| 24 | **[CRITICAL]** FRED sort_order=desc ignores as_of_date | fetch FRED for 2024-06-01 | **EXPECT FAIL**: returns 2026 rate | **P0** |
| 25 | Sunday run uses Friday PriceContext | Sunday call | uses Friday close | P2 |
| 26 | FinalDecision golden snapshot | known-good run | diff against golden, ±1% float tol | P1 |
| 27 | LLM temperature=0 determinism gate | same briefing 2x | byte-identical thesis output | P1 |
| 28 | Prompt version bump replay | old snapshots + new prompt | capture drift, human approval to update golden | P2 |
| 29 | Cost regression (40 tickers) | canned LLM, T=0 | total cost ≈ $1.25 ± 5% | P1 |
| 30 | Budget alarm | $1 budget, 10 tickers | first 5 complete, rest raise BudgetExceededError | P0 |

## 9.2 Replay Dataset Layout

```
tests/replay/
├── fixtures/
│   ├── aapl_2024-11-01_earnings/
│   │   ├── briefing.json
│   │   ├── finnhub_news.json
│   │   ├── polygon_aggregates.json
│   │   ├── quiver_insiders.json
│   │   └── expected_decision.json    ← golden
│   ├── gme_2021-01-28_squeeze/
│   ├── tsla_sec_probe/
│   ├── nvda_consensus_upgrades/
│   ├── penny_stock_0_50/
│   ├── zero_volume_ticker/
│   ├── merger_gap_day/
│   ├── ipo_15_days/
│   ├── weekend_saturday/
│   └── dst_transition_2026-03-09/
├── test_replay_news_events.py
├── test_replay_source_delays.py
├── test_replay_backtest_live_parity.py    ← includes CRITICAL #23, #24
├── test_replay_edge_cases.py
├── test_golden_decision_snapshots.py
├── test_cost_regression.py
└── replay_helpers.py
```

## 9.3 Golden Snapshot Helper

```python
def assert_matches_golden(
    decision: FinalDecision,
    golden_path: str,
    tolerance_pct: float = 1.0,
    fields_to_ignore: set[str] | None = None,
) -> None:
    """Assert decision matches golden snapshot within tolerance.

    Ignores: timestamp, pipeline_latency_ms, model_versions.
    Numeric fields use tolerance_pct relative error.
    Raises AssertionError with unified diff on mismatch.
    """
```

## 9.4 Top 5 Must-Have Replay Cases Before Real Capital

1. **#23 — yfinance period look-ahead bias** — confirm or fix before any backtest
2. **#24 — FRED sort_order look-ahead bias** — confirm or fix
3. **#2 — GME short squeeze retail dimension** — validates social pipeline end-to-end
4. **#1 — AAPL earnings beat thesis** — validates news → thesis → synthesis
5. **#30 — Budget enforcement** — prevents runaway spend

---

# 10. Priority Fix Roadmap

## P0 — Must Fix Before Production / Real Capital

| # | Item | Why | Files | Tests | Effort |
|---|---|---|---|---|---|
| P0-1 | **yfinance look-ahead bias** — replace `.history(period="1y")` with Polygon range endpoint | Any backtest produces phantom P&L | `materializer.py:262-321` | Case #23 | 4h |
| P0-2 | **FRED as-of-date** — use `realtime_start/end` params | FRED currently returns latest regardless of date | `fred_macro.py:106-107` | Case #24 | 2h |
| P0-3 | **Prompt versioning** — `_PROMPT_VERSION` constant per agent | Decisions untraceable across prompt changes | all 4 agents | version in FinalDecision.model_versions | 3h |
| P0-4 | **Cost observability endpoint** — `GET /api/config/costs/today` | Session already hit credit depletion blind | `api/routes/config.py` | endpoint test | 2h |
| P0-5 | **Schema version bump on cache** | Stale entries deserialize wrong after field additions | `signals_cache._SCHEMA_VERSION` | purge-on-mismatch test | 1h |
| P0-6 | **Pin LLM temperature=0** | Non-determinism breaks replay | all `_call_anthropic` | determinism test | 1h |
| P0-7 | **`used_mock: bool` on FinalDecision + warning log** | Silent fallback contaminates synthesis | `schemas/v3.py` + all agents | test with unset key | 2h |
| P0-8 | **News scorer negation** | "fails to beat" matches `earnings_beat` | `news_scorer.py` | regex test with negation | 2h |
| P0-9 | **API key auth middleware** (if non-localhost deploy) | CORS=* + no auth = critical vulnerability | `api/main.py` | auth test | 3h |
| P0-10 | **Options signal hysteresis** — ±0.25 threshold or previous-state bias | BULL↔BEAR flip noise at ±0.15 | `runner.py`, `divergence.py` | signal stability test | 2h |

**P0 total: ~22 hours critical path** before any real capital deploy.

## P1 — Should Fix Soon

1. Alpha Vantage free-tier throttle too strict — document as opt-in
2. Delete `tradingagents/divergence/aggregator.py` — confirmed dead
3. Remove legacy `/api/analyze` stub — verify frontend doesn't call it
4. Register pytest markers in `pyproject.toml`
5. Frontend Vitest setup + 5 high-value tests (`indicators.ts`, `sortValue`, `formatRelativeTime`)
6. Trading calendar awareness — Sunday run returns Friday data silently
7. Polygon 429 circuit breaker — auto-switch to yfinance after 3 consecutive 429s in 60s
8. Golden FinalDecision snapshots for 10 tickers × 1 date + CI diff check
9. Config change audit log — append-only JSONL
10. Structured logging with correlation_id = analysis_id
11. Quiver deduplication on same-day refilings
12. Decision snapshot persistence (briefing + all 4 agent outputs)
13. Configuration snapshot / `config_hash` on FinalDecision
14. Error budget alarm — counter for mock_fallback incidents
15. Prompt recording — store exact prompts + responses per analysis_id
16. Missing risk rules — earnings blackout, FOMC buffer, halt detection, daily loss limit, options expiry rolldown
17. Determinism replay mode (`replay_mode=True` flag)

## P2 — Quality / Maintainability

1. Docstrings on all public API endpoints
2. Refactor materializer into sub-modules (price, options, news, social, macro, events, volatility, institutional, divergence)
3. Extract magic numbers to `config.py` constants (weights, thresholds)
4. Add MyPy to CI
5. Extract reusable `ApiHealthDot` component in Settings UI
6. Prometheus/StatsD metrics emitter
7. Docker Compose for reproducible dev
8. Backup + restore script for 3 SQLite stores
9. Consolidate duplicated options scoring (divergence + runner) into one helper
10. Remove in-memory L1 once L2 proves stable (simplification)
11. Event lineage tracking (`sources_used` per context)
12. Feature dump endpoint (`GET /api/v3/briefing/{ticker}/{date}`)
13. Source-level health history (uptime % per provider over 24h)
14. Rate-limit observability metrics per provider
15. OS keychain for API key storage (instead of SQLite plaintext)

---

# 11. Suggested File / Folder Refactor

## 11.1 Current Structural Problems

1. `tradingagents/data/` flat layout mixes materializer + 10 source modules + snapshot
2. `tradingagents/api/routes/` has 17 files, no namespacing for v1 vs v3
3. `tradingagents/agents/` has both v1 (analysts, managers, researchers, trader, risk_mgmt) and v3 (`v3/`)
4. `tradingagents/divergence/aggregator.py` is dead code alongside active `dimensions/`
5. `tradingagents/dataflows/connectors/` has 20 files, 16 unused
6. Frontend `components/{tabs,dashboard,terminal}/` has semantic blur (TopBar is layout, not tab)

## 11.2 Minimal Refactor Proposal

| From | To | Why | Risk |
|---|---|---|---|
| `tradingagents/agents/{analysts,managers,researchers,trader,risk_mgmt}/` | `tradingagents/agents/legacy/` | Clarifies v1 vs v3 generations | Import paths break; grep before move |
| `tradingagents/api/routes/{analysis,price,holdings,options,social}.py` (v1) | `tradingagents/api/routes/legacy/` | Distinguish v1 from v3 routes | Route registration needs update |
| `tradingagents/divergence/aggregator.py` | **DELETE** | Confirmed dead post-route rewrite | None |
| `tradingagents/dataflows/connectors/*.py` (16 unused) | `tradingagents/dataflows/connectors/legacy/` | Reduces audit surface | Import cleanup in tests |
| Frontend `components/{tabs,dashboard,terminal}/` | `components/{layout,panels,widgets,shared}/` | Clarifies semantic roles | TSX import paths, Vitest paths |

## 11.3 Refactor Risks & Mitigation

- **Python imports**: Pre-move `grep -r "from tradingagents.agents.analysts"` to map blast radius
- **Test paths**: Use IDE rename (PyCharm, VSCode refactor) to auto-update
- **PR discipline**: One domain per PR; pure renames with zero behavior changes
- **CI validation**: Ensure pytest still discovers tests after moves

---

# 12. Immediate Next Actions

## This Week (P0 Critical)

- [ ] Top up Anthropic credits (session depleted them; real BUY/SHORT signals blocked)
- [ ] (P0-6) Pin `temperature=0` in all 4 `_call_anthropic` calls
- [ ] (P0-7) Add `used_mock: bool` to FinalDecision + emit `logger.warning` on every fallback
- [ ] (P0-1) Fix yfinance look-ahead bias — Polygon vendor with explicit date ranges
- [ ] (P0-2) Fix FRED as-of-date with `realtime_start/end`
- [ ] (P0-4) Add `GET /api/config/costs/today` + Settings UI widget
- [ ] (P0-5) Bump `signals_cache._SCHEMA_VERSION` + purge logic
- [ ] (P0-3) Add `_PROMPT_VERSION` constants to each agent + thread into `model_versions`
- [ ] (P0-9) API key auth middleware if any non-localhost deploy planned
- [ ] Delete `tradingagents/divergence/aggregator.py` (confirmed dead)

## Next Week (P1 High-Value)

- [ ] Golden FinalDecision snapshots for 10 tickers × 1 date + CI diff gate
- [ ] Polygon 429 circuit breaker — auto-fallback after 3 consecutive 429s
- [ ] News scorer negation lookbehind patterns
- [ ] Register pytest markers in `pyproject.toml`
- [ ] Structured logging with `correlation_id = analysis_id`
- [ ] Remove legacy `/api/analyze` route (verify frontend untouched)
- [ ] Frontend Vitest setup + 5 tests
- [ ] Options signal hysteresis to ±0.25
- [ ] Missing risk rules: earnings blackout, daily loss limit, halt detection
- [ ] Decision snapshot persistence endpoint

## Before Next Release

- [ ] Replay test suite for 6 historical event fixtures + parity check
- [ ] Prompt versioning required in every FinalDecision
- [ ] Cost alerting (daily burn threshold)
- [ ] Prometheus/StatsD metrics for cost, latency, rate limits, mock fallback rate
- [ ] Runbook docs for top 10 production failures
- [ ] Backup + restore script + DR test for 3 SQLite stores
- [ ] Docker Compose for reproducible dev env
- [ ] One-click smoke test script (`scripts/smoke_test.py`)

---

# 13. Quant-Specific Risk Deep Dive

| # | Risk | Verdict | Severity | Priority |
|---|---|---|---|---|
| 13.1 | Data time alignment errors across contexts | Partial | High | **P0** |
| 13.2 | **Look-ahead bias / future leakage** | **Yes** (multiple vectors) | **Critical** | **P0** |
| 13.3 | Survivorship bias in screener universe | Yes | High | P1 |
| 13.4 | Timezone / trading calendar errors | Partial | Medium | P1 |
| 13.5 | Dirty / duplicate / missing data propagation | Partial | Medium | P1 |
| 13.6 | Schema semantic inconsistency across sources | Partial | Low | P2 |
| 13.7 | Sentiment generation vs execution delay | Partial | Medium | P2 |
| 13.8 | Strategy signal vs execution signal mixing | No | — | Green ✓ |
| 13.9 | Agent state machine inconsistency | Partial | Low | P2 |
| 13.10 | **Backtest / live logic divergence** | **Yes** (materializer shared) | **Critical** | **P0** |
| 13.11 | Missing / bypassed risk rules | Partial | High | P1 |
| 13.12 | Config switch behavior drift | Yes | Medium | P2 |
| 13.13 | Cache pollution | Partial | Low | P2 |
| 13.14 | Concurrency / async ordering | Partial | Medium | P2 |
| 13.15 | Retry / idempotency (double cost-charging) | Partial | Low | P2 |

## 13.Top-5 Immediate Concerns (capital-impact ordered)

1. **Look-ahead bias (13.2 + 13.10)** — P0 — Any backtest using this system today produces phantom P&L because yfinance/social/options/news sources all pull live data. Fix requires `backtest_mode=True` flag + Polygon-only vendor routing.
2. **Data time alignment (13.1)** — P0 — TickerBriefing looks coherent but is a Frankenstein: price is live, FRED respects date, social is live. Must add explicit `timestamp` per context + validate in materializer.
3. **Missing earnings / ex-dividend blackout (13.11)** — P1 — System can trade through earnings (gap risk) and short on ex-dividend (dividend forfeiture). Add hard stops in `deterministic.py`.
4. **No daily loss limit (13.11)** — P1 — Bad day → >5% loss before system halts. Implement 2%-of-NAV daily circuit breaker.
5. **Double-counted LLM costs on retry (13.9, 13.15)** — P2 — Cost tracking overstates spend; misleads budget management.

## 13.2 Evidence for Critical Look-Ahead Bias

| Source | Code path | Leakage |
|---|---|---|
| yfinance price | `materializer.py:314` `ticker_obj.history(period="1y")` | Uses wall-clock now, not `date` param |
| FRED | `fred_macro.py:105-107` `sort_order=desc&limit=1` | Returns latest observation, ignoring `observation_end` filter |
| yfinance news | `materializer.py:739` `ticker_obj.news` | Returns latest headlines at fetch time |
| Fear & Greed | `social_sentiment.py` | CNN endpoint returns current index only |
| ApeWisdom | `social_sentiment.py` | WSB rank is snapshot at fetch time |
| Quiver 30d/90d | `quiver_institutional.py` | Windows relative to call time, not `date` |
| yfinance options | `materializer.py:282-314` | `ticker_obj.options` returns nearest expiry from today |
| Screener universe | `volatility_screener.py` `_KNOWN_ETFS` | Hardcoded to 2026 ETF list |

**Mitigation plan**:
1. Add `backtest_mode: bool` to `RuntimeConfig`
2. When True:
   - Force `data_vendor_price="polygon"` (only vendor with date anchoring)
   - Pass explicit `start/end` dates to Polygon
   - Disable social sentiment (no historical API)
   - Use Finnhub with explicit date range if possible
   - Skip Quiver (no historical query)
   - Use FRED `realtime_end=date`
   - Pin LLM `temperature=0`
   - Set `random.seed(hash(ticker + date) % 2**32)`
3. Refuse to run analyses with `date < today - 2 days` unless `backtest_mode=True`

---

## Appendix: Section produced by sub-agent

This document was produced by 10 parallel sub-agents dispatched by the main agent. Each sub-agent was read-only (Explore type) and targeted a specific phase of the master prompt. No code was modified during the audit. All findings reference concrete file paths and line numbers verified against the repository state as of 2026-04-05.

| Section | Sub-agent |
|---|---|
| §1 Repository Map | Phase 0 Explorer |
| §2 Runtime Dataflow | Phase 1 Explorer |
| §3 Debug Playbook | Phase 2AB Explorer |
| §4 Debug Instrumentation Gaps | Phase 2C Explorer |
| §5 Architecture + Data Audit | Phase 3-I Explorer |
| §6 Model/Signal + Agent Audit | Phase 3-II Explorer |
| §7 Testing + Operational Audit | Phase 3-III Explorer |
| §8 Unit + Integration Test Matrix | Phase 4-I Explorer |
| §9 Replay + Regression Matrix | Phase 4-II Explorer |
| §10, §11, §12 Roadmap + Refactor + Next Actions | Phase 5 Explorer |
| §13 Quant-Specific Risk Deep Dive | Quant Risk Explorer |

**Document length**: ~680 lines of actionable markdown.
**Estimated read time**: 30 minutes.
**Estimated P0 fix critical path**: ~22 engineering hours.
