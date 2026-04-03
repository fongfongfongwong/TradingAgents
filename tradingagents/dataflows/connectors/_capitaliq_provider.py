"""
Capital IQ data provider for TradingAgents.

Drop-in vendor implementation that queries the Capital IQ PostgreSQL database.
Copy this file into tradingagents/dataflows/ and register in interface.py.

Requires: psycopg2-binary, pandas, stockstats
DB: flab2:5432/postgres, schema=capitaliq, user=readonly
"""

import io
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

_DB_CONFIG = {
    "host": "flab2",
    "port": 5432,
    "dbname": "postgres",
    "user": "readonly",
    "password": "3lGzwDY0G8",
    "options": "-c search_path=capitaliq,public",
}


def _get_conn():
    return psycopg2.connect(**_DB_CONFIG)


def _query(sql: str, params: dict | tuple = None) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def _query_df(sql: str, params: dict | tuple = None) -> pd.DataFrame:
    with _get_conn() as conn:
        return pd.read_sql(sql, conn, params=params)


# ---------------------------------------------------------------------------
# Ticker resolution (cached)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1024)
def _resolve_ticker(symbol: str) -> dict:
    """Resolve ticker symbol to Capital IQ IDs.

    Returns dict with companyid, securityid, tradingitemid, companyname.
    Raises ValueError if ticker not found.
    """
    rows = _query(
        """
        SELECT c.companyid, c.companyname, ti.tradingitemid, s.securityid
        FROM ciqtradingitem ti
        JOIN ciqsecurity s ON s.securityid = ti.securityid
        JOIN ciqcompany c ON c.companyid = s.companyid
        WHERE ti.tickersymbol = %(symbol)s
          AND ti.primaryflag = 1
          AND ti.currencyid = 160
        LIMIT 1
        """,
        {"symbol": symbol.upper()},
    )
    if not rows:
        # Fallback: try Compustat-style table (ticker is in security table)
        rows = _query(
            """SELECT s.gvkey, c.conm as companyname
               FROM security s JOIN company c ON c.gvkey = s.gvkey
               WHERE s.tic = %(s)s LIMIT 1""",
            {"s": symbol.upper()},
        )
        if rows:
            return {"companyid": None, "gvkey": rows[0]["gvkey"],
                    "companyname": rows[0]["companyname"],
                    "securityid": None, "tradingitemid": None}
        raise ValueError(f"Ticker '{symbol}' not found in Capital IQ")
    return rows[0]


@lru_cache(maxsize=1024)
def _resolve_gvkey(symbol: str) -> str:
    """Resolve ticker to Compustat gvkey."""
    rows = _query("SELECT gvkey FROM security WHERE tic = %(s)s LIMIT 1",
                  {"s": symbol.upper()})
    if not rows:
        # Try via ciq tables
        info = _resolve_ticker(symbol)
        if info.get("companyid"):
            rows = _query(
                "SELECT gvkey FROM ciqgvkeyiid WHERE relatedcompanyid = %(cid)s LIMIT 1",
                {"cid": info["companyid"]},
            )
    if not rows:
        raise ValueError(f"gvkey not found for '{symbol}'")
    return rows[0]["gvkey"]


# ---------------------------------------------------------------------------
# 1. get_stock_data
# ---------------------------------------------------------------------------


def get_capitaliq_stock(symbol: str, start_date: str, end_date: str) -> str:
    """OHLCV price data from ciqpriceequity."""
    info = _resolve_ticker(symbol)

    if info.get("tradingitemid"):
        df = _query_df(
            """
            SELECT pricingdate as "Date", priceopen as "Open", pricehigh as "High",
                   pricelow as "Low", priceclose as "Close", volume as "Volume"
            FROM ciqpriceequity
            WHERE tradingitemid = %(tid)s
              AND pricingdate BETWEEN %(s)s AND %(e)s
            ORDER BY pricingdate
            """,
            {"tid": info["tradingitemid"], "s": start_date, "e": end_date},
        )
    else:
        # Compustat fallback
        gvkey = info.get("gvkey") or _resolve_gvkey(symbol)
        df = _query_df(
            """
            SELECT datadate as "Date", prcod as "Open", prchd as "High",
                   prcld as "Low", prccd as "Close", cshtrd as "Volume"
            FROM sec_dprc
            WHERE gvkey = %(gv)s
              AND datadate BETWEEN %(s)s AND %(e)s
            ORDER BY datadate
            """,
            {"gv": gvkey, "s": start_date, "e": end_date},
        )

    if df.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    df = df.set_index("Date")
    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    header = f"# Stock data for {symbol} from {start_date} to {end_date}\n"
    header += f"# Source: Capital IQ ({info.get('companyname', symbol)})\n"
    return header + df.to_csv()


# ---------------------------------------------------------------------------
# 2. get_indicators
# ---------------------------------------------------------------------------

INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50-day Simple Moving Average of closing prices",
    "close_200_sma": "200-day Simple Moving Average of closing prices",
    "close_10_ema": "10-day Exponential Moving Average of closing prices",
    "macd": "Moving Average Convergence Divergence (EMA12 - EMA26)",
    "macds": "MACD Signal Line (9-day EMA of MACD)",
    "macdh": "MACD Histogram (MACD - Signal)",
    "rsi": "Relative Strength Index (14-day)",
    "boll": "Bollinger Band Middle (20-day SMA)",
    "boll_ub": "Bollinger Band Upper (Middle + 2*StdDev)",
    "boll_lb": "Bollinger Band Lower (Middle - 2*StdDev)",
    "atr": "Average True Range (14-day)",
    "vwma": "Volume Weighted Moving Average",
    "mfi": "Money Flow Index",
}

INDICATOR_WARMUP = {
    "close_50_sma": 50, "close_200_sma": 200, "close_10_ema": 30,
    "macd": 35, "macds": 45, "macdh": 45, "rsi": 20,
    "boll": 25, "boll_ub": 25, "boll_lb": 25,
    "atr": 20, "vwma": 20, "mfi": 20,
}


def get_capitaliq_indicator(symbol: str, indicator: str, curr_date: str,
                            look_back_days: int = 30) -> str:
    """Compute technical indicator from Capital IQ price data."""
    indicator = indicator.strip().lower()
    if indicator not in INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Unsupported indicator '{indicator}'. "
            f"Supported: {', '.join(INDICATOR_DESCRIPTIONS)}"
        )

    warmup = INDICATOR_WARMUP.get(indicator, 50)
    total_days = look_back_days + warmup + 30  # extra buffer for weekends
    dt_end = datetime.strptime(curr_date, "%Y-%m-%d")
    dt_start = dt_end - timedelta(days=total_days)

    info = _resolve_ticker(symbol)
    if info.get("tradingitemid"):
        df = _query_df(
            """
            SELECT pricingdate as date, priceopen as open, pricehigh as high,
                   pricelow as low, priceclose as close, volume
            FROM ciqpriceequity
            WHERE tradingitemid = %(tid)s
              AND pricingdate BETWEEN %(s)s AND %(e)s
            ORDER BY pricingdate
            """,
            {"tid": info["tradingitemid"],
             "s": dt_start.strftime("%Y-%m-%d"),
             "e": curr_date},
        )
    else:
        gvkey = info.get("gvkey") or _resolve_gvkey(symbol)
        df = _query_df(
            """
            SELECT datadate as date, prcod as open, prchd as high,
                   prcld as low, prccd as close, cshtrd as volume
            FROM sec_dprc
            WHERE gvkey = %(gv)s AND datadate BETWEEN %(s)s AND %(e)s
            ORDER BY datadate
            """,
            {"gv": gvkey,
             "s": dt_start.strftime("%Y-%m-%d"),
             "e": curr_date},
        )

    if df.empty:
        return f"No price data found for '{symbol}' to compute {indicator}"

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.apply(pd.to_numeric, errors="coerce")

    # Compute indicator using stockstats
    from stockstats import StockDataFrame

    sdf = StockDataFrame.retype(df.copy())
    try:
        values = sdf[indicator]
    except Exception as e:
        return f"Error computing {indicator}: {e}"

    # Window for output
    window_start = dt_end - timedelta(days=look_back_days)
    all_dates = pd.date_range(window_start, dt_end, freq="D")

    lines = [f"## {indicator} values from {window_start.strftime('%Y-%m-%d')} to {curr_date}:\n"]
    for d in all_dates:
        if d in values.index and pd.notna(values.loc[d]):
            lines.append(f"{d.strftime('%Y-%m-%d')}: {values.loc[d]:.3f}")
        else:
            if d.weekday() >= 5:
                lines.append(f"{d.strftime('%Y-%m-%d')}: N/A: Not a trading day (weekend)")
            else:
                lines.append(f"{d.strftime('%Y-%m-%d')}: N/A: Not a trading day (weekend or holiday)")

    lines.append(f"\n{INDICATOR_DESCRIPTIONS[indicator]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. get_fundamentals
# ---------------------------------------------------------------------------


def get_capitaliq_fundamentals(ticker: str, curr_date: str = None) -> str:
    """Company overview / key ratios.

    Uses CIQ tables for company info + market cap, Compustat for financials (fast).
    """
    info = _resolve_ticker(ticker)
    lines = [f"# Company Overview for {ticker} (Capital IQ)"]

    # Basic info from ciqcompany (fast, small table)
    if info.get("companyid"):
        rows = _query(
            """
            SELECT c.companyname, c.city, c.zipcode,
                   si.simpleindustrydescription as industry, ct.companytypename,
                   cg.country
            FROM ciqcompany c
            LEFT JOIN ciqsimpleindustry si ON si.simpleindustryid = c.simpleindustryid
            LEFT JOIN ciqcompanytype ct ON ct.companytypeid = c.companytypeid
            LEFT JOIN ciqcountrygeo cg ON cg.countryid = c.countryid
            WHERE c.companyid = %(cid)s
            """,
            {"cid": info["companyid"]},
        )
        if rows:
            r = rows[0]
            for label, key in [("Name", "companyname"), ("Industry", "industry"),
                               ("Company Type", "companytypename"), ("Country", "country"),
                               ("City", "city")]:
                if r.get(key):
                    lines.append(f"{label}: {r[key]}")

        # Market cap (indexed by companyid + pricingdate)
        mc = _query(
            """
            SELECT marketcap FROM ciqmarketcap
            WHERE companyid = %(cid)s AND pricingdate <= %(d)s
            ORDER BY pricingdate DESC LIMIT 1
            """,
            {"cid": info["companyid"], "d": curr_date or "9999-12-31"},
        )
        if mc and mc[0]["marketcap"]:
            lines.append(f"Market Cap: {mc[0]['marketcap']:,.0f}")

    # Financial ratios from Compustat (co_afnd1 is ~700K rows, fast)
    try:
        gvkey = _resolve_gvkey(ticker)
        rows = _query(
            """
            SELECT * FROM co_afnd1
            WHERE gvkey = %(gv)s AND datadate <= %(d)s
            ORDER BY datadate DESC LIMIT 1
            """,
            {"gv": gvkey, "d": curr_date or "9999-12-31"},
        )
        if rows:
            r = rows[0]
            lines.append("")
            lines.append("# Key Financial Data (Latest Annual, Compustat)")
            # Map Compustat fields to readable names
            field_map = {
                "revt": "Revenue", "ni": "Net Income", "ebitda": "EBITDA",
                "oiadp": "Operating Income", "gp": "Gross Profit",
                "at": "Total Assets", "lt": "Total Liabilities",
                "seq": "Stockholders Equity", "ceq": "Common Equity",
                "dltt": "Long-term Debt", "dlc": "Short-term Debt",
                "ch": "Cash", "che": "Cash & Equivalents",
                "oancf": "Operating Cash Flow", "capx": "Capital Expenditure",
                "csho": "Shares Outstanding", "epspx": "EPS (Diluted)",
                "dv": "Dividends", "dvpsp_f": "Dividends Per Share",
            }
            for key, label in field_map.items():
                v = r.get(key)
                if v is not None:
                    lines.append(f"{label}: {v}")
    except ValueError:
        pass  # No gvkey found, skip Compustat data

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4-6. Financial statements
# ---------------------------------------------------------------------------


def _get_financial_statement(ticker: str, freq: str, curr_date: str,
                             collection_type: int) -> str:
    """Generic financial statement fetcher using Compustat tables (fast).

    collection_type: 1=Income Statement, 2=Balance Sheet, 3=Cash Flow
    Uses co_ifndq (quarterly) or co_afnd1 (annual) — indexed by gvkey, ~700K rows.
    """
    stmt_names = {1: "Income Statement", 2: "Balance Sheet", 3: "Cash Flow Statement"}
    stmt_name = stmt_names.get(collection_type, "Financial Statement")

    gvkey = _resolve_gvkey(ticker)
    table = "co_ifndq" if freq == "quarterly" else "co_afnd1"

    # Select relevant columns based on statement type
    # Compustat stores all items in one wide table, so we select subsets
    income_cols = [
        "datadate", "revtq", "cogsq", "xsgaq", "oiadpq", "niq", "epspxq",
        "epsfxq", "txtq", "xintq", "dpq",
    ]
    balance_cols = [
        "datadate", "atq", "actq", "cheq", "rectq", "invtq", "acoq",
        "ppentq", "ltq", "lctq", "dlcq", "apq", "dlttq", "txditcq",
        "seqq", "ceqq", "cshoq",
    ]
    cashflow_cols = [
        "datadate", "oancfq", "capxq", "ivncfq", "fincfq", "chechq",
        "dpcq", "sstk", "prstkc", "dv",
    ]
    # Annual variants have no 'q' suffix
    income_cols_a = [
        "datadate", "revt", "cogs", "xsga", "oiadp", "ni", "epspx",
        "epsfx", "txt", "xint", "dp", "ebitda", "gp",
    ]
    balance_cols_a = [
        "datadate", "at", "act", "che", "rect", "invt", "aco",
        "ppent", "lt", "lct", "dlc", "ap", "dltt", "txditc",
        "seq", "ceq", "csho",
    ]
    cashflow_cols_a = [
        "datadate", "oancf", "capx", "ivncf", "fincf", "chech",
        "dpc", "sstk", "prstkc", "dv",
    ]

    if freq == "quarterly":
        col_map = {1: income_cols, 2: balance_cols, 3: cashflow_cols}
    else:
        col_map = {1: income_cols_a, 2: balance_cols_a, 3: cashflow_cols_a}

    cols = col_map.get(collection_type)
    if not cols:
        cols = ["*"]

    # Only select columns that exist in the table
    col_str = ", ".join(cols)
    try:
        df = _query_df(
            f"SELECT {col_str} FROM {table} WHERE gvkey = %(gv)s ORDER BY datadate DESC",
            {"gv": gvkey},
        )
    except Exception:
        # Fallback: select all if specific columns don't exist
        df = _query_df(
            f"SELECT * FROM {table} WHERE gvkey = %(gv)s ORDER BY datadate DESC",
            {"gv": gvkey},
        )

    if df.empty:
        return f"No {stmt_name} data for '{ticker}'"

    # Filter by curr_date to prevent look-ahead bias
    if curr_date and "datadate" in df.columns:
        df = df[pd.to_datetime(df["datadate"]) <= pd.Timestamp(curr_date)]

    if df.empty:
        return f"No {stmt_name} data for '{ticker}' before {curr_date}"

    # Drop all-null columns and metadata columns
    drop_cols = [c for c in df.columns if c in ("gvkey", "indfmt", "consol", "popsrc", "datafmt", "fyr")]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")
    df = df.dropna(axis=1, how="all")

    header = f"# {freq.title()} {stmt_name} for {ticker} (Capital IQ / Compustat)\n"
    return header + df.to_csv(index=False)


def get_capitaliq_balance_sheet(ticker: str, freq: str = "quarterly",
                                curr_date: str = None) -> str:
    return _get_financial_statement(ticker, freq, curr_date, collection_type=2)


def get_capitaliq_cashflow(ticker: str, freq: str = "quarterly",
                           curr_date: str = None) -> str:
    return _get_financial_statement(ticker, freq, curr_date, collection_type=3)


def get_capitaliq_income_statement(ticker: str, freq: str = "quarterly",
                                   curr_date: str = None) -> str:
    return _get_financial_statement(ticker, freq, curr_date, collection_type=1)


# ---------------------------------------------------------------------------
# 7. get_news (Key Developments)
# ---------------------------------------------------------------------------


def get_capitaliq_news(ticker: str, start_date: str, end_date: str) -> str:
    """Company-specific key developments as news."""
    info = _resolve_ticker(ticker)
    if not info.get("companyid"):
        return f"No news data available for '{ticker}' (company not found in CIQ)"

    # Use subquery with EXISTS to leverage PK index on ciqkeydev
    # and avoid full scan of unindexed objectid column
    rows = _query(
        """
        SELECT kd.keydevid, kd.headline, kd.situation, kd.announceddate
        FROM ciqkeydev kd
        WHERE kd.announceddate BETWEEN %(s)s AND %(e)s
          AND EXISTS (
              SELECT 1 FROM ciqkeydevtoobjecttoeventtype kdo
              WHERE kdo.keydevid = kd.keydevid AND kdo.objectid = %(cid)s
          )
        ORDER BY kd.announceddate DESC
        LIMIT 50
        """,
        {"cid": info["companyid"], "s": start_date, "e": end_date},
    )
    cat_map = {}

    if not rows:
        return f"No news found for {ticker} between {start_date} and {end_date}"

    lines = [f"## {ticker} News, from {start_date} to {end_date}:\n"]
    for r in rows:
        headline = r.get("headline") or "No headline"
        situation = r.get("situation") or ""
        date_str = r["announceddate"].strftime("%Y-%m-%d") if r.get("announceddate") else ""

        lines.append(f"### {headline} (source: Capital IQ Key Developments)")
        if situation:
            lines.append(situation[:500])
        lines.append(f"Date: {date_str}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 8. get_global_news
# ---------------------------------------------------------------------------


def get_capitaliq_global_news(curr_date: str, look_back_days: int = 7,
                              limit: int = 10) -> str:
    """Market-wide key developments.

    NOTE: ciqkeydev (39M rows) has no date index, so broad date scans are slow.
    This uses economic indicator descriptions as a proxy for macro news.
    For full global news, consider keeping yfinance as the vendor for news_data.
    """
    dt_end = datetime.strptime(curr_date, "%Y-%m-%d")
    dt_start = dt_end - timedelta(days=look_back_days)

    # Use economic indicator data as macro news proxy
    # ecind_mth has wide columns: gdp, cpi, unemp, fedfunds, etc.
    rows = _query(
        """
        SELECT econiso, datadate, gdp, cpi, unemp, fedfunds,
               ip1, rtlsales, house, ppi, m2, tbill3m, note10yr, bond30yr
        FROM ecind_mth
        WHERE econiso = 'USA'
          AND datadate BETWEEN %(s)s AND %(e)s
        ORDER BY datadate DESC
        LIMIT %(lim)s
        """,
        {"s": dt_start.strftime("%Y-%m-%d"), "e": curr_date, "lim": limit},
    )

    if not rows:
        return f"No global market data found from {dt_start.strftime('%Y-%m-%d')} to {curr_date}"

    indicator_names = {
        "gdp": "GDP", "cpi": "CPI", "unemp": "Unemployment Rate",
        "fedfunds": "Fed Funds Rate", "ip1": "Industrial Production (1M)",
        "rtlsales": "Retail Sales", "house": "Housing Starts",
        "ppi": "PPI", "m2": "M2 Money Supply",
        "tbill3m": "3M T-Bill", "note10yr": "10Y Treasury Note",
        "bond30yr": "30Y Treasury Bond",
    }

    lines = [f"## Global Market Data (USA), from {dt_start.strftime('%Y-%m-%d')} to {curr_date}:\n"]
    for r in rows:
        date_str = r["datadate"].strftime("%Y-%m-%d") if r.get("datadate") else ""
        lines.append(f"### Economic Indicators - {date_str} (source: Capital IQ)")
        for col, name in indicator_names.items():
            v = r.get(col)
            if v is not None:
                lines.append(f"{name}: {v}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. get_insider_transactions
# ---------------------------------------------------------------------------


def get_capitaliq_insider_transactions(ticker: str) -> str:
    """Insider trading activity."""
    info = _resolve_ticker(ticker)
    if not info.get("companyid"):
        return f"No insider transaction data for '{ticker}'"

    df = _query_df(
        """
        SELECT CONCAT(p.firstname, ' ', p.lastname) as "Person",
               ois.maxtradedate as "Date",
               ott.description as "Type",
               ois.shares as "Shares",
               ois.maxprice as "Price",
               ois.transactionvalue as "Value"
        FROM ciqowninsidersummary ois
        LEFT JOIN ciqowninsidertransactiontype ott
            ON ott.insidertransactiontypeid = ois.insidertransactiontypeid
        LEFT JOIN ciqperson p ON p.personid = ois.ownerobjectid
        WHERE ois.ownedcompanyid = %(cid)s
        ORDER BY ois.maxtradedate DESC
        LIMIT 100
        """,
        {"cid": info["companyid"]},
    )

    if df.empty:
        return f"No insider transactions found for {ticker}"

    header = f"# Insider Transactions for {ticker} (Capital IQ)\n"
    return header + df.to_csv(index=False)
