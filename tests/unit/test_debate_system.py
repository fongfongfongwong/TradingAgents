"""Tests for the Structured Debate + Bayesian Aggregation system."""

import pytest

from tradingagents.debate.structured_round import (
    StructuredArgument,
    parse_structured_argument,
)
from tradingagents.debate.bayesian_aggregator import BrierScore, BayesianAggregator


# ---------------------------------------------------------------------------
# StructuredArgument validation
# ---------------------------------------------------------------------------


class TestStructuredArgumentValidation:
    def test_valid_argument(self):
        arg = StructuredArgument(
            agent_name="Bull Analyst",
            position="bullish",
            probability=0.75,
            confidence=0.8,
            reasoning="Strong earnings growth",
            key_evidence=["Revenue up 20%", "Market expansion"],
            fake_bet=500.0,
        )
        assert arg.position == "bullish"
        assert arg.probability == 0.75

    def test_position_case_insensitive(self):
        arg = StructuredArgument(
            agent_name="test",
            position="BULLISH",
            probability=0.5,
            confidence=0.5,
            reasoning="test",
            key_evidence=[],
            fake_bet=100,
        )
        assert arg.position == "bullish"

    def test_invalid_position_rejected(self):
        with pytest.raises(ValueError, match="position must be"):
            StructuredArgument(
                agent_name="test",
                position="sideways",
                probability=0.5,
                confidence=0.5,
                reasoning="test",
                key_evidence=[],
                fake_bet=100,
            )

    def test_probability_out_of_range(self):
        with pytest.raises(ValueError, match="probability must be"):
            StructuredArgument(
                agent_name="test",
                position="bullish",
                probability=1.5,
                confidence=0.5,
                reasoning="test",
                key_evidence=[],
                fake_bet=100,
            )

    def test_confidence_out_of_range(self):
        with pytest.raises(ValueError, match="confidence must be"):
            StructuredArgument(
                agent_name="test",
                position="bearish",
                probability=0.5,
                confidence=-0.1,
                reasoning="test",
                key_evidence=[],
                fake_bet=100,
            )

    def test_fake_bet_out_of_range(self):
        with pytest.raises(ValueError, match="fake_bet must be"):
            StructuredArgument(
                agent_name="test",
                position="neutral",
                probability=0.5,
                confidence=0.5,
                reasoning="test",
                key_evidence=[],
                fake_bet=2000,
            )


# ---------------------------------------------------------------------------
# parse_structured_argument
# ---------------------------------------------------------------------------


class TestParseStructuredArgument:
    def test_well_formatted_text(self):
        text = """
agent_name: Bull Analyst
position: bullish
probability: 0.80
confidence: 0.9
reasoning: The company has strong fundamentals and growing market share.
key_evidence:
- Revenue grew 25% YoY
- New product launch successful
- Market share increased to 30%
fake_bet: 750
"""
        arg = parse_structured_argument(text)
        assert arg.agent_name == "Bull Analyst"
        assert arg.position == "bullish"
        assert abs(arg.probability - 0.80) < 0.01
        assert abs(arg.confidence - 0.9) < 0.01
        assert len(arg.key_evidence) >= 2
        assert abs(arg.fake_bet - 750.0) < 0.01

    def test_percentage_format(self):
        text = """
agent_name: Bear Analyst
position: bearish
probability: 25%
confidence: 85%
reasoning: Declining margins and increased competition.
evidence: margin compression, competitor gains
fake_bet: 600
"""
        arg = parse_structured_argument(text)
        assert abs(arg.probability - 0.25) < 0.01
        assert abs(arg.confidence - 0.85) < 0.01

    def test_malformed_text_graceful_fallback(self):
        text = "This is just a free-form bullish argument about why the stock should go up. Buy buy buy!"
        arg = parse_structured_argument(text)
        # Should not raise, should return defaults
        assert arg.agent_name is not None
        assert arg.position in ("bullish", "bearish", "neutral")
        assert 0.0 <= arg.probability <= 1.0
        assert 0.0 <= arg.confidence <= 1.0
        assert len(arg.key_evidence) >= 1

    def test_completely_empty_text(self):
        arg = parse_structured_argument("")
        assert arg.agent_name == "unknown_agent"
        assert arg.confidence == 0.3  # low default confidence
        assert arg.probability == 0.5  # neutral default

    def test_infers_bull_position_from_content(self):
        text = "Bull Analyst: I believe this stock has incredible upside growth potential. Buy recommendation."
        arg = parse_structured_argument(text)
        assert arg.position == "bullish"
        assert arg.agent_name == "Bull Analyst"

    def test_infers_bear_position_from_content(self):
        text = "Bear Analyst: The downside risk is enormous. I recommend selling short."
        arg = parse_structured_argument(text)
        assert arg.position == "bearish"


# ---------------------------------------------------------------------------
# BrierScore
# ---------------------------------------------------------------------------


class TestBrierScore:
    def test_perfect_predictions_score_near_zero(self):
        bs = BrierScore()
        # Predict high probability for events that happen
        bs.update(0.99, True)
        bs.update(0.99, True)
        bs.update(0.01, False)
        bs.update(0.01, False)
        assert bs.score() < 0.01

    def test_terrible_predictions_score_near_one(self):
        bs = BrierScore()
        # Predict high probability for events that don't happen
        bs.update(0.99, False)
        bs.update(0.99, False)
        bs.update(0.01, True)
        bs.update(0.01, True)
        assert bs.score() > 0.95

    def test_accuracy_weight_inversely_related_to_score(self):
        good = BrierScore()
        good.update(0.9, True)
        good.update(0.1, False)

        bad = BrierScore()
        bad.update(0.1, True)
        bad.update(0.9, False)

        assert good.accuracy_weight() > bad.accuracy_weight()

    def test_no_predictions_default_score(self):
        bs = BrierScore()
        assert bs.score() == 0.5

    def test_accuracy_weight_range(self):
        bs = BrierScore()
        bs.update(0.7, True)
        w = bs.accuracy_weight()
        assert 0.0 <= w <= 1.0


# ---------------------------------------------------------------------------
# BayesianAggregator
# ---------------------------------------------------------------------------


def _make_arg(name: str, position: str, probability: float, confidence: float = 0.8) -> StructuredArgument:
    return StructuredArgument(
        agent_name=name,
        position=position,
        probability=probability,
        confidence=confidence,
        reasoning="test reasoning",
        key_evidence=["evidence"],
        fake_bet=500.0,
    )


class TestBayesianAggregator:
    def test_equal_weights_when_no_history(self):
        agg = BayesianAggregator()
        args = [
            _make_arg("A", "bullish", 0.8),
            _make_arg("B", "bearish", 0.2),
        ]
        result = agg.aggregate(args)
        weights = result["agent_weights"]
        # Both should have equal weight (0.5 each) since no history
        assert abs(weights["A"] - weights["B"]) < 1e-9

    def test_better_agent_gets_higher_weight(self):
        agg = BayesianAggregator()
        # Give agent A a good track record
        agg.update_scores("A", 0.9, True)
        agg.update_scores("A", 0.1, False)
        # Give agent B a bad track record
        agg.update_scores("B", 0.1, True)
        agg.update_scores("B", 0.9, False)

        args = [
            _make_arg("A", "bullish", 0.8),
            _make_arg("B", "bearish", 0.3),
        ]
        result = agg.aggregate(args)
        assert result["agent_weights"]["A"] > result["agent_weights"]["B"]

    def test_extremization_moves_away_from_half(self):
        agg = BayesianAggregator(extremization_factor=2.0)
        args = [_make_arg("A", "bullish", 0.7)]
        result = agg.aggregate(args)
        # Extremization should push 0.7 further from 0.5
        assert result["extremized_probability"] > 0.7

    def test_extremization_symmetric_below_half(self):
        agg = BayesianAggregator(extremization_factor=2.0)
        args = [_make_arg("A", "bearish", 0.3)]
        result = agg.aggregate(args)
        # Extremization should push 0.3 further below 0.5
        assert result["extremized_probability"] < 0.3

    def test_extremization_preserves_half(self):
        agg = BayesianAggregator(extremization_factor=2.0)
        args = [_make_arg("A", "neutral", 0.5)]
        result = agg.aggregate(args)
        assert abs(result["extremized_probability"] - 0.5) < 0.01

    def test_direction_bullish(self):
        agg = BayesianAggregator()
        args = [_make_arg("A", "bullish", 0.85)]
        result = agg.aggregate(args)
        assert result["direction"] == "bullish"

    def test_direction_bearish(self):
        agg = BayesianAggregator()
        args = [_make_arg("A", "bearish", 0.15)]
        result = agg.aggregate(args)
        assert result["direction"] == "bearish"

    def test_direction_neutral(self):
        agg = BayesianAggregator()
        args = [
            _make_arg("A", "bullish", 0.55),
            _make_arg("B", "bearish", 0.45),
        ]
        result = agg.aggregate(args)
        assert result["direction"] == "neutral"

    def test_conviction_high(self):
        agg = BayesianAggregator()
        args = [_make_arg("A", "bullish", 0.95)]
        result = agg.aggregate(args)
        assert result["conviction"] == "high"

    def test_conviction_low(self):
        agg = BayesianAggregator(extremization_factor=1.0)  # no extremization
        args = [
            _make_arg("A", "bullish", 0.52),
            _make_arg("B", "bearish", 0.48),
        ]
        result = agg.aggregate(args)
        assert result["conviction"] == "low"

    def test_conviction_medium(self):
        agg = BayesianAggregator(extremization_factor=1.0)
        args = [_make_arg("A", "bullish", 0.7)]
        result = agg.aggregate(args)
        assert result["conviction"] == "medium"

    def test_empty_arguments(self):
        agg = BayesianAggregator()
        result = agg.aggregate([])
        assert result["consensus_probability"] == 0.5
        assert result["direction"] == "neutral"
        assert result["conviction"] == "low"

    def test_aggregate_returns_all_keys(self):
        agg = BayesianAggregator()
        args = [_make_arg("A", "bullish", 0.7)]
        result = agg.aggregate(args)
        expected_keys = {
            "consensus_probability",
            "raw_probability",
            "extremized_probability",
            "agent_weights",
            "direction",
            "conviction",
        }
        assert set(result.keys()) == expected_keys

    def test_update_scores_changes_weight(self):
        agg = BayesianAggregator()
        # Initially equal
        args = [_make_arg("A", "bullish", 0.8), _make_arg("B", "bearish", 0.3)]
        r1 = agg.aggregate(args)
        assert abs(r1["agent_weights"]["A"] - r1["agent_weights"]["B"]) < 1e-9

        # Now update A with good predictions
        agg.update_scores("A", 0.9, True)
        agg.update_scores("A", 0.1, False)
        agg.update_scores("B", 0.5, True)  # mediocre

        r2 = agg.aggregate(args)
        assert r2["agent_weights"]["A"] > r2["agent_weights"]["B"]
