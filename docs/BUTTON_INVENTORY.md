# BUTTON INVENTORY

> Updated: 2026-04-07 by Harness Button Audit Agent

## Summary

- **Total buttons/controls found**: 40+
- **WIRED (API calls)**: 15
- **PARTIAL (local state only)**: 18
- **DEAD (handler missing)**: 2
- **UNKNOWN**: 5

## Main Dashboard (page.tsx)

| # | Section | Element | Label | Handler | API | Trading Relevance | Status |
|---|---------|---------|-------|---------|-----|-------------------|--------|
| 1 | TopBar | button | Fast (F) | `fetchSignals` | `GET /api/v3/signals/batch` | MED | WIRED |
| 2 | TopBar | button | Deep Debate (Cmd+R) | `handleRunAll` | `POST /api/v3/signals/batch/start` | **HIGH** | WIRED |
| 3 | TopBar | button | Auto 30:00 | toggle auto-refresh | local state | MED | PARTIAL |
| 4 | TopBar | select | 5/15/30/60 min | `setAutoRefreshInterval` | local state | LOW | PARTIAL |
| 5 | TopBar | button | Palette (Cmd+K) | `setPaletteOpen` | local state | LOW | PARTIAL |
| 6 | Universe | button | All 39 | `setSegment("all")` | local state | LOW | PARTIAL |
| 7 | Universe | button | Equity | `setSegment("equity")` | local state | LOW | PARTIAL |
| 8 | Universe | button | ETF | `setSegment("etf")` | local state | LOW | PARTIAL |
| 9 | Universe | select | rank by dropdown | `setSortKey` | local state | LOW | PARTIAL |
| 10 | Presets | button | LONGS | `togglePreset` | local state | MED | PARTIAL |
| 11 | Presets | button | SHORTS | `togglePreset` | local state | MED | PARTIAL |
| 12 | Presets | button | HOLD | `togglePreset` | local state | MED | PARTIAL |
| 13 | Presets | button | HIGH CONV >=75 | `togglePreset` | local state | MED | PARTIAL |
| 14 | Presets | button | FLIPPED | `togglePreset` | local state | MED | PARTIAL |
| 15 | Presets | button | AGENT DISAGREE >0.5 | `togglePreset` | local state | MED | PARTIAL |
| 16 | Presets | button | DATA FRESH <30s | `togglePreset` | local state | MED | PARTIAL |
| 17 | Divergence | button | Retry | `fetchDivergence` | `GET /api/divergence/{ticker}` | HIGH | WIRED |
| 18 | News | div.news-row | (click to expand) | `setExpandedNews` | local state | LOW | PARTIAL |
| 19 | News | a | Read article | external link | N/A | LOW | EXTERNAL |
| 20 | Palette | div | ticker item | `setTicker` | local state | MED | PARTIAL |

## Signal Table (SignalTable.tsx)

| # | Section | Element | Label | Handler | API | Trading Relevance | Status |
|---|---------|---------|-------|---------|-----|-------------------|--------|
| 21 | Header | button | Refresh | `fetchBatch` | `GET /api/v3/signals/batch` | MED | WIRED |
| 22 | Header | button | Run All | `handleRunAll` | `POST /api/v3/signals/batch/start` | **HIGH** | WIRED |
| 23 | Header | th | column headers | `handleSort` | local state | LOW | PARTIAL |
| 24 | Body | tr | row click | `handleRowClick` | local state (setTicker) | MED | PARTIAL |
| 25 | Row | button | Rerun | `onRerun` | single ticker signal | MED | UNKNOWN |
| 26 | Row | button | Pin | `onPin` | local state | LOW | PARTIAL |
| 27 | Row | button | Copy | `onCopy` | clipboard API | LOW | PARTIAL |

## Tab Bar

| # | Section | Element | Label | Handler | API | Trading Relevance | Status |
|---|---------|---------|-------|---------|-----|-------------------|--------|
| 28 | Tab bar | button | Inspector (Cmd+1) | `setActiveTab` | local state | LOW | PARTIAL |
| 29 | Tab bar | button | Chart (Cmd+2) | `setActiveTab` | local state | LOW | PARTIAL |
| 30 | Tab bar | button | Options (Cmd+3) | `setActiveTab` | local state | LOW | PARTIAL |
| 31 | Tab bar | button | Debate Full (Cmd+4) | `setActiveTab` | local state | LOW | PARTIAL |
| 32 | Tab bar | button | Backtest (Cmd+5) | `setActiveTab` | local state | LOW | PARTIAL |
| 33 | Tab bar | button | Settings (Cmd+6) | `setActiveTab` | local state | LOW | PARTIAL |
| 34 | Tab bar | button | Sources (Cmd+7) | `setActiveTab` | local state | LOW | PARTIAL |

## Settings Tab

| # | Section | Element | Label | Handler | API | Trading Relevance | Status |
|---|---------|---------|-------|---------|-----|-------------------|--------|
| 35 | API Keys | button | Save API Keys | `handleSave` | `PUT /api/config/api-keys` | **CRITICAL** | WIRED |
| 36 | API Keys | button | Test Keys | `runHealthCheck` | `POST /api/config/test-keys` | HIGH | WIRED |
| 37 | Runtime | form | Save config | `handleRuntimeSave` | `PUT /api/config/runtime` | HIGH | WIRED |
| 38 | Costs | button | Refresh | `refreshCosts` | `GET /api/config/costs/today` | MED | WIRED |

## Chart Tab

| # | Section | Element | Label | Handler | API | Trading Relevance | Status |
|---|---------|---------|-------|---------|-----|-------------------|--------|
| 39 | Header | button | RSI toggle | `setShowRsi` | local state | LOW | PARTIAL |
| 40 | Header | button | MACD toggle | `setShowMacd` | local state | LOW | PARTIAL |
| 41 | Header | button | SIGNALS toggle | `setShowSignals` | local state | LOW | PARTIAL |
| 42 | Header | button | 1MO-5Y range | `setRange` | `GET /api/price/{ticker}` | LOW | WIRED |

## Sources Tab

| # | Section | Element | Label | Handler | API | Trading Relevance | Status |
|---|---------|---------|-------|---------|-----|-------------------|--------|
| 43 | Per-source | button | Re-probe | `onProbe` | `POST /api/v3/sources/{name}/probe` | HIGH | WIRED |

## DEAD BUTTONS (No Handler)

| # | Location | Element | Issue |
|---|----------|---------|-------|
| D1 | TradeTopBar:354 | "Refresh" button | onClick handler missing |
| D2 | TradeTopBar:366 | "Deep Debate" button | onClick handler missing |

## DOUBLE-CLICK HAZARDS

| Button | Risk | Mitigation Needed |
|--------|------|-------------------|
| Run All / Deep Debate | Triggers full LLM pipeline ($$$) | Add loading state + debounce |
| Save API Keys | Double-submit to backend | Form submit prevents multi-click |
| Test Keys | Spams upstream APIs | Add rate-limit / cooldown |
