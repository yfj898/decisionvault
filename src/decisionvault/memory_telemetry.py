from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from statistics import fmean
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from decisionvault.adaptive_memory import (
    GovernedAdaptiveMemoryResolver,
    GovernedMemory,
)
from decisionvault.agent.memory_governance import ConflictAwareMemoryResolver
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, Outcome, RecalledEpisode, Strategy


MEMORY_QUALITY_TELEMETRY_REVISION = "memory-quality-telemetry-v1"
MEMORY_QUALITY_CALIBRATION_REVISION = "telemetry-calibration-v3"
DEFAULT_CALIBRATION_LOOKBACK_DAYS = 90
DEFAULT_CALIBRATION_MINIMUM_SAMPLES = 30
DEFAULT_CALIBRATION_MINIMUM_SUCCESS_RETENTION = 0.95
DEFAULT_CALIBRATION_MAXIMUM_HARMFUL_RATE = 0.05
DEFAULT_CALIBRATION_INTERVAL_HOURS = 24
DEFAULT_CALIBRATION_MINIMUM_LABEL_COVERAGE = 0.80
DEFAULT_CALIBRATION_MAXIMUM_LABEL_DISTRIBUTION_TVD = 0.20
DEFAULT_CALIBRATION_MINIMUM_SCOPE_LEVELS = 2
DEFAULT_CALIBRATION_MAXIMUM_DOMINANT_SCOPE_SHARE = 0.80
DEFAULT_CALIBRATION_MINIMUM_STRATEGIES = 2
DEFAULT_CALIBRATION_MAXIMUM_DOMINANT_STRATEGY_SHARE = 0.80
DEFAULT_CALIBRATION_MINIMUM_STRATUM_SAMPLES = 5
DEFAULT_CALIBRATION_MINIMUM_EVIDENCE_SPAN_DAYS = 30.0
DEFAULT_CALIBRATION_MINIMUM_DRIFT_SEGMENT_SAMPLES = 5
DEFAULT_CALIBRATION_MAXIMUM_TEMPORAL_TVD = 0.35
DEFAULT_CALIBRATION_MINIMUM_MEMORY_AGE_BUCKETS = 2
DEFAULT_CALIBRATION_MINIMUM_AGED_MEMORY_SAMPLES = 5
DEFAULT_MEMORY_QUALITY_RAW_RETENTION_DAYS = 180
DEFAULT_MEMORY_QUALITY_CALIBRATION_RUN_RETENTION_DAYS = 730


@dataclass(frozen=True, slots=True)
class ShadowThresholdProfile:
    name: str
    episodic_minimum_similarity: float
    episodic_minimum_signal: float
    episodic_conflict_margin: float
    adaptive_minimum_similarity: float
    adaptive_minimum_effective_confidence: float
    adaptive_conflict_margin: float


def production_threshold_profile(policy: OutcomeAwarePolicy) -> ShadowThresholdProfile:
    return ShadowThresholdProfile(
        name="champion",
        episodic_minimum_similarity=policy.resolver.minimum_similarity,
        episodic_minimum_signal=policy.resolver.minimum_signal,
        episodic_conflict_margin=policy.resolver.conflict_margin,
        adaptive_minimum_similarity=policy.adaptive_resolver.minimum_similarity,
        adaptive_minimum_effective_confidence=(
            policy.adaptive_resolver.minimum_effective_confidence
        ),
        adaptive_conflict_margin=policy.adaptive_resolver.conflict_margin,
    )


def monotone_shadow_profiles(policy: OutcomeAwarePolicy) -> tuple[ShadowThresholdProfile, ...]:
    """Return only stricter/equal profiles that historical telemetry can evaluate.

    Production recall already censors evidence below the live similarity gate,
    so telemetry must never claim to evaluate a looser threshold. Each profile
    here is monotone stricter than the champion along exactly one dimension.
    """

    champion = production_threshold_profile(policy)
    candidates = (
        ("episodic_similarity_0_45", "episodic_minimum_similarity", 0.45),
        ("episodic_similarity_0_50", "episodic_minimum_similarity", 0.50),
        ("episodic_signal_0_16", "episodic_minimum_signal", 0.16),
        ("episodic_conflict_0_12", "episodic_conflict_margin", 0.12),
        ("adaptive_similarity_0_45", "adaptive_minimum_similarity", 0.45),
        ("adaptive_similarity_0_50", "adaptive_minimum_similarity", 0.50),
        (
            "adaptive_effective_confidence_0_35",
            "adaptive_minimum_effective_confidence",
            0.35,
        ),
        (
            "adaptive_effective_confidence_0_40",
            "adaptive_minimum_effective_confidence",
            0.40,
        ),
        ("adaptive_conflict_0_12", "adaptive_conflict_margin", 0.12),
    )
    profiles: list[ShadowThresholdProfile] = []
    base = asdict(champion)
    for name, field_name, value in candidates:
        if value <= float(base[field_name]):
            continue
        payload = dict(base)
        payload["name"] = name
        payload[field_name] = value
        profiles.append(ShadowThresholdProfile(**payload))
    return tuple(profiles)


def threshold_profile_catalog(
    policy: OutcomeAwarePolicy | None = None,
) -> dict[str, ShadowThresholdProfile]:
    resolved = policy or OutcomeAwarePolicy()
    profiles = (production_threshold_profile(resolved), *monotone_shadow_profiles(resolved))
    return {profile.name: profile for profile in profiles}


def _age_days(observed_at: datetime, *, now: datetime) -> float:
    return max(0.0, (now - observed_at).total_seconds() / 86400.0)


def _summary(values: Iterable[float]) -> dict[str, float] | None:
    items = [float(value) for value in values]
    if not items:
        return None
    return {
        "min": round(min(items), 6),
        "max": round(max(items), 6),
        "mean": round(fmean(items), 6),
    }


def _episodic_features(
    recalled: list[RecalledEpisode],
    *,
    selected_ids: set[str],
    now: datetime,
) -> dict[str, Any]:
    selected = [item for item in recalled if item.episode.episode_id in selected_ids]
    source = selected or recalled
    return {
        "candidate_count": len(recalled),
        "selected_count": len(selected),
        "selected": bool(selected),
        "similarity": _summary(item.similarity for item in source),
        "confidence": _summary(item.episode.confidence for item in source),
        "age_days": _summary(_age_days(item.episode.observed_at, now=now) for item in source),
    }


def _adaptive_features(
    memories: list[GovernedMemory],
    *,
    selected_ids: set[str],
    now: datetime,
) -> dict[str, Any]:
    selected = [item for item in memories if item.memory_id in selected_ids]
    source = selected or memories
    return {
        "candidate_count": len(memories),
        "selected_count": len(selected),
        "selected": bool(selected),
        "similarity": _summary(item.similarity for item in source),
        "base_confidence": _summary(item.confidence for item in source),
        "effective_confidence": _summary(
            item.effective_confidence(now=now) for item in source
        ),
        "age_days": _summary(_age_days(item.observed_to, now=now) for item in source),
        "memory_classes": sorted({item.memory_class.value for item in source}),
        "scope_levels": sorted({item.scope_level.value for item in source}),
    }


def _shadow_policy(
    champion: OutcomeAwarePolicy,
    profile: ShadowThresholdProfile,
) -> OutcomeAwarePolicy:
    resolver = champion.resolver
    episodic = ConflictAwareMemoryResolver(
        minimum_similarity=profile.episodic_minimum_similarity,
        max_age_days=resolver.max_age_days,
        minimum_signal=profile.episodic_minimum_signal,
        conflict_margin=profile.episodic_conflict_margin,
        producer_trust=resolver.producer_trust,
        unknown_producer_trust=resolver.unknown_producer_trust,
    )
    adaptive = GovernedAdaptiveMemoryResolver(
        minimum_similarity=profile.adaptive_minimum_similarity,
        minimum_effective_confidence=profile.adaptive_minimum_effective_confidence,
        conflict_margin=profile.adaptive_conflict_margin,
    )
    return OutcomeAwarePolicy(resolver=episodic, adaptive_resolver=adaptive)


def build_memory_quality_telemetry(
    *,
    decision: Decision,
    policy: OutcomeAwarePolicy,
    recalled: list[RecalledEpisode],
    adaptive_memories: list[GovernedMemory],
    context_tags: set[str] | frozenset[str],
    scope_level: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected_episode_ids = set(decision.recalled_episode_ids)
    selected_memory_ids = set(decision.recalled_memory_ids)
    shadows: list[dict[str, Any]] = []
    for profile in monotone_shadow_profiles(policy):
        shadow = _shadow_policy(policy, profile).decide(
            recalled=recalled,
            adaptive_memories=adaptive_memories,
            context_tags=context_tags,
        )
        shadows.append(
            {
                "profile": asdict(profile),
                "strategy": shadow.strategy.value if shadow.strategy is not None else None,
                "executable": shadow.executable,
                "memory_influenced": shadow.memory_influenced,
                "memory_resolution": shadow.memory_resolution,
                "memory_conflict": shadow.memory_conflict,
                "same_strategy_as_champion": shadow.strategy == decision.strategy,
            }
        )
    selected_layer = (
        "BOTH"
        if selected_episode_ids and selected_memory_ids
        else "L1"
        if selected_episode_ids
        else "L3"
        if selected_memory_ids
        else "NONE"
    )
    return {
        "telemetry_revision": MEMORY_QUALITY_TELEMETRY_REVISION,
        "scope_level": scope_level,
        "selected_layer": selected_layer,
        "champion": asdict(production_threshold_profile(policy)),
        "episodic": _episodic_features(
            recalled, selected_ids=selected_episode_ids, now=current
        ),
        "adaptive": _adaptive_features(
            adaptive_memories, selected_ids=selected_memory_ids, now=current
        ),
        "shadows": shadows,
    }


def insert_decision_quality_event(
    *,
    connection_factory: Callable[[], object],
    decision_snapshot_id: str,
    source: str,
    decision: Decision,
    scope_level: str,
    decided_at: datetime,
) -> None:
    payload = dict(decision.memory_quality_telemetry)
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decision_memory_quality_decisions (
                    decision_snapshot_id, source, decided_at, scope_level,
                    selected_strategy, executable, memory_influenced,
                    memory_resolution, memory_conflict, quality_features,
                    telemetry_revision
                ) VALUES (
                    %s::UUID, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s::JSONB,
                    %s
                )
                ON CONFLICT (decision_snapshot_id) DO NOTHING
                """,
                (
                    decision_snapshot_id,
                    source,
                    decided_at,
                    scope_level,
                    decision.strategy.value if decision.strategy is not None else None,
                    decision.executable,
                    decision.memory_influenced,
                    decision.memory_resolution,
                    decision.memory_conflict,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    MEMORY_QUALITY_TELEMETRY_REVISION,
                ),
            )
        conn.commit()
    except Exception:
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            rollback()
        raise
    finally:
        conn.close()


def insert_outcome_quality_event(
    *,
    connection_factory: Callable[[], object],
    decision_snapshot_id: str,
    execution_receipt_id: str,
    outcome: Outcome,
    effectiveness: float,
    confidence: float,
    observed_at: datetime,
    recorded_at: datetime,
) -> None:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decision_memory_quality_outcomes (
                    decision_snapshot_id, execution_receipt_id, outcome,
                    effectiveness, confidence, observed_at, recorded_at,
                    telemetry_revision
                ) VALUES (
                    %s::UUID, %s, %s,
                    %s, %s, %s, %s,
                    %s
                )
                ON CONFLICT (decision_snapshot_id) DO NOTHING
                """,
                (
                    decision_snapshot_id,
                    execution_receipt_id,
                    outcome.value,
                    float(effectiveness),
                    float(confidence),
                    observed_at,
                    recorded_at,
                    MEMORY_QUALITY_TELEMETRY_REVISION,
                ),
            )
        conn.commit()
    except Exception:
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            rollback()
        raise
    finally:
        conn.close()


@dataclass(frozen=True, slots=True)
class TelemetryCalibrationSummary:
    source: str
    observed_samples: int
    champion_successes: int
    champion_harmful: int
    recommendation: str
    recommended_profile: str | None
    challengers: tuple[Mapping[str, Any], ...]
    sampling_gate_pass: bool
    sampling_audit: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PersistedCalibrationRun:
    run_id: str
    source: str
    decision_rows: int
    labeled_outcomes: int
    summary: TelemetryCalibrationSummary
    generated_at: datetime


def _qualified_success(outcome: str, effectiveness: float) -> bool:
    return outcome == Outcome.SUCCESS.value and effectiveness >= 0.7


def _harmful(outcome: str, effectiveness: float) -> bool:
    return outcome == Outcome.FAILED.value and effectiveness <= 0.3


def _memory_exposed(row: Mapping[str, Any]) -> bool:
    features = row.get("quality_features", {}) or {}
    if not isinstance(features, Mapping):
        return False
    episodic = features.get("episodic", {}) or {}
    adaptive = features.get("adaptive", {}) or {}
    try:
        episodic_candidates = int(
            episodic.get("candidate_count", 0) if isinstance(episodic, Mapping) else 0
        )
        adaptive_candidates = int(
            adaptive.get("candidate_count", 0) if isinstance(adaptive, Mapping) else 0
        )
    except (TypeError, ValueError):
        return False
    return episodic_candidates > 0 or adaptive_candidates > 0


def _distribution(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        key = "NONE" if value is None else str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _dominant_share(counts: Mapping[str, int]) -> float:
    total = sum(int(value) for value in counts.values())
    if total <= 0:
        return 0.0
    return max(int(value) for value in counts.values()) / total


def _total_variation_distance(
    left: Mapping[str, int], right: Mapping[str, int]
) -> float:
    left_total = sum(int(value) for value in left.values())
    right_total = sum(int(value) for value in right.values())
    if left_total <= 0 or right_total <= 0:
        return 1.0
    keys = set(left) | set(right)
    return 0.5 * sum(
        abs(
            (int(left.get(key, 0)) / left_total)
            - (int(right.get(key, 0)) / right_total)
        )
        for key in keys
    )


def _row_decided_at(row: Mapping[str, Any]) -> datetime | None:
    value = row.get("decided_at")
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value:
        try:
            result = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _memory_age_days(row: Mapping[str, Any]) -> float | None:
    features = row.get("quality_features", {}) or {}
    if not isinstance(features, Mapping):
        return None
    values: list[float] = []
    for layer_name in ("episodic", "adaptive"):
        layer = features.get(layer_name, {}) or {}
        if not isinstance(layer, Mapping):
            continue
        age_summary = layer.get("age_days") or {}
        if not isinstance(age_summary, Mapping):
            continue
        value = age_summary.get("mean")
        if isinstance(value, (int, float)):
            values.append(max(0.0, float(value)))
    return max(values) if values else None


def _memory_age_bucket_name(row: Mapping[str, Any]) -> str:
    age_days = _memory_age_days(row)
    if age_days is None:
        return "UNKNOWN"
    if age_days <= 7:
        return "0_7d"
    if age_days <= 30:
        return "8_30d"
    if age_days <= 90:
        return "31_90d"
    if age_days <= 180:
        return "91_180d"
    return "181d_plus"


def audit_telemetry_sampling_bias(
    rows: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    minimum_label_coverage: float = DEFAULT_CALIBRATION_MINIMUM_LABEL_COVERAGE,
    maximum_label_distribution_tvd: float = DEFAULT_CALIBRATION_MAXIMUM_LABEL_DISTRIBUTION_TVD,
    minimum_scope_levels: int = DEFAULT_CALIBRATION_MINIMUM_SCOPE_LEVELS,
    maximum_dominant_scope_share: float = DEFAULT_CALIBRATION_MAXIMUM_DOMINANT_SCOPE_SHARE,
    minimum_strategies: int = DEFAULT_CALIBRATION_MINIMUM_STRATEGIES,
    maximum_dominant_strategy_share: float = DEFAULT_CALIBRATION_MAXIMUM_DOMINANT_STRATEGY_SHARE,
    minimum_stratum_samples: int = DEFAULT_CALIBRATION_MINIMUM_STRATUM_SAMPLES,
    minimum_evidence_span_days: float = DEFAULT_CALIBRATION_MINIMUM_EVIDENCE_SPAN_DAYS,
    minimum_drift_segment_samples: int = DEFAULT_CALIBRATION_MINIMUM_DRIFT_SEGMENT_SAMPLES,
    maximum_temporal_tvd: float = DEFAULT_CALIBRATION_MAXIMUM_TEMPORAL_TVD,
    minimum_memory_age_buckets: int = DEFAULT_CALIBRATION_MINIMUM_MEMORY_AGE_BUCKETS,
    minimum_aged_memory_samples: int = DEFAULT_CALIBRATION_MINIMUM_AGED_MEMORY_SAMPLES,
) -> dict[str, Any]:
    """Audit whether labeled threshold evidence is representative enough.

    The audit deliberately works only with low-cardinality categorical fields
    already present in telemetry. It never groups by raw scope IDs, agents,
    situations, episodes, memories, snapshots, or receipts.
    """

    items = list(rows)
    exposed = [row for row in items if _memory_exposed(row)]
    observed = [row for row in exposed if row.get("outcome")]
    label_coverage = len(observed) / len(exposed) if exposed else 0.0

    exposed_scope = _distribution(exposed, "scope_level")
    observed_scope = _distribution(observed, "scope_level")
    exposed_strategy = _distribution(exposed, "selected_strategy")
    observed_strategy = _distribution(observed, "selected_strategy")
    scope_label_tvd = _total_variation_distance(exposed_scope, observed_scope)
    strategy_label_tvd = _total_variation_distance(exposed_strategy, observed_strategy)

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamps = [value for row in observed if (value := _row_decided_at(row))]
    evidence_span_days = (
        max(0.0, (max(timestamps) - min(timestamps)).total_seconds() / 86400.0)
        if timestamps
        else 0.0
    )
    age_buckets = {"0_7d": 0, "8_30d": 0, "31_60d": 0, "61_90d": 0}
    recent: list[Mapping[str, Any]] = []
    older: list[Mapping[str, Any]] = []
    for row in observed:
        decided_at = _row_decided_at(row)
        if decided_at is None:
            continue
        age_days = max(0.0, (current - decided_at).total_seconds() / 86400.0)
        if age_days <= 7:
            age_buckets["0_7d"] += 1
        elif age_days <= 30:
            age_buckets["8_30d"] += 1
        elif age_days <= 60:
            age_buckets["31_60d"] += 1
        else:
            age_buckets["61_90d"] += 1
        (recent if age_days <= 30 else older).append(row)

    drift_evaluable = (
        len(recent) >= minimum_drift_segment_samples
        and len(older) >= minimum_drift_segment_samples
    )
    recent_scope = _distribution(recent, "scope_level")
    older_scope = _distribution(older, "scope_level")
    recent_strategy = _distribution(recent, "selected_strategy")
    older_strategy = _distribution(older, "selected_strategy")
    scope_temporal_tvd = (
        _total_variation_distance(recent_scope, older_scope)
        if drift_evaluable
        else None
    )
    strategy_temporal_tvd = (
        _total_variation_distance(recent_strategy, older_strategy)
        if drift_evaluable
        else None
    )

    memory_age_buckets = {
        "0_7d": 0,
        "8_30d": 0,
        "31_90d": 0,
        "91_180d": 0,
        "181d_plus": 0,
    }
    memory_age_samples = 0
    aged_memory_samples = 0
    for row in observed:
        memory_age = _memory_age_days(row)
        if memory_age is None:
            continue
        memory_age_samples += 1
        if memory_age > 30:
            aged_memory_samples += 1
        if memory_age <= 7:
            memory_age_buckets["0_7d"] += 1
        elif memory_age <= 30:
            memory_age_buckets["8_30d"] += 1
        elif memory_age <= 90:
            memory_age_buckets["31_90d"] += 1
        elif memory_age <= 180:
            memory_age_buckets["91_180d"] += 1
        else:
            memory_age_buckets["181d_plus"] += 1
    occupied_memory_age_buckets = sum(
        1 for value in memory_age_buckets.values() if value > 0
    )
    scope_minimum_stratum_samples = bool(observed_scope) and min(
        observed_scope.values()
    ) >= minimum_stratum_samples
    strategy_minimum_stratum_samples = bool(observed_strategy) and min(
        observed_strategy.values()
    ) >= minimum_stratum_samples

    gates = {
        "label_coverage": label_coverage >= minimum_label_coverage,
        "label_distribution": (
            scope_label_tvd <= maximum_label_distribution_tvd
            and strategy_label_tvd <= maximum_label_distribution_tvd
        ),
        "scope_coverage": (
            len(observed_scope) >= minimum_scope_levels
            and _dominant_share(observed_scope) <= maximum_dominant_scope_share
            and scope_minimum_stratum_samples
        ),
        "strategy_coverage": (
            len(observed_strategy) >= minimum_strategies
            and _dominant_share(observed_strategy) <= maximum_dominant_strategy_share
            and strategy_minimum_stratum_samples
        ),
        "evidence_span": evidence_span_days >= minimum_evidence_span_days,
        "memory_age_coverage": (
            memory_age_samples == len(observed)
            and occupied_memory_age_buckets >= minimum_memory_age_buckets
            and aged_memory_samples >= minimum_aged_memory_samples
        ),
        "temporal_drift_evaluable": drift_evaluable,
        "temporal_drift": bool(
            drift_evaluable
            and scope_temporal_tvd is not None
            and strategy_temporal_tvd is not None
            and scope_temporal_tvd <= maximum_temporal_tvd
            and strategy_temporal_tvd <= maximum_temporal_tvd
        ),
    }
    blockers = tuple(name for name, passed in gates.items() if not passed)
    return {
        "policy": {
            "minimum_label_coverage": minimum_label_coverage,
            "maximum_label_distribution_tvd": maximum_label_distribution_tvd,
            "minimum_scope_levels": minimum_scope_levels,
            "maximum_dominant_scope_share": maximum_dominant_scope_share,
            "minimum_strategies": minimum_strategies,
            "maximum_dominant_strategy_share": maximum_dominant_strategy_share,
            "minimum_stratum_samples": minimum_stratum_samples,
            "minimum_evidence_span_days": minimum_evidence_span_days,
            "minimum_drift_segment_samples": minimum_drift_segment_samples,
            "maximum_temporal_tvd": maximum_temporal_tvd,
            "minimum_memory_age_buckets": minimum_memory_age_buckets,
            "minimum_aged_memory_samples": minimum_aged_memory_samples,
        },
        "memory_exposed_decisions": len(exposed),
        "labeled_memory_exposed": len(observed),
        "label_coverage": round(label_coverage, 6),
        "scope_counts": observed_scope,
        "strategy_counts": observed_strategy,
        "dominant_scope_share": round(_dominant_share(observed_scope), 6),
        "dominant_strategy_share": round(_dominant_share(observed_strategy), 6),
        "scope_label_tvd": round(scope_label_tvd, 6),
        "strategy_label_tvd": round(strategy_label_tvd, 6),
        "evidence_span_days": round(evidence_span_days, 6),
        "age_buckets": age_buckets,
        "memory_age_samples": memory_age_samples,
        "memory_age_buckets": memory_age_buckets,
        "aged_memory_samples": aged_memory_samples,
        "recent_samples": len(recent),
        "older_samples": len(older),
        "scope_temporal_tvd": (
            round(scope_temporal_tvd, 6) if scope_temporal_tvd is not None else None
        ),
        "strategy_temporal_tvd": (
            round(strategy_temporal_tvd, 6)
            if strategy_temporal_tvd is not None
            else None
        ),
        "gates": gates,
        "blockers": blockers,
        "passed": not blockers,
    }


def calibrate_from_telemetry_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    source: str = "AGENT_API",
    minimum_samples: int = 30,
    minimum_success_retention: float = 0.95,
    maximum_harmful_rate: float = 0.05,
) -> TelemetryCalibrationSummary:
    # Pure default-policy requests with no recalled L1/L3 candidates say
    # nothing about memory thresholds and would otherwise dilute harmful rates
    # and inflate challenger success retention. Keep only verified outcomes
    # where the live decision was actually exposed to governed memory evidence.
    items = list(rows)
    sampling_audit = audit_telemetry_sampling_bias(items)
    sampling_gate_pass = bool(sampling_audit["passed"])
    observed = [
        row for row in items if row.get("outcome") and _memory_exposed(row)
    ]
    champion_successes = sum(
        _qualified_success(str(row["outcome"]), float(row["effectiveness"]))
        for row in observed
    )
    champion_harmful = sum(
        _harmful(str(row["outcome"]), float(row["effectiveness"]))
        for row in observed
    )
    profile_names = sorted(
        {
            str(shadow.get("profile", {}).get("name", ""))
            for row in observed
            for shadow in (row.get("quality_features", {}).get("shadows", []) or [])
            if str(shadow.get("profile", {}).get("name", ""))
        }
    )
    challenger_results: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for name in profile_names:
        retained = 0
        retained_successes = 0
        retained_harmful = 0
        suppressed_successes = 0
        suppressed_harmful = 0
        counterfactual_unobserved = 0
        stratum_state: dict[str, dict[str, dict[str, int]]] = {
            "scope_level": {},
            "selected_strategy": {},
            "memory_age_bucket": {},
        }
        for row in observed:
            shadows = row.get("quality_features", {}).get("shadows", []) or []
            shadow = next(
                (
                    item
                    for item in shadows
                    if str(item.get("profile", {}).get("name", "")) == name
                ),
                None,
            )
            if shadow is None:
                continue
            success = _qualified_success(
                str(row["outcome"]), float(row["effectiveness"])
            )
            harmful = _harmful(str(row["outcome"]), float(row["effectiveness"]))
            retained_by_shadow = bool(shadow.get("same_strategy_as_champion")) and bool(
                shadow.get("executable")
            )
            stratum_keys = {
                "scope_level": str(row.get("scope_level") or "UNKNOWN"),
                "selected_strategy": str(row.get("selected_strategy") or "NONE"),
                "memory_age_bucket": _memory_age_bucket_name(row),
            }
            for dimension, key in stratum_keys.items():
                metrics = stratum_state[dimension].setdefault(
                    key,
                    {
                        "samples": 0,
                        "champion_successes": 0,
                        "retained_samples": 0,
                        "retained_successes": 0,
                        "retained_harmful": 0,
                    },
                )
                metrics["samples"] += 1
                metrics["champion_successes"] += int(success)
                if retained_by_shadow:
                    metrics["retained_samples"] += 1
                    metrics["retained_successes"] += int(success)
                    metrics["retained_harmful"] += int(harmful)
            if retained_by_shadow:
                retained += 1
                retained_successes += int(success)
                retained_harmful += int(harmful)
            else:
                suppressed_successes += int(success)
                suppressed_harmful += int(harmful)
                if bool(shadow.get("executable")):
                    counterfactual_unobserved += 1
        retention = (
            retained_successes / champion_successes if champion_successes else 1.0
        )
        harmful_rate = retained_harmful / retained if retained else 0.0
        stratum_results: dict[str, dict[str, dict[str, Any]]] = {}
        stratum_safe = True
        for dimension, groups in stratum_state.items():
            stratum_results[dimension] = {}
            for key, metrics in sorted(groups.items()):
                champion_stratum_successes = metrics["champion_successes"]
                retained_stratum_successes = metrics["retained_successes"]
                retained_stratum_samples = metrics["retained_samples"]
                retained_stratum_harmful = metrics["retained_harmful"]
                stratum_retention = (
                    retained_stratum_successes / champion_stratum_successes
                    if champion_stratum_successes
                    else 1.0
                )
                stratum_harmful_rate = (
                    retained_stratum_harmful / retained_stratum_samples
                    if retained_stratum_samples
                    else 0.0
                )
                safe = bool(
                    stratum_retention >= minimum_success_retention
                    and stratum_harmful_rate <= maximum_harmful_rate
                )
                stratum_safe = stratum_safe and safe
                stratum_results[dimension][key] = {
                    **metrics,
                    "success_retention": round(stratum_retention, 6),
                    "harmful_rate": round(stratum_harmful_rate, 6),
                    "safe": safe,
                }
        result = {
            "profile": name,
            "retained_samples": retained,
            "retained_successes": retained_successes,
            "retained_harmful": retained_harmful,
            "suppressed_successes": suppressed_successes,
            "suppressed_harmful": suppressed_harmful,
            "counterfactual_unobserved": counterfactual_unobserved,
            "success_retention": round(retention, 6),
            "harmful_rate": round(harmful_rate, 6),
            "stratum_safe": stratum_safe,
            "strata": stratum_results,
            "eligible": False,
        }
        result["eligible"] = bool(
            len(observed) >= minimum_samples
            and sampling_gate_pass
            and counterfactual_unobserved == 0
            and retention >= minimum_success_retention
            and harmful_rate <= maximum_harmful_rate
            and stratum_safe
            and retained_harmful <= champion_harmful
            and suppressed_harmful > 0
        )
        if result["eligible"]:
            eligible.append(result)
        challenger_results.append(result)
    recommended = None
    if eligible:
        recommended = max(
            eligible,
            key=lambda item: (
                item["suppressed_harmful"],
                item["success_retention"],
                -item["suppressed_successes"],
            ),
        )["profile"]
    recommendation = (
        "INSUFFICIENT_REAL_TELEMETRY"
        if len(observed) < minimum_samples
        else "INSUFFICIENT_DISTRIBUTION_COVERAGE"
        if not sampling_gate_pass
        else "KEEP_CHAMPION"
        if recommended is None
        else "RECOMMEND_CHALLENGER_SHADOW_ONLY"
    )
    return TelemetryCalibrationSummary(
        source=source,
        observed_samples=len(observed),
        champion_successes=champion_successes,
        champion_harmful=champion_harmful,
        recommendation=recommendation,
        recommended_profile=recommended,
        challengers=tuple(challenger_results),
        sampling_gate_pass=sampling_gate_pass,
        sampling_audit=sampling_audit,
    )


def load_calibration_rows(
    *,
    connection_factory: Callable[[], object],
    source: str = "AGENT_API",
    lookback_days: int = DEFAULT_CALIBRATION_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """Read de-identified decision/outcome telemetry for offline calibration.

    The result deliberately excludes decision snapshot IDs and execution receipt
    IDs because neither is needed by the threshold evaluator. This keeps the
    calibration boundary aggregate/feature-only even though those identifiers
    exist as internal database join keys.
    """

    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.source, d.decided_at, d.scope_level, d.selected_strategy,
                       d.executable, d.memory_influenced, d.memory_resolution,
                       d.memory_conflict, d.quality_features,
                       o.outcome, o.effectiveness, o.confidence,
                       o.observed_at, o.recorded_at
                FROM decision_memory_quality_decisions d
                LEFT JOIN decision_memory_quality_outcomes o
                  ON o.decision_snapshot_id = d.decision_snapshot_id
                WHERE d.source = %s
                  AND d.decided_at >= now() - (%s * INTERVAL '1 day')
                ORDER BY d.decided_at
                """,
                (source, int(lookback_days)),
            )
            result: list[dict[str, Any]] = []
            for row in cur.fetchall():
                quality_features = row[8] or {}
                if isinstance(quality_features, str):
                    try:
                        quality_features = json.loads(quality_features)
                    except json.JSONDecodeError:
                        quality_features = {}
                result.append(
                    {
                        "source": str(row[0]),
                        "decided_at": row[1].isoformat(),
                        "scope_level": str(row[2]),
                        "selected_strategy": str(row[3]) if row[3] is not None else None,
                        "executable": bool(row[4]),
                        "memory_influenced": bool(row[5]),
                        "memory_resolution": str(row[6]),
                        "memory_conflict": bool(row[7]),
                        "quality_features": quality_features,
                        "outcome": str(row[9]) if row[9] is not None else None,
                        "effectiveness": float(row[10]) if row[10] is not None else None,
                        "confidence": float(row[11]) if row[11] is not None else None,
                        "observed_at": row[12].isoformat() if row[12] is not None else None,
                        "recorded_at": row[13].isoformat() if row[13] is not None else None,
                    }
                )
            return result
    finally:
        conn.close()


def insert_calibration_run(
    *,
    connection_factory: Callable[[], object],
    summary: TelemetryCalibrationSummary,
    decision_rows: int,
    labeled_outcomes: int,
    lookback_days: int,
    minimum_samples: int,
    minimum_success_retention: float,
    maximum_harmful_rate: float,
    generated_at: datetime | None = None,
) -> PersistedCalibrationRun:
    """Append one aggregate champion/challenger evaluation artifact.

    Calibration runs are intentionally immutable. They carry only aggregate
    counts and challenger summaries; no scope, agent, situation, episode,
    memory, snapshot, or receipt identifier is persisted in this table.
    """

    at = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    run_id = str(uuid4())
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decision_memory_quality_calibration_runs (
                    run_id, source, calibration_revision, lookback_days,
                    minimum_samples, minimum_success_retention,
                    maximum_harmful_rate, decision_rows, labeled_outcomes,
                    observed_samples, champion_successes, champion_harmful,
                    recommendation, recommended_profile, challengers,
                    sampling_gate_pass, sampling_audit, generated_at
                ) VALUES (
                    %s::UUID, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s::JSONB,
                    %s, %s::JSONB, %s
                )
                """,
                (
                    run_id,
                    summary.source,
                    MEMORY_QUALITY_CALIBRATION_REVISION,
                    int(lookback_days),
                    int(minimum_samples),
                    float(minimum_success_retention),
                    float(maximum_harmful_rate),
                    int(decision_rows),
                    int(labeled_outcomes),
                    int(summary.observed_samples),
                    int(summary.champion_successes),
                    int(summary.champion_harmful),
                    summary.recommendation,
                    summary.recommended_profile,
                    json.dumps(
                        list(summary.challengers),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    bool(summary.sampling_gate_pass),
                    json.dumps(
                        dict(summary.sampling_audit),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    at,
                ),
            )
        conn.commit()
    except Exception:
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            rollback()
        raise
    finally:
        conn.close()
    return PersistedCalibrationRun(
        run_id=run_id,
        source=summary.source,
        decision_rows=int(decision_rows),
        labeled_outcomes=int(labeled_outcomes),
        summary=summary,
        generated_at=at,
    )


def run_persisted_calibration(
    *,
    connection_factory: Callable[[], object],
    source: str = "AGENT_API",
    lookback_days: int = DEFAULT_CALIBRATION_LOOKBACK_DAYS,
    minimum_samples: int = DEFAULT_CALIBRATION_MINIMUM_SAMPLES,
    minimum_success_retention: float = DEFAULT_CALIBRATION_MINIMUM_SUCCESS_RETENTION,
    maximum_harmful_rate: float = DEFAULT_CALIBRATION_MAXIMUM_HARMFUL_RATE,
) -> PersistedCalibrationRun:
    rows = load_calibration_rows(
        connection_factory=connection_factory,
        source=source,
        lookback_days=lookback_days,
    )
    summary = calibrate_from_telemetry_rows(
        rows,
        source=source,
        minimum_samples=minimum_samples,
        minimum_success_retention=minimum_success_retention,
        maximum_harmful_rate=maximum_harmful_rate,
    )
    return insert_calibration_run(
        connection_factory=connection_factory,
        summary=summary,
        decision_rows=len(rows),
        labeled_outcomes=sum(row.get("outcome") is not None for row in rows),
        lookback_days=lookback_days,
        minimum_samples=minimum_samples,
        minimum_success_retention=minimum_success_retention,
        maximum_harmful_rate=maximum_harmful_rate,
    )


def calibration_is_due(
    *,
    connection_factory: Callable[[], object],
    source: str = "AGENT_API",
    interval_hours: int = DEFAULT_CALIBRATION_INTERVAL_HOURS,
    now: datetime | None = None,
) -> bool:
    """Return whether the append-only evaluator should create another run."""

    if interval_hours <= 0:
        raise ValueError("interval_hours must be positive")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT generated_at
                FROM decision_memory_quality_calibration_runs
                WHERE source = %s
                ORDER BY generated_at DESC, run_id DESC
                LIMIT 1
                """,
                (source,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        return True
    last = row[0]
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return current - last.astimezone(timezone.utc) >= timedelta(hours=interval_hours)


def purge_memory_quality_retention(
    *,
    connection_factory: Callable[[], object],
    raw_retention_days: int = DEFAULT_MEMORY_QUALITY_RAW_RETENTION_DAYS,
    calibration_run_retention_days: int = DEFAULT_MEMORY_QUALITY_CALIBRATION_RUN_RETENTION_DAYS,
    now: datetime | None = None,
) -> dict[str, int]:
    """Bound raw telemetry retention while preserving long-lived aggregates.

    Request runtime never receives DELETE. This function is intended for the
    separately authenticated consolidation/maintenance identity. Raw decision
    and outcome telemetry is kept for two 90-day calibration windows; aggregate
    calibration runs are retained longer because they contain no join IDs or
    user context.
    """

    if raw_retention_days <= DEFAULT_CALIBRATION_LOOKBACK_DAYS:
        raise ValueError("raw telemetry retention must exceed calibration lookback")
    if calibration_run_retention_days <= raw_retention_days:
        raise ValueError("aggregate calibration retention must exceed raw retention")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    raw_cutoff = current - timedelta(days=raw_retention_days)
    aggregate_cutoff = current - timedelta(days=calibration_run_retention_days)
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM decision_memory_quality_outcomes
                WHERE decision_snapshot_id IN (
                    SELECT decision_snapshot_id
                    FROM decision_memory_quality_decisions
                    WHERE decided_at < %s
                )
                """,
                (raw_cutoff,),
            )
            outcomes = max(0, int(getattr(cur, "rowcount", 0) or 0))
            cur.execute(
                "DELETE FROM decision_memory_quality_decisions WHERE decided_at < %s",
                (raw_cutoff,),
            )
            decisions = max(0, int(getattr(cur, "rowcount", 0) or 0))
            cur.execute(
                "DELETE FROM decision_memory_quality_calibration_runs WHERE generated_at < %s",
                (aggregate_cutoff,),
            )
            calibration_runs = max(0, int(getattr(cur, "rowcount", 0) or 0))
        conn.commit()
    except Exception:
        rollback = getattr(conn, "rollback", None)
        if callable(rollback):
            rollback()
        raise
    finally:
        conn.close()
    return {
        "outcomes": outcomes,
        "decisions": decisions,
        "calibration_runs": calibration_runs,
    }
