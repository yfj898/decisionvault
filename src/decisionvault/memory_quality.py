from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from itertools import product
from math import log2

from decisionvault.adaptive_memory import (
    Applicability,
    GovernedAdaptiveMemoryResolver,
    GovernedMemory,
    MemoryClass,
    MemoryPolarity,
    MemoryScopeLevel,
)
from decisionvault.agent.memory_governance import ConflictAwareMemoryResolver
from decisionvault.domain import DecisionEpisode, Outcome, RecalledEpisode, Strategy


CALIBRATION_NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class EpisodicThresholdProfile:
    minimum_similarity: float
    minimum_signal: float
    conflict_margin: float


@dataclass(frozen=True, slots=True)
class AdaptiveThresholdProfile:
    minimum_similarity: float
    minimum_effective_confidence: float
    conflict_margin: float


@dataclass(frozen=True, slots=True)
class CalibrationScore:
    total_cases: int
    passed_cases: int
    safety_failures: int
    benefit_failures: int

    @property
    def objective(self) -> int:
        # False influence/conflict misses are much more expensive than a missed
        # optimization opportunity. This keeps calibration aligned with the
        # fail-closed production contract.
        return self.passed_cases - (5 * self.safety_failures) - self.benefit_failures


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    episodic_profile: EpisodicThresholdProfile
    episodic_score: CalibrationScore
    adaptive_profile: AdaptiveThresholdProfile
    adaptive_score: CalibrationScore


def influence_cutoff_days(
    *,
    memory_class: MemoryClass,
    scope_level: MemoryScopeLevel,
    evidence_strength: float = 0.95,
    minimum_effective_confidence: float = 0.30,
) -> float | None:
    """Estimate when a strong memory stops influencing execution before expiry."""

    horizon = memory_class.max_age
    if horizon is None:
        return None
    producers = scope_level.minimum_distinct_producers
    base_confidence = (producers / (producers + 1.0)) * evidence_strength
    if base_confidence <= minimum_effective_confidence:
        return 0.0
    horizon_days = horizon.total_seconds() / 86400.0
    cutoff = (horizon_days / 2.0) * log2(
        base_confidence / minimum_effective_confidence
    )
    return max(0.0, min(horizon_days, cutoff))


@dataclass(frozen=True, slots=True)
class _ExpectedCase:
    name: str
    expected_strategy: Strategy | None
    expected_conflict: bool
    safety_critical: bool


def _episode(
    name: str,
    *,
    strategy: Strategy,
    outcome: Outcome,
    effectiveness: float,
    confidence: float,
    similarity: float,
    age_days: float = 0.0,
    producer: str | None = None,
) -> RecalledEpisode:
    return RecalledEpisode(
        episode=DecisionEpisode(
            episode_id=f"episode-{name}",
            scope_id="calibration",
            situation=name,
            strategy=strategy,
            outcome=outcome,
            effectiveness=effectiveness,
            confidence=confidence,
            evidence={"producer_agent_id": producer or f"producer-{name}"},
            observed_at=CALIBRATION_NOW - timedelta(days=age_days),
            recorded_at=CALIBRATION_NOW,
        ),
        similarity=similarity,
    )


def _episodic_cases() -> tuple[tuple[_ExpectedCase, list[RecalledEpisode]], ...]:
    return (
        (
            _ExpectedCase("failed-generic", Strategy.REFRESH_PAYMENT_TOKEN, False, False),
            [
                _episode(
                    "failed-generic",
                    strategy=Strategy.GENERIC_RETRY,
                    outcome=Outcome.FAILED,
                    effectiveness=0.1,
                    confidence=0.95,
                    similarity=0.42,
                )
            ],
        ),
        (
            _ExpectedCase("successful-billing", Strategy.VERIFY_BILLING_PROFILE, False, False),
            [
                _episode(
                    "successful-billing",
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.85,
                    confidence=0.9,
                    similarity=0.44,
                )
            ],
        ),
        (
            _ExpectedCase("irrelevant", None, False, True),
            [
                _episode(
                    "irrelevant",
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.95,
                    confidence=1.0,
                    similarity=0.28,
                )
            ],
        ),
        (
            _ExpectedCase("low-confidence", None, False, True),
            [
                _episode(
                    "low-confidence",
                    strategy=Strategy.GENERIC_RETRY,
                    outcome=Outcome.FAILED,
                    effectiveness=0.1,
                    confidence=0.45,
                    similarity=0.9,
                )
            ],
        ),
        (
            _ExpectedCase("stale", None, False, True),
            [
                _episode(
                    "stale",
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.95,
                    confidence=1.0,
                    similarity=0.9,
                    age_days=100,
                )
            ],
        ),
        (
            _ExpectedCase("contradiction", None, True, True),
            [
                _episode(
                    "contradiction-success",
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.9,
                    confidence=1.0,
                    similarity=0.75,
                    producer="producer-a",
                ),
                _episode(
                    "contradiction-failure",
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.FAILED,
                    effectiveness=0.1,
                    confidence=1.0,
                    similarity=0.75,
                    producer="producer-b",
                ),
            ],
        ),
        (
            _ExpectedCase("close-strategies", None, True, True),
            [
                _episode(
                    "close-refresh",
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.9,
                    confidence=1.0,
                    similarity=0.60,
                ),
                _episode(
                    "close-billing",
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.9,
                    confidence=1.0,
                    similarity=0.55,
                ),
            ],
        ),
        (
            _ExpectedCase("clear-winner", Strategy.REFRESH_PAYMENT_TOKEN, True, False),
            [
                _episode(
                    "clear-refresh",
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.95,
                    confidence=1.0,
                    similarity=0.80,
                ),
                _episode(
                    "clear-billing",
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.75,
                    confidence=1.0,
                    similarity=0.50,
                ),
            ],
        ),
    )


def _memory(
    name: str,
    *,
    strategy: Strategy,
    confidence: float,
    similarity: float,
    polarity: MemoryPolarity = MemoryPolarity.POSITIVE,
    age_days: float = 0.0,
    memory_class: MemoryClass = MemoryClass.OPERATIONAL,
) -> GovernedMemory:
    memory = GovernedMemory.for_test(
        memory_id=name,
        intervention=strategy,
        polarity=polarity,
        applicability=Applicability(preconditions=frozenset({"payment"})),
        confidence=confidence,
        similarity=similarity,
    )
    observed = CALIBRATION_NOW - timedelta(days=age_days)
    horizon = memory_class.max_age
    return replace(
        memory,
        observed_from=observed,
        observed_to=observed,
        memory_class=memory_class,
        expires_at=None if horizon is None else observed + horizon,
    )


def _adaptive_cases() -> tuple[tuple[_ExpectedCase, list[GovernedMemory]], ...]:
    return (
        (
            _ExpectedCase("fresh-positive", Strategy.REFRESH_PAYMENT_TOKEN, False, False),
            [_memory("fresh-positive", strategy=Strategy.REFRESH_PAYMENT_TOKEN, confidence=0.55, similarity=0.48)],
        ),
        (
            _ExpectedCase("low-similarity", None, False, True),
            [_memory("low-similarity", strategy=Strategy.REFRESH_PAYMENT_TOKEN, confidence=0.9, similarity=0.35)],
        ),
        (
            _ExpectedCase("low-confidence", None, False, True),
            [_memory("low-confidence-adaptive", strategy=Strategy.REFRESH_PAYMENT_TOKEN, confidence=0.14, similarity=0.9)],
        ),
        (
            _ExpectedCase("late-life-operational", None, False, True),
            [_memory("late-life-operational", strategy=Strategy.REFRESH_PAYMENT_TOKEN, confidence=0.9, similarity=0.8, age_days=80)],
        ),
        (
            _ExpectedCase("negative-veto", None, False, True),
            [_memory("negative-veto", strategy=Strategy.REFRESH_PAYMENT_TOKEN, confidence=0.9, similarity=0.8, polarity=MemoryPolarity.AVOID)],
        ),
        (
            _ExpectedCase("adaptive-close", None, True, True),
            [
                _memory("adaptive-close-a", strategy=Strategy.REFRESH_PAYMENT_TOKEN, confidence=0.8, similarity=0.70),
                _memory("adaptive-close-b", strategy=Strategy.VERIFY_BILLING_PROFILE, confidence=0.8, similarity=0.64),
            ],
        ),
        (
            _ExpectedCase("adaptive-clear", Strategy.REFRESH_PAYMENT_TOKEN, False, False),
            [
                _memory("adaptive-clear-a", strategy=Strategy.REFRESH_PAYMENT_TOKEN, confidence=0.9, similarity=0.85),
                _memory("adaptive-clear-b", strategy=Strategy.VERIFY_BILLING_PROFILE, confidence=0.65, similarity=0.55),
            ],
        ),
    )


def _score(actual: list[tuple[_ExpectedCase, Strategy | None, bool]]) -> CalibrationScore:
    passed = 0
    safety_failures = 0
    benefit_failures = 0
    for case, strategy, conflict in actual:
        ok = strategy == case.expected_strategy and conflict == case.expected_conflict
        if ok:
            passed += 1
        elif case.safety_critical:
            safety_failures += 1
        else:
            benefit_failures += 1
    return CalibrationScore(len(actual), passed, safety_failures, benefit_failures)


def score_episodic(profile: EpisodicThresholdProfile) -> CalibrationScore:
    resolver = ConflictAwareMemoryResolver(
        minimum_similarity=profile.minimum_similarity,
        minimum_signal=profile.minimum_signal,
        conflict_margin=profile.conflict_margin,
    )
    actual = []
    for case, memories in _episodic_cases():
        result = resolver.resolve(memories, now=CALIBRATION_NOW)
        actual.append((case, result.selected_strategy, result.conflict))
    return _score(actual)


def score_adaptive(profile: AdaptiveThresholdProfile) -> CalibrationScore:
    resolver = GovernedAdaptiveMemoryResolver(
        minimum_similarity=profile.minimum_similarity,
        minimum_effective_confidence=profile.minimum_effective_confidence,
        conflict_margin=profile.conflict_margin,
    )
    actual = []
    for case, memories in _adaptive_cases():
        result = resolver.resolve(
            memories, context_tags={"payment"}, now=CALIBRATION_NOW
        )
        actual.append((case, result.selected_strategy, result.conflict))
    return _score(actual)


def calibrate_memory_quality() -> CalibrationResult:
    episodic_candidates = [
        EpisodicThresholdProfile(*values)
        for values in product(
            (0.25, 0.30, 0.35, 0.40, 0.45),
            (0.08, 0.12, 0.16),
            (0.05, 0.08, 0.12),
        )
    ]
    adaptive_candidates = [
        AdaptiveThresholdProfile(*values)
        for values in product(
            (0.35, 0.40, 0.45),
            (0.15, 0.20, 0.25, 0.30),
            (0.05, 0.08, 0.12),
        )
    ]

    def episodic_key(profile: EpisodicThresholdProfile):
        score = score_episodic(profile)
        distance = (
            abs(profile.minimum_similarity - 0.30)
            + abs(profile.minimum_signal - 0.12)
            + abs(profile.conflict_margin - 0.08)
        )
        return (score.objective, score.passed_cases, -score.safety_failures, -distance)

    def adaptive_key(profile: AdaptiveThresholdProfile):
        score = score_adaptive(profile)
        distance = (
            abs(profile.minimum_similarity - 0.40)
            + abs(profile.minimum_effective_confidence - 0.15)
            + abs(profile.conflict_margin - 0.08)
        )
        return (score.objective, score.passed_cases, -score.safety_failures, -distance)

    episodic = max(episodic_candidates, key=episodic_key)
    adaptive = max(adaptive_candidates, key=adaptive_key)
    return CalibrationResult(
        episodic_profile=episodic,
        episodic_score=score_episodic(episodic),
        adaptive_profile=adaptive,
        adaptive_score=score_adaptive(adaptive),
    )
