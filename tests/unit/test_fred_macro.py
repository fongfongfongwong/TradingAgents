"""Unit tests for FRED macro source, regime classifier, and materializer wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.data.sources.fred_macro import FredMacroResult, fetch_fred_macro
from tradingagents.data.sources.regime_classifier import classify_regime
from tradingagents.schemas.v3 import Regime


# ---------------------------------------------------------------------------
# fetch_fred_macro
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_fred_macro_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    result = fetch_fred_macro("2026-04-05")

    assert isinstance(result, FredMacroResult)
    assert result.fetched_ok is False
    assert result.fed_funds_rate is None
    assert result.yield_curve_2y10y_bps is None
    assert result.dgs2 is None
    assert result.dgs10 is None
    assert result.error is not None
    assert "FRED_API_KEY" in result.error


@pytest.mark.unit
def test_fetch_fred_macro_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    result = fetch_fred_macro("2026-04-05")
    with pytest.raises(Exception):
        result.fetched_ok = True  # type: ignore[misc]


@pytest.mark.unit
def test_fetch_fred_macro_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a successful FRED round-trip via a patched session."""
    monkeypatch.setenv("FRED_API_KEY", "dummy-key")

    # Clear cache so repeated test runs always hit the mocked session.
    from tradingagents.data.sources import fred_macro as fm

    fm._obs_cache.clear()

    series_values = {
        "DFF": "5.33",
        "DGS2": "4.20",
        "DGS10": "4.50",
    }

    def fake_get(url: str, params: dict, timeout: float):  # noqa: ANN001
        series_id = params["series_id"]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "observations": [
                {"date": "2026-04-04", "value": series_values[series_id]}
            ]
        }
        return mock_resp

    with patch.object(fm._session, "get", side_effect=fake_get):
        result = fetch_fred_macro("2026-04-05")

    assert result.fetched_ok is True
    assert result.error is None
    assert result.fed_funds_rate == pytest.approx(5.33)
    assert result.dgs2 == pytest.approx(4.20)
    assert result.dgs10 == pytest.approx(4.50)
    assert result.yield_curve_2y10y_bps == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# classify_regime truth table
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "vix,yc,spy,expected",
    [
        # Rule 1: RISK_OFF via VIX >= 30
        (35.0, -100.0, -5.0, Regime.RISK_OFF),
        # Rule 1: RISK_OFF via deep inversion + weak SPY
        (25.0, -60.0, -4.0, Regime.RISK_OFF),
        # Rule 2: BEARISH_BIAS
        (25.0, 10.0, -2.0, Regime.BEARISH_BIAS),
        # Rule 3: RISK_ON
        (14.0, 50.0, 3.0, Regime.RISK_ON),
        # Rule 4: BULLISH_BIAS
        (18.0, 20.0, 1.0, Regime.BULLISH_BIAS),
        # Rule 5: all None -> TRANSITIONING
        (None, None, None, Regime.TRANSITIONING),
        # Partial info, no rule matches (VIX in no-man's land, mixed signals)
        (21.0, -10.0, 0.0, Regime.TRANSITIONING),
    ],
)
def test_classify_regime_truth_table(
    vix: float | None,
    yc: float | None,
    spy: float | None,
    expected: Regime,
) -> None:
    assert classify_regime(vix, yc, spy) == expected


# ---------------------------------------------------------------------------
# Materializer integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_materializer_macro_no_fred_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no FRED key, VIX path still works and fred_fallback is recorded."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    from tradingagents.data import materializer as mz
    from tradingagents.data.sources import fred_macro as fm

    fm._obs_cache.clear()

    # Fake VIX history: final close = 17.0
    vix_hist = MagicMock()
    vix_hist.empty = False
    vix_hist.__getitem__.return_value.iloc.__getitem__.return_value = 17.0

    # Fake SPY history: 25 closes, last 100, -20 idx 98, -6 idx 99.5
    spy_closes = [100.0 + i * 0.1 for i in range(30)]
    spy_hist = MagicMock()
    spy_hist.empty = False
    spy_hist.__len__.return_value = len(spy_closes)
    spy_hist.__getitem__.return_value.tolist.return_value = spy_closes

    def fake_ticker(symbol: str) -> MagicMock:
        t = MagicMock()
        if symbol == "^VIX":
            t.history.return_value = vix_hist
        elif symbol == "SPY":
            t.history.return_value = spy_hist
        else:
            t.history.return_value = MagicMock(empty=True)
        return t

    data_gaps: list[str] = []
    with patch.object(mz.yf, "Ticker", side_effect=fake_ticker):
        macro = mz._build_macro_context(data_gaps, "2026-04-05")

    assert macro.vix_level == 17.0
    assert macro.fed_funds_rate is None
    assert macro.yield_curve_2y10y_bps is None
    assert "macro:fred_fallback" in data_gaps
    assert isinstance(macro.regime, Regime)
    # Regime should be something sensible — not crash.
    assert macro.sector_etf_5d_pct is not None
    assert macro.sector_etf_20d_pct is not None


@pytest.mark.unit
def test_materializer_macro_with_mocked_fred(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch fetch_fred_macro to simulate successful FRED fetch."""
    from tradingagents.data import materializer as mz

    fake_fred = FredMacroResult(
        fed_funds_rate=5.25,
        yield_curve_2y10y_bps=35.0,
        dgs2=4.10,
        dgs10=4.45,
        fetched_ok=True,
        error=None,
    )
    monkeypatch.setattr(mz, "fetch_fred_macro", lambda _date: fake_fred)

    vix_hist = MagicMock()
    vix_hist.empty = False
    vix_hist.__getitem__.return_value.iloc.__getitem__.return_value = 15.0

    spy_closes = [100.0 + i * 0.2 for i in range(30)]  # strong uptrend
    spy_hist = MagicMock()
    spy_hist.empty = False
    spy_hist.__len__.return_value = len(spy_closes)
    spy_hist.__getitem__.return_value.tolist.return_value = spy_closes

    def fake_ticker(symbol: str) -> MagicMock:
        t = MagicMock()
        if symbol == "^VIX":
            t.history.return_value = vix_hist
        elif symbol == "SPY":
            t.history.return_value = spy_hist
        else:
            t.history.return_value = MagicMock(empty=True)
        return t

    data_gaps: list[str] = []
    with patch.object(mz.yf, "Ticker", side_effect=fake_ticker):
        macro = mz._build_macro_context(data_gaps, "2026-04-05")

    assert macro.fed_funds_rate == pytest.approx(5.25)
    assert macro.yield_curve_2y10y_bps == 35
    assert macro.vix_level == 15.0
    assert "macro:fred_fallback" not in data_gaps
    # VIX 15, SPY strongly up, yc > 0 — classifier should pick RISK_ON.
    assert macro.regime == Regime.RISK_ON
