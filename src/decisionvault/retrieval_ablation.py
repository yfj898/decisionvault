from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from decisionvault.agent.memory_governance import (
    PRODUCTION_SEMANTIC_MIN_SIMILARITY,
    ConflictAwareMemoryResolver,
    MemoryGovernanceResult,
)
from decisionvault.domain import DecisionAction, DecisionEpisode, Outcome, RecalledEpisode, Strategy


MODES = ("raw_top_k", "current_head_top_k", "dual_stage")
DEFAULT_K_VALUES = (5, 10, 32)
DEFAULT_PRESSURES = (0, 4, 12, 40)
FIXED_NOW = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class RetrievalScenario:
    scenario_id: str
    family: str
    pressure: int
    candidates: tuple[RecalledEpisode, ...]
    scope_id: str = "scope-main"


def _candidate(
    identifier: str,
    *,
    producer: str,
    strategy: Strategy,
    outcome: Outcome,
    similarity: float,
    effectiveness: float = 0.0,
    confidence: float = 1.0,
    age_days: float = 0.0,
    memory_status: str = "ACTIVE",
    scope_id: str = "scope-main",
    supersedes: str | None = None,
    observed_offset_seconds: int = 0,
) -> RecalledEpisode:
    evidence = {
        "producer_agent_id": producer,
        "memory_status": memory_status,
    }
    if supersedes:
        evidence["supersedes_episode_id"] = supersedes
    observed_at = FIXED_NOW - timedelta(days=age_days, seconds=observed_offset_seconds)
    return RecalledEpisode(
        episode=DecisionEpisode(
            episode_id=identifier,
            scope_id=scope_id,
            situation=f"synthetic retrieval ablation evidence {identifier}",
            strategy=strategy,
            outcome=outcome,
            effectiveness=effectiveness,
            confidence=confidence,
            evidence=evidence,
            observed_at=observed_at,
            recorded_at=observed_at,
        ),
        similarity=similarity,
    )


def _duplicate_crowding(pressure: int) -> RetrievalScenario:
    duplicates = [
        _candidate(
            f"dup-failed-{index}",
            producer="duplicate-observer",
            strategy=Strategy.GENERIC_RETRY,
            outcome=Outcome.FAILED,
            effectiveness=0.1,
            similarity=max(0.82, 0.99 - (index * 0.001)),
            observed_offset_seconds=index,
        )
        for index in range(pressure + 1)
    ]
    contradiction = _candidate(
        "dup-independent-success",
        producer="independent-observer",
        strategy=Strategy.GENERIC_RETRY,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
        similarity=0.72,
    )
    return RetrievalScenario(
        scenario_id=f"duplicate-crowding-p{pressure}",
        family="duplicate_crowding",
        pressure=pressure,
        candidates=tuple([*duplicates, contradiction]),
    )


def _stale_revoked_crowding(pressure: int) -> RetrievalScenario:
    blockers: list[RecalledEpisode] = []
    for index in range(pressure):
        blockers.append(
            _candidate(
                f"stale-{index}",
                producer=f"stale-observer-{index}",
                strategy=Strategy.VERIFY_BILLING_PROFILE,
                outcome=Outcome.SUCCESS,
                effectiveness=0.95,
                similarity=max(0.80, 0.99 - (index * 0.001)),
                age_days=120,
            )
        )
        blockers.append(
            _candidate(
                f"revoked-{index}",
                producer=f"revoked-observer-{index}",
                strategy=Strategy.VERIFY_BILLING_PROFILE,
                outcome=Outcome.SUCCESS,
                effectiveness=0.95,
                similarity=max(0.79, 0.985 - (index * 0.001)),
                memory_status="REVOKED",
            )
        )
    valid = _candidate(
        "fresh-generic-failure",
        producer="fresh-failure-observer",
        strategy=Strategy.GENERIC_RETRY,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
        similarity=0.70,
    )
    return RetrievalScenario(
        scenario_id=f"stale-revoked-crowding-p{pressure}",
        family="stale_revoked_crowding",
        pressure=pressure,
        candidates=tuple([*blockers, valid]),
    )


def _distinct_head_conflict_crowding(pressure: int) -> RetrievalScenario:
    noise = [
        _candidate(
            f"unknown-head-{index}",
            producer=f"unknown-observer-{index}",
            strategy=Strategy.VERIFY_BILLING_PROFILE,
            outcome=Outcome.UNKNOWN,
            effectiveness=0.0,
            similarity=max(0.78, 0.99 - (index * 0.001)),
        )
        for index in range(pressure)
    ]
    success = _candidate(
        "refresh-success",
        producer="refresh-success-observer",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
        similarity=0.71,
    )
    failure = _candidate(
        "refresh-failure",
        producer="refresh-failure-observer",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
        similarity=0.70,
    )
    return RetrievalScenario(
        scenario_id=f"distinct-head-conflict-p{pressure}",
        family="distinct_head_conflict",
        pressure=pressure,
        candidates=tuple([*noise, success, failure]),
    )


def _supersession_crowding(pressure: int) -> RetrievalScenario:
    old = _candidate(
        "superseded-old",
        producer="payments-corrector",
        strategy=Strategy.VERIFY_BILLING_PROFILE,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
        similarity=0.995,
        observed_offset_seconds=60,
    )
    noise = [
        _candidate(
            f"supersession-noise-{index}",
            producer=f"noise-observer-{index}",
            strategy=Strategy.VERIFY_BILLING_PROFILE,
            outcome=Outcome.UNKNOWN,
            effectiveness=0.0,
            similarity=max(0.80, 0.98 - (index * 0.001)),
        )
        for index in range(pressure)
    ]
    corrected = _candidate(
        "superseding-new",
        producer="payments-corrector",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
        similarity=0.70,
        supersedes="superseded-old",
    )
    return RetrievalScenario(
        scenario_id=f"supersession-crowding-p{pressure}",
        family="supersession_crowding",
        pressure=pressure,
        candidates=tuple([old, *noise, corrected]),
    )


def _low_quality_crowding(pressure: int) -> RetrievalScenario:
    weak = [
        _candidate(
            f"weak-success-{index}",
            producer=f"weak-observer-{index}",
            strategy=Strategy.VERIFY_BILLING_PROFILE,
            outcome=Outcome.SUCCESS,
            effectiveness=0.4,
            similarity=max(0.80, 0.99 - (index * 0.001)),
        )
        for index in range(pressure)
    ]
    valid = _candidate(
        "qualified-generic-failure",
        producer="qualified-observer",
        strategy=Strategy.GENERIC_RETRY,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
        confidence=0.95,
        similarity=0.70,
    )
    return RetrievalScenario(
        scenario_id=f"low-quality-crowding-p{pressure}",
        family="low_quality_crowding",
        pressure=pressure,
        candidates=tuple([*weak, valid]),
    )


def _cross_scope_control(pressure: int) -> RetrievalScenario:
    foreign = [
        _candidate(
            f"foreign-{index}",
            producer=f"foreign-observer-{index}",
            strategy=Strategy.VERIFY_BILLING_PROFILE,
            outcome=Outcome.SUCCESS,
            effectiveness=1.0,
            similarity=max(0.90, 1.0 - (index * 0.001)),
            scope_id="scope-foreign",
        )
        for index in range(max(1, pressure))
    ]
    local = _candidate(
        "local-qualified-failure",
        producer="local-observer",
        strategy=Strategy.GENERIC_RETRY,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
        similarity=0.70,
    )
    return RetrievalScenario(
        scenario_id=f"cross-scope-control-p{pressure}",
        family="cross_scope_control",
        pressure=pressure,
        candidates=tuple([*foreign, local]),
    )


def build_scenarios(
    *, pressures: Iterable[int] = DEFAULT_PRESSURES,
) -> tuple[RetrievalScenario, ...]:
    scenarios: list[RetrievalScenario] = []
    builders = (
        _duplicate_crowding,
        _stale_revoked_crowding,
        _distinct_head_conflict_crowding,
        _supersession_crowding,
        _low_quality_crowding,
        _cross_scope_control,
    )
    for pressure in pressures:
        if pressure < 0:
            raise ValueError("pressure must be non-negative")
        scenarios.extend(builder(pressure) for builder in builders)
    return tuple(scenarios)


def _sorted(items: Iterable[RecalledEpisode]) -> list[RecalledEpisode]:
    return sorted(
        items,
        key=lambda item: (
            item.similarity,
            item.episode.confidence,
            item.episode.observed_at,
            item.episode.episode_id,
        ),
        reverse=True,
    )


def _scope_items(scenario: RetrievalScenario) -> list[RecalledEpisode]:
    return [
        item
        for item in scenario.candidates
        if item.episode.scope_id == scenario.scope_id
    ]


def current_heads(scenario: RetrievalScenario) -> list[RecalledEpisode]:
    """Model the current-head candidate set used before the DVI fast path.

    The benchmark intentionally does not lifecycle-filter this set. Production's
    DVI-compatible ANN query also keeps lifecycle/outcome predicates out of the
    ANN query and relies on exact coverage + the resolver for correctness.
    """

    scoped = _scope_items(scenario)
    superseded_ids = {
        str(item.episode.evidence.get("supersedes_episode_id", "")).strip()
        for item in scoped
        if str(item.episode.evidence.get("supersedes_episode_id", "")).strip()
    }
    scoped = [item for item in scoped if item.episode.episode_id not in superseded_ids]
    latest: dict[tuple[str, Strategy], RecalledEpisode] = {}
    for item in scoped:
        producer = str(item.episode.evidence.get("producer_agent_id", "")).strip()
        key = (producer or item.episode.episode_id, item.episode.strategy)
        existing = latest.get(key)
        if existing is None or item.episode.observed_at > existing.episode.observed_at:
            latest[key] = item
    return _sorted(latest.values())


def exact_governance_coverage(
    scenario: RetrievalScenario,
    *,
    minimum_similarity: float = PRODUCTION_SEMANTIC_MIN_SIMILARITY,
    now: datetime = FIXED_NOW,
) -> list[RecalledEpisode]:
    rows: list[RecalledEpisode] = []
    for item in current_heads(scenario):
        episode = item.episode
        status = str(episode.evidence.get("memory_status", "ACTIVE")).upper()
        pinned = str(episode.evidence.get("pinned", "false")).lower() == "true"
        age_days = max(0.0, (now - episode.observed_at).total_seconds() / 86400.0)
        qualified_outcome = (
            episode.outcome == Outcome.SUCCESS and episode.effectiveness >= 0.7
        ) or (
            episode.outcome == Outcome.FAILED and episode.confidence >= 0.6
        )
        if (
            item.similarity >= minimum_similarity
            and status != "REVOKED"
            and (pinned or age_days <= 90.0)
            and qualified_outcome
        ):
            rows.append(item)
    return _sorted(rows)


def retrieve(
    scenario: RetrievalScenario,
    *,
    mode: str,
    k: int,
    minimum_similarity: float = PRODUCTION_SEMANTIC_MIN_SIMILARITY,
) -> tuple[list[RecalledEpisode], list[RecalledEpisode]]:
    if k <= 0:
        raise ValueError("k must be positive")
    if mode not in MODES:
        raise ValueError(f"unknown retrieval mode: {mode}")

    if mode == "raw_top_k":
        ann = _sorted(_scope_items(scenario))[:k]
        return ann, ann

    ann = current_heads(scenario)[:k]
    if mode == "current_head_top_k":
        return ann, ann

    coverage = exact_governance_coverage(
        scenario,
        minimum_similarity=minimum_similarity,
    )
    merged: dict[str, RecalledEpisode] = {
        item.episode.episode_id: item for item in ann
    }
    for item in coverage:
        merged[item.episode.episode_id] = item
    return ann, _sorted(merged.values())


def _effective_decision(result: MemoryGovernanceResult) -> tuple[str, str | None]:
    if result.resolution == "CONFLICT_ABSTAIN":
        return (DecisionAction.ABSTAIN.value, None)
    if result.memory_influenced and result.selected_strategy is not None:
        return (DecisionAction.EXECUTE.value, result.selected_strategy.value)
    return (DecisionAction.EXECUTE.value, Strategy.GENERIC_RETRY.value)


def evaluate_matrix(
    *,
    k_values: Iterable[int] = DEFAULT_K_VALUES,
    pressures: Iterable[int] = DEFAULT_PRESSURES,
    minimum_similarity: float = PRODUCTION_SEMANTIC_MIN_SIMILARITY,
) -> dict:
    k_values = tuple(k_values)
    pressures = tuple(pressures)
    resolver = ConflictAwareMemoryResolver(minimum_similarity=minimum_similarity)
    rows: list[dict] = []
    scenarios = build_scenarios(pressures=pressures)

    for scenario in scenarios:
        coverage = exact_governance_coverage(
            scenario,
            minimum_similarity=minimum_similarity,
        )
        coverage_ids = {item.episode.episode_id for item in coverage}
        oracle = resolver.resolve(coverage, now=FIXED_NOW)
        oracle_decision = _effective_decision(oracle)
        for k in k_values:
            if k <= 0:
                raise ValueError("k values must be positive")
            target_top_k = {item.episode.episode_id for item in coverage[:k]}
            for mode in MODES:
                ann, retrieved = retrieve(
                    scenario,
                    mode=mode,
                    k=k,
                    minimum_similarity=minimum_similarity,
                )
                ann_ids = {item.episode.episode_id for item in ann}
                retrieved_ids = {item.episode.episode_id for item in retrieved}
                result = resolver.resolve(retrieved, now=FIXED_NOW)
                decision = _effective_decision(result)
                ann_denominator = len(target_top_k)
                coverage_denominator = len(coverage_ids)
                qualified_recall = (
                    len(ann_ids & target_top_k) / ann_denominator
                    if ann_denominator
                    else 1.0
                )
                governed_coverage = (
                    len(retrieved_ids & coverage_ids) / coverage_denominator
                    if coverage_denominator
                    else 1.0
                )
                mismatch = decision != oracle_decision
                inadmissible_in_budget = any(
                    item.episode.episode_id not in coverage_ids for item in ann
                )
                rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "family": scenario.family,
                        "pressure": scenario.pressure,
                        "k": k,
                        "mode": mode,
                        "ann_candidates": len(ann),
                        "retrieved_candidates": len(retrieved),
                        "qualified_recall_at_k": qualified_recall,
                        "governed_evidence_coverage": governed_coverage,
                        "decision_match_oracle": not mismatch,
                        "missed_conflict": (
                            oracle_decision[0] == DecisionAction.ABSTAIN.value
                            and decision[0] != DecisionAction.ABSTAIN.value
                        ),
                        "invalid_candidate_changed_decision": (
                            mismatch and inadmissible_in_budget
                        ),
                        "oracle_action": oracle_decision[0],
                        "oracle_strategy": oracle_decision[1],
                        "action": decision[0],
                        "strategy": decision[1],
                    }
                )

    summary: dict[str, dict] = {}
    for mode in MODES:
        mode_rows = [row for row in rows if row["mode"] == mode]
        count = len(mode_rows)
        summary[mode] = {
            "runs": count,
            "decision_accuracy": (
                sum(row["decision_match_oracle"] for row in mode_rows) / count
                if count
                else 0.0
            ),
            "qualified_recall_at_k": (
                sum(row["qualified_recall_at_k"] for row in mode_rows) / count
                if count
                else 0.0
            ),
            "governed_evidence_coverage": (
                sum(row["governed_evidence_coverage"] for row in mode_rows) / count
                if count
                else 0.0
            ),
            "missed_conflict_rate": (
                sum(row["missed_conflict"] for row in mode_rows) / count
                if count
                else 0.0
            ),
            "invalid_candidate_decision_change_rate": (
                sum(row["invalid_candidate_changed_decision"] for row in mode_rows)
                / count
                if count
                else 0.0
            ),
        }

    return {
        "benchmark": "DecisionVault Retrieval Ablation V2",
        "minimum_similarity": minimum_similarity,
        "k_values": list(k_values),
        "pressures": list(pressures),
        "scenario_count": len(scenarios),
        "run_count": len(rows),
        "summary": summary,
        "rows": rows,
    }


def markdown_report(report: dict) -> str:
    lines = [
        "# DecisionVault Retrieval Ablation V2",
        "",
        "Controlled deterministic candidate-pressure benchmark. It does not call an external embedding provider; candidate similarity scores are fixed so the experiment isolates retrieval-stage correctness rather than model drift.",
        "",
        f"- scenarios: {report['scenario_count']}",
        f"- matrix runs: {report['run_count']}",
        f"- K values: {', '.join(str(value) for value in report['k_values'])}",
        f"- crowding pressures: {', '.join(str(value) for value in report['pressures'])}",
        f"- semantic qualification threshold: {report['minimum_similarity']:.2f}",
        "",
        "| Retrieval mode | Decision accuracy vs exact oracle | Qualified Recall@K | Governed evidence coverage | Missed-conflict rate | Invalid-candidate decision-change rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        item = report["summary"][mode]
        lines.append(
            f"| {mode} | {item['decision_accuracy']:.3f} | "
            f"{item['qualified_recall_at_k']:.3f} | "
            f"{item['governed_evidence_coverage']:.3f} | "
            f"{item['missed_conflict_rate']:.3f} | "
            f"{item['invalid_candidate_decision_change_rate']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Metric definitions",
            "",
            "- **Qualified Recall@K**: fraction of exact-governance-qualified top-K evidence also present in the ANN/top-K fast-path candidate set.",
            "- **Governed evidence coverage**: fraction of all exact-governance-qualified evidence available to the resolver after retrieval/merge.",
            "- **Missed-conflict rate**: exact coverage requires conflict abstention but the tested retrieval mode does not surface enough evidence to abstain.",
            "- **Invalid-candidate decision-change rate**: a mode disagrees with the exact-coverage oracle while its bounded ANN budget contains candidates excluded by exact governance coverage.",
            "",
            "`dual_stage` models the production architecture: current-head ANN Top-K remains a performance fast path, while exact similarity-threshold governance coverage supplies correctness beyond fixed K.",
            "",
        ]
    )
    return "\n".join(lines)
