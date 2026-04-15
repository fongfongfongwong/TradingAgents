# BUG BACKLOG

> Updated: 2026-04-07 by Harness Agent

---

## [Severity: Critical] Infinite re-render loop in fetchSignals

- **title**: Maximum update depth exceeded — fetchSignals infinite loop
- **page/route**: `/` (DashboardPage)
- **component/file**: `hooks/useUniverseRerank.ts:93`, `app/page.tsx:406-417`
- **reproduction**: Load page → console floods with "Maximum update depth exceeded"
- **expected**: fetchSignals fires once on mount + when tickers change
- **actual**: Fires infinitely every render frame, 460+ errors in console
- **root cause**: `allTickers = [...equityTickers, ...etfTickers]` creates a new array reference on every render. `fetchSignals` depends on `allTickers` via `useCallback`, which recreates on every render. `useEffect(() => fetchSignals(), [fetchSignals])` fires every render → infinite loop.
- **fix**: Wrap `allTickers` in `useMemo(() => [...eq, ...etf], [eq, etf])` ✅ FIXED
- **regression**: Verify no "Maximum update depth" errors in console after page load. Verify signals still fetch correctly when universe changes.
- **status**: FIXED

---

## [Severity: High] PX and Δ% columns show "—" for cached signals

- **title**: Price columns empty for L1/L2 cached signal items
- **page/route**: `/` (SignalTable)
- **component/file**: `dashboard/SignalTable.tsx:486-494`, `api/routes/signals_v3.py`
- **reproduction**: Load page with existing cached signals → PX/Δ% show em-dash
- **expected**: PX shows last price, Δ% shows daily change with color
- **actual**: Shows "—" because cached items were built before `_enrich_prices()` was added
- **root cause**: L1 cache (5min) and L2 cache (24h) contain items without `last_price`/`change_pct` fields. Enrichment only runs post-pipeline, not on cache hits.
- **fix**: Either (a) enrich cached items too, or (b) force a full re-run to populate cache, or (c) fetch prices separately on the frontend via `/api/v3/prices/snapshot`
- **regression**: After cache expiry or forced run, verify PX/Δ% columns show data
- **status**: OPEN — needs architectural decision

---

## [Severity: High] yfinance probe fails without start_date/end_date

- **title**: yfinance health probe crashes on missing date params
- **page/route**: Sources panel, `/api/v3/sources/status`
- **component/file**: `dataflows/connectors/yfinance_connector.py:77-85`
- **reproduction**: Backend starts → probe engine calls `fetch("AAPL", {"data_type": "ohlcv"})` → raises ConnectorError
- **expected**: Probe succeeds with a lightweight check
- **actual**: `ConnectorError: ohlcv requires 'start_date' and 'end_date'`
- **root cause**: `_fetch_ohlcv` required date params but probe doesn't pass them
- **fix**: Added fallback: when dates missing, use `yf.download(period="5d")` for a quick check ✅ FIXED
- **regression**: `GET /api/v3/sources/yfinance/probe` returns `status=ok`
- **status**: FIXED

---

## [Severity: Medium] Databento API key not loaded from .env

- **title**: DATABENTO_API_KEY not in environment at startup
- **page/route**: Sources panel
- **component/file**: `dataflows/connectors/databento_connector.py`, `api/main.py`
- **reproduction**: Start backend without sourcing .env → databento probe fails
- **expected**: API key loaded from .env automatically
- **actual**: Backend doesn't call `load_dotenv()` — relies on api_key_store
- **root cause**: No `load_dotenv()` in startup path; key only exists in .env file
- **fix**: Start backend with `set -a && source .env && set +a` prefix ✅ WORKAROUND
- **regression**: Verify databento source shows OK in sources panel
- **status**: WORKAROUND (should add load_dotenv to main.py lifespan)

---

## [Severity: Medium] stockstats package missing from venv

- **title**: yfinance connector fails — ModuleNotFoundError: stockstats
- **page/route**: Backend startup
- **component/file**: `dataflows/stockstats_utils.py`
- **reproduction**: Fresh backend start → yfinance probe → "No module named 'stockstats'"
- **expected**: All dependencies installed
- **actual**: stockstats not in requirements
- **fix**: `pip install stockstats` ✅ FIXED
- **regression**: Verify yfinance probe succeeds
- **status**: FIXED

---

## [Severity: Low] Console error spam from network failures during reload

- **title**: ERR_ABORTED errors flood console during page reload
- **page/route**: `/` (all API calls)
- **component/file**: `lib/api.ts:52`
- **reproduction**: Reload page → in-flight requests get aborted → logged as errors
- **expected**: Aborted requests should be silently ignored
- **actual**: Logs "Failed to fetch batch signals: TypeError: Failed to fetch"
- **root cause**: `request()` catches all errors and logs them; doesn't distinguish AbortError
- **fix**: Check for `AbortError` or `err.name === 'AbortError'` before logging
- **regression**: Verify no error spam after page reload
- **status**: OPEN
