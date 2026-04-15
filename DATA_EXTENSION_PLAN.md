# TradingAgents Data Extension Plan

> Compiled by Main Agent from 5 parallel deep research agents | 2026-04-04

---

## Current State: What's Working vs What's Broken

| Analyst | Data Sources Wired | Critical Gap |
|---------|-------------------|--------------|
| Market | yfinance OHLCV + StockStats | yfinance unreliable (2/5), frequent 429s |
| News | yfinance news | No sentiment scoring |
| **Social** | **Only `get_news()`** | **ApeWisdom, Fear/Greed, AAII registered but NOT wired** |
| Fundamentals | yfinance + SEC EDGAR XBRL | `get_insider_transactions` not in agent tools |
| **Options** | CBOE VIX + put/call | **News & Retail dimensions return None** |
| Macro | FRED (7 series) | No global macro, no geopolitical risk |

---

## Phase 1: Wire Existing + Free Sources ($0/mo)

> Week 1-2. Fix the biggest gaps using code we already have.

| Action | Source | What It Does | Agent |
|--------|--------|-------------|-------|
| Wire ApeWisdom connector to Social Analyst | ApeWisdom (registered) | Reddit mentions, trending stocks | Social |
| Wire Fear/Greed connector to Social Analyst | Fear/Greed (registered) | Market sentiment gauge | Social |
| Wire AAII connector to Social Analyst | AAII (registered) | Individual investor survey | Social |
| Wire Finnhub sentiment to Divergence | Finnhub (registered) | News sentiment dimension | Options |
| Add `get_insider_transactions` to Fundamentals tools | yfinance (existing) | Insider buy/sell data | Fundamentals |
| Deploy FinBERT model | HuggingFace (free) | Score news sentiment locally | News |
| Add Alpaca News API | Free tier (200 calls/min) | Real-time Benzinga news feed | News |
| Add DBnomics connector | Free | IMF, OECD, Eurostat, ECB in one API | Macro |
| Add GPR Index + EPU Index | Free (CSV download) | Geopolitical risk signals | Macro |
| Install TA-Lib | Free (open source) | 200+ technical indicators, 10x faster | Market |
| Install py_vollib_vectorized | Free (open source) | Fast batch Greeks/IV calculation | Options |

**New Python packages:**
```
pip install ta-lib finbert-embedding dbnomics wbgapi finnhub-python py-vollib-vectorized alpaca-py
```

---

## Phase 2: Production Data Tier ($300-500/mo)

> Week 3-4. Replace yfinance with reliable paid sources.

| Provider | Cost | Replaces | Data |
|----------|------|----------|------|
| **Polygon.io Starter** | $29/mo | yfinance OHLCV | US stocks, options, crypto. Unlimited calls. Python SDK. |
| **FMP (Financial Modeling Prep)** | $49/mo | yfinance fundamentals | 70K+ securities, 30yr history, 13F, ESG, ratios |
| **Quiver Quant (Trader)** | $75/mo | ApeWisdom (free fallback) | Congressional trades + Reddit + lobbying + Wikipedia |
| **Unusual Whales** | $50/mo | None (new) | Options flow + dark pool + MCP Server |
| **Fintel** | $25/mo | SEC EDGAR 13F (supplement) | Parsed 13F + short interest + insider trades via API |
| **SEC-API.io** | $55/mo | Raw EDGAR parsing | Structured 10-K/Q extraction + real-time 8-K stream |
| **FINRA Short Interest** | Free | None (new) | Biweekly short interest from regulator |

**Total: ~$283/mo**

---

## Phase 3: Enhanced Analytics ($500-800/mo)

> Month 2. Add real-time streaming and deeper analytics.

| Provider | Cost | Data |
|----------|------|------|
| **Polygon.io Advanced** | +$171/mo (upgrade from $29 to $200) | Real-time WebSocket streaming, full SIP data |
| **Polygon.io Options Developer** | $79/mo | Options chains with Greeks + IV, 4yr history |
| **ORATS** | $99/mo | Proprietary IV forecasts, slope analysis, 100+ indicators |
| **Trading Economics** | $149/mo | 196 countries, real-time economic calendar, proprietary forecasts |
| **SentimenTrader** | $98/mo | 20,000+ composite sentiment indicators |

**Total: ~$596/mo additional**

---

## Phase 4: Crypto + Broker Integration (mostly free)

| Provider | Cost | Data |
|----------|------|------|
| Binance API | Free | Crypto OHLCV + WebSocket + order book |
| CoinGecko Demo | Free | 35M+ tokens, DeFi, NFT metrics |
| CFTC COT Reports | Free | Futures positioning (weekly) |
| Alpaca Algo Trader Plus | $99/mo | Combined trading + full market data |
| Interactive Brokers | Variable | Global execution + data (requires account) |

---

## Phase 5: Enterprise ($10K+/yr, when AUM justifies)

| Provider | Cost | When |
|----------|------|------|
| Earnest Analytics | $100K+/yr | Managing $10M+ — credit card transaction alpha |
| Vanda Research | $36K+/yr | Need real-time retail flow |
| Refinitiv MarketPsych | $30K+/yr | Multi-language global sentiment |
| MSCI ESG | $25K+/yr | Institutional ESG compliance |
| Databento OPRA | $2,400/yr | Tick-level options data |
| OptionMetrics IvyDB | Institutional | Academic-grade IV backtesting (25yr) |

---

## New Connectors to Build

### Phase 1 Connectors (Free)

```
tradingagents/dataflows/connectors/
├── finbert_connector.py       # Local FinBERT model for news sentiment
├── alpaca_news_connector.py   # Alpaca Markets free news API
├── dbnomics_connector.py      # DBnomics (IMF/OECD/Eurostat/ECB)
├── gpr_connector.py           # Geopolitical Risk Index (CSV)
└── talib_connector.py         # TA-Lib indicator calculation
```

### Phase 2 Connectors (Paid)

```
tradingagents/dataflows/connectors/
├── polygon_connector.py       # Polygon.io (OHLCV + options + streaming)
├── fmp_connector.py           # Financial Modeling Prep (fundamentals + 13F)
├── quiver_connector.py        # Quiver Quant (congressional + Reddit + lobbying)
├── unusual_whales_connector.py # Options flow + dark pool
├── fintel_connector.py        # 13F + short interest + insider trades
├── sec_api_connector.py       # SEC-API.io (structured filing extraction)
└── finra_connector.py         # FINRA short interest (free)
```

### Phase 3 Connectors

```
tradingagents/dataflows/connectors/
├── orats_connector.py         # IV analytics + forecasts
├── trading_economics_connector.py  # Global macro + calendar
├── sentimentrader_connector.py     # Composite sentiment indicators
└── polygon_ws_connector.py    # Real-time WebSocket streaming
```

---

## New Agent Tools to Create

### Social Analyst (fix the biggest gap)

```python
# NEW: tradingagents/agents/utils/social_tools.py
def get_social_sentiment(ticker: str) -> str:
    """Aggregate social sentiment from multiple sources."""
    # 1. ApeWisdom → Reddit mentions + rank
    # 2. Fear/Greed → market sentiment gauge
    # 3. AAII → individual investor survey
    # 4. Finnhub → social sentiment scores
    # 5. Quiver → congressional trades (if available)

def get_retail_flow(ticker: str) -> str:
    """Get retail investor positioning."""
    # 1. Unusual Whales → retail vs institutional flow
    # 2. FINRA → short interest
```

### Options Analyst (fix divergence gaps)

```python
# EXTEND: tradingagents/agents/utils/divergence_tools.py
def get_options_flow(ticker: str) -> str:
    """Unusual options activity detection."""
    # 1. Unusual Whales → large block trades
    # 2. Dark pool prints
    # 3. Put/call ratio trends

def get_iv_analytics(ticker: str) -> str:
    """Implied volatility analysis."""
    # 1. ORATS → IV rank, IV percentile, IV forecast
    # 2. py_vollib → Greeks calculation
    # 3. Term structure analysis
```

### News Analyst (add NLP sentiment)

```python
# EXTEND: tradingagents/agents/utils/news_tools.py
def get_news_with_sentiment(ticker: str) -> str:
    """News + FinBERT sentiment scoring."""
    # 1. Alpaca News / Finnhub → raw articles
    # 2. FinBERT → score each article
    # 3. Return articles with sentiment scores
```

### Macro Analyst (go global)

```python
# EXTEND: tradingagents/agents/utils/macro_tools.py
def get_global_macro(trade_date: str) -> str:
    """Global macro indicators beyond FRED."""
    # 1. DBnomics → ECB rates, EU CPI, global GDP
    # 2. BIS → global credit cycle
    # 3. GPR Index → geopolitical risk
    # 4. Trading Economics → economic calendar
```

---

## Data Budget Summary

| Phase | Monthly Cost | What You Get |
|-------|-------------|-------------|
| 1 (Free) | $0 | Fix all gaps, FinBERT sentiment, TA-Lib, global macro |
| 2 (Production) | ~$283 | Reliable OHLCV, fundamentals, congressional, options flow, short interest |
| 3 (Enhanced) | ~$879 total | Real-time streaming, IV analytics, global macro calendar, 20K sentiment indicators |
| 4 (Crypto+Broker) | ~$978 total | Crypto support, live trading execution |
| 5 (Enterprise) | $100K+ | Credit card data, institutional flow, academic-grade IV |

---

## Implementation Priority

1. **IMMEDIATE**: Wire existing connectors (Social Analyst is useless without this)
2. **WEEK 1**: Deploy FinBERT + Alpaca News (free news sentiment pipeline)
3. **WEEK 2**: Add TA-Lib + py_vollib (indicator + Greeks upgrade)
4. **WEEK 3**: Add Polygon.io + FMP (replace yfinance for production)
5. **WEEK 4**: Add Quiver + Unusual Whales (congressional + options flow)
6. **MONTH 2**: Add ORATS + Trading Economics (IV analytics + global macro)

---

## Key Research Sources

- Market: [Polygon.io](https://polygon.io/), [Twelve Data](https://twelvedata.com/), [TA-Lib](https://ta-lib.org/)
- Social: [Quiver Quant](https://quiverquant.com/), [FinBERT](https://huggingface.co/ProsusAI/finbert), [Finnhub](https://finnhub.io/)
- Options: [Unusual Whales](https://unusualwhales.com/), [ORATS](https://orats.com/), [py_vollib](https://vollib.org/)
- Fundamentals: [FMP](https://financialmodelingprep.com/), [SEC-API.io](https://sec-api.io/), [Fintel](https://fintel.io/)
- Macro: [DBnomics](https://db.nomics.world/), [Trading Economics](https://tradingeconomics.com/), [GPR Index](https://www.matteoiacoviello.com/gpr.htm)
