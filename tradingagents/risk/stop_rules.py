"""Stop-loss rules: trailing, ATR-based, time-based, and composite."""

from __future__ import annotations

import abc
from statistics import mean


class StopRule(abc.ABC):
    """Abstract base class for exit / stop-loss rules."""

    @abc.abstractmethod
    def should_exit(
        self,
        current_price: float,
        entry_price: float,
        peak_price: float,
        days_held: int,
        indicators: dict | None = None,
    ) -> dict:
        """Evaluate whether the position should be exited.

        Returns
        -------
        dict with at least: {"exit": bool, "reason": str}
        """
        ...


class TrailingStop(StopRule):
    """Exit if price drops *pct* from peak."""

    def __init__(self, pct: float = 0.10) -> None:
        self.pct = pct

    def should_exit(
        self,
        current_price: float,
        entry_price: float,
        peak_price: float,
        days_held: int,
        indicators: dict | None = None,
    ) -> dict:
        if peak_price <= 0:
            return {"exit": False, "reason": "invalid peak price"}
        drop = (peak_price - current_price) / peak_price
        triggered = drop >= self.pct
        return {
            "exit": triggered,
            "reason": f"trailing_stop: drop {drop:.2%} vs limit {self.pct:.2%}",
            "drop_pct": round(drop, 6),
        }


class ATRStop(StopRule):
    """Exit if price drops *multiplier* x ATR from entry."""

    def __init__(self, multiplier: float = 2.0) -> None:
        self.multiplier = multiplier

    def should_exit(
        self,
        current_price: float,
        entry_price: float,
        peak_price: float,
        days_held: int,
        indicators: dict | None = None,
    ) -> dict:
        indicators = indicators or {}
        atr = indicators.get("atr", 0.0)
        if atr <= 0:
            return {"exit": False, "reason": "atr unavailable"}
        threshold = entry_price - self.multiplier * atr
        triggered = current_price <= threshold
        return {
            "exit": triggered,
            "reason": f"atr_stop: price {current_price} vs threshold {threshold:.2f}",
            "threshold": round(threshold, 4),
        }


class TimeStop(StopRule):
    """Exit after holding for *max_days*."""

    def __init__(self, max_days: int = 30) -> None:
        self.max_days = max_days

    def should_exit(
        self,
        current_price: float,
        entry_price: float,
        peak_price: float,
        days_held: int,
        indicators: dict | None = None,
    ) -> dict:
        triggered = days_held >= self.max_days
        return {
            "exit": triggered,
            "reason": f"time_stop: held {days_held}d vs max {self.max_days}d",
        }


class CompositeStop:
    """Combine multiple stop rules; exit if ANY triggers."""

    def __init__(self, rules: list[StopRule]) -> None:
        self.rules = list(rules)

    def should_exit(
        self,
        current_price: float,
        entry_price: float,
        peak_price: float,
        days_held: int,
        indicators: dict | None = None,
    ) -> dict:
        results: list[dict] = []
        triggered_reasons: list[str] = []

        for rule in self.rules:
            result = rule.should_exit(
                current_price, entry_price, peak_price, days_held, indicators
            )
            results.append(result)
            if result["exit"]:
                triggered_reasons.append(result["reason"])

        should = len(triggered_reasons) > 0
        return {
            "exit": should,
            "reason": "; ".join(triggered_reasons) if should else "no stop triggered",
            "details": results,
        }
