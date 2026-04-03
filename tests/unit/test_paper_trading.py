"""Tests for the paper trading execution layer."""

import json
import os
import tempfile

import pytest

from tradingagents.execution.paper_broker import PaperBroker
from tradingagents.execution.trade_journal import TradeJournal
from tradingagents.execution.alpaca_broker import AlpacaBroker


# ──────────────────────────────────────────────
# PaperBroker Tests
# ──────────────────────────────────────────────

class TestPaperBrokerBuy:
    def test_buy_order_fills_with_slippage_and_commission(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.001, commission_pct=0.001)
        result = broker.submit_order("AAPL", "BUY", 10, 150.0)

        assert result["status"] == "filled"
        assert result["ticker"] == "AAPL"
        assert result["action"] == "BUY"
        assert result["shares"] == 10
        # fill_price = 150 * 1.001 = 150.15
        assert abs(result["fill_price"] - 150.15) < 0.01
        # commission = 150.15 * 10 * 0.001 = ~1.5015
        assert result["commission"] > 0
        assert result["order_id"] is not None
        assert result["timestamp"] is not None

    def test_buy_deducts_cash_correctly(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.001, commission_pct=0.001)
        broker.submit_order("AAPL", "BUY", 10, 150.0)
        # total cost = 150.15 * 10 = 1501.5, commission = ~1.5015
        # cash should be 100000 - 1501.5 - 1.5015 ~ 98497.0
        assert broker.cash < 100000
        assert broker.cash > 98000

    def test_buy_creates_position(self):
        broker = PaperBroker(initial_capital=100000)
        broker.submit_order("AAPL", "BUY", 10, 150.0)
        assert "AAPL" in broker.positions
        assert broker.positions["AAPL"]["shares"] == 10

    def test_buy_multiple_lots_averages_cost(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.0, commission_pct=0.0)
        broker.submit_order("AAPL", "BUY", 10, 100.0)
        broker.submit_order("AAPL", "BUY", 10, 200.0)
        assert broker.positions["AAPL"]["shares"] == 20
        assert abs(broker.positions["AAPL"]["avg_cost"] - 150.0) < 0.01


class TestPaperBrokerSell:
    def test_sell_order_fills_with_slippage(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.001, commission_pct=0.001)
        broker.submit_order("AAPL", "BUY", 10, 150.0)
        result = broker.submit_order("AAPL", "SELL", 5, 160.0)

        assert result["status"] == "filled"
        assert result["action"] == "SELL"
        # fill_price = 160 * 0.999 = 159.84
        assert abs(result["fill_price"] - 159.84) < 0.01
        assert broker.positions["AAPL"]["shares"] == 5

    def test_sell_all_removes_position(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.0, commission_pct=0.0)
        broker.submit_order("AAPL", "BUY", 10, 100.0)
        broker.submit_order("AAPL", "SELL", 10, 110.0)
        assert "AAPL" not in broker.positions

    def test_sell_adds_cash(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.0, commission_pct=0.0)
        broker.submit_order("AAPL", "BUY", 10, 100.0)
        cash_after_buy = broker.cash
        broker.submit_order("AAPL", "SELL", 10, 110.0)
        assert broker.cash > cash_after_buy


class TestPaperBrokerValidation:
    def test_cannot_sell_more_than_owned(self):
        broker = PaperBroker(initial_capital=100000)
        broker.submit_order("AAPL", "BUY", 5, 100.0)
        with pytest.raises(ValueError, match="Cannot sell"):
            broker.submit_order("AAPL", "SELL", 10, 110.0)

    def test_cannot_sell_without_position(self):
        broker = PaperBroker(initial_capital=100000)
        with pytest.raises(ValueError, match="Cannot sell"):
            broker.submit_order("AAPL", "SELL", 1, 100.0)

    def test_cannot_buy_with_insufficient_cash(self):
        broker = PaperBroker(initial_capital=1000)
        with pytest.raises(ValueError, match="Insufficient cash"):
            broker.submit_order("AAPL", "BUY", 100, 150.0)

    def test_invalid_action_raises(self):
        broker = PaperBroker()
        with pytest.raises(ValueError, match="Invalid action"):
            broker.submit_order("AAPL", "SHORT", 10, 100.0)

    def test_zero_shares_raises(self):
        broker = PaperBroker()
        with pytest.raises(ValueError, match="positive"):
            broker.submit_order("AAPL", "BUY", 0, 100.0)


class TestPaperBrokerPositionAndPortfolio:
    def test_get_position_returns_correct_values(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.0, commission_pct=0.0)
        broker.submit_order("AAPL", "BUY", 10, 100.0)
        broker.update_prices({"AAPL": 110.0})
        pos = broker.get_position("AAPL")

        assert pos["ticker"] == "AAPL"
        assert pos["shares"] == 10
        assert abs(pos["avg_cost"] - 100.0) < 0.01
        assert abs(pos["current_value"] - 1100.0) < 0.01
        assert abs(pos["unrealized_pnl"] - 100.0) < 0.01

    def test_get_position_no_position(self):
        broker = PaperBroker()
        pos = broker.get_position("AAPL")
        assert pos["shares"] == 0
        assert pos["unrealized_pnl"] == 0.0

    def test_get_portfolio_total_value(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.0, commission_pct=0.0)
        broker.submit_order("AAPL", "BUY", 10, 100.0)
        broker.update_prices({"AAPL": 110.0})
        portfolio = broker.get_portfolio()

        assert portfolio["cash"] == 99000.0  # 100000 - 1000
        assert abs(portfolio["total_value"] - 100100.0) < 0.01  # 99000 + 1100
        assert abs(portfolio["unrealized_pnl"] - 100.0) < 0.01

    def test_update_prices_updates_pnl(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.0, commission_pct=0.0)
        broker.submit_order("AAPL", "BUY", 10, 100.0)

        broker.update_prices({"AAPL": 90.0})
        pos = broker.get_position("AAPL")
        assert pos["unrealized_pnl"] == -100.0

        broker.update_prices({"AAPL": 120.0})
        pos = broker.get_position("AAPL")
        assert pos["unrealized_pnl"] == 200.0


class TestPaperBrokerCloseAndHistory:
    def test_close_position_works(self):
        broker = PaperBroker(initial_capital=100000, slippage_pct=0.0, commission_pct=0.0)
        broker.submit_order("AAPL", "BUY", 10, 100.0)
        result = broker.close_position("AAPL", 110.0)
        assert result["status"] == "filled"
        assert result["shares"] == 10
        assert "AAPL" not in broker.positions

    def test_close_nonexistent_position_raises(self):
        broker = PaperBroker()
        with pytest.raises(ValueError, match="No position"):
            broker.close_position("AAPL", 100.0)

    def test_trade_history_recorded(self):
        broker = PaperBroker(initial_capital=100000)
        broker.submit_order("AAPL", "BUY", 10, 100.0)
        broker.submit_order("AAPL", "SELL", 5, 110.0)
        history = broker.get_trade_history()
        assert len(history) == 2
        assert history[0]["action"] == "BUY"
        assert history[1]["action"] == "SELL"


# ──────────────────────────────────────────────
# TradeJournal Tests
# ──────────────────────────────────────────────

class TestTradeJournal:
    def _make_trade(self, ticker="AAPL", action="BUY", fill_price=100.0, shares=10,
                    commission=0.1, timestamp="2025-01-15T10:00:00"):
        return {
            "order_id": "abc123",
            "status": "filled",
            "ticker": ticker,
            "action": action,
            "fill_price": fill_price,
            "shares": shares,
            "commission": commission,
            "timestamp": timestamp,
        }

    def test_record_and_get_trades(self):
        journal = TradeJournal()
        trade = self._make_trade()
        journal.record(trade)
        assert len(journal.get_trades()) == 1
        assert journal.get_trades()[0]["ticker"] == "AAPL"

    def test_filter_by_ticker(self):
        journal = TradeJournal()
        journal.record(self._make_trade(ticker="AAPL"))
        journal.record(self._make_trade(ticker="GOOG"))
        journal.record(self._make_trade(ticker="AAPL"))

        aapl_trades = journal.get_trades(ticker="AAPL")
        assert len(aapl_trades) == 2
        goog_trades = journal.get_trades(ticker="GOOG")
        assert len(goog_trades) == 1

    def test_filter_by_start_date(self):
        journal = TradeJournal()
        journal.record(self._make_trade(timestamp="2025-01-01T10:00:00"))
        journal.record(self._make_trade(timestamp="2025-06-01T10:00:00"))
        journal.record(self._make_trade(timestamp="2025-12-01T10:00:00"))

        recent = journal.get_trades(start_date="2025-05-01")
        assert len(recent) == 2

    def test_summary_calculates_correctly(self):
        journal = TradeJournal()
        # Buy AAPL at 100, sell at 110 -> profit
        journal.record(self._make_trade(ticker="AAPL", action="BUY", fill_price=100.0,
                                        shares=10, commission=1.0))
        journal.record(self._make_trade(ticker="AAPL", action="SELL", fill_price=110.0,
                                        shares=10, commission=1.1))

        summary = journal.summary()
        assert summary["total_trades"] == 2
        # PNL = (110-100)*10 - 1.0 - 1.1 = 97.9
        assert abs(summary["total_pnl"] - 97.9) < 0.01
        assert summary["win_rate"] == 1.0
        assert "AAPL" in summary["by_ticker"]

    def test_summary_empty_journal(self):
        journal = TradeJournal()
        summary = journal.summary()
        assert summary["total_trades"] == 0
        assert summary["total_pnl"] == 0.0
        assert summary["win_rate"] == 0.0

    def test_save_and_load_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "journal.json")
            journal = TradeJournal(journal_path=path)
            journal.record(self._make_trade())
            journal.record(self._make_trade(ticker="GOOG"))
            journal.save()

            # Load into new instance
            journal2 = TradeJournal(journal_path=path)
            journal2.load()
            assert len(journal2.get_trades()) == 2
            assert journal2.get_trades()[1]["ticker"] == "GOOG"

    def test_export_csv_format(self):
        journal = TradeJournal()
        journal.record(self._make_trade())
        csv_str = journal.export_csv()
        lines = csv_str.strip().split("\n")
        assert len(lines) == 2  # header + 1 row
        assert "order_id" in lines[0]
        assert "AAPL" in lines[1]

    def test_export_csv_empty(self):
        journal = TradeJournal()
        assert journal.export_csv() == ""


# ──────────────────────────────────────────────
# AlpacaBroker Tests
# ──────────────────────────────────────────────

class TestAlpacaBroker:
    def test_submit_order_raises(self):
        broker = AlpacaBroker()
        with pytest.raises(NotImplementedError, match="Phase D"):
            broker.submit_order("AAPL", "BUY", 10, 150.0)

    def test_get_position_raises(self):
        broker = AlpacaBroker()
        with pytest.raises(NotImplementedError, match="Phase D"):
            broker.get_position("AAPL")

    def test_get_portfolio_raises(self):
        broker = AlpacaBroker()
        with pytest.raises(NotImplementedError, match="Phase D"):
            broker.get_portfolio()

    def test_update_prices_raises(self):
        broker = AlpacaBroker()
        with pytest.raises(NotImplementedError, match="Phase D"):
            broker.update_prices({"AAPL": 150.0})

    def test_close_position_raises(self):
        broker = AlpacaBroker()
        with pytest.raises(NotImplementedError, match="Phase D"):
            broker.close_position("AAPL", 150.0)

    def test_get_trade_history_raises(self):
        broker = AlpacaBroker()
        with pytest.raises(NotImplementedError, match="Phase D"):
            broker.get_trade_history()

    def test_constructor_accepts_params(self):
        broker = AlpacaBroker(api_key="key", secret_key="secret", paper=False)
        assert broker.api_key == "key"
        assert broker.secret_key == "secret"
        assert broker.paper is False
