"""Unit tests for the Quiver institutional source + its materializer/agent
integration (Feature P0-B).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.data.sources import quiver_institutional as q_src
from tradingagents.data.sources.quiver_institutional import (
    QuiverInstitutionalResult,
    fetch_quiver_institutional,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    q_src._clear_cache_for_testing()
    yield
    q_src._clear_cache_for_testing()


def _now_iso(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _mk_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _build_side_effect(
    congress=None, contracts=None, lobbying=None, insiders=None
):
    """Build a requests.Session.get side_effect dispatching by endpoint."""

    def _get(url, headers=None, timeout=None):  # noqa: ARG001
        if "congresstrading" in url:
            return _mk_response(congress if congress is not None else [])
        if "govcontractsall" in url:
            return _mk_response(contracts if contracts is not None else [])
        if "lobbying" in url:
            return _mk_response(lobbying if lobbying is not None else [])
        if "live/insiders" in url or "insiders" in url:
            return _mk_response(insiders if insiders is not None else [])
        raise AssertionError(f"unexpected url: {url}")

    return _get


# ---------------------------------------------------------------------------
# 1. No API key -> fetched_ok=False
# ---------------------------------------------------------------------------


def test_missing_api_key_returns_empty(monkeypatch):
    monkeypatch.delenv("QUIVER_API_KEY", raising=False)
    result = fetch_quiver_institutional("AAPL")
    assert isinstance(result, QuiverInstitutionalResult)
    assert result.fetched_ok is False
    assert result.error == "missing_api_key"
    assert result.congressional_net_buys_30d == 0
    assert result.congressional_top_buyers == []


# ---------------------------------------------------------------------------
# 2 + 3 + 4. Full aggregation with synthetic endpoint responses
# ---------------------------------------------------------------------------


def test_full_aggregation(monkeypatch):
    monkeypatch.setenv("QUIVER_API_KEY", "test-key")

    congress = [
        # 5 BUY
        {"ReportDate": _now_iso(1), "Transaction": "Purchase", "Representative": "Alice"},
        {"ReportDate": _now_iso(2), "Transaction": "Purchase", "Representative": "Alice"},
        {"ReportDate": _now_iso(3), "Transaction": "Purchase", "Representative": "Bob"},
        {"ReportDate": _now_iso(4), "Transaction": "Purchase", "Representative": "Carol"},
        {"ReportDate": _now_iso(5), "Transaction": "Purchase", "Representative": "Dave"},
        # 3 SELL
        {"ReportDate": _now_iso(6), "Transaction": "Sale", "Representative": "Eve"},
        {"ReportDate": _now_iso(7), "Transaction": "Sale (Full)", "Representative": "Eve"},
        {"ReportDate": _now_iso(8), "Transaction": "Sale (Partial)", "Representative": "Frank"},
        # Outside window -> excluded
        {"ReportDate": _now_iso(31), "Transaction": "Purchase", "Representative": "Ghost"},
    ]
    contracts = [
        {"Date": _now_iso(10), "Amount": 1_000_000, "Agency": "DoD"},
        {"Date": _now_iso(20), "Amount": 500_000, "Agency": "GSA"},
        {"Date": _now_iso(100), "Amount": 999_999, "Agency": "DoE"},  # out of window
    ]
    lobbying = [
        {"Year": 2026, "Quarter": 1, "Amount": 150_000, "Client": "AAPL"},
        {"Year": 2026, "Quarter": 1, "Amount": 100_000, "Client": "AAPL"},
        {"Year": 2025, "Quarter": 4, "Amount": 999_999, "Client": "AAPL"},  # older
    ]
    insiders = [
        {"Ticker": "AAPL", "Date": _now_iso(5), "AcquiredDisposedCode": "A", "Name": "Tim Cook"},
        {"Ticker": "AAPL", "Date": _now_iso(6), "AcquiredDisposedCode": "A", "Name": "Tim Cook"},
        {"Ticker": "AAPL", "Date": _now_iso(7), "AcquiredDisposedCode": "A", "Name": "Jeff Williams"},
        {"Ticker": "AAPL", "Date": _now_iso(8), "AcquiredDisposedCode": "A", "Name": "Luca Maestri"},
        {"Ticker": "AAPL", "Date": _now_iso(9), "AcquiredDisposedCode": "D", "Name": "Other"},
        # Different ticker should be ignored.
        {"Ticker": "MSFT", "Date": _now_iso(5), "AcquiredDisposedCode": "A", "Name": "Ignored"},
    ]

    with patch.object(
        q_src._SESSION,
        "get",
        side_effect=_build_side_effect(
            congress=congress,
            contracts=contracts,
            lobbying=lobbying,
            insiders=insiders,
        ),
    ):
        r = fetch_quiver_institutional("AAPL")

    assert r.fetched_ok is True
    assert r.error is None

    # Congressional: 5 buys - 3 sells = 2
    assert r.congressional_net_buys_30d == 2
    # Top buyer by txn count: Alice (2), then Bob/Carol/Dave tied with 1
    assert r.congressional_top_buyers[0] == "Alice"
    assert len(r.congressional_top_buyers) == 3
    assert "Eve" in r.congressional_top_sellers  # Eve=2, Frank=1

    # Contracts
    assert r.govt_contracts_count_90d == 2
    assert r.govt_contracts_total_usd == 1_500_000.0

    # Lobbying: most recent quarter (2026 Q1) = 150k + 100k
    assert r.lobbying_usd_last_quarter == 250_000.0

    # Insiders: 4 A - 1 D = 3
    assert r.insider_net_txns_90d == 3
    assert r.insider_top_buyers[0] == "Tim Cook"


# ---------------------------------------------------------------------------
# 3. Top buyer aggregation: unique names, ranked by txn count
# ---------------------------------------------------------------------------


def test_top_buyer_aggregation_ranks_by_count(monkeypatch):
    monkeypatch.setenv("QUIVER_API_KEY", "test-key")

    congress = [
        {"ReportDate": _now_iso(1), "Transaction": "Purchase", "Representative": "Alice"},
        {"ReportDate": _now_iso(2), "Transaction": "Purchase", "Representative": "Alice"},
        {"ReportDate": _now_iso(3), "Transaction": "Purchase", "Representative": "Alice"},
        {"ReportDate": _now_iso(4), "Transaction": "Purchase", "Representative": "Bob"},
        {"ReportDate": _now_iso(5), "Transaction": "Purchase", "Representative": "Bob"},
        {"ReportDate": _now_iso(6), "Transaction": "Purchase", "Representative": "Carol"},
        {"ReportDate": _now_iso(7), "Transaction": "Purchase", "Representative": "Dave"},
    ]
    with patch.object(
        q_src._SESSION, "get", side_effect=_build_side_effect(congress=congress)
    ):
        r = fetch_quiver_institutional("AAPL")

    assert r.fetched_ok is True
    # Alice (3) > Bob (2) > Carol or Dave (1); exactly 3 items
    assert r.congressional_top_buyers[:2] == ["Alice", "Bob"]
    assert len(r.congressional_top_buyers) == 3


# ---------------------------------------------------------------------------
# 4. Date filtering: entry 31 days old is excluded from 30d window
# ---------------------------------------------------------------------------


def test_date_filter_excludes_old_entries(monkeypatch):
    monkeypatch.setenv("QUIVER_API_KEY", "test-key")

    congress = [
        {"ReportDate": _now_iso(1), "Transaction": "Purchase", "Representative": "Alice"},
        {"ReportDate": _now_iso(31), "Transaction": "Purchase", "Representative": "Stale"},
    ]
    with patch.object(
        q_src._SESSION, "get", side_effect=_build_side_effect(congress=congress)
    ):
        r = fetch_quiver_institutional("AAPL")

    assert r.congressional_net_buys_30d == 1
    assert "Stale" not in r.congressional_top_buyers


# ---------------------------------------------------------------------------
# 5. Cache hit: 2nd call within TTL produces zero HTTP calls
# ---------------------------------------------------------------------------


def test_cache_hit_skips_http(monkeypatch):
    monkeypatch.setenv("QUIVER_API_KEY", "test-key")

    mock_get = MagicMock(side_effect=_build_side_effect())
    with patch.object(q_src._SESSION, "get", mock_get):
        first = fetch_quiver_institutional("AAPL")
        assert first.fetched_ok is True
        call_count_after_first = mock_get.call_count

        second = fetch_quiver_institutional("AAPL")
        assert second.fetched_ok is True
        # No extra calls the second time.
        assert mock_get.call_count == call_count_after_first


# ---------------------------------------------------------------------------
# 6. Partial failure: congress 500 but others ok -> fetched_ok=True,
#    congress fields are zeros
# ---------------------------------------------------------------------------


def test_partial_failure_congress_500(monkeypatch):
    monkeypatch.setenv("QUIVER_API_KEY", "test-key")

    import requests

    def _side_effect(url, headers=None, timeout=None):  # noqa: ARG001
        if "congresstrading" in url:
            resp = MagicMock()
            resp.status_code = 500
            err = requests.HTTPError("500 server error")
            err.response = resp
            resp.raise_for_status.side_effect = err
            return resp
        if "govcontractsall" in url:
            return _mk_response(
                [{"Date": _now_iso(5), "Amount": 2_000_000}]
            )
        if "lobbying" in url:
            return _mk_response(
                [{"Year": 2026, "Quarter": 1, "Amount": 50_000}]
            )
        if "live/insiders" in url or "insiders" in url:
            return _mk_response(
                [{"Ticker": "AAPL", "Date": _now_iso(5), "AcquiredDisposedCode": "A", "Name": "Alice"}]
            )
        raise AssertionError(url)

    with patch.object(q_src._SESSION, "get", side_effect=_side_effect):
        r = fetch_quiver_institutional("AAPL")

    assert r.fetched_ok is True
    assert r.error == "partial:congress"
    assert r.congressional_net_buys_30d == 0
    assert r.congressional_top_buyers == []
    assert r.govt_contracts_count_90d == 1
    assert r.govt_contracts_total_usd == 2_000_000.0
    assert r.lobbying_usd_last_quarter == 50_000.0
    assert r.insider_net_txns_90d == 1


# ---------------------------------------------------------------------------
# 7. Materializer integration: no QUIVER_API_KEY -> fetched_ok=False,
#    data_gaps tagged.
# ---------------------------------------------------------------------------


def test_materializer_without_key(monkeypatch):
    monkeypatch.delenv("QUIVER_API_KEY", raising=False)
    q_src._clear_cache_for_testing()

    from tradingagents.data.materializer import _build_institutional_context

    gaps: list[str] = []
    inst = _build_institutional_context("AAPL", gaps)

    assert inst.fetched_ok is False
    assert inst.congressional_net_buys_30d == 0
    assert any(g.startswith("institutional:quiver_fallback") for g in gaps)


# ---------------------------------------------------------------------------
# 8. Agent prompt integration: _format_briefing renders the block populated.
# ---------------------------------------------------------------------------


def _mk_briefing_with_institutional():
    from tradingagents.schemas.v3 import (
        EventCalendar,
        InstitutionalContext,
        MacroContext,
        NewsContext,
        OptionsContext,
        PriceContext,
        Regime,
        SocialContext,
        TickerBriefing,
    )

    inst = InstitutionalContext(
        congressional_net_buys_30d=4,
        congressional_top_buyers=["Nancy Pelosi", "Dan Crenshaw"],
        congressional_top_sellers=["Some Senator"],
        govt_contracts_count_90d=7,
        govt_contracts_total_usd=12_500_000.0,
        lobbying_usd_last_quarter=3_400_000.0,
        insider_net_txns_90d=5,
        insider_top_buyers=["Tim Cook"],
        data_age_seconds=0,
        fetched_ok=True,
    )

    return TickerBriefing(
        ticker="AAPL",
        date="2026-04-05",
        snapshot_id="snap_test",
        price=PriceContext(
            price=180.0,
            change_1d_pct=0.5,
            change_5d_pct=1.0,
            change_20d_pct=2.0,
            sma_20=178.0,
            sma_50=175.0,
            sma_200=170.0,
            rsi_14=55.0,
            macd_above_signal=True,
            macd_crossover_days=3,
            bollinger_position="middle_third",
            volume_vs_avg_20d=1.0,
            atr_14=2.0,
            data_age_seconds=0,
        ),
        options=OptionsContext(),
        news=NewsContext(),
        social=SocialContext(),
        institutional=inst,
        macro=MacroContext(regime=Regime.RISK_ON),
        events=EventCalendar(),
    )


def _load_agent_module(name: str):
    """Load a v3 agent module directly from its file path, bypassing
    ``tradingagents/agents/__init__.py`` which pulls in langchain at import
    time (and langchain is not a dev-test dependency).
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "tradingagents"
        / "agents"
        / "v3"
        / f"{name}.py"
    )
    spec = importlib.util.spec_from_file_location(f"_v3_{name}_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_thesis_formatter_renders_institutional():
    thesis = _load_agent_module("thesis_agent")
    output = thesis._format_briefing(_mk_briefing_with_institutional())
    assert "INSTITUTIONAL SIGNALS" in output
    assert "Congressional net buys (30d): 4" in output
    assert "Nancy Pelosi" in output
    assert "12,500,000" in output
    assert "Tim Cook" in output


def test_antithesis_formatter_renders_institutional():
    antithesis = _load_agent_module("antithesis_agent")
    output = antithesis._format_briefing(_mk_briefing_with_institutional())
    assert "INSTITUTIONAL SIGNALS" in output
    assert "Congressional net buys (30d): 4" in output


def test_base_rate_formatter_renders_institutional():
    base_rate = _load_agent_module("base_rate_agent")
    output = base_rate._format_briefing(_mk_briefing_with_institutional())
    assert "INSTITUTIONAL SIGNALS" in output
    assert "3,400,000" in output


def test_formatter_renders_unavailable_when_not_fetched():
    thesis = _load_agent_module("thesis_agent")
    from tradingagents.schemas.v3 import InstitutionalContext

    briefing = _mk_briefing_with_institutional()
    briefing = briefing.model_copy(update={"institutional": InstitutionalContext()})
    output = thesis._format_briefing(briefing)
    assert "INSTITUTIONAL SIGNALS" in output
    assert "data unavailable" in output
    # Must NOT render the numeric block when fetched_ok=False
    assert "Congressional net buys (30d): 0" not in output
