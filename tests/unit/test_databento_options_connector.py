"""Unit tests for the Databento OPRA options data connector."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helper: build a fake BBO DataFrame that mimics Databento OPRA output
# ---------------------------------------------------------------------------

def _make_bbo_df(ticker: str = "AAPL", strikes: list[float] | None = None) -> pd.DataFrame:
    """Create a synthetic BBO DataFrame with OPRA-style symbols."""
    if strikes is None:
        strikes = [200.0, 210.0, 220.0]

    rows = []
    for strike in strikes:
        strike_code = f"{int(strike * 1000):08d}"
        for opt_type, code in [("call", "C"), ("put", "P")]:
            symbol = f"{ticker}  260501{code}{strike_code}"
            rows.append({
                "ts_event": pd.Timestamp("2026-05-01 10:00:00"),
                "symbol": symbol,
                "bid_px_00": 5.0 * 1e9,
                "ask_px_00": 5.5 * 1e9,
                "bid_sz_00": 100,
                "ask_sz_00": 50,
            })
    return pd.DataFrame(rows)


def _make_trades_df(ticker: str = "AAPL") -> pd.DataFrame:
    """Create a synthetic trades DataFrame."""
    return pd.DataFrame([
        {
            "ts_event": pd.Timestamp("2026-05-01 10:00:00"),
            "symbol": f"{ticker}  260501C00200000",
            "price": 5.25,
            "size": 50,
        },
        {
            "ts_event": pd.Timestamp("2026-05-01 10:01:00"),
            "symbol": f"{ticker}  260501P00200000",
            "price": 3.10,
            "size": 200,  # large trade
        },
        {
            "ts_event": pd.Timestamp("2026-05-01 10:02:00"),
            "symbol": f"{ticker}  260501C00210000",
            "price": 2.75,
            "size": 30,
        },
    ])


# ---------------------------------------------------------------------------
# Connector import — guard against missing databento package
# ---------------------------------------------------------------------------

@pytest.fixture
def connector():
    """Create a DatabentoOptionsConnector with API key patched."""
    with patch.dict(os.environ, {"DATABENTO_API_KEY": "test-key-123"}):
        from tradingagents.dataflows.connectors.databento_options_connector import (
            DatabentoOptionsConnector,
        )
        conn = DatabentoOptionsConnector()
        conn._connected = True
        return conn


# ---------------------------------------------------------------------------
# Tests: Properties
# ---------------------------------------------------------------------------

class TestConnectorProperties:
    def test_name(self, connector):
        assert connector.name == "databento-options"

    def test_tier(self, connector):
        assert connector.tier == 2

    def test_categories(self, connector):
        from tradingagents.dataflows.connectors.base import ConnectorCategory
        assert ConnectorCategory.OPTIONS in connector.categories

    def test_probe_data_type(self, connector):
        assert connector.probe_data_type == "chains"


# ---------------------------------------------------------------------------
# Tests: OPRA symbol parsing
# ---------------------------------------------------------------------------

class TestOPRAParsing:
    def test_parse_call_symbol(self):
        from tradingagents.dataflows.connectors.databento_options_connector import (
            _parse_opra_symbol,
        )
        result = _parse_opra_symbol("AAPL  260501C00200000")
        assert result["underlying"] == "AAPL"
        assert result["expiration"] == "2026-05-01"
        assert result["option_type"] == "call"
        assert result["strike"] == 200.0

    def test_parse_put_symbol(self):
        from tradingagents.dataflows.connectors.databento_options_connector import (
            _parse_opra_symbol,
        )
        result = _parse_opra_symbol("TSLA  260815P00150500")
        assert result["underlying"] == "TSLA"
        assert result["expiration"] == "2026-08-15"
        assert result["option_type"] == "put"
        assert result["strike"] == 150.5

    def test_parse_invalid_symbol(self):
        from tradingagents.dataflows.connectors.databento_options_connector import (
            _parse_opra_symbol,
        )
        result = _parse_opra_symbol("INVALID")
        assert result["underlying"] == "INVALID"
        assert result["expiration"] is None


# ---------------------------------------------------------------------------
# Tests: Chain aggregation
# ---------------------------------------------------------------------------

class TestChainAggregation:
    def test_aggregate_chain_returns_strikes(self, connector):
        df = _make_bbo_df("AAPL", strikes=[200.0, 210.0])
        df = connector._enrich_opra_fields(df)
        chain = connector._aggregate_chain(df)
        assert len(chain) == 2
        assert chain[0]["strike"] == 200.0
        assert chain[1]["strike"] == 210.0

    def test_aggregate_chain_has_call_and_put(self, connector):
        df = _make_bbo_df("AAPL", strikes=[200.0])
        df = connector._enrich_opra_fields(df)
        chain = connector._aggregate_chain(df)
        assert len(chain) == 1
        row = chain[0]
        assert "call_bid" in row
        assert "put_bid" in row

    def test_aggregate_empty_df(self, connector):
        chain = connector._aggregate_chain(pd.DataFrame())
        assert chain == []


# ---------------------------------------------------------------------------
# Tests: Fetch dispatch
# ---------------------------------------------------------------------------

class TestFetchDispatch:
    def test_unknown_data_type_raises(self, connector):
        from tradingagents.dataflows.connectors.base import ConnectorError
        with pytest.raises(ConnectorError, match="Unknown data_type"):
            connector._fetch_impl("AAPL", {"data_type": "invalid"})

    def test_chains_dispatch(self, connector):
        """Verify that data_type=chains calls _fetch_chains."""
        with patch.object(connector, "_download_bbo", return_value=_make_bbo_df("AAPL")):
            result = connector._fetch_impl("AAPL", {"data_type": "chains", "lookback_days": 1})
            assert result["source"] == "databento-options"
            assert result["ticker"] == "AAPL"
            assert "chain" in result
            assert "put_call_ratio" in result

    def test_flow_dispatch(self, connector):
        """Verify that data_type=flow calls _fetch_flow."""
        with patch.object(connector, "_download_trades", return_value=_make_trades_df("AAPL")):
            result = connector._fetch_impl("AAPL", {"data_type": "flow", "lookback_days": 1})
            assert result["source"] == "databento-options"
            assert result["ticker"] == "AAPL"
            assert "put_call_ratio" in result
            assert "sentiment" in result


# ---------------------------------------------------------------------------
# Tests: Flow analysis
# ---------------------------------------------------------------------------

class TestFlowAnalysis:
    def test_sentiment_bullish_when_low_pc_ratio(self, connector):
        """Low put/call ratio → BULLISH."""
        # More call volume than puts
        df = pd.DataFrame([
            {"ts_event": pd.Timestamp.now(), "symbol": "AAPL  260501C00200000", "price": 5.0, "size": 500},
            {"ts_event": pd.Timestamp.now(), "symbol": "AAPL  260501P00200000", "price": 3.0, "size": 100},
        ])
        with patch.object(connector, "_download_trades", return_value=df):
            result = connector._fetch_flow("AAPL", {"lookback_days": 1})
            assert result["sentiment"] == "BULLISH"
            assert result["put_call_ratio"] < 0.7

    def test_sentiment_bearish_when_high_pc_ratio(self, connector):
        """High put/call ratio → BEARISH."""
        df = pd.DataFrame([
            {"ts_event": pd.Timestamp.now(), "symbol": "AAPL  260501C00200000", "price": 5.0, "size": 100},
            {"ts_event": pd.Timestamp.now(), "symbol": "AAPL  260501P00200000", "price": 3.0, "size": 500},
        ])
        with patch.object(connector, "_download_trades", return_value=df):
            result = connector._fetch_flow("AAPL", {"lookback_days": 1})
            assert result["sentiment"] == "BEARISH"
            assert result["put_call_ratio"] > 1.3

    def test_large_trade_detection(self, connector):
        """Trades >= threshold count as large."""
        with patch.object(connector, "_download_trades", return_value=_make_trades_df("AAPL")):
            result = connector._fetch_flow("AAPL", {
                "lookback_days": 1,
                "large_trade_threshold": 100,
            })
            assert result["large_trade_count"] >= 1
            assert result["large_put_volume"] > 0


# ---------------------------------------------------------------------------
# Tests: Cost tracking pricing fix
# ---------------------------------------------------------------------------

class TestCostTrackerPricing:
    """Verify that model aliases used in runtime_config have correct pricing."""

    @pytest.fixture(autouse=True)
    def _load_pricing(self):
        # Import cost_tracker directly to avoid gateway/__init__ chain
        import importlib
        mod = importlib.import_module("tradingagents.gateway.cost_tracker")
        self.PRICING = mod.PRICING

    def test_sonnet_alias_in_pricing(self):
        assert "claude-sonnet-4-5" in self.PRICING
        assert self.PRICING["claude-sonnet-4-5"]["input"] == 3.00
        assert self.PRICING["claude-sonnet-4-5"]["output"] == 15.00

    def test_opus_alias_in_pricing(self):
        assert "claude-opus-4-1-20250805" in self.PRICING
        assert self.PRICING["claude-opus-4-1-20250805"]["input"] == 15.00

    def test_haiku_alias_in_pricing(self):
        assert "claude-haiku-4-5" in self.PRICING
