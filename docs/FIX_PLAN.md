# FIX PLAN

> Updated: 2026-04-07 by Harness Agent

## P0 — Release Blockers (FIXED)

| # | Bug | Fix | Status |
|---|-----|-----|--------|
| 1 | Infinite re-render loop in fetchSignals | `useMemo` for `allTickers` in `useUniverseRerank.ts` | FIXED |
| 2 | yfinance probe crash (missing dates) | Added fallback `yf.download(period="5d")` in probe path | FIXED |
| 3 | Missing `stockstats` dependency | `pip install stockstats` | FIXED |

## P1 — High Priority (OPEN)

| # | Bug | Proposed Fix | Owner |
|---|-----|-------------|-------|
| 4 | PX/Δ% empty for cached signals | Option A: Enrich cached items in `_cache_get()` and `_l2_get()`. Option B: Add independent frontend price polling via `/api/v3/prices/snapshot` every 30s | TBD |
| 5 | Databento API key not auto-loaded | Add `load_dotenv()` call in `api/main.py` `_lifespan()` before connector bootstrap | TBD |
| 6 | Console error spam on page reload | Add `AbortError` check in `api.ts` `request()` function | TBD |

## P2 — Improvements (OPEN)

| # | Item | Description |
|---|------|-------------|
| 7 | TP/SL indicators hidden on small viewports | Change `xl:inline` to `lg:inline` or add a dedicated row |
| 8 | News expand not keyboard-accessible | Add Enter/Space handler on news rows |
| 9 | Add `databento` to pip requirements | Ensure `databento` and `stockstats` in `requirements.txt` |
