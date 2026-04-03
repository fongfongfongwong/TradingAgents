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
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Analyst selection -- all six available; remove entries to disable
    "selected_analysts": ["market", "social", "news", "fundamentals", "options", "macro"],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Memory backend configuration
    "memory_backend": "bm25",  # "bm25" (original) or "hybrid" (BM25 + vector)
    "memory_config": {
        "retrieval_mode": "hybrid",
        "bm25_weight": 0.5,
        "vector_weight": 0.5,
        "persistence": False,  # SQLite persistence
        "db_path": "./data/memories.db",
    },
    # LLM Gateway - tiered model routing and cost control
    "llm_gateway": {
        "enabled": False,  # Set True to use tiered routing
        "tier_models": {
            "extract": "gpt-4o-mini",
            "reason": "gpt-4o",
            "decide": "gpt-4o",
        },
        "budget_limit": None,  # USD limit per analysis, None = unlimited
    },
    # Connector registry configuration
    "connector_registry": {
        "enabled": True,
        "enabled_tiers": [1],
        "cache_ttl": {
            "ohlcv": 60,
            "news": 120,
            "fundamentals": 3600,
            "macro": 1800,
            "divergence": 300,
        },
    },
}
