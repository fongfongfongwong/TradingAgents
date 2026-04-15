# DATA CONNECTION MATRIX

> Updated: 2026-04-07 by Harness Data Connection Agent

## Critical Data Flows

| # | UI Action | Frontend Handler | API Endpoint | Backend Service | Data Source | Algo/Output | Validation | Priority |
|---|-----------|-----------------|--------------|-----------------|-------------|-------------|------------|----------|
| 1 | Page load (auto) | `useUniverseRerank` | `GET /api/v3/universe` | `universe.py` | yfinance batch OHLC | HAR-RV ranking | Universe loads 39 tickers | **CRITICAL** |
| 2 | Page load (auto) | `fetchSignals` | `GET /api/v3/signals/batch?tickers=...` | `signals_v3.py` | L1 cache (5min) > L2 (24h) > pipeline | LLM thesis/antithesis/synthesis | 39 rows with signal/conviction | **CRITICAL** |
| 3 | Deep Debate click | `handleRunAll` | `POST /api/v3/signals/batch/start` | `signals_v3.py` | Full v3 pipeline (LLM) | All agents run fresh | SSE progress stream works | **CRITICAL** |
| 4 | SSE progress | `EventSource` | `GET /api/v3/signals/batch/{id}/stream` | `signals_v3.py` | Server-sent events | Real-time ticker updates | Modal shows progress | **HIGH** |
| 5 | Page load (auto) | `fetchDivergence` | `GET /api/divergence/{ticker}` | `divergence.py` | Multi-factor z-scores | Composite divergence score | Score + dimensions shown | HIGH |
| 6 | Page load (auto) | `getScoredNews` | `GET /api/v3/news/{ticker}/scored` | `news_v3.py` | Finnhub + yfinance | LLM scoring | 10 ranked items | HIGH |
| 7 | Chart tab (auto) | `getPriceData` | `GET /api/price/{ticker}?range=6mo` | `price.py` | yfinance | Client-side RSI/MACD/BB/ATR | Candles + indicators | HIGH |
| 8 | Chart tab (auto) | `getRVForecast` | `GET /api/v3/rv/forecast/{ticker}` | `rv_forecast.py` | yfinance history | HAR-RV Ridge model | Pred 1d/5d in header | HIGH |
| 9 | Sources panel (auto) | `getSourcesStatus` | `GET /api/v3/sources/status` | `sources.py` | Probe engine | Health scoring | Green/red chips | MED |
| 10 | Settings save | `handleRuntimeSave` | `PUT /api/config/runtime` | `config.py` | Runtime config | Affects all future signals | Config persists to disk | HIGH |
| 11 | Price snapshot | `_enrich_prices` | `GET /api/v3/prices/snapshot` | `realtime_prices.py` | Databento > yfinance | last_price + change_pct | PX/Δ% columns (when not cached) | HIGH |
| 12 | Market overview (auto) | TopBar poll | `GET /api/market/overview` | `market.py` | yfinance indices | SPY, QQQ, VIX display | Index prices + changes | MED |

## Data Freshness

| Data | Source | Cache TTL | Stale Risk |
|------|--------|-----------|------------|
| Signals | LLM pipeline | L1: 5min, L2: 24h | **HIGH** — old signals may not reflect market moves |
| Prices (PX/Δ%) | Databento live / yfinance | 30s (yfinance fallback) | MED — can be 30s stale |
| Universe ranking | yfinance batch | 60s | LOW — updates every minute |
| News scores | Finnhub + LLM | On-demand | MED — may miss breaking news |
| RV forecast | HAR-RV model | 1h | LOW — model doesn't change fast |
| Source health | Probe engine | 60s | LOW |
| Market indices | yfinance | 60s poll | MED — delayed if market moving fast |

## Known Data Connection Issues

| Issue | Flow | Impact | Status |
|-------|------|--------|--------|
| Cached signals lack price data | Flow #2 | PX/Δ% show "—" | OPEN |
| yfinance probe needed date params | Flow #9 | Source showed "down" | FIXED |
| Databento key not auto-loaded | Flow #11 | Databento probe failed | WORKAROUND |
| No `load_dotenv()` in backend | All flows | Env vars not loaded | WORKAROUND |
