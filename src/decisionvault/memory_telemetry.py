from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from statistics import fmean
from typing import Any, Callable, Iterable, Mapping

from decisionvault.adaptive_memory import (
    GovernedAdaptiveMemoryResolver,
    GovernedMemory,
)
from decisionvault.agent.memory_governance import ConflictAwareMemoryResolver
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, Outcome, RecalledEpisode, Strategy


MEMORY_QUALITY_TELEMETRY_REVISION = "memory-quality-telemetry-v1"
MEMORY_QUALITY_CALIBRATION_REVISION = "telemetry-calibration-v1"


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
    observed = [
        row for row in rows if row.get("outcome") and _memory_exposed(row)
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
            if bool(shadow.get("same_strategy_as_champion")) and bool(
                shadow.get("executable")
            ):
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
            "eligible": False,
        }
        result["eligible"] = bool(
            len(observed) >= minimum_samples
            and counterfactual_unobserved == 0
            and retention >= minimum_success_retention
            and harmful_rate <= maximum_harmful_rate
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
    )
