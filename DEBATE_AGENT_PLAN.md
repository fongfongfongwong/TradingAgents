# TradingAgents Multi-Agent Debate System — Detailed Implementation Plan

> 先不写代码。这是一个详细的 Plan，把 multiple agent debate 做到极致。

---

## 1. 当前 Debate 架构理解

### 完整的 5 阶段流程

```
阶段 1: DATA COLLECTION (6 Analysts 并行收集数据)
    ┌─ Market Analyst ──→ market_report (技术指标, OHLCV)
    ├─ Social Analyst ──→ sentiment_report (Reddit, 情绪)
    ├─ News Analyst ────→ news_report (新闻, 宏观事件)
    ├─ Fundamentals ────→ fundamentals_report (财务报表)
    ├─ Options Analyst ─→ options_report (期权, 分歧)
    └─ Macro Analyst ───→ macro_report (利率, 失业率, CPI)

阶段 2: INVESTMENT DEBATE (Bull vs Bear 交替辩论)
    Bull Researcher ←→ Bear Researcher (交替 N 轮)
    │  Bull: 用数据论证为什么要买
    │  Bear: 用数据论证为什么要卖
    │  每轮都反驳对方的论点
    └──→ Research Manager (裁判) → investment_plan (BUY/SELL/HOLD)

阶段 3: TRADER EXECUTION
    Trader 接收 investment_plan → 制定具体执行方案
    └──→ trader_investment_plan (入场价, 仓位, 止损)

阶段 4: RISK MANAGEMENT DEBATE (3 方辩论)
    Aggressive ←→ Conservative ←→ Neutral (交替 N 轮)
    │  Aggressive: 为什么要大胆
    │  Conservative: 为什么要保守
    │  Neutral: 平衡两方观点
    └──→ Portfolio Manager (最终裁判) → final_trade_decision

阶段 5: MEMORY & REFLECTION
    实际收益出来后 → 每个 agent 反思自己的决策
    └──→ 存入 BM25 memory，下次类似情况时检索
```

### 核心状态 (AgentState)

```python
{
    # 输入
    "company_of_interest": "AAPL",
    "trade_date": "2026-04-05",

    # 6 份分析报告 (阶段1 输出)
    "market_report": str,        # 技术分析
    "sentiment_report": str,     # 社交情绪
    "news_report": str,          # 新闻分析
    "fundamentals_report": str,  # 基本面
    "options_report": str,       # 期权分歧
    "macro_report": str,         # 宏观经济

    # 投资辩论 (阶段2)
    "investment_debate_state": {
        "bull_history": [],
        "bear_history": [],
        "history": [],
        "count": int,
        "judge_decision": str,
    },
    "investment_plan": str,      # Research Manager 的决定

    # 交易方案 (阶段3)
    "trader_investment_plan": str,

    # 风险辩论 (阶段4)
    "risk_debate_state": {
        "aggressive_history": [],
        "conservative_history": [],
        "neutral_history": [],
        "count": int,
        "judge_decision": str,
    },
    "final_trade_decision": str,  # 最终决定
}
```

---

## 2. 当前代码的问题

### 2.1 API 层完全是 Stub
`_run_analysis()` 在 `api/routes/analysis.py:141-172` 只是循环 agent 名字，
**从未调用真正的 `TradingAgentsGraph`**。返回硬编码 `HOLD/0.5`。

### 2.2 Social Analyst 数据缺失
只有 `get_news()` 一个工具。ApeWisdom、Fear/Greed、AAII 连接器已注册但未接入。

### 2.3 Options Analyst 分歧引擎不完整
5 维分歧中的 News 和 Retail 维度返回 None。

### 2.4 Memory 系统需要 LLM
Reflection 需要 LLM 来分析决策 vs 实际收益。之前没有 API key 无法运行。

### 2.5 前端无法展示辩论过程
当前 SSE 事件只有 `agent_start`/`agent_complete`，没有辩论内容的流式传输。

---

## 3. 实施计划 (6 个阶段)

### Phase A: Wire Real Agent Pipeline to API

**目标**: 让 `/api/analyze` 调用真正的 `TradingAgentsGraph`

**具体步骤**:

1. **修改 `api/routes/analysis.py`**
   - 在 `_run_analysis()` 中 import `TradingAgentsGraph`
   - 创建 graph 实例，传入 Anthropic Claude API key
   - 调用 `graph.propagate()` 获取真实结果
   - 每个阶段完成时 emit SSE 事件（不只是 agent_start/complete）

2. **新增 SSE 事件类型**
   ```
   agent_start         → 分析师开始工作
   agent_report        → 分析师报告完成（附带报告内容）
   debate_turn         → 辩论中的一个回合（Bull 或 Bear 的论点）
   debate_judge        → 裁判做出决定
   risk_debate_turn    → 风险辩论的一个回合
   risk_debate_judge   → Portfolio Manager 最终决定
   analysis_complete   → 全流程完成
   ```

3. **配置 LLM provider**
   - 使用提供的 Anthropic Claude API key
   - `quick_think_llm` = Claude Haiku (快速，便宜)
   - `deep_think_llm` = Claude Sonnet (深度推理)

**关键文件**:
- `tradingagents/api/routes/analysis.py` — 重写 `_run_analysis()`
- `tradingagents/graph/trading_graph.py` — 主 graph（已存在，只需正确调用）
- `tradingagents/graph/setup.py` — graph 初始化
- `tradingagents/default_config.py` — LLM 配置

---

### Phase B: Enhance Data Sources for Each Analyst

**目标**: 让每个 Analyst 有丰富的真实数据来支撑辩论

| Analyst | 当前工具 | 新增工具 | 数据来源 |
|---------|---------|---------|---------|
| Market | `get_stock_data`, `get_indicators` | `get_realtime_quote` | yfinance (已有) + Polygon (有 key 后) |
| Social | `get_news` (仅此一个!) | `get_social_sentiment`, `get_fear_greed`, `get_congressional` | ApeWisdom, Fear/Greed, AAII, Quiver |
| News | `get_news`, `get_global_news` | `get_news_with_sentiment` | yfinance + FinBERT 情绪评分 |
| Fundamentals | 4 个财务工具 | `get_insider_transactions`, `get_short_interest` | yfinance + Fintel + SEC EDGAR |
| Options | `get_divergence_report` | `get_options_flow`, `get_iv_analytics` | CBOE + Unusual Whales + ORATS |
| Macro | `get_macro_data` | `get_global_macro`, `get_geopolitical_risk`, `get_economic_calendar` | FRED + DBnomics + GPR Index |

**实现方式**:
- 每个新工具先用 mock data
- 接入 API key 后自动切换到 real data
- Social Analyst 是最大的改进 — 从 1 个工具变成 3+ 个

---

### Phase C: Enrich the Debate Prompts

**目标**: 让辩论更深入、更有质量

**当前问题**: Bull/Bear 的 prompt 比较通用，没有利用到所有 6 份报告的结构化数据。

**改进方案**:

1. **Bull Researcher 增强 prompt**
   ```
   你是一个看多研究员。你收到了以下分析报告:

   [MARKET]: {market_report}
   [SOCIAL]: {sentiment_report}  ← 新增社交情绪数据
   [NEWS]: {news_report}
   [FUNDAMENTALS]: {fundamentals_report}
   [OPTIONS]: {options_report}   ← 新增期权流向
   [MACRO]: {macro_report}       ← 新增宏观数据

   基于这些数据，你需要:
   1. 从每份报告中提取支持买入的证据
   2. 量化你的信心: 每个维度给 1-10 分
   3. 直接反驳 Bear 的以下论点: {bear_last_argument}
   4. 给出具体的价格目标和时间框架
   ```

2. **Bear Researcher 增强 prompt**
   - 同样结构，但从风险角度分析
   - 特别关注: 空头利息、内部人卖出、期权看跌信号、宏观风险

3. **Research Manager 增强 prompt**
   - 不只是看辩论文本，还要看每个维度的定量评分
   - 引入 "证据权重" 概念：哪些数据更可靠
   - 输出结构化决策而非纯文本

4. **Risk Debaters 增强**
   - Aggressive: 关注期权流向中的异常活跃
   - Conservative: 关注宏观风险和地缘政治
   - Neutral: 用历史数据做均值回归分析

---

### Phase D: Frontend Debate Visualization

**目标**: 在 Bloomberg Terminal UI 中实时展示辩论过程

**新增组件**:

1. **DebatePanel** (右侧面板，Analysis tab 激活时显示)
   ```
   ┌─────────────────────┐
   │  INVESTMENT DEBATE   │
   │  Round 1/3          │
   ├─────────────────────┤
   │  🟢 BULL            │
   │  "Based on strong   │
   │   earnings and 15%  │
   │   revenue growth..." │
   │  Confidence: 8/10   │
   ├─────────────────────┤
   │  🔴 BEAR            │
   │  "However, P/E at   │
   │   32x is 40% above  │
   │   sector average..." │
   │  Confidence: 6/10   │
   ├─────────────────────┤
   │  ⚖️ JUDGE           │
   │  Decision: BUY      │
   │  Rationale: "Bull's │
   │  growth argument    │
   │  outweighs..."      │
   └─────────────────────┘
   ```

2. **RiskDebatePanel** (风险辩论可视化)
   - 三列展示: Aggressive | Neutral | Conservative
   - 每一轮实时更新

3. **AnalystReportCards** (6 份报告的可折叠卡片)
   - 每张卡片显示: 信号 (BUY/HOLD/SELL), 信心度, 关键发现

4. **DecisionSummary** (最终决策卡)
   - Rating: BUY/OVERWEIGHT/HOLD/UNDERWEIGHT/SELL
   - 5 维度评分雷达图
   - Entry/exit 策略
   - 风险等级

---

### Phase E: Memory & Continuous Learning

**目标**: 让系统从过去的决策中学习

1. **初始化 Memory**
   - 5 个 BM25 memory 实例 (bull, bear, trader, judge, portfolio_manager)
   - 可选: 升级到 hybrid (BM25 + vector embeddings)

2. **Reflection 循环**
   - 分析完成后，获取实际股价变化
   - 每个 agent 反思: "我的论点对了吗? 哪些证据最重要?"
   - 存入 memory，下次类似情况检索

3. **Memory 可视化** (前端)
   - Settings tab 中显示 memory 大小
   - 可以查看/清除/导出 memory

---

### Phase F: Multi-Stock Screening Pipeline

**目标**: 从 "分析单只股票" 扩展到 "筛选最佳投资机会"

1. **Watchlist Batch Analysis**
   - 用户 watchlist 中的所有 ticker
   - 并行运行分析（用便宜的 quick_think_llm）
   - 按最终评分排序

2. **Cross-Stock Comparison**
   - 同行业股票的横向比较
   - 哪只股票的 debate 中 Bull 赢得最决定性

3. **Alert System**
   - 当某只股票的信号从 HOLD 变为 BUY
   - 当社交情绪突然飙升
   - 当期权流向出现异常

---

## 4. LLM 使用策略

### Token 成本优化

| Agent | LLM | 原因 |
|-------|-----|------|
| 6 Analysts | Claude Haiku 4.5 | 数据提取和格式化，不需要深度推理 |
| Bull/Bear Researchers | Claude Sonnet 4.6 | 需要论证和反驳能力 |
| Trader | Claude Sonnet 4.6 | 需要制定具体执行方案 |
| Risk Debaters (3个) | Claude Haiku 4.5 | 风险评估相对标准化 |
| Research Manager | Claude Sonnet 4.6 | 关键决策，需要深度推理 |
| Portfolio Manager | Claude Sonnet 4.6 | 最终决策，需要综合判断 |
| Reflection | Claude Haiku 4.5 | 结构化分析，模板化 |

**预估成本 (单次完整分析)**:
- 6 Analysts × ~2K tokens = ~12K tokens (Haiku)
- 3 debate rounds × 2 debaters × ~1K = ~6K tokens (Sonnet)
- Trader + 2 Judges = ~6K tokens (Sonnet)
- Risk debate 3 rounds × 3 debaters × ~1K = ~9K tokens (Haiku)
- Reflection = ~3K tokens (Haiku)
- **总计: ~36K tokens ≈ $0.10-0.30 per analysis**

### Budget Control

- `llm_gateway.budget_limit` 限制每次分析的美元上限
- 超出预算 → 跳过剩余辩论轮次，直接让 Judge 做决定

---

## 5. 数据流的 Real-time 增强

### 当前 Mock → Real 切换策略

每个 connector 都是:
```python
if api_key_exists:
    return real_api_call()
else:
    return realistic_mock_data()
```

### 需要的 Free Real-time 数据 (无需 API key)

| 数据 | 来源 | 方法 |
|------|------|------|
| 股价 OHLCV | yfinance | `yf.download()` — 已有 |
| 新闻 | yfinance | `yf.Ticker().news` — 已有 |
| 期权链 | yfinance | `yf.Ticker().option_chain()` — 已有 |
| 机构持仓 | yfinance | `yf.Ticker().institutional_holders` — 已有 |
| 内部人交易 | yfinance | `yf.Ticker().insider_transactions` — 已有 |
| VIX | CBOE | CSV download — 已有 |
| Fear/Greed | CNN | 已有 connector |
| FRED 宏观 | FRED | 需要 free API key |

**结论**: 即使没有付费 API，yfinance + CBOE + FRED 已经能提供完整的 real data 给所有 6 个 analyst。

---

## 6. 实施顺序 (优先级排序)

### Week 1: 核心 Pipeline 打通
1. ✅ Wire `_run_analysis()` to `TradingAgentsGraph`
2. ✅ 配置 Claude API key 作为 LLM provider
3. ✅ 新增 SSE 事件类型 (debate_turn, debate_judge)
4. ✅ 验证: 提交 AAPL 分析 → 看到完整 6 analyst + debate + 最终决策

### Week 2: 数据增强
5. Wire Social Analyst 新工具 (social_tools.py 已建)
6. Wire Options Analyst 新工具 (分歧引擎补全)
7. 接入 FinBERT 情绪评分到 News Analyst
8. 验证: Social 报告包含 Reddit + Fear/Greed + Congressional

### Week 3: 前端辩论可视化
9. DebatePanel 组件
10. RiskDebatePanel 组件
11. AnalystReportCards 组件
12. DecisionSummary 雷达图

### Week 4: Memory + Multi-Stock
13. 初始化 5 个 memory 实例
14. Reflection 循环
15. Watchlist batch analysis
16. Alert system

---

## 7. 风险和注意事项

### 7.1 LLM 延迟
完整 debate 可能需要 60-120 秒。需要:
- SSE 实时流式反馈
- 前端进度条
- 可中断 (用户可以跳过剩余辩论)

### 7.2 Token 成本
每次分析 $0.10-0.30。100 次/天 = $10-30/天。
- 用 budget_limit 控制
- 用 Haiku 做低优先级任务

### 7.3 数据一致性
所有 analyst 必须使用同一 trade_date 的数据。
- 不能让 Market Analyst 看今天的价格，而 Fundamentals 看上个月的报表

### 7.4 Memory 增长
BM25 memory 无限增长。需要:
- 最大 memory 条目限制 (1000)
- 定期清理过时的 memory
- 按 ticker/sector 分类存储

---

## 8. 成功标准

这个 plan 做到极致的标准:

1. **完整性**: 提交一个 ticker → 自动完成 6 analyst 分析 + 2 轮辩论 + 风险评估 → 得到 BUY/SELL/HOLD 决策
2. **可追溯性**: 每一步的推理都可以在前端看到（哪个 analyst 说了什么，Bull 怎么反驳 Bear）
3. **数据驱动**: 决策基于真实数据（yfinance + CBOE + FRED），不是 GPT 的想象
4. **学习能力**: 系统从过去的决策中学习，避免重复犯错
5. **速度**: 60 秒内完成完整分析（用 Haiku 加速）
6. **成本可控**: 每次分析 < $0.30，每天 budget 上限可配置
