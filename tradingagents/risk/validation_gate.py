"""Validation gate: thin quant layer that can BLOCK bad trades but never generates signals."""

from __future__ import annotations


class ValidationGate:
    """Run five sanity / risk checks on a trade proposal.

    The gate **never** generates trading signals; it only vetoes bad ones.
    """

    def __init__(
        self,
        max_position_pct: float = 0.10,
        max_drawdown: float = 0.15,
        min_avg_volume: int = 100_000,
        max_commission_pct: float = 0.01,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.max_drawdown = max_drawdown
        self.min_avg_volume = min_avg_volume
        self.max_commission_pct = max_commission_pct

    def validate(self, trade_proposal: dict) -> dict:
        """Validate *trade_proposal* through five independent checks.

        Expected keys in *trade_proposal*:
            ticker, price, shares, portfolio_value, avg_volume,
            current_drawdown, estimated_commission

        Returns
        -------
        dict with keys: approved, checks_passed, checks_failed, adjustments
        """
        passed: list[str] = []
        failed: list[str] = []
        adjustments: dict = {}

        ticker = trade_proposal.get("ticker", "")
        price = trade_proposal.get("price", 0)
        shares = trade_proposal.get("shares", 0)
        portfolio_value = trade_proposal.get("portfolio_value", 0)
        avg_volume = trade_proposal.get("avg_volume", 0)
        current_dd = trade_proposal.get("current_drawdown", 0.0)
        commission = trade_proposal.get("estimated_commission", 0.0)

        # 1. Sanity ---------------------------------------------------------
        if price > 0 and shares > 0 and ticker:
            passed.append("sanity")
        else:
            reasons = []
            if price <= 0:
                reasons.append("price<=0")
            if shares <= 0:
                reasons.append("shares<=0")
            if not ticker:
                reasons.append("ticker empty")
            failed.append(f"sanity ({', '.join(reasons)})")

        # 2. Liquidity ------------------------------------------------------
        if avg_volume >= self.min_avg_volume:
            passed.append("liquidity")
        else:
            failed.append(
                f"liquidity (avg_volume {avg_volume} < {self.min_avg_volume})"
            )

        # 3. Concentration --------------------------------------------------
        if portfolio_value > 0:
            pos_pct = (price * shares) / portfolio_value
            if pos_pct <= self.max_position_pct:
                passed.append("concentration")
            else:
                failed.append(
                    f"concentration (position {pos_pct:.2%} > {self.max_position_pct:.2%})"
                )
                max_shares = int((portfolio_value * self.max_position_pct) // price) if price > 0 else 0
                adjustments["suggested_shares"] = max_shares
        else:
            failed.append("concentration (portfolio_value<=0)")

        # 4. Drawdown -------------------------------------------------------
        if current_dd < self.max_drawdown:
            passed.append("drawdown")
        else:
            failed.append(
                f"drawdown ({current_dd:.2%} >= {self.max_drawdown:.2%})"
            )

        # 5. Cost -----------------------------------------------------------
        trade_value = price * shares
        if trade_value > 0:
            cost_pct = commission / trade_value
            if cost_pct < self.max_commission_pct:
                passed.append("cost")
            else:
                failed.append(
                    f"cost (commission {cost_pct:.2%} >= {self.max_commission_pct:.2%})"
                )
        else:
            # If trade value is zero, cost check is moot (sanity already failed)
            passed.append("cost")

        return {
            "approved": len(failed) == 0,
            "checks_passed": passed,
            "checks_failed": failed,
            "adjustments": adjustments,
        }
