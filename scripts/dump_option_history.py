"""Export historical OPRA options data from Databento to parquet.

Use this to build training / backtest fixtures for the HAR-RV model and
options-flow features. For *runtime* options data, use
``tradingagents.dataflows.connectors.databento_options_connector`` instead.

API key is read from ``DATABENTO_API_KEY`` in the environment / .env.

Examples
--------
Dump one day of AAPL quotes + trades::

    python scripts/dump_option_history.py --ticker AAPL \\
        --start 2026-04-14 --end 2026-04-14

Dump trades only, capped at 50k rows for testing::

    python scripts/dump_option_history.py --ticker SPY \\
        --start 2026-04-01 --end 2026-04-01 --type trades --limit 50000
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _client():
    """Build a Databento Historical client from ``DATABENTO_API_KEY``."""
    try:
        import databento as db
    except ImportError as exc:  # pragma: no cover — hard dependency of script
        raise SystemExit(
            "databento package not installed — pip install databento"
        ) from exc

    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "DATABENTO_API_KEY is not set. "
            "Export it or add it to the project .env before running."
        )
    return db.Historical(key=key)


def _fetch_range(
    *,
    schema: str,
    ticker: str,
    start_date: str,
    end_date: str,
    limit: int | None,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Fetch ``schema`` rows for ``ticker`` from OPRA.PILLAR with retries."""
    client = _client()
    symbol = f"{ticker}.OPT"

    params: dict = {
        "dataset": "OPRA.PILLAR",
        "schema": schema,
        "symbols": [symbol],
        "start": f"{start_date}T00:00:00",
        "end": f"{end_date}T23:59:59",
        "stype_in": "parent",
    }
    if limit is not None:
        params["limit"] = limit

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            df = client.timeseries.get_range(**params).to_df()
            df.reset_index(inplace=True)
            if "ts_event" in df.columns:
                df["ts_event"] = (
                    pd.to_datetime(df["ts_event"])
                    .dt.tz_convert("America/New_York")
                    .dt.tz_localize(None)
                )
            logger.info("[%s] downloaded %d rows for %s", schema, len(df), ticker)
            return df
        except Exception as exc:  # noqa: BLE001 — retry + surface on final attempt
            last_exc = exc
            if attempt < max_retries - 1:
                logger.warning(
                    "[%s] retry %d/%d for %s: %s",
                    schema,
                    attempt + 1,
                    max_retries,
                    ticker,
                    exc,
                )
                time.sleep(2)
    logger.error(
        "[%s] failed after %d retries for %s: %s",
        schema,
        max_retries,
        ticker,
        last_exc,
    )
    return pd.DataFrame()


def _extract_option_details(df: pd.DataFrame, symbol_col: str = "symbol") -> pd.DataFrame:
    """Parse OPRA symbol into underlying / expiration / option_type / strike."""
    if df.empty or symbol_col not in df.columns:
        return df
    parts = df[symbol_col].str.strip().str.split(r"\s+", n=1, expand=True)
    df["underlying"] = parts[0]
    detail = parts[1]
    df["expiration"] = (
        "20" + detail.str[:2] + "-" + detail.str[2:4] + "-" + detail.str[4:6]
    )
    df["option_type"] = detail.str[6].map({"C": "call", "P": "put"})
    df["strike"] = pd.to_numeric(detail.str[7:], errors="coerce") / 1000
    return df


def _save(df: pd.DataFrame, label: str, output_dir: Path, ticker: str, start: str, end: str) -> None:
    if df.empty:
        logger.warning("[%s] no rows returned — skipping parquet write", label)
        return
    df = _extract_option_details(df)
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{ticker}_option_{label}_{start}_{end}.parquet"
    df.to_parquet(out, index=False)
    logger.info("[%s] saved %d rows -> %s", label, len(df), out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dump OPRA.PILLAR option BBO + trades to parquet (for training/backtest)."
    )
    parser.add_argument("--ticker", required=True, help="Underlying ticker, e.g. AAPL")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--type",
        choices=["bbo", "trades", "both"],
        default="both",
        help="Which schema(s) to dump",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Row cap per schema (useful for smoke tests)",
    )
    parser.add_argument(
        "--output-dir",
        default="./data/option_history",
        help="Directory for parquet output",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )

    ticker = args.ticker.upper()
    output_dir = Path(args.output_dir)

    if args.type in ("bbo", "both"):
        bbo = _fetch_range(
            schema="cbbo-1m",
            ticker=ticker,
            start_date=args.start,
            end_date=args.end,
            limit=args.limit,
        )
        _save(bbo, "bbo", output_dir, ticker, args.start, args.end)

    if args.type in ("trades", "both"):
        trades = _fetch_range(
            schema="trades",
            ticker=ticker,
            start_date=args.start,
            end_date=args.end,
            limit=args.limit,
        )
        _save(trades, "trades", output_dir, ticker, args.start, args.end)

    return 0


if __name__ == "__main__":
    sys.exit(main())
