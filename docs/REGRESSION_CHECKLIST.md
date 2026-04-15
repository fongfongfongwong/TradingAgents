# REGRESSION CHECKLIST

> Updated: 2026-04-07 by Harness Agent

## After Every Code Change

- [ ] Frontend compiles without errors (`Ready in Xs`)
- [ ] No "Maximum update depth exceeded" in console
- [ ] Backend health check passes (`GET /health` → `status: ok`)
- [ ] Signal table loads 39 tickers with data
- [ ] Sort by PRED 1D works correctly
- [ ] Preset filters (LONGS, SHORTS, HOLD) show correct counts

## After Data Source Changes

- [ ] `GET /api/v3/sources/status` — all critical sources show `status: ok`
- [ ] yfinance probe succeeds (score >= 70)
- [ ] databento probe succeeds (score >= 70)
- [ ] finnhub, fred, sec_edgar all healthy

## After Price Enrichment Changes

- [ ] `GET /api/v3/prices/snapshot?tickers=AAPL` returns `last` and `change_pct`
- [ ] Forced signal run (`force=1`) returns `last_price` and `change_pct` in response
- [ ] PX column shows dollar values (not "—")
- [ ] Δ% column shows colored percentage (green positive, red negative)

## After Indicator Changes

- [ ] Chart tab renders candlesticks
- [ ] RSI panel shows 14-period RSI with 70/30 lines
- [ ] MACD panel shows histogram + signal line
- [ ] Signal markers (GC/DC) appear on chart
- [ ] TP/SL header row shows on XL viewport

## After News Changes

- [ ] News panel loads scored headlines
- [ ] Clicking news row expands to show rationale
- [ ] Clicking again collapses
- [ ] "Read article" link opens in new tab
