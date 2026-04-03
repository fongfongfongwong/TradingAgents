"""Pydantic v2 normalized data schemas for the connector framework.

All connectors return data conforming to these schemas, regardless of vendor.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# OHLCV / Market Data
# ---------------------------------------------------------------------------

class OHLCVBar(BaseModel):
    """Single OHLCV price bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | float = 0
    ticker: str = ""

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class OHLCVSeries(BaseModel):
    """Time series of OHLCV bars for a single instrument."""
    ticker: str
    bars: list[OHLCVBar] = Field(default_factory=list)
    timeframe: str = "1d"  # 1m, 5m, 1h, 1d, 1w, 1M
    source: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    total_records: int = 0

    def model_post_init(self, __context: Any) -> None:
        if self.total_records == 0 and self.bars:
            self.total_records = len(self.bars)


# ---------------------------------------------------------------------------
# Technical Indicators
# ---------------------------------------------------------------------------

class TechnicalIndicators(BaseModel):
    """Technical indicator values at a point in time."""
    ticker: str
    indicators: dict[str, float | None] = Field(default_factory=dict)
    timestamp: datetime | None = None
    lookback_days: int = 30
    source: str = ""


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

class NewsArticle(BaseModel):
    """Single news article with optional sentiment."""
    title: str
    summary: str = ""
    source: str = ""
    url: str = ""
    published_at: datetime | None = None
    tickers: list[str] = Field(default_factory=list)
    sentiment_score: float | None = None  # -1.0 (bearish) to +1.0 (bullish)
    sentiment_label: str = ""  # positive, negative, neutral


class NewsFeed(BaseModel):
    """Collection of news articles."""
    articles: list[NewsArticle] = Field(default_factory=list)
    query: str = ""
    source: str = ""
    total_results: int = 0

    def model_post_init(self, __context: Any) -> None:
        if self.total_results == 0 and self.articles:
            self.total_results = len(self.articles)


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

class SentimentScore(BaseModel):
    """Sentiment measurement from a single source."""
    ticker: str
    score: float = Field(ge=-1.0, le=1.0)  # -1 bearish to +1 bullish
    label: str = ""  # bullish, bearish, neutral
    source: str = ""
    timestamp: datetime | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------

class FinancialStatement(BaseModel):
    """Standardized financial statement data."""
    ticker: str
    period: str = ""  # "2024-Q4", "2024-FY"
    statement_type: str = ""  # income_statement, balance_sheet, cash_flow, overview
    data: dict[str, Any] = Field(default_factory=dict)
    currency: str = "USD"
    source: str = ""
    as_of_date: datetime | None = None


# ---------------------------------------------------------------------------
# Insider Transactions
# ---------------------------------------------------------------------------

class InsiderTransaction(BaseModel):
    """Single insider trading transaction."""
    ticker: str
    insider_name: str = ""
    title: str = ""  # CEO, CFO, Director, etc.
    transaction_type: str = ""  # Purchase, Sale, Option Exercise
    shares: float = 0
    value: float = 0
    price_per_share: float | None = None
    date: datetime | None = None
    source: str = ""


class InsiderTransactionList(BaseModel):
    """Collection of insider transactions."""
    ticker: str
    transactions: list[InsiderTransaction] = Field(default_factory=list)
    source: str = ""


# ---------------------------------------------------------------------------
# Macroeconomic
# ---------------------------------------------------------------------------

class MacroDataPoint(BaseModel):
    """Single macroeconomic data point."""
    series_id: str  # e.g. "GDP", "UNRATE", "FEDFUNDS"
    value: float
    date: datetime
    source: str = ""


class MacroSeries(BaseModel):
    """Time series of macro data."""
    series_id: str
    name: str = ""
    data_points: list[MacroDataPoint] = Field(default_factory=list)
    frequency: str = ""  # daily, weekly, monthly, quarterly
    units: str = ""
    source: str = ""


# ---------------------------------------------------------------------------
# Divergence
# ---------------------------------------------------------------------------

class DivergenceRaw(BaseModel):
    """Raw divergence signal from a single source."""
    ticker: str = ""  # Empty for market-wide signals
    dimension: str = ""  # institutional, options, price_action, news, retail
    value: float = Field(ge=-1.0, le=1.0)  # -1 extreme bear to +1 extreme bull
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = ""
    timestamp: datetime | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Connector Response Wrapper
# ---------------------------------------------------------------------------

class ConnectorResponse(BaseModel):
    """Wrapper around any connector response with metadata."""
    data: Any
    source: str
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    cached: bool = False
    latency_ms: float = 0.0
    connector_name: str = ""
    ticker: str = ""
