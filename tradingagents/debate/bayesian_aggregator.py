"""Bayesian aggregation of structured debate arguments with Brier score weighting."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from tradingagents.debate.structured_round import StructuredArgument


@dataclass
class BrierScore:
    """Tracks prediction accuracy using Brier scores.

    The Brier score measures the accuracy of probabilistic predictions.
    Lower scores indicate better calibration (0 = perfect, 1 = worst).
    """

    predictions: list[tuple[float, bool]] = field(default_factory=list)

    def update(self, predicted_prob: float, actual_outcome: bool) -> None:
        """Record a prediction and its actual outcome.

        Args:
            predicted_prob: The predicted probability of a positive outcome (0-1).
            actual_outcome: Whether the positive outcome actually occurred.
        """
        self.predictions.append((predicted_prob, actual_outcome))

    def score(self) -> float:
        """Compute the Brier score over all recorded predictions.

        Returns:
            The mean Brier score (0-1). Lower is better.
            Returns 0.5 if no predictions have been recorded.
        """
        if not self.predictions:
            return 0.5
        total = 0.0
        for predicted, actual in self.predictions:
            outcome = 1.0 if actual else 0.0
            total += (predicted - outcome) ** 2
        return total / len(self.predictions)

    def accuracy_weight(self) -> float:
        """Convert Brier score to a weight (higher = more accurate).

        Returns:
            A weight in [0, 1] where 1 means perfect predictions.
        """
        return 1.0 - self.score()


class BayesianAggregator:
    """Aggregates structured debate arguments using Brier-score-weighted Bayesian updating.

    Agents with better historical prediction accuracy receive higher weights
    in the consensus probability calculation.
    """

    def __init__(self, extremization_factor: float = 1.5) -> None:
        """Initialize the aggregator.

        Args:
            extremization_factor: The 'a' parameter for extremization.
                Must be > 1. Higher values push probabilities further from 0.5.
                Default is 1.5.
        """
        self.agent_scores: dict[str, BrierScore] = {}
        self.extremization_factor = extremization_factor

    def _get_or_create_score(self, agent_name: str) -> BrierScore:
        """Get or create a BrierScore tracker for an agent."""
        if agent_name not in self.agent_scores:
            self.agent_scores[agent_name] = BrierScore()
        return self.agent_scores[agent_name]

    def aggregate(self, arguments: list[StructuredArgument]) -> dict:
        """Aggregate multiple structured arguments into a consensus view.

        Args:
            arguments: List of StructuredArgument from debate participants.

        Returns:
            Dictionary with:
                - consensus_probability: final extremized probability
                - raw_probability: simple weighted average before extremization
                - extremized_probability: after extremization correction
                - agent_weights: dict of agent_name -> weight used
                - direction: "bullish", "bearish", or "neutral"
                - conviction: "high", "medium", or "low"
        """
        if not arguments:
            return {
                "consensus_probability": 0.5,
                "raw_probability": 0.5,
                "extremized_probability": 0.5,
                "agent_weights": {},
                "direction": "neutral",
                "conviction": "low",
            }

        # Compute weights from Brier scores
        weights: dict[str, float] = {}
        for arg in arguments:
            brier = self._get_or_create_score(arg.agent_name)
            weights[arg.agent_name] = brier.accuracy_weight()

        # Normalize weights
        total_weight = sum(weights.values())
        if total_weight == 0:
            # All agents have worst possible scores; fall back to equal
            norm_weights = {name: 1.0 / len(weights) for name in weights}
        else:
            norm_weights = {name: w / total_weight for name, w in weights.items()}

        # Compute weighted average probability
        raw_prob = sum(
            arg.probability * norm_weights[arg.agent_name]
            for arg in arguments
        )

        # Clamp to avoid log(0) in extremization
        raw_prob = max(1e-9, min(1.0 - 1e-9, raw_prob))

        # Extremization: p_ext = p^a / (p^a + (1-p)^a)
        a = self.extremization_factor
        p_a = math.pow(raw_prob, a)
        q_a = math.pow(1.0 - raw_prob, a)
        extremized_prob = p_a / (p_a + q_a)

        # Classify direction
        if extremized_prob > 0.6:
            direction = "bullish"
        elif extremized_prob < 0.4:
            direction = "bearish"
        else:
            direction = "neutral"

        # Classify conviction based on distance from 0.5
        distance = abs(extremized_prob - 0.5)
        if distance > 0.3:
            conviction = "high"
        elif distance > 0.15:
            conviction = "medium"
        else:
            conviction = "low"

        return {
            "consensus_probability": extremized_prob,
            "raw_probability": raw_prob,
            "extremized_probability": extremized_prob,
            "agent_weights": dict(norm_weights),
            "direction": direction,
            "conviction": conviction,
        }

    def update_scores(
        self, agent_name: str, predicted_prob: float, actual_outcome: bool
    ) -> None:
        """Update Brier score tracking after an outcome is known.

        Args:
            agent_name: Name of the agent whose prediction to update.
            predicted_prob: The probability the agent predicted.
            actual_outcome: Whether the positive outcome actually occurred.
        """
        brier = self._get_or_create_score(agent_name)
        brier.update(predicted_prob, actual_outcome)
