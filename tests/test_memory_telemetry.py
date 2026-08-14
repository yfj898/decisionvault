from __future__ import annotations

from datetime import datetime, timezone
import json

from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, Outcome, Strategy
from decisionvault.memory_telemetry import (
    build_memory_quality_telemetry,
    calibrate_from_telemetry_rows,
    monotone_shadow_profiles,
    production_threshold_profile,
)


def _row(*, outcome: str, effectiveness: float, shadow: dict) -> dict:
    return {
        "outcome": outcome,
        "effectiveness": effectiveness,
        "quality_features": {"shadows": [shadow]},
    }


def test_shadow_profiles_are_never_looser_than_the_champion():
    policy = OutcomeAwarePolicy()
    champion = production_threshold_profile(policy)
    for profile in monotone_shadow_profiles(policy):
        assert profile.episodic_minimum_similarity >= champion.episodic_minimum_similarity
        assert profile.episodic_minimum_signal >= champion.episodic_minimum_signal
        assert profile.episodic_conflict_margin >= champion.episodic_conflict_margin
        assert profile.adaptive_minimum_similarity >= champion.adaptive_minimum_similarity
        assert (
            profile.adaptive_minimum_effective_confidence
            >= champion.adaptive_minimum_effective_confidence
        )
        assert profile.adaptive_conflict_margin >= champion.adaptive_conflict_margin


def test_real_telemetry_requires_a_minimum_sample_floor():
    shadow = {
        "profile": {"name": "adaptive_effective_confidence_0_35"},
        "same_strategy_as_champion": True,
        "executable": True,
    }
    result = calibrate_from_telemetry_rows(
        [_row(outcome="SUCCESS", effectiveness=0.95, shadow=shadow)],
        minimum_samples=30,
    )
    assert result.recommendation == "INSUFFICIENT_REAL_TELEMETRY"
    assert result.recommended_profile is None


def test_counterfactual_different_executable_strategy_is_never_auto_recommended():
    rows = []
    for _ in range(30):
        rows.append(
            _row(
                outcome="FAILED",
                effectiveness=0.1,
                shadow={
                    "profile": {"name": "adaptive_effective_confidence_0_35"},
                    "same_strategy_as_champion": False,
                    "executable": True,
                },
            )
        )
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    challenger = result.challengers[0]
    assert challenger["counterfactual_unobserved"] == 30
    assert challenger["eligible"] is False
    assert result.recommendation == "KEEP_CHAMPION"


def test_stricter_shadow_can_be_recommended_only_after_real_labeled_evidence():
    rows = []
    for _ in range(27):
        rows.append(
            _row(
                outcome="SUCCESS",
                effectiveness=0.95,
                shadow={
                    "profile": {"name": "adaptive_effective_confidence_0_35"},
                    "same_strategy_as_champion": True,
                    "executable": True,
                },
            )
        )
    for _ in range(3):
        rows.append(
            _row(
                outcome="FAILED",
                effectiveness=0.1,
                shadow={
                    "profile": {"name": "adaptive_effective_confidence_0_35"},
                    "same_strategy_as_champion": False,
                    "executable": False,
                },
            )
        )
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    assert result.recommendation == "RECOMMEND_CHALLENGER_SHADOW_ONLY"
    assert result.recommended_profile == "adaptive_effective_confidence_0_35"


def test_quality_telemetry_domain_field_is_internal_and_not_required_for_decision():
    decision = Decision(strategy=Strategy.GENERIC_RETRY, reason="default")
    assert decision.memory_quality_telemetry == {}
    serialized = json.dumps(
        {
            "strategy": decision.strategy.value,
            "outcome": Outcome.UNKNOWN.value,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    assert "memory_quality_telemetry" not in serialized


def test_quality_features_contain_no_raw_scope_situation_or_identity():
    telemetry = build_memory_quality_telemetry(
        decision=Decision(strategy=Strategy.GENERIC_RETRY, reason="default"),
        policy=OutcomeAwarePolicy(),
        recalled=[],
        adaptive_memories=[],
        context_tags=frozenset(),
        scope_level="TEAM",
    )
    serialized = json.dumps(telemetry, sort_keys=True)
    for forbidden in (
        "scope_id",
        "agent_id",
        "producer_agent_id",
        "episode_id",
        "memory_id",
        "situation",
        "token",
    ):
        assert forbidden not in serialized
