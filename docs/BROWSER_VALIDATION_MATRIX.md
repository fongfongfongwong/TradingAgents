# BROWSER VALIDATION MATRIX

**Date**: 2026-04-07 | **Agent**: Harness Browser Validation

## Signal Table — Main Dashboard

| Surface | Precondition | Action | Expected | Observed | Mismatch | Severity |
|---------|-------------|--------|----------|----------|----------|----------|
| Signal table load | Backend running, 39 tickers | Page load | All 39 rows with data | 39 rows loaded, RV20/PRED/ΔPRED/SIG/CONV all populated | None | OK |
| PX column | Cached signals | Page load | Last price shown | Shows "—" for all tickers | **YES** — cached items lack `last_price` | HIGH |
| Δ% column | Cached signals | Page load | Daily change % | Shows "—" for all tickers | **YES** — cached items lack `change_pct` | HIGH |
| PX column | Forced signal (AAPL) | `force=1` API call | Price shown | `last_price=246.11` returned correctly | None (verified via API) | OK |
| ΔPRED column | All tickers | Page load | Forecast delta shown | Values like -1.0, -2.8, -16.1 shown correctly | None | OK |
| Sort by PRED 1D | Click PRED 1D header | Table sorts descending | Rows reorder by predicted vol | Confirmed working | None | OK |
| Preset: SHORTS | Click SHORTS button | Filter to SHORT signals only | Shows only SHORT tickers | Shows (2) SHORT tickers | None | OK |
| Preset: HOLD | Click HOLD button | Filter to HOLD signals only | Shows 36-37 HOLD tickers | Shows (36) HOLD tickers | None | OK |

## Sources Panel

| Surface | Precondition | Action | Expected | Observed | Mismatch | Severity |
|---------|-------------|--------|----------|----------|----------|----------|
| yfinance chip | Backend probed | Page load | Green dot, latency shown | Green, "1468ms" | None (FIXED) | OK |
| databento chip | Backend probed | Page load | Green dot, latency shown | Green, "2615ms" | None (NEW) | OK |
| finnhub chip | Backend probed | Page load | Green dot | Green, "37s" | None | OK |
| finbert chip | No model loaded | Page load | Status indicator | Red, "down" | Expected — no local model | LOW |

## News Panel

| Surface | Precondition | Action | Expected | Observed | Mismatch | Severity |
|---------|-------------|--------|----------|----------|----------|----------|
| News load | AAPL selected | Page load | Scored headlines shown | 10 items, composite ranked | None | OK |
| News expand | Click news row | Row expands | Rationale, impact, tags, link | **NOT TESTED YET** — need to click | TBD | TBD |
| Source badge | News items | Visual check | Source tier shown (T1/T2/T3) | Badges shown correctly | None | OK |

## Chart Tab

| Surface | Precondition | Action | Expected | Observed | Mismatch | Severity |
|---------|-------------|--------|----------|----------|----------|----------|
| Candlestick chart | AAPL selected, Chart tab | Click Chart tab | OHLCV candles + RSI + MACD | **NOT TESTED YET** | TBD | TBD |
| TP/SL header | Chart tab with bars | View header | ATR, Signal, TP, SL, R:R shown | **NOT TESTED YET** | TBD | TBD |

## Settings Tab

| Surface | Precondition | Action | Expected | Observed | Mismatch | Severity |
|---------|-------------|--------|----------|----------|----------|----------|
| Settings load | Click Settings tab | Page renders | Config form with LLM/vendor/budget | Confirmed rendering | None | OK |
| LLM spend | Backend running | View spend section | Today's spend shown | "$0.00 of $50.00 (0.0%)" | None | OK |

## Console Errors

| Check | Expected | Observed | Severity |
|-------|----------|----------|----------|
| "Maximum update depth" | None | **460+ errors before fix, 0 after fix** | CRITICAL → FIXED |
| "Failed to fetch" | None during normal load | Appears when backend restarts or during reload | MEDIUM |
| React warnings | None | None observed | OK |
| TypeScript compile errors | None | None — "Ready in 3.1s" | OK |
