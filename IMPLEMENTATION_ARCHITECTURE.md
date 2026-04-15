# Implementation Architecture — Tournament-Based Quality Control

> How to prevent implementation drift from design, at scale, with parallel agents.

---

## The Problem We're Solving

Past failures:
1. Sub-agents produce code that doesn't match the plan
2. Code is experimental, not production-grade
3. No enforcement mechanism between design and implementation
4. No quality gate before code is accepted

---

## The Solution: Spec-First Tournament Model

```
For EACH feature:

  Step 1: Main Agent writes a PRECISE SPEC
    - Exact file path
    - Exact function signatures (with types)
    - Exact input/output schemas (Pydantic or TypeScript)
    - Exact behavior description
    - Exact test cases the code must pass
    - NO ambiguity. If a sub-agent has to "decide" something, the spec failed.

  Step 2: 5 Sub-Agents implement IN PARALLEL (isolated)
    - Each gets the IDENTICAL spec
    - Each produces: implementation + unit tests
    - They cannot see each other's work
    - They must follow the spec EXACTLY — any deviation = rejection

  Step 3: Main Agent evaluates ALL 5
    - Run unit tests for all 5
    - Check: does output match spec? (types, behavior, edge cases)
    - Check: is code production-grade? (no TODOs, no stubs, proper error handling)
    - SELECT the best one. ABANDON the rest.
    - If NONE pass: Main Agent rewrites the spec (the spec was bad, not the agents)

  Step 4: Integration test
    - Selected code integrated into the project
    - Run full build (TypeScript check, Python import check)
    - If build breaks: fix or reject

  Step 5: Next feature
    - Only after current feature is accepted
```

---

## Why This Prevents Past Failures

| Past Failure | Prevention Mechanism |
|-------------|---------------------|
| Code doesn't match plan | Spec includes EXACT signatures and schemas — deviation = automatic rejection |
| Experimental quality | Spec includes required test cases — tests must pass |
| No enforcement | Main Agent is the sole gatekeeper — 5 compete, 1 wins |
| Drift accumulates | Sequential features — each builds on accepted code only |
| Ambiguous requirements | If 3+ agents interpret the spec differently, the spec is rewritten |

---

## Feature Decomposition

The v3 plan has these implementation units. Each is a self-contained, testable feature with exact specs.

### Phase 1: Data Foundation (4 features)

```
F1: TickerBriefing Materializer
    Input: Raw market data (yfinance)
    Output: Frozen TickerBriefing dataclass with 5 contexts
    Test: Given AAPL data → produces valid PriceContext, OptionsContext, etc.
    Files: tradingagents/data/materializer.py

F2: Tiered Screening Engine
    Input: List of tickers + TickerBriefings
    Output: Tier 1/2/3 classification for each ticker
    Test: Ticker with >2 ATR move → Tier 1. Watchlist default → Tier 3.
    Files: tradingagents/data/screener.py

F3: Factor Baseline Model (no LLM)
    Input: TickerBriefing
    Output: Momentum + Quality + Value composite score
    Test: Known data → known score. Deterministic, reproducible.
    Files: tradingagents/signals/factor_baseline.py

F4: Snapshot Pinning & Audit Log
    Input: Ticker entering pipeline
    Output: Frozen snapshot ID + stored briefing in SQLite
    Test: Same snapshot retrieved hours later. Full audit trail queryable.
    Files: tradingagents/data/snapshot.py
```

### Phase 2: Agent Analysis (3 features)

```
F5: Thesis Agent (Upside Catalyst)
    Input: TickerBriefing + memories
    Output: Pydantic ThesisOutput (signal, conviction, must_be_true[3], catalysts[], weakest_link)
    Test: Given mock briefing → valid ThesisOutput with all fields populated
    LLM: Claude Sonnet 4.6 with structured output
    Files: tradingagents/agents/v3/thesis_agent.py
    Prompt: EXACT copy of D6's Bull Advocate prompt

F6: Antithesis Agent (Downside Risk)
    Input: TickerBriefing + memories
    Output: Pydantic AntithesisOutput (same schema as thesis but bearish)
    Test: Given mock briefing → valid AntithesisOutput
    LLM: GPT-5-mini (heterogeneous diversity)
    Files: tradingagents/agents/v3/antithesis_agent.py
    Prompt: EXACT copy of D6's Bear Advocate prompt

F7: Base Rate Agent (Statistical)
    Input: TickerBriefing + historical stats
    Output: Pydantic BaseRateOutput (expected_move, distribution, regime, base_rate_prob)
    Test: Given mock briefing → valid BaseRateOutput with regime classification
    LLM: Claude Sonnet 4.6
    Files: tradingagents/agents/v3/base_rate_agent.py
```

### Phase 3: Synthesis & Decision (2 features)

```
F8: Synthesis Agent (Judge)
    Input: ThesisOutput + AntithesisOutput + BaseRateOutput
    Output: Pydantic SynthesisOutput (signal, conviction, scenarios[], disagreement_score)
    Test: Given 3 mock agent outputs → valid SynthesisOutput
          Must verify: HOLD only if all 3 conditions met
    LLM: Claude Opus 4.6
    Files: tradingagents/agents/v3/synthesis_agent.py
    Prompt: EXACT copy of D6's Judge prompt

F9: Deterministic Risk Layer
    Input: SynthesisOutput + portfolio state
    Output: Pydantic RiskOutput (final_shares, stop_loss, take_profit, risk_flags)
    Test: Position > 2% NAV → capped. VIX > 35 → HOLD. Drawdown > 3% → penalty.
    NO LLM: Pure Python calculation
    Files: tradingagents/risk/deterministic.py
```

### Phase 4: Memory & Learning (2 features)

```
F10: Memory Store (Hybrid Retrieval)
    Input: Trade record, agent reflections
    Output: Top-K relevant memories for a query
    Test: Store 10 memories → query → retrieve top 3 by relevance
    Files: tradingagents/memory/hybrid_store.py

F11: Reflection Pipeline
    Input: Trade outcome + original agent outputs
    Output: Per-agent reflections + semantic lessons
    Test: Given a losing trade → each agent produces specific, actionable reflection
    Files: tradingagents/memory/reflection.py
```

### Phase 5: Pipeline Orchestration (2 features)

```
F12: Analysis Pipeline (end-to-end)
    Input: Ticker + trade_date
    Output: Complete analysis with signal, sizing, risk, audit trail
    Test: AAPL → runs all stages → produces valid FinalDecision
    Files: tradingagents/pipeline/runner.py

F13: API Integration
    Input: POST /api/analyze with ticker + date
    Output: SSE events streaming each stage → final result
    Test: Curl POST → receive agent_start, thesis_complete, synthesis_complete, etc.
    Files: tradingagents/api/routes/analysis.py (rewrite)
```

### Phase 6: Frontend (2 features)

```
F14: Debate Visualization Panel
    Input: SSE events from pipeline
    Output: Real-time UI showing Thesis/Antithesis/BaseRate/Synthesis
    Test: Mock SSE events → panel renders all stages with correct data
    Files: frontend/src/components/tabs/AnalysisTab.tsx (rewrite)

F15: Signal Dashboard
    Input: List of completed analyses
    Output: Table of all tickers with signals, conviction, P&L
    Test: 5 mock signals → table renders with correct sorting/filtering
    Files: frontend/src/components/tabs/SignalsTab.tsx (new)
```

---

## Spec Template (used for every feature)

Every feature spec follows this EXACT template:

```markdown
# Feature F{N}: {Name}

## File
{exact file path}

## Dependencies
{list of other features this depends on — must be completed first}

## Interface
```python
# Exact function signatures
def function_name(param: Type) -> ReturnType:
    """Exact docstring describing behavior."""
    ...
```

## Pydantic Schema
```python
class OutputModel(BaseModel):
    field1: type = Field(description="...")
    field2: type = Field(ge=0, le=1)
    ...
```

## Behavior Rules
1. {Exact rule 1 — no ambiguity}
2. {Exact rule 2}
...

## Test Cases
```python
def test_basic():
    """Given X, expect Y."""
    result = function_name(X)
    assert result.field1 == expected

def test_edge_case():
    """Given edge case, expect specific handling."""
    ...

def test_error_handling():
    """Given invalid input, expect graceful failure."""
    ...
```

## Production Requirements
- [ ] No TODOs, FIXMEs, or stubs
- [ ] All error paths handled
- [ ] Type hints on all function signatures
- [ ] Docstring on all public functions
- [ ] No hardcoded values (use config)
- [ ] Imports are all used
```

---

## Execution Order (dependency chain)

```
F1 (Materializer) ──┐
F2 (Screener) ───────┤
F3 (Factor Baseline) ┤──→ F12 (Pipeline) ──→ F13 (API)
F4 (Snapshot) ───────┘         │                  │
                               │                  │
F5 (Thesis) ─────────┐        │            F14 (Debate UI)
F6 (Antithesis) ──────┤──→ F8 (Synthesis)  F15 (Signal Dashboard)
F7 (Base Rate) ───────┘        │
                               │
                          F9 (Risk Layer)
                               │
F10 (Memory Store) ────→ F11 (Reflection)
```

**Parallel groups (features that can be built simultaneously):**

```
Group 1: F1, F2, F3, F4 (data foundation — no dependencies)
Group 2: F5, F6, F7 (agents — depend on F1 schema only)
Group 3: F8, F9, F10 (synthesis + risk + memory — depend on Group 2 schemas)
Group 4: F11, F12 (orchestration — depends on all above)
Group 5: F13, F14, F15 (frontend — depends on F12)
```

**Total: 5 groups × 5 competing agents per feature = 75 sub-agent invocations**
**But only 15 features worth of code accepted (1 winner per feature)**

---

## Quality Gates

### Gate 1: Spec Compliance
- Does the output match the Pydantic schema EXACTLY?
- Are all function signatures as specified?
- Are all test cases included AND passing?

### Gate 2: Production Quality
- No TODOs, FIXMEs, stubs, or placeholder data
- All imports used, no unused imports
- Proper error handling (try/except with specific exceptions)
- Type hints on all functions
- Docstrings on all public functions

### Gate 3: Integration
- TypeScript compiles clean (`npx tsc --noEmit`)
- Python imports clean (`python -c "from module import ..."`)
- No build warnings

### Gate 4: Acceptance Criteria
Main Agent asks:
1. Does this code do what the spec says? (behavior match)
2. Would I be embarrassed showing this to Jane Street? (quality bar)
3. Can I build the next feature on top of this? (composability)

If ANY gate fails → reject ALL 5, rewrite spec, re-run tournament.

---

## Anti-Drift Mechanisms

### 1. Spec is the contract
Sub-agents receive ONLY the spec. Not the full plan, not the design philosophy, not "context." The spec is the entire world. If the spec is ambiguous, the solution is to fix the spec, not to let agents interpret.

### 2. Tests are the acceptance criteria
If all tests pass and the code matches the spec, it's accepted. If tests pass but the code "feels wrong," the tests are bad — fix the tests and re-run.

### 3. One feature at a time
No batch implementation. Feature N must be accepted before Feature N+1 begins. This prevents accumulated drift.

### 4. Schemas are shared upfront
All Pydantic schemas for all features are defined BEFORE any implementation begins. Sub-agents can't invent new fields or change types. The schema IS the interface contract.

### 5. Main Agent never writes implementation code
Main Agent writes specs and evaluates results. If Main Agent writes code, it bypasses the quality process.

---

## Timeline Estimate

| Group | Features | Sub-agents | Calendar Time |
|-------|----------|------------|--------------|
| 1 | F1-F4 (data) | 20 (4×5) | 1 session |
| 2 | F5-F7 (agents) | 15 (3×5) | 1 session |
| 3 | F8-F10 (synthesis) | 15 (3×5) | 1 session |
| 4 | F11-F12 (orchestration) | 10 (2×5) | 1 session |
| 5 | F13-F15 (frontend) | 15 (3×5) | 1 session |
| **Total** | **15 features** | **75 sub-agents** | **5 sessions** |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| All 5 agents fail on a feature | Spec was ambiguous → Main Agent rewrites spec with more detail |
| Agent produces great code that doesn't match spec | Reject. Spec compliance > code quality. |
| Feature works alone but breaks integration | Gate 3 catches this. Fix integration or reject. |
| Sub-agent adds "nice to have" features not in spec | Reject. Scope creep is the #1 quality killer. |
| Testing takes too long | Tests are part of the spec, not an afterthought. Agent writes both. |
