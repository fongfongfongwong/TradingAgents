#!/usr/bin/env python
"""Train HAR-RV Ridge baseline models for 1d and 5d horizons.

Usage
-----
    PYTHONPATH=. .venv/bin/python scripts/train_har_rv_baseline.py
    PYTHONPATH=. .venv/bin/python scripts/train_har_rv_baseline.py --tickers AAPL MSFT GOOGL
    PYTHONPATH=. .venv/bin/python scripts/train_har_rv_baseline.py --smoke  # 10 tickers, fast

Outputs
-------
    Models:  ~/.tradingagents/models/har_rv_ridge_1d.joblib
             ~/.tradingagents/models/har_rv_ridge_5d.joblib
    Reports: ~/.tradingagents/outputs/rv_prediction/baseline/

This script is the live activation entry point for the HAR-RV baseline.
It does NOT perform any LLM calls; it fetches OHLC data via yfinance and
trains small ridge models locally.
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("har_rv_training")


def _resolve_target_col(horizon: int) -> str:
    """Return the target column name produced by data_assembly for a horizon.

    Keeping this in one place so that a rename of the convention (e.g.
    ``rv_next_1d`` -> ``rv_daily_next_1d``) only needs a single update here.
    """
    return f"rv_next_{horizon}d"


def main() -> int:
    parser = argparse.ArgumentParser(description="Train HAR-RV Ridge baseline")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker list (default: CLEAN_STOCK_TICKERS + CLEAN_ETF_TICKERS)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run with 10 tickers only, quick smoke test",
    )
    parser.add_argument("--train-start", default="2020-01-01")
    parser.add_argument("--train-end", default="2023-12-31")
    parser.add_argument("--valid-end", default="2024-06-30")
    parser.add_argument("--panel-end", default="2025-08-31")
    parser.add_argument("--horizons", nargs="+", type=int, default=[1, 5])
    parser.add_argument(
        "--target-transform",
        choices=("raw", "log"),
        default="log",
        help="Ridge training target transform ('raw' level or 'log' of level). "
        "Default 'log' matches the Corsi (2009) log-HAR specification.",
    )
    parser.add_argument(
        "--feature-set-version",
        default="tier0",
        help="Feature set version tag stored in the model artefact "
        "(e.g. 'tier0', 'tier1'). Default 'tier0'.",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Run purged walk-forward evaluation (López de Prado 2018, Ch. 7) "
        "instead of the single 70/15/15 split.",
    )
    parser.add_argument(
        "--wf-splits",
        type=int,
        default=5,
        help="Number of purged walk-forward folds (only used with --walk-forward).",
    )
    parser.add_argument(
        "--wf-embargo",
        type=int,
        default=10,
        help="Embargo days between train and test in each walk-forward fold.",
    )
    args = parser.parse_args()

    # Imports are deferred until after argparse so --help is snappy and
    # does not pay the cost of the heavy scientific stack.
    import pandas as pd

    from tradingagents.evaluation.ic_metrics import full_evaluation
    from tradingagents.evaluation.output_writer import (
        write_summary,
        write_target_outputs,
    )
    from tradingagents.factors.clean_tickers import (
        CLEAN_ETF_TICKERS,
        CLEAN_STOCK_TICKERS,
    )
    from tradingagents.models.data_assembly import assemble_panel, split_by_date
    from tradingagents.models.har_rv_ridge import (
        predict,
        save_model,
        train_ridge_model,
    )

    if args.smoke:
        tickers = list(CLEAN_STOCK_TICKERS[:8]) + list(CLEAN_ETF_TICKERS[:2])
        logger.info("SMOKE mode: %d tickers", len(tickers))
    elif args.tickers:
        tickers = list(args.tickers)
    else:
        tickers = list(CLEAN_STOCK_TICKERS) + list(CLEAN_ETF_TICKERS)

    logger.info("Assembling panel for %d tickers", len(tickers))
    panel = assemble_panel(
        tickers=tickers,
        start=args.train_start,
        end=args.panel_end,
        horizons=tuple(args.horizons),
    )
    if panel.empty:
        logger.error("assemble_panel returned an empty panel; aborting")
        return 2
    logger.info("Panel assembled: %d rows", len(panel))

    if args.walk_forward:
        from tradingagents.evaluation.walk_forward import walk_forward_evaluate

        target_summaries: dict[str, dict] = {}
        for h in args.horizons:
            target_col = _resolve_target_col(h)
            report_name = f"rv_daily_next_{h}d"
            logger.info(
                "Walk-forward evaluating %s (n_splits=%d, embargo=%d, transform=%s)",
                report_name,
                args.wf_splits,
                args.wf_embargo,
                args.target_transform,
            )
            try:
                from tradingagents.models.har_rv_ridge import _default_feature_cols

                wf_result = walk_forward_evaluate(
                    panel=panel,
                    feature_cols=_default_feature_cols(),
                    target_col=target_col,
                    n_splits=args.wf_splits,
                    embargo_days=args.wf_embargo,
                    target_transform=args.target_transform,
                )
                summary = wf_result["summary"]
                logger.info(
                    "WF %s [%s]: R2=%.4f+/-%.4f  IC=%.4f+/-%.4f  QLIKE=%.4f+/-%.4f  (n=%d)",
                    report_name,
                    args.target_transform,
                    summary["r2_mean"],
                    summary["r2_std"],
                    summary["ic_mean"],
                    summary["ic_std"],
                    summary["qlike_mean"],
                    summary["qlike_std"],
                    summary["n_splits_ok"],
                )
                for s in wf_result["splits"]:
                    logger.info(
                        "  split %d [%s..%s -> %s..%s]: R2=%.4f IC=%.4f QLIKE=%.4f "
                        "(n_train=%d n_test=%d)",
                        s["split_idx"],
                        s["train_start"],
                        s["train_end"],
                        s["test_start"],
                        s["test_end"],
                        s["pooled_r2"],
                        s["ic_mean"],
                        s["qlike"],
                        s["n_train"],
                        s["n_test"],
                    )
                target_summaries[report_name] = wf_result
            except Exception as exc:  # noqa: BLE001
                logger.exception("Walk-forward failed for horizon %d: %s", h, exc)
                target_summaries[report_name] = {"error": str(exc)}
        logger.info("DONE. Walk-forward summary printed above.")
        return 0

    train, valid, test = split_by_date(
        panel,
        train_end=args.train_end,
        valid_end=args.valid_end,
    )
    logger.info(
        "Split sizes: train=%d, valid=%d, test=%d",
        len(train),
        len(valid),
        len(test),
    )

    target_summaries: dict[str, dict] = {}

    for h in args.horizons:
        # Report name follows the BASELINE.md "rv_daily_next_{h}d" convention.
        report_name = f"rv_daily_next_{h}d"
        target_col = _resolve_target_col(h)
        logger.info(
            "Training model for %s (horizon=%d, target_col=%s)",
            report_name,
            h,
            target_col,
        )

        try:
            model = train_ridge_model(
                train,
                horizon=h,
                target_transform=args.target_transform,
                feature_set_version=args.feature_set_version,
            )
            logger.info(
                "Model trained: alpha=%s, train_rows=%d",
                model.alpha,
                model.train_rows,
            )
            save_path = save_model(model)
            logger.info("Model saved to %s", save_path)

            predictions: dict[str, pd.DataFrame] = {}
            for name, split in (("train", train), ("valid", valid), ("test", test)):
                if split.empty or target_col not in split.columns:
                    logger.warning(
                        "Skipping %s for horizon=%d: split empty or target missing",
                        name,
                        h,
                    )
                    continue
                pred = predict(model, split, min_tickers=1)
                if pred.empty:
                    continue
                actual = split.loc[pred.index, target_col]
                pred_df = (
                    pd.DataFrame({"actual": actual, "predicted": pred.values})
                    .dropna()
                    .reset_index()
                )
                predictions[name] = pred_df

            metrics = {
                name: full_evaluation(pred_df, period_name=name)
                for name, pred_df in predictions.items()
            }
            target_summaries[report_name] = metrics

            write_target_outputs(report_name, metrics, predictions)
            logger.info("Wrote outputs for %s", report_name)
        except Exception as exc:  # noqa: BLE001 - log and continue to next horizon
            logger.exception("Training failed for horizon %d: %s", h, exc)
            target_summaries[report_name] = {"error": str(exc)}

    write_summary(target_summaries)
    logger.info("DONE. Summary written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
