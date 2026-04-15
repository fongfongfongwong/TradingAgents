"""High-volatility universe screener package.

Step 1 of FLAB MASA v3: ranks US equities and ETFs by realized volatility and
returns a curated daily shortlist (top 20 equities + top 20 ETFs) produced by
a two-stage pipeline (quant ranking -> LLM filter).
"""

from .volatility_screener import (
    ScreenerResult,
    VolRank,
    run_screener,
)

__all__ = ["ScreenerResult", "VolRank", "run_screener"]
