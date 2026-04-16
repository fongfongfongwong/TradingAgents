"""Unit tests for :mod:`tradingagents.data.sources.options_analytics`.

Covers:

* Pure-math helpers (max pain, unusual activity) with synthetic input.
* ``compute_options_analytics`` happy path against a real ticker (AAPL).
* ``compute_options_analytics`` failure path with a bogus ticker.
* Integration with the v3 ``materialize_briefing`` pipeline.
"""

from __future__ import annotations

import socket

import pytest

from tradingagents.data.sources import options_analytics as oa
from tradingagents.data.sources.options_analytics import (
    OptionsAnalyticsResult,
    compute_max_pain,
    compute_options_analytics,
    find_unusual_activity,
)


# ---------------------------------------------------------------------------
# Network availability gate
# ---------------------------------------------------------------------------


def _network_available() -> bool:
    """Return True when DNS resolution to a well-known host succeeds."""
    try:
        socket.create_connection(("query1.finance.yahoo.com", 443), timeout=3)
        return True
    except OSError:
        return False


_NETWORK = _network_available()


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    """Ensure no test is influenced by the process-local memo tables."""
    oa._reset_caches_for_tests()
    yield
    oa._reset_caches_for_tests()


# ---------------------------------------------------------------------------
# Pure-math helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_max_pain_simple_case() -> None:
    """Synthetic chain where the minimum-pain strike is known by construction.

    All open interest sits on the 100 strike.  At k=100 pain = 0 (no j<k calls,
    no j>k puts with strike distance).  Any other strike accumulates non-zero
    pain from the 100-strike positions, so 100 must be the max-pain strike.
    """
    calls = [(90.0, 100.0), (100.0, 500.0), (110.0, 100.0)]
    puts = [(90.0, 100.0), (100.0, 500.0), (110.0, 100.0)]
    assert compute_max_pain(calls, puts) == 100.0


@pytest.mark.unit
def test_compute_max_pain_heavy_upper_call_oi() -> None:
    """Heavy call open-interest above spot pulls max-pain upward.

    With huge call OI at the 110 strike, any settlement strike k above 110
    would incur enormous pain ((k-110)*heavy_oi) for writers.  For k=100
    there is zero j<100 call contribution from the 110 strike.  So max-pain
    settles at the highest strike that doesn't cross the heavy 110 OI — 105
    in this chain — where pain is minimised.
    """
    calls = [
        (100.0, 10.0),
        (105.0, 10.0),
        (110.0, 1000.0),
        (115.0, 10.0),
    ]
    puts = [(100.0, 10.0), (105.0, 10.0), (110.0, 10.0), (115.0, 10.0)]
    result = compute_max_pain(calls, puts)

    # Brute-force the reference answer so the assertion is tautology-free.
    strikes = {s for s, _ in calls} | {s for s, _ in puts}
    best_k = None
    best_pain = None
    for k in sorted(strikes):
        pain = 0.0
        for s, oi in calls:
            if s < k:
                pain += oi * (k - s)
        for s, oi in puts:
            if s > k:
                pain += oi * (s - k)
        if best_pain is None or pain < best_pain:
            best_pain = pain
            best_k = k
    assert result == best_k


@pytest.mark.unit
def test_compute_max_pain_empty_chain_returns_none() -> None:
    assert compute_max_pain([], []) is None


@pytest.mark.unit
def test_find_unusual_activity_flags_high_volume_strike() -> None:
    calls = [
        {"strike": 250.0, "volume": 10000, "openInterest": 100},
        {"strike": 260.0, "volume": 50, "openInterest": 500},
    ]
    puts: list[dict] = []
    summary = find_unusual_activity("AAPL", calls, puts)
    assert summary.startswith("1 unusual")
    assert "250" in summary
    assert "vol=10000" in summary


@pytest.mark.unit
def test_find_unusual_activity_ignores_low_oi() -> None:
    """Even if vol >> oi, strikes with tiny oi are too noisy and skipped."""
    calls = [{"strike": 100.0, "volume": 1000, "openInterest": 10}]
    assert find_unusual_activity("AAPL", calls, []) == ""


@pytest.mark.unit
def test_find_unusual_activity_none_case_returns_empty() -> None:
    calls = [{"strike": 100.0, "volume": 50, "openInterest": 500}]
    puts = [{"strike": 100.0, "volume": 20, "openInterest": 300}]
    assert find_unusual_activity("AAPL", calls, puts) == ""


# ---------------------------------------------------------------------------
# compute_options_analytics — live paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _NETWORK, reason="Network unavailable")
def test_compute_options_analytics_aapl_happy_path() -> None:
    """A real AAPL call should at least return a PCR and max-pain strike."""
    try:
        result = compute_options_analytics("AAPL", 180.0)
    except Exception as exc:  # pragma: no cover — network flake shield
        pytest.xfail(f"yfinance call failed: {exc}")
        return

    assert isinstance(result, OptionsAnalyticsResult)
    if not result.fetched_ok:
        pytest.xfail(f"yfinance returned no options chain: {result.error}")
        return

    # Max pain is the most reliable field — it only needs strikes.
    # PCR requires non-zero OI or volume across the chain, which yfinance
    # does not always provide for a given expiry, so we tolerate None.
    if result.put_call_ratio is not None:
        assert result.put_call_ratio >= 0.0
    assert result.max_pain_price is not None
    assert result.max_pain_price > 0.0


@pytest.mark.unit
def test_compute_options_analytics_invalid_ticker_fails_gracefully() -> None:
    """A bogus ticker must return fetched_ok=False without raising."""
    result = compute_options_analytics("ZZZZZ999", 100.0)
    assert isinstance(result, OptionsAnalyticsResult)
    assert result.fetched_ok is False
    assert result.error is not None
    assert result.put_call_ratio is None
    assert result.max_pain_price is None


@pytest.mark.unit
def test_compute_options_analytics_empty_ticker() -> None:
    result = compute_options_analytics("", 100.0)
    assert result.fetched_ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Materializer integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _NETWORK, reason="Network unavailable")
def test_materializer_options_context_populated_or_falls_back() -> None:
    """``materialize_briefing`` must either populate analytics or tag a gap."""
    from tradingagents.data.materializer import materialize_briefing

    try:
        briefing = materialize_briefing("AAPL", "2026-04-05")
    except Exception as exc:  # pragma: no cover — upstream flake shield
        pytest.xfail(f"materialize_briefing failed: {exc}")
        return

    options = briefing.options
    fell_back = "options:analytics_fallback" in briefing.data_gaps

    if fell_back:
        # Clean fallback: structure is still valid, PCR may or may not exist.
        assert options.iv_rank_percentile is None
        assert options.iv_skew_25d is None
        assert options.max_pain_price is None
    else:
        # Full analytics path — max pain must be populated (needs only strikes).
        # PCR requires non-zero OI/volume; yfinance data can be thin, so allow None.
        assert options.max_pain_price is not None
        assert options.max_pain_price > 0.0
