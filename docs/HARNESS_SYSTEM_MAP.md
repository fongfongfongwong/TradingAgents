# HARNESS SYSTEM MAP

> Generated: 2026-04-07 | Harness Agent

## Routes / Pages

| Route | Page/Component | Purpose | Trading Relevance |
|-------|---------------|---------|-------------------|
| `/` | `page.tsx` DashboardPage | Main dashboard: signal table, divergence, news, pipeline, inspector | **CRITICAL** |
| `/` tab: Inspector | `InspectorCard.tsx` | Per-ticker thesis/antithesis/synthesis detail | HIGH |
| `/` tab: Chart | `ChartTab.tsx` | OHLCV candles + RSI/MACD/Signals/TP/SL | HIGH |
| `/` tab: Options | `OptionsTab.tsx` | Options chain (IV, greeks) | MED |
| `/` tab: Debate Full | `AnalysisTab.tsx` | Full v3 pipeline with SSE | HIGH |
| `/` tab: Backtest | `BacktestTab.tsx` | Historical strategy backtest | HIGH |
| `/` tab: Settings | `SettingsTab.tsx` | Runtime config (LLM, vendors, budget) | HIGH |
| `/` tab: Sources | `DataSourcesTab.tsx` | Data source health dashboard | MED |

## Critical Frontend Modules

| File | Purpose | Risk |
|------|---------|------|
| `app/page.tsx` | Main dashboard (1300+ lines) — most buttons | **CRITICAL** |
| `dashboard/SignalTable.tsx` | Signal table: 39 tickers, PX, Δ%, RV, PRED, SIG | **CRITICAL** |
| `dashboard/TopBar.tsx` | Market overview indices | HIGH |
| `dashboard/TradeTopBar.tsx` | Trade window/cycle status | HIGH |
| `lib/api.ts` | All API client functions + interfaces | **CRITICAL** |
| `lib/indicators.ts` | RSI, MACD, Bollinger, ATR, Keltner, TP/SL | HIGH |
| `stores/signalsStore.ts` | Zustand state for signals | HIGH |
| `hooks/useUniverseRerank.ts` | Polls universe every 60s | HIGH |
| `hooks/useAutoRefresh.ts` | Auto-refresh timer | MED |

## Backend API Routes (Trading-Critical)

| Route | File | Purpose |
|-------|------|---------|
| `GET /api/v3/signals/batch` | `signals_v3.py` | Batch signal generation (LLM pipeline) |
| `POST /api/v3/signals/batch/start` | `signals_v3.py` | Async batch + SSE (Run All) |
| `GET /api/v3/prices/snapshot` | `realtime_prices.py` | Real-time prices (Databento/yfinance) |
| `GET /api/price/{ticker}` | `price.py` | Historical OHLCV for charts |
| `GET /api/v3/rv/forecast/{ticker}` | `rv_forecast.py` | HAR-RV volatility forecast |
| `GET /api/v3/universe/top-volatile` | `universe.py` | Dynamic universe ranking |
| `GET /api/v3/sources/status` | `sources.py` | Data source health probes |
| `GET /api/divergence/{ticker}` | `divergence.py` | Multi-factor divergence |
| `GET /api/v3/news/{ticker}/scored` | `news_v3.py` | LLM-scored news |
| `PUT /api/config/runtime` | `config.py` | Runtime config changes |

## Data Sources

| Source | Connector | Feeds |
|--------|----------|-------|
| yfinance | `yfinance_connector.py` | OHLCV, fundamentals, news |
| Databento | `databento_connector.py` | Real-time OHLCV (1s/1m) |
| Finnhub | `finnhub_connector.py` | News, sentiment |
| FRED | `fred_connector.py` | Macro |
| SEC EDGAR | `sec_edgar_connector.py` | Filings |
| CBOE | `cboe_connector.py` | Options |
| Anthropic | `llm_clients/` | LLM agents |

## Browser-Verifiable Surfaces

| Surface | Validations Needed |
|---------|-------------------|
| Signal table (39 rows) | All columns populated, sort works, presets filter |
| PX / Δ% columns | Prices match market, correct sign |
| Deep Debate button | SSE progress, signals update, cost tracked |
| Chart + indicators | Candles render, RSI/MACD correct, TP/SL reasonable |
| News expand | Click expands rationale, link works |
| Source chips | Green=OK, red=down, latency shown |
| Settings tab | Changes persist, affect signals |
| Auto-refresh | Timer counts down, re-fetches |
