# TradingAgents — Final Debate System Design v3

> Synthesized from 10 independent debate agents. This is the definitive architecture.

---

## The Core Insight: Build Simple First, Add Complexity Only Where Measured Alpha Justifies It

The Devil's Advocate (D8) and Hedge Fund PM (D9) both argue: validate the core hypothesis before building elaborate architecture. The Quant Strategist (D3) says: assume LLMs are wrong and design so the system still makes money.

**Resolution**: We build in two modes that run simultaneously:

```
MODE A: "Dumb Baseline" (always runs, no LLM)
  Momentum + Quality + Value factor model
  Cost: $0/day
  Purpose: floor performance, never turned off

MODE B: "Agent Pipeline" (the debate system)
  Full multi-agent analysis with debate
  Cost: ~$4-6/day (tiered processing)
  Purpose: alpha generation above baseline
```

The final signal is: **Baseline weight (15%) + Agent weight (85%)**, adjustable. If Agent pipeline underperforms Baseline for 8+ weeks, auto-reduce Agent weight to 50%.

---

## The 5-Stage Pipeline

### Stage 0: Data Materialization (no LLM)

**From D1 (Data Flow Architect):**

```
Raw Data Sources → Normalized Event Store → Materialized TickerBriefing
                                              (~800 tokens per ticker)
```

| Source | Poll Interval | Max Staleness |
|--------|--------------|---------------|
| Price OHLCV | 60s | 2 min |
| Options chain | 5 min | 15 min |
| News | 2 min | 10 min |
| Social sentiment | 10 min | 30 min |
| Macro (FRED) | 6 hours | 24 hours |

**Key design from D1**: Pre-compute materialized views (PriceContext, OptionsContext, NewsContext, SocialContext, MacroContext). This cuts token cost 10x vs raw data. Every view carries `data_age_seconds` and freshness weight.

**Snapshot pinning**: Once a ticker enters the pipeline, its data is frozen. All agents argue over the same snapshot.

### Stage 1: Tiered Screening (determines pipeline depth)

**From D1:**

| Tier | Trigger | Analysis | Expected/day |
|------|---------|----------|-------------|
| **1 (Full)** | Holding position, unusual activity, >2 ATR move, news event | 3 agents + debate | 8-15 |
| **2 (Quick)** | On watchlist + minor signal | 1 agent structured analysis | 15-25 |
| **3 (Screen)** | Default watchlist | Factor model score only | 20-30 |

**Estimated cost: $4-6/day for 50+ tickers** (from D1's analysis).

### Stage 2: Agent Analysis

**From D2 (Debate Structure) + D6 (Prompt Engineer):**

Three agents, not six. The Hedge Fund PM (D9) says keep only 3:

```
┌─────────────────────────────────────────────────────────┐
│  ALL THREE AGENTS RECEIVE:                               │
│  • Full TickerBriefing (800 tokens, all 5 data types)   │
│  • Their domain-specific deep dive data                  │
│  • Relevant memories from their personal memory store    │
│  THEY DO NOT SEE EACH OTHER (blind)                      │
│                                                          │
│  THESIS AGENT (Claude Sonnet 4.6)                        │
│  Framework: Upside Catalyst Identification               │
│  Deep data: momentum indicators, growth metrics          │
│  Output: {signal, conviction, must_be_true[3],           │
│           catalysts[], weakest_link}                      │
│                                                          │
│  ANTITHESIS AGENT (GPT-5-mini for diversity)             │
│  Framework: Downside Risk Mapping                        │
│  Deep data: valuation ratios, risk metrics               │
│  Output: {signal, conviction, must_be_true[3],           │
│           risk_catalysts[], weakest_link}                 │
│                                                          │
│  BASE RATE AGENT (Claude Sonnet 4.6)                     │
│  Framework: Statistical + Macro Regime Analysis          │
│  Deep data: macro indicators, sector flows, options      │
│  Output: {expected_move, distribution, regime,           │
│           historical_analog, base_rate_probability}      │
└─────────────────────────────────────────────────────────┘
```

**Why 3, not 6**: D9 (PM) argues Social and News analysts add noise, not signal. Fundamentals + Macro + Options/Divergence are the 3 that matter. We fold their capabilities into the 3-agent framework:
- Thesis = Fundamentals + Momentum + Catalyst
- Antithesis = Valuation Risk + Macro Headwinds + Crowding
- Base Rate = Options/Divergence + Statistical + Regime

### Stage 3: Synthesis (not "judgment")

**From D2 (Debate Structure):**

> "A judge that picks a winner discards information. Synthesis integrates."

```
SYNTHESIS AGENT (Claude Opus 4.6)
│
│ Receives: All 3 blind agent outputs
│ Process:
│   1. Data Verification Audit (from D6)
│      - Check every claim against TickerBriefing
│      - Flag factual errors, penalize confidence
│   2. Must-Be-True Cross-Examination (from D6)
│      - Evaluate each condition: TRUE / FALSE / INDETERMINATE
│   3. Magnitude Asymmetry (from D3)
│      - Upside magnitude × thesis confidence vs
│        downside magnitude × antithesis confidence
│   4. Base Rate Integration (from D2)
│      - Statistical anchor prevents narrative bias
│   5. Signal + Conviction
│
│ HOLD only if ALL 3 conditions met (from D6):
│   - Both sides 2+ conditions INDETERMINATE
│   - Expected value between -2% and +2%
│   - Both adjusted confidences < 40
│
│ Output: {
│   signal: BUY | SHORT | HOLD,
│   conviction: 0-100 (calibrated),
│   scenarios: [{prob, target, rationale}],
│   must_be_true_resolved: [...],
│   disagreement_score: float,  // D2: divergence as meta-signal
│   key_evidence: [...]
│ }
```

### Stage 4: Risk Evaluation (independent, not debate)

**From D4 (Risk Manager) — two layers:**

**Layer 1: Deterministic (code, no LLM)**
```python
# Hard limits — schema-enforced, non-negotiable
MAX_POSITION_PCT = 0.02      # 2% per name
MAX_SECTOR_PCT = 0.15        # 15% per sector
MAX_CORRELATED_CLUSTER = 0.20 # 20% correlated group
MIN_LIQUIDITY = 0.05         # < 5% of 20-day ADV

# Circuit breakers
DAILY_DRAWDOWN_REDUCE = 0.015   # 1.5% → reduce 50%
WEEKLY_DRAWDOWN_HALT = 0.03     # 3% → halt new entries
MONTHLY_DRAWDOWN_HALF = 0.05    # 5% → half exposure
MONTHLY_DRAWDOWN_FLAT = 0.08    # 8% → flatten to cash

# Event rules
EARNINGS_WITHIN_3D = half position size
FOMC_WITHIN_7D = reduce 25%
VIX_ABOVE_35 = HOLD everything, alert human
```

**Layer 2: LLM Risk Evaluation (advisory)**
```
RISK AGENT (Sonnet 4.6)
│ Sees: ticker, direction, size, portfolio state, macro
│ Does NOT see: thesis, debate, or conviction score
│ Output: risk_rating, size_modifier (0-1), stress_test_results, flags
│ Can reduce but never increase beyond Layer 1 limits
```

**Position Sizing Formula (from D4 + D3):**
```
base = NAV × 0.02 × (conviction/100)  // Quarter-Kelly base
× risk_modifier                         // from Risk Agent
× vol_scalar (target_vol / realized)    // volatility normalization
× drawdown_penalty                      // 0.5 if >3% month drawdown
× disagreement_discount                 // 0.4 + 0.6 × agreement score
final = min(result, NAV × 0.02)         // hard cap
```

### Stage 5: Execution (deterministic, NO LLM)

**From D7 (Systems Architect) + D4 (Risk Manager):**

- Order placed via broker API (Alpaca/IBKR)
- Latency: <1 second
- Stop-loss: auto-set at 2× ATR from entry
- Budget caps: per-run $50, per-ticker $5, daily $200 kill switch

### Stage 6: Reflection & Memory

**From D5 (Memory & Learning):**

```
AFTER EACH TRADE:
  T+0 (pre-mortem): Each agent records predictions before outcome
  T+close (reflection): Compare pre-mortem vs actual, identify causes
  Weekly: Judge synthesizes → extract semantic lessons
  Monthly: Prune low-value memories, update importance weights

MEMORY ARCHITECTURE:
  Per-agent working memory (session-scoped, NOT shared)
  Shared episodic store (actor-tagged, 12-month window)
  Shared semantic store (permanent principles)
  Crisis archive (NEVER decays — VIX>35, >5% drawdown, unanimous+wrong)

RETRIEVAL: Hybrid BM25 + vector + reranker
  Triple scoring: recency × importance × relevance
  Crisis memories force-injected when regime similarity > 0.7
```

---

## Model Assignment

| Role | Model | Accuracy | Why |
|------|-------|----------|-----|
| Thesis Agent | Claude Sonnet 4.6 | 83.6% | Good reasoning, cost-effective |
| Antithesis Agent | GPT-5-mini | 87.4% | Different model = diversity (91% vs 82%) |
| Base Rate Agent | Claude Sonnet 4.6 | 83.6% | Statistical grounding |
| Synthesis (Judge) | **Claude Opus 4.6** | **87.8%** | Critical decision, 5x fewer tokens than GPT-5 |
| Risk Evaluator | Claude Sonnet 4.6 | 83.6% | Advisory role |
| Reflection | Claude Sonnet 4.6 | 83.6% | Learning from outcomes |
| Regime Detector | **NOT an LLM** | N/A | HMM on VIX, yields, breadth (from D3) |
| Factor Baseline | **NOT an LLM** | N/A | Momentum + Quality + Value (from D3/D8) |

---

## What Changed from Original TradingAgents

| Aspect | Original | v3 | Evidence |
|--------|----------|-----|---------|
| Analysts | 6 sequential with tool-calling | 3 parallel with pre-fetched data | D1 (10x cheaper), D9 (only 3 matter) |
| Debate | Bull vs Bear with personas | Thesis/Antithesis/BaseRate, blind, no personas | D2 (91% vs 82%), D6 (personas -3.6%) |
| Rounds | N configurable | 1 round blind + optional 1 rebuttal | D2 (>2 = persuasion bias) |
| Judge | "Pick a winner" | Synthesize with data audit + must-be-true cross-exam | D2, D6 |
| Risk | 3-way debate (aggressive/neutral/conservative) | 2-layer: deterministic limits + blind LLM evaluation | D4 (Citadel model), D9 |
| Output | BUY/SELL/HOLD text | Pydantic JSON with scenarios, sizing, stops | D6, D3 |
| Memory | BM25 only, per-agent | Hybrid retrieval + crisis archive + pre-mortem | D5 |
| Execution | LLM decides everything | LLM signals → deterministic code executes | D7, D4 |
| Cost | ~$25-40/day | ~$4-6/day (tiered processing) | D1 |
| Safety | None | Hard schema limits + circuit breakers + budget caps | D4, D8 |
| Baseline | None | Factor model always running (15% weight floor) | D3, D8 |

---

## Cost Projection

| Component | Daily Cost | Notes |
|-----------|-----------|-------|
| Data ingestion | $0 | yfinance/CBOE/FRED free |
| Tier 1 analysis (12 tickers × 3 agents + synthesis) | $2.50 | Sonnet + Opus |
| Tier 2 analysis (20 tickers × 1 agent) | $1.20 | Sonnet only |
| Tier 3 screening (25 tickers) | $0 | Factor model, no LLM |
| Risk evaluation | $0.50 | Sonnet |
| Reflection (daily) | $0.80 | Sonnet |
| **TOTAL** | **~$5/day** | **~$150/month** |

---

## Validation Plan (from D8 + D9)

```
Month 1-3: Paper trading, both modes
  - Track Mode A (baseline) vs Mode B (agents) vs Mode A+B (combined)
  - Measure: Sharpe, max drawdown, win rate, calibration

Month 4-6: Shadow mode
  - Agent signals visible to team, no capital at risk
  - PMs use as research screening tool (D9 Phase 1)

Month 7-12: Limited allocation
  - 5-10% of portfolio in systematic pocket
  - Hard risk limits enforced by Layer 1

Month 13-24: Scale based on evidence
  - If Sharpe > 1.5 net of costs → increase allocation
  - If Sharpe < 1.0 → reduce to baseline only

SUCCESS CRITERIA:
  - Agent pipeline Sharpe > Baseline Sharpe + 0.3 over 6 months
  - Max drawdown < 15%
  - Agent agreement rate 40-70% (not too low, not too high)
  - Conviction calibration r² > 0.5
```

---

## Implementation Order

1. **Week 1**: Data materialization pipeline + factor baseline
2. **Week 2**: 3-agent analysis with D6 prompts + Pydantic schemas
3. **Week 3**: Synthesis agent + deterministic risk layer
4. **Week 4**: Memory system + reflection pipeline
5. **Week 5**: Bloomberg UI integration (debate visualization)
6. **Month 2-3**: Paper trading + calibration
7. **Month 4+**: Shadow → Limited → Scale
