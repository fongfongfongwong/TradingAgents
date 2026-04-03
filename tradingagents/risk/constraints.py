"""Portfolio-level constraints: position limits, sector caps, drawdown guard."""

from __future__ import annotations


class PortfolioConstraints:
    """Validate a proposed trade against portfolio-level risk limits."""

    def __init__(
        self,
        max_position_pct: float = 0.10,
        max_sector_pct: float = 0.30,
        max_drawdown: float = 0.15,
        max_correlation: float = 0.7,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
        self.max_drawdown = max_drawdown
        self.max_correlation = max_correlation

    def check(self, proposed_trade: dict, portfolio: dict) -> dict:
        """Check whether *proposed_trade* respects portfolio constraints.

        Parameters
        ----------
        proposed_trade : dict
            Must contain at least: ticker, shares, price, sector.
        portfolio : dict
            Must contain at least: total_value, sector_exposures (dict[str,float]),
            current_drawdown (float).

        Returns
        -------
        dict with keys: allowed, violations, adjusted_size
        """
        violations: list[str] = []
        total_value = portfolio.get("total_value", 0.0)
        if total_value <= 0:
            return {
                "allowed": False,
                "violations": ["portfolio total_value <= 0"],
                "adjusted_size": None,
            }

        trade_value = proposed_trade.get("shares", 0) * proposed_trade.get("price", 0)
        position_pct = trade_value / total_value

        # --- Position concentration ---
        if position_pct > self.max_position_pct:
            violations.append(
                f"position {position_pct:.2%} exceeds max {self.max_position_pct:.2%}"
            )

        # --- Sector exposure ---
        sector = proposed_trade.get("sector", "unknown")
        sector_exposures = portfolio.get("sector_exposures", {})
        existing_sector_pct = sector_exposures.get(sector, 0.0)
        new_sector_pct = existing_sector_pct + position_pct
        if new_sector_pct > self.max_sector_pct:
            violations.append(
                f"sector '{sector}' exposure {new_sector_pct:.2%} exceeds max {self.max_sector_pct:.2%}"
            )

        # --- Drawdown guard ---
        current_dd = portfolio.get("current_drawdown", 0.0)
        if current_dd >= self.max_drawdown:
            violations.append(
                f"portfolio drawdown {current_dd:.2%} exceeds max {self.max_drawdown:.2%}"
            )

        # Compute adjusted size if position too large
        adjusted_size = None
        if position_pct > self.max_position_pct and total_value > 0:
            max_dollar = total_value * self.max_position_pct
            price = proposed_trade.get("price", 1)
            adjusted_size = int(max_dollar // price) if price > 0 else 0

        allowed = len(violations) == 0
        return {
            "allowed": allowed,
            "violations": violations,
            "adjusted_size": adjusted_size,
        }
