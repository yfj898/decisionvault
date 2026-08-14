from __future__ import annotations

from datetime import datetime, timezone
import json

from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, Outcome, Strategy
from decisionvault.memory_telemetry import (
    build_memory_quality_telemetry,
    calibration_is_due,
    calibrate_from_telemetry_rows,
    monotone_shadow_profiles,
    production_threshold_profile,
    run_persisted_calibration,
    threshold_profile_catalog,
)


def _row(*, outcome: str, effectiveness: float, shadow: dict) -> dict:
    return {
        "outcome": outcome,
        "effectiveness": effectiveness,
        "quality_features": {
            "episodic": {"candidate_count": 1},
            "adaptive": {"candidate_count": 0},
            "shadows": [shadow],
        },
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


def test_threshold_profile_catalog_contains_champion_and_all_shadows():
    catalog = threshold_profile_catalog()
    assert catalog["champion"].name == "champion"
    assert set(catalog) == {
        "champion",
        *(profile.name for profile in monotone_shadow_profiles(OutcomeAwarePolicy())),
    }


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


def test_no_memory_default_requests_do_not_count_as_threshold_evidence():
    row = _row(
        outcome="SUCCESS",
        effectiveness=0.95,
        shadow={
            "profile": {"name": "adaptive_effective_confidence_0_35"},
            "same_strategy_as_champion": True,
            "executable": True,
        },
    )
    row["quality_features"]["episodic"]["candidate_count"] = 0
    result = calibrate_from_telemetry_rows([row], minimum_samples=1)
    assert result.observed_samples == 0
    assert result.recommendation == "INSUFFICIENT_REAL_TELEMETRY"


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


def test_challenger_harmful_rate_above_five_percent_is_not_eligible():
    rows = []
    shadow = {
        "profile": {"name": "adaptive_effective_confidence_0_35"},
        "same_strategy_as_champion": True,
        "executable": True,
    }
    for _ in range(28):
        rows.append(_row(outcome="SUCCESS", effectiveness=0.95, shadow=shadow))
    for _ in range(2):
        rows.append(_row(outcome="FAILED", effectiveness=0.1, shadow=shadow))
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    challenger = result.challengers[0]
    assert challenger["harmful_rate"] > 0.05
    assert challenger["eligible"] is False


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


class _TelemetryCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _TelemetryConnection:
    def __init__(self, rows=()):
        self.cursor_value = _TelemetryCursor(rows)
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True

    def rollback(self):
        self.committed = False

    def close(self):
        self.closed = True


def test_persisted_calibration_is_aggregate_append_only_and_keeps_champion_below_floor():
    now = datetime.now(timezone.utc)
    shadow = {
        "profile": {"name": "adaptive_effective_confidence_0_35"},
        "same_strategy_as_champion": True,
        "executable": True,
    }
    rows = [
        (
            "AGENT_API",
            now,
            "TEAM",
            "REFRESH_PAYMENT_TOKEN",
            True,
            True,
            "GOVERNED_MEMORY",
            False,
            {
                "episodic": {"candidate_count": 1},
                "adaptive": {"candidate_count": 0},
                "shadows": [shadow],
            },
            "SUCCESS",
            0.95,
            1.0,
            now,
            now,
        )
    ]
    read_conn = _TelemetryConnection(rows)
    write_conn = _TelemetryConnection()
    connections = [read_conn, write_conn]

    run = run_persisted_calibration(
        connection_factory=lambda: connections.pop(0),
        minimum_samples=30,
    )

    assert run.summary.observed_samples == 1
    assert run.summary.recommendation == "INSUFFICIENT_REAL_TELEMETRY"
    assert write_conn.committed is True
    insert_sql, insert_params = write_conn.cursor_value.executions[0]
    assert "INSERT INTO decision_memory_quality_calibration_runs" in insert_sql
    serialized = json.dumps(insert_params, default=str)
    for forbidden in (
        "scope_id",
        "agent_id",
        "producer_agent_id",
        "episode_id",
        "memory_id",
        "situation",
    ):
        assert forbidden not in serialized


def test_calibration_due_uses_persisted_run_as_durable_24h_throttle():
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    never = _TelemetryConnection()
    recent = _TelemetryConnection(
        [(datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc),)]
    )
    stale = _TelemetryConnection(
        [(datetime(2026, 8, 13, 11, 0, tzinfo=timezone.utc),)]
    )

    assert calibration_is_due(connection_factory=lambda: never, now=now)
    assert not calibration_is_due(connection_factory=lambda: recent, now=now)
    assert calibration_is_due(connection_factory=lambda: stale, now=now)
