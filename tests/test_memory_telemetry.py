from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, Outcome, Strategy
from decisionvault.memory_telemetry import (
    audit_telemetry_sampling_bias,
    build_memory_quality_telemetry,
    calibration_is_due,
    calibrate_from_telemetry_rows,
    monotone_shadow_profiles,
    production_threshold_profile,
    purge_memory_quality_retention,
    run_persisted_calibration,
    threshold_profile_catalog,
)


def _row(
    *,
    outcome: str | None,
    effectiveness: float,
    shadow: dict,
    scope_level: str = "TEAM",
    selected_strategy: str = "REFRESH_PAYMENT_TOKEN",
    decided_at: datetime | None = None,
    memory_age_days: float = 0.0,
) -> dict:
    return {
        "outcome": outcome,
        "effectiveness": effectiveness,
        "scope_level": scope_level,
        "selected_strategy": selected_strategy,
        "decided_at": (decided_at or datetime.now(timezone.utc)).isoformat(),
        "quality_features": {
            "episodic": {
                "candidate_count": 1,
                "age_days": {"min": memory_age_days, "max": memory_age_days, "mean": memory_age_days},
            },
            "adaptive": {"candidate_count": 0},
            "shadows": [shadow],
        },
    }


def _balanced_row(
    index: int,
    *,
    outcome: str,
    effectiveness: float,
    shadow: dict,
    now: datetime,
) -> dict:
    return _row(
        outcome=outcome,
        effectiveness=effectiveness,
        shadow=shadow,
        scope_level="TEAM" if index % 2 == 0 else "PRIVATE",
        selected_strategy=(
            "REFRESH_PAYMENT_TOKEN" if index % 2 == 0 else "VERIFY_BILLING_PROFILE"
        ),
        decided_at=now - timedelta(days=index * 2),
        memory_age_days=60.0 if index % 3 == 0 else 5.0,
    )


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
    now = datetime.now(timezone.utc)
    for index in range(30):
        rows.append(
            _balanced_row(
                index,
                outcome="FAILED",
                effectiveness=0.1,
                shadow={
                    "profile": {"name": "adaptive_effective_confidence_0_35"},
                    "same_strategy_as_champion": False,
                    "executable": True,
                },
                now=now,
            )
        )
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    challenger = result.challengers[0]
    assert challenger["counterfactual_unobserved"] == 30
    assert challenger["eligible"] is False
    assert result.recommendation == "KEEP_CHAMPION"


def test_challenger_harmful_rate_above_five_percent_is_not_eligible():
    rows = []
    now = datetime.now(timezone.utc)
    shadow = {
        "profile": {"name": "adaptive_effective_confidence_0_35"},
        "same_strategy_as_champion": True,
        "executable": True,
    }
    for index in range(28):
        rows.append(
            _balanced_row(
                index,
                outcome="SUCCESS",
                effectiveness=0.95,
                shadow=shadow,
                now=now,
            )
        )
    for index in range(28, 30):
        rows.append(
            _balanced_row(
                index,
                outcome="FAILED",
                effectiveness=0.1,
                shadow=shadow,
                now=now,
            )
        )
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    challenger = result.challengers[0]
    assert challenger["harmful_rate"] > 0.05
    assert challenger["eligible"] is False


def test_stricter_shadow_can_be_recommended_only_after_real_labeled_evidence():
    rows = []
    now = datetime.now(timezone.utc)
    for index in range(27):
        rows.append(
            _balanced_row(
                index,
                outcome="SUCCESS",
                effectiveness=0.95,
                shadow={
                    "profile": {"name": "adaptive_effective_confidence_0_35"},
                    "same_strategy_as_champion": True,
                    "executable": True,
                },
                now=now,
            )
        )
    for index in range(27, 30):
        rows.append(
            _balanced_row(
                index,
                outcome="FAILED",
                effectiveness=0.1,
                shadow={
                    "profile": {"name": "adaptive_effective_confidence_0_35"},
                    "same_strategy_as_champion": False,
                    "executable": False,
                },
                now=now,
            )
        )
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    assert result.recommendation == "RECOMMEND_CHALLENGER_SHADOW_ONLY"
    assert result.recommended_profile == "adaptive_effective_confidence_0_35"
    assert result.sampling_gate_pass is True


def test_thirty_samples_from_one_scope_and_strategy_cannot_promote_global_thresholds():
    now = datetime.now(timezone.utc)
    shadow = {
        "profile": {"name": "adaptive_effective_confidence_0_35"},
        "same_strategy_as_champion": True,
        "executable": True,
    }
    rows = [
        _row(
            outcome="SUCCESS",
            effectiveness=0.95,
            shadow=shadow,
            scope_level="TEAM",
            selected_strategy="REFRESH_PAYMENT_TOKEN",
            decided_at=now - timedelta(days=index * 2),
        )
        for index in range(30)
    ]
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    assert result.observed_samples == 30
    assert result.sampling_gate_pass is False
    assert result.recommendation == "INSUFFICIENT_DISTRIBUTION_COVERAGE"
    assert "scope_coverage" in result.sampling_audit["blockers"]
    assert "strategy_coverage" in result.sampling_audit["blockers"]


def test_memory_exposed_label_selection_bias_blocks_promotion():
    now = datetime.now(timezone.utc)
    shadow = {
        "profile": {"name": "adaptive_effective_confidence_0_35"},
        "same_strategy_as_champion": True,
        "executable": True,
    }
    rows = []
    for index in range(30):
        row = _balanced_row(
            index,
            outcome="SUCCESS",
            effectiveness=0.95,
            shadow=shadow,
            now=now,
        )
        if index >= 15:
            row["outcome"] = None
        rows.append(row)
    audit = audit_telemetry_sampling_bias(rows, now=now)
    assert audit["memory_exposed_decisions"] == 30
    assert audit["labeled_memory_exposed"] == 15
    assert audit["label_coverage"] == 0.5
    assert audit["passed"] is False
    assert "label_coverage" in audit["blockers"]


def test_short_burst_of_diverse_samples_is_not_long_term_evidence():
    now = datetime.now(timezone.utc)
    shadow = {
        "profile": {"name": "adaptive_effective_confidence_0_35"},
        "same_strategy_as_champion": True,
        "executable": True,
    }
    rows = [
        _row(
            outcome="SUCCESS",
            effectiveness=0.95,
            shadow=shadow,
            scope_level="TEAM" if index % 2 == 0 else "PRIVATE",
            selected_strategy=(
                "REFRESH_PAYMENT_TOKEN"
                if index % 2 == 0
                else "VERIFY_BILLING_PROFILE"
            ),
            decided_at=now - timedelta(hours=index * 4),
        )
        for index in range(30)
    ]
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    assert result.recommendation == "INSUFFICIENT_DISTRIBUTION_COVERAGE"
    assert "evidence_span" in result.sampling_audit["blockers"]
    assert "temporal_drift_evaluable" in result.sampling_audit["blockers"]


def test_challenger_cannot_hide_harm_inside_one_scope_stratum():
    now = datetime.now(timezone.utc)
    rows = []
    for index in range(30):
        harmful = index in {1, 2}
        retained = index != 2
        rows.append(
            _balanced_row(
                index,
                outcome="FAILED" if harmful else "SUCCESS",
                effectiveness=0.1 if harmful else 0.95,
                shadow={
                    "profile": {"name": "adaptive_effective_confidence_0_35"},
                    "same_strategy_as_champion": retained,
                    "executable": retained,
                },
                now=now,
            )
        )
    result = calibrate_from_telemetry_rows(rows, minimum_samples=30)
    challenger = result.challengers[0]
    assert result.sampling_gate_pass is True
    assert challenger["harmful_rate"] <= 0.05
    assert challenger["stratum_safe"] is False
    assert challenger["strata"]["scope_level"]["PRIVATE"]["harmful_rate"] > 0.05
    assert challenger["eligible"] is False
    assert result.recommendation == "KEEP_CHAMPION"


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


class _RetentionCursor(_TelemetryCursor):
    def __init__(self, rowcounts):
        super().__init__()
        self._rowcounts = list(rowcounts)
        self.rowcount = 0

    def execute(self, sql, params=None):
        super().execute(sql, params)
        self.rowcount = self._rowcounts.pop(0)


class _RetentionConnection(_TelemetryConnection):
    def __init__(self, rowcounts):
        self.cursor_value = _RetentionCursor(rowcounts)
        self.committed = False
        self.closed = False


def test_retention_keeps_two_calibration_windows_and_long_lived_aggregates():
    conn = _RetentionConnection([3, 4, 2])
    result = purge_memory_quality_retention(
        connection_factory=lambda: conn,
        raw_retention_days=180,
        calibration_run_retention_days=730,
        now=datetime(2026, 8, 15, tzinfo=timezone.utc),
    )
    assert result == {"outcomes": 3, "decisions": 4, "calibration_runs": 2}
    assert conn.committed is True
    statements = [sql for sql, _ in conn.cursor_value.executions]
    assert "decision_memory_quality_outcomes" in statements[0]
    assert "decision_memory_quality_decisions" in statements[1]
    assert "decision_memory_quality_calibration_runs" in statements[2]


def test_retention_rejects_raw_window_that_cannot_cover_the_90_day_calibration_window():
    try:
        purge_memory_quality_retention(
            connection_factory=lambda: _RetentionConnection([]),
            raw_retention_days=90,
            calibration_run_retention_days=730,
        )
    except ValueError as exc:
        assert "must exceed calibration lookback" in str(exc)
    else:
        raise AssertionError("expected invalid retention policy to fail")
