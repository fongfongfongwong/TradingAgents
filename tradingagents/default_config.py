import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    "backend_url": "https://api.openai.com/v1",
    # Provider-specific thinking configuration
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    # Output language for analyst reports and final decision
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Analyst selection
    "selected_analysts": ["market", "social", "news", "fundamentals", "options", "macro"],
    # ================================================================
    # DATA VENDOR CONFIGURATION
    # Category-level: default for all tools in category
    # Options per category listed in comments
    # ================================================================
    "data_vendors": {
        # Market data (OHLCV, quotes)
        # Options: yfinance (free), polygon (paid), alpha_vantage (freemium)
        "core_stock_apis": "yfinance",
        # Technical indicators
        # Options: yfinance (StockStats), talib (TA-Lib, faster), alpha_vantage
        "technical_indicators": "yfinance",
        # Fundamentals (financials, ratios)
        # Options: yfinance (free), fmp (paid, 30yr+), alpha_vantage, sec_edgar
        "fundamental_data": "yfinance",
        # News
        # Options: yfinance, finnhub (free tier), alpaca_news (free), fmp
        "news_data": "yfinance",
        # Social sentiment
        # Options: finnhub (free), quiver (paid), apewisdom (free)
        "social_data": "finnhub",
        # Options flow & unusual activity
        # Options: cboe (free, limited), unusual_whales (paid), orats (paid)
        "options_flow": "cboe",
        # Institutional holdings (13F)
        # Options: yfinance (free), fintel (paid), fmp (paid), sec_edgar
        "holdings_data": "yfinance",
        # Macro economics
        # Options: fred (free, US), dbnomics (free, global), trading_economics (paid)
        "macro_data": "fred",
        # Geopolitical risk
        # Options: gpr_index (free), epu_index (free)
        "geopolitical_data": "gpr_index",
        # Crypto
        # Options: binance (free), coingecko (free), cryptocompare (freemium)
        "crypto_data": "coingecko",
    },
    # Tool-level overrides (takes precedence over category-level)
    "tool_vendors": {},
    # ================================================================
    # API KEYS — read from environment variables
    # Fill .env file, these will be picked up automatically
    # ================================================================
    "api_keys": {
        "polygon": os.environ.get("POLYGON_API_KEY", ""),
        "alpha_vantage": os.environ.get("ALPHA_VANTAGE_API_KEY", ""),
        "fmp": os.environ.get("FMP_API_KEY", ""),
        "sec_api": os.environ.get("SEC_API_KEY", ""),
        "quiver": os.environ.get("QUIVER_API_KEY", ""),
        "finnhub": os.environ.get("FINNHUB_API_KEY", ""),
        "unusual_whales": os.environ.get("UNUSUAL_WHALES_API_KEY", ""),
        "orats": os.environ.get("ORATS_API_KEY", ""),
        "fintel": os.environ.get("FINTEL_API_KEY", ""),
        "fred": os.environ.get("FRED_API_KEY", ""),
        "trading_economics": os.environ.get("TRADING_ECONOMICS_API_KEY", ""),
        "binance": os.environ.get("BINANCE_API_KEY", ""),
        "coingecko": os.environ.get("COINGECKO_API_KEY", ""),
        "alpaca": os.environ.get("ALPACA_API_KEY", ""),
    },
    # ================================================================
    # CONNECTOR REGISTRY
    # ================================================================
    "connector_registry": {
        "enabled": True,
        "enabled_tiers": [1],  # Tier 1 = free, Tier 2 = paid, Tier 3 = premium, Tier 4 = enterprise
        "cache_ttl": {
            "ohlcv": 60,
            "news": 120,
            "fundamentals": 3600,
            "macro": 1800,
            "divergence": 300,
            "social": 300,
            "options_flow": 120,
            "holdings": 3600,
            "geopolitical": 86400,
        },
    },
    # Memory backend configuration
    "memory_backend": "bm25",
    "memory_config": {
        "retrieval_mode": "hybrid",
        "bm25_weight": 0.5,
        "vector_weight": 0.5,
        "persistence": False,
        "db_path": "./data/memories.db",
    },
    # LLM Gateway - tiered model routing and cost control
    "llm_gateway": {
        "enabled": False,
        "tier_models": {
            "extract": "gpt-4o-mini",
            "reason": "gpt-4o",
            "decide": "gpt-4o",
        },
        "budget_limit": None,
    },
}
