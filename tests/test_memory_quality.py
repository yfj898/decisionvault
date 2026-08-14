from decisionvault.memory_quality import (
    AdaptiveThresholdProfile,
    EpisodicThresholdProfile,
    calibrate_memory_quality,
    influence_cutoff_days,
    score_adaptive,
    score_episodic,
)
from decisionvault.adaptive_memory import (
    GovernedAdaptiveMemoryResolver,
    MemoryClass,
    MemoryScopeLevel,
    PRODUCTION_ADAPTIVE_MIN_EFFECTIVE_CONFIDENCE,
)


def test_current_quality_profiles_are_measured_not_assumed():
    episodic = score_episodic(EpisodicThresholdProfile(0.30, 0.12, 0.08))
    adaptive = score_adaptive(AdaptiveThresholdProfile(0.40, 0.15, 0.08))

    assert episodic.total_cases == 8
    assert adaptive.total_cases == 7
    assert episodic.safety_failures >= 0
    assert adaptive.safety_failures >= 0


def test_calibration_never_prefers_more_safety_failures_for_raw_accuracy():
    result = calibrate_memory_quality()
    current_episodic = score_episodic(EpisodicThresholdProfile(0.30, 0.12, 0.08))
    current_adaptive = score_adaptive(AdaptiveThresholdProfile(0.40, 0.15, 0.08))

    assert result.episodic_score.objective >= current_episodic.objective
    assert result.adaptive_score.objective >= current_adaptive.objective
    assert result.episodic_score.safety_failures <= current_episodic.safety_failures
    assert result.adaptive_score.safety_failures <= current_adaptive.safety_failures


def test_calibrated_adaptive_confidence_is_the_production_default():
    result = calibrate_memory_quality()
    resolver = GovernedAdaptiveMemoryResolver()

    assert result.adaptive_profile.minimum_effective_confidence == 0.30
    assert PRODUCTION_ADAPTIVE_MIN_EFFECTIVE_CONFIDENCE == 0.30
    assert resolver.minimum_effective_confidence == 0.30


def test_calibrated_long_term_decay_stops_execution_influence_before_expiry():
    private_days = influence_cutoff_days(
        memory_class=MemoryClass.LONG_TERM,
        scope_level=MemoryScopeLevel.PRIVATE,
    )
    team_days = influence_cutoff_days(
        memory_class=MemoryClass.LONG_TERM,
        scope_level=MemoryScopeLevel.TEAM,
    )
    global_days = influence_cutoff_days(
        memory_class=MemoryClass.LONG_TERM,
        scope_level=MemoryScopeLevel.GLOBAL,
    )

    assert private_days is not None and 90 < private_days < 180
    assert team_days is not None and private_days < team_days < 260
    assert global_days is not None and team_days < global_days < 300
