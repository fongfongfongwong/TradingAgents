# TRADING OUTPUT AUDIT

> Updated: 2026-04-07 by Harness Trading Output Agent

## Summary

18 trading-related values audited across frontend. No look-ahead bias found. Key concerns: price staleness, conviction range validation, cache desync.

---

## Findings

### Finding 1: PX (Last Price) — Stale by 5-30min

- **page**: Signal table
- **component**: `SignalTable.tsx:487`
- **field**: `last_price`
- **source**: `_enrich_prices()` in `signals_v3.py` → Databento cache / yfinance `fast_info`
- **timestamp behavior**: Set at pipeline assembly time, NOT continuously refreshed
- **issue**: Price can be 5-30 minutes stale during market hours
- **trading risk**: Users may act on outdated prices
- **validation**: Null-safe (shows "—"), no range check
- **severity**: HIGH

### Finding 2: Δ% (Change %) — Follows PX staleness

- **page**: Signal table
- **component**: `SignalTable.tsx:491-509`
- **field**: `change_pct`
- **source**: Same as PX (snapshot at pipeline time)
- **timestamp behavior**: Snapshot, not live
- **issue**: Same staleness as PX; color coding correct (green +, red −)
- **trading risk**: Stale intraday change misleading
- **severity**: HIGH

### Finding 3: ΔPRED — Cache desync risk

- **page**: Signal table
- **component**: `SignalTable.tsx:531-549`
- **field**: `rv_forecast_delta_pct`
- **source**: `predicted_rv_1d_pct - realized_vol_20d_pct`
- **timestamp behavior**: Both cached independently (1h TTL each)
- **issue**: Forecast and RV20 may be from different time snapshots
- **trading risk**: Misleading delta if one component refreshed but not the other
- **severity**: MEDIUM

### Finding 4: Conviction — No range clamping in backend

- **page**: Signal table
- **component**: `SignalTable.tsx:570-587`
- **field**: `conviction` (0-100)
- **source**: `int(decision.conviction)` from FinalDecision
- **issue**: Backend doesn't clamp; could theoretically be negative
- **trading risk**: Negative conviction would display incorrectly
- **validation**: Frontend clamps to [0,100] at display (line 577)
- **severity**: LOW

### Finding 5: EV% — No bounds clamping

- **page**: Signal table
- **component**: `SignalTable.tsx:589-603`
- **field**: `expected_value_pct`
- **source**: Synthesis stage
- **issue**: Raw value with no bounds; could show −200% or +500%
- **trading risk**: Extreme EV% may mislead position sizing
- **severity**: MEDIUM

### Finding 6: TP/SL — ATR multipliers reasonable but undocumented

- **page**: Chart tab header
- **component**: `ChartTab.tsx` + `indicators.ts:338-413`
- **field**: takeProfit, stopLoss
- **source**: Client-side computation: ATR × 2.0 (TP) / ATR × 1.5 (SL)
- **timestamp behavior**: Computed from fetched bars each time
- **issue**: Multipliers hardcoded, not configurable; R:R ratio fixed at 1.33
- **trading risk**: One-size-fits-all TP/SL may not suit all vol regimes
- **look-ahead risk**: NONE
- **severity**: LOW

### Finding 7: Options Impact mislabeled as "IVR"

- **page**: Signal table
- **component**: `SignalTable.tsx:552`
- **field**: `options_impact` displayed as "IVR"
- **source**: Second-dimension briefing
- **issue**: UI header says "OPT" with tooltip "IV Rank" but field is `options_impact` (0-100), not true IV Rank
- **trading risk**: Users may conflate with actual IV Rank percentile
- **severity**: LOW

### Finding 8: FRESH chip — Misleading metric

- **page**: Signal table
- **component**: `signalDiff.ts`
- **field**: Pipeline latency as "freshness"
- **source**: `pipeline_latency_ms`
- **issue**: Shows pipeline execution time, NOT data age. A fast pipeline on stale cache data still shows "green"
- **trading risk**: False sense of data freshness
- **severity**: MEDIUM

### Finding 9: News impact_score — 4h decay aggressive

- **page**: News panel
- **component**: `page.tsx:1193-1238`
- **field**: `impact_score`
- **source**: Deterministic scorer: `relevance × confidence × direction × decay(4h)`
- **issue**: 4-hour half-life means headlines >16h old show <10% impact
- **trading risk**: Overnight/weekend news may be underweighted
- **look-ahead risk**: NONE
- **severity**: LOW

---

## Summary Table

| Value | Source | Cache TTL | Look-ahead | Range Valid | Stale Risk | Severity |
|-------|--------|-----------|-----------|-------------|------------|----------|
| PX | Post-pipeline snapshot | 5min L1 / 24h L2 | None | No | **HIGH** | HIGH |
| Δ% | Same as PX | Same | None | No | **HIGH** | HIGH |
| RV20 | Pipeline vol context | 1h | None | No | Low | OK |
| PRED 1D | HAR-RV model | 1h | None | No | Low | OK |
| ΔPRED | Delta of above two | Independent | None | No | **MED** | MED |
| SIG | V3 synthesis | 5min/24h | None | Enum-safe | Low | OK |
| CONV | Pipeline output | Same | None | **Frontend only** | Low | LOW |
| EV% | Synthesis | Same | None | **None** | Low | MED |
| RSI | Client-side | Per-fetch | None | [0,100] | None | OK |
| MACD | Client-side | Per-fetch | None | Valid | None | OK |
| ATR | Client-side | Per-fetch | None | Div-safe | None | OK |
| TP/SL | Client-side ATR×mult | Per-fetch | None | No | None | LOW |
| Impact | News scorer | None | None | [0,1] | None | OK |
| Cost | Real-time tracker | 30s poll | None | None | None | OK |
| FRESH | Pipeline latency | Per-signal | None | No | **Misleading** | MED |

## Verdict

**No look-ahead bias or future leakage found.** Primary concerns are price staleness (PX/Δ%) and FRESH chip misrepresenting data age. All client-side indicators (RSI, MACD, ATR, Bollinger, Keltner, TP/SL) are correctly computed with no look-ahead.
