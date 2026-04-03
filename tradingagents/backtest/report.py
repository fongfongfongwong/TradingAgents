"""Markdown report generator for backtest results.

Uses only Python stdlib.
"""

from __future__ import annotations


class BacktestReport:
    """Generates a markdown-formatted backtest report."""

    def generate(
        self,
        metrics: dict,
        equity_curve: list,
        trades: list,
    ) -> str:
        """Return a complete markdown report string."""
        sections = [
            self._header(),
            self._performance_summary(metrics),
            self._trade_log(trades),
            self._key_statistics(metrics, equity_curve),
        ]
        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    @staticmethod
    def _header() -> str:
        return "# Backtest Report"

    @staticmethod
    def _performance_summary(metrics: dict) -> str:
        rows = [
            ("Total Return", f"{metrics.get('total_return', 0) * 100:.2f}%"),
            ("Annual Return", f"{metrics.get('annual_return', 0) * 100:.2f}%"),
            ("Sharpe Ratio", f"{metrics.get('sharpe_ratio', 0):.4f}"),
            ("Sortino Ratio", f"{metrics.get('sortino_ratio', 0):.4f}"),
            ("Max Drawdown", f"{metrics.get('max_drawdown', 0) * 100:.2f}%"),
            ("Max DD Duration", f"{metrics.get('max_drawdown_duration', 0)} days"),
        ]
        lines = ["## Performance Summary", "", "| Metric | Value |", "|---|---|"]
        for name, val in rows:
            lines.append(f"| {name} | {val} |")
        return "\n".join(lines)

    @staticmethod
    def _trade_log(trades: list) -> str:
        lines = [
            "## Trade Log",
            "",
            "| Date | Ticker | Action | Price | Shares | Commission | P&L |",
            "|---|---|---|---|---|---|---|",
        ]
        for t in trades:
            lines.append(
                f"| {t.get('date', '')} "
                f"| {t.get('ticker', '')} "
                f"| {t.get('action', '')} "
                f"| {t.get('price', 0):.2f} "
                f"| {t.get('shares', 0):.4f} "
                f"| {t.get('commission', 0):.2f} "
                f"| {t.get('pnl', 0):.2f} |"
            )
        if not trades:
            lines.append("| - | - | - | - | - | - | - |")
        return "\n".join(lines)

    @staticmethod
    def _key_statistics(metrics: dict, equity_curve: list) -> str:
        lines = [
            "## Key Statistics",
            "",
            "| Statistic | Value |",
            "|---|---|",
            f"| Total Trades | {metrics.get('total_trades', 0)} |",
            f"| Win Rate | {metrics.get('win_rate', 0) * 100:.2f}% |",
            f"| Profit Factor | {metrics.get('profit_factor', 0):.4f} |",
            f"| Avg Trade Return | {metrics.get('avg_trade_return', 0):.2f} |",
            f"| Expectancy | {metrics.get('expectancy', 0):.2f} |",
        ]
        if equity_curve:
            lines.append(f"| Starting Value | {equity_curve[0]:,.2f} |")
            lines.append(f"| Ending Value | {equity_curve[-1]:,.2f} |")
        return "\n".join(lines)
