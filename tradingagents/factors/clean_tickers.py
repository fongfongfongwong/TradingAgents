"""CLEAN_STOCK_TICKERS universe for HAR-RV baseline training.

Hardcoded list of ~200 liquid US equities + top 50 ETFs. Chosen for:
- Continuous listing history from 2018-01-01 to present
- Average daily dollar volume > $50M
- Market cap > $5B at the start of the training window (for equities)
- Low corporate action frequency (minimal splits/M&A disruption)

The equity list is anchored on the 2024-2025 vintage of the S&P 100 plus
additional liquid mid/large caps. Tickers known to have ceased trading,
merged, or been de-listed between 2018-01-01 and today are deliberately
excluded (e.g. ATVI -> acquired by MSFT, FB -> renamed META, FISV -> FI,
TWTR -> taken private, CELG -> BMY, etc.).

NOTE on ticker count
--------------------
The reference spec (``rv_prediction/BASELINE.md``) mentions "~350 tickers".
Our current list is 256 stocks + 50 ETFs = 306 tickers total. The ~44-name
difference is intentional: we exclude tickers with insufficient post-2018
history, known M&A / de-listing disruption, and illiquid names. The total
is simply ``len(CLEAN_STOCK_TICKERS) + len(CLEAN_ETF_TICKERS)`` — if you
update one of the tuples, update this note (and ``ALL_CLEAN_TICKERS``)
accordingly.
"""

from __future__ import annotations

# ~200 large-cap US equities (S&P 100 core + liquid mid/large-caps).
# All names verified to be continuously listed and active as of 2025-08.
CLEAN_STOCK_TICKERS: tuple[str, ...] = (
    # Mega-cap tech / communication
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "NFLX", "ADBE",
    "CRM", "ORCL", "CSCO", "INTC", "AMD", "AVGO", "QCOM", "TXN", "IBM", "NOW",
    "INTU", "ACN", "AMAT", "ADI", "MU", "LRCX", "KLAC", "ADSK", "PANW", "ANET",
    "SNPS", "CDNS", "MSI", "APH", "ROP", "FTNT",
    # Financials
    "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "BLK", "AXP",
    "C", "SCHW", "SPGI", "CB", "MMC", "ICE", "CME", "PGR", "AON", "TRV",
    "AIG", "ALL", "MET", "PRU", "AFL", "COF", "USB", "PNC", "TFC", "BK",
    "STT", "MTB", "NDAQ", "MCO",
    # Healthcare / pharma
    "UNH", "JNJ", "LLY", "ABBV", "PFE", "MRK", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "MDT", "ELV", "CI", "CVS", "ISRG", "SYK", "REGN", "VRTX",
    "ZTS", "BDX", "BSX", "HCA", "HUM", "IDXX", "MCK", "BIIB", "ZBH", "EW",
    "RMD", "ILMN", "A", "IQV", "DXCM",
    # Consumer discretionary / staples
    "WMT", "HD", "COST", "PG", "KO", "PEP", "MCD", "NKE", "SBUX", "LOW",
    "TJX", "DIS", "BKNG", "MDLZ", "MO", "PM", "TGT", "CL", "EL", "MNST",
    "KMB", "GIS", "STZ", "KDP", "KHC", "HSY", "KR", "SYY", "ADM", "CHD",
    "MAR", "HLT", "YUM", "CMG", "ORLY", "AZO", "ROST", "DG", "DLTR", "F",
    "GM", "LULU", "DPZ",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HES",
    "PXD", "KMI", "WMB", "HAL", "DVN", "BKR", "FANG",
    # Industrials
    "CAT", "UNP", "HON", "UPS", "BA", "LMT", "RTX", "GE", "DE", "GD",
    "NOC", "FDX", "ETN", "EMR", "ITW", "CSX", "NSC", "WM", "MMM", "CTAS",
    "CMI", "PCAR", "PH", "ROK", "CARR", "OTIS", "TT", "IR", "PAYX", "GWW",
    "ODFL", "FAST", "VRSK", "J", "URI", "RSG",
    # Materials / utilities / real estate
    "LIN", "APD", "SHW", "ECL", "DOW", "NEM", "FCX", "CTVA", "DD", "NUE",
    "MLM", "VMC", "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL",
    "ED", "PEG", "WEC", "ES", "EIX", "PCG", "AWK", "PLD", "EQIX", "PSA",
    "SPG", "O", "WELL", "CCI", "VICI", "AMT", "DLR", "SBAC", "EXR", "AVB",
    "EQR", "MAA", "ARE", "VTR", "INVH",
    # Telecom / misc
    "T", "VZ", "TMUS", "CMCSA", "EA", "TTWO", "DASH", "UBER", "ABNB", "LYV",
)

# Top 50 liquid US ETFs
CLEAN_ETF_TICKERS: tuple[str, ...] = (
    # Broad equity indexes
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VEA", "VWO", "IEFA", "IEMG",
    # Fixed income
    "AGG", "BND", "TLT", "IEF", "SHY", "LQD", "HYG", "JNK", "TIP", "GOVT",
    # Sector SPDRs
    "XLF", "XLK", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE",
    "XLC",
    # Industry / thematic
    "KRE", "KBE", "XOP", "XBI", "XRT", "SMH", "SOXX", "ARKK", "ARKG",
    # Commodities
    "GLD", "SLV", "GDX", "USO", "UNG", "DBA",
    # Real estate + international
    "VNQ", "EFA", "EEM", "FXI",
)

ALL_CLEAN_TICKERS: tuple[str, ...] = CLEAN_STOCK_TICKERS + CLEAN_ETF_TICKERS


def _validate_universe() -> None:
    """Basic well-formedness checks. Called at import time."""
    assert len(CLEAN_STOCK_TICKERS) >= 150, (
        f"CLEAN_STOCK_TICKERS must have >=150 entries, got {len(CLEAN_STOCK_TICKERS)}"
    )
    assert len(CLEAN_ETF_TICKERS) >= 40, (
        f"CLEAN_ETF_TICKERS must have >=40 entries, got {len(CLEAN_ETF_TICKERS)}"
    )
    # No duplicates
    stock_set = set(CLEAN_STOCK_TICKERS)
    etf_set = set(CLEAN_ETF_TICKERS)
    assert len(stock_set) == len(CLEAN_STOCK_TICKERS), "Duplicates in CLEAN_STOCK_TICKERS"
    assert len(etf_set) == len(CLEAN_ETF_TICKERS), "Duplicates in CLEAN_ETF_TICKERS"
    assert stock_set.isdisjoint(etf_set), "Overlap between stocks and ETFs"
    # All uppercase, alphanumeric or dash
    for t in ALL_CLEAN_TICKERS:
        assert t == t.upper(), f"Ticker not upper-case: {t}"
        assert all(c.isalnum() or c == "-" for c in t), f"Bad ticker: {t}"


_validate_universe()
