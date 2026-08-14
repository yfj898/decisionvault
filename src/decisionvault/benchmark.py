from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import DecisionEpisode, Outcome, Strategy
from decisionvault.memory.base import MemoryStore
from decisionvault.providers.base import DecisionAdvisor


BENEFIT_FAMILIES = {
    "failed_generic_adaptation",
    "successful_refresh_reuse",
    "successful_billing_reuse",
}


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    family: str
    query_scope_id: str
    query: str
    memory_episode: DecisionEpisode | None
    expected_on_strategy: Strategy
    expected_influenced: bool


@dataclass(frozen=True, slots=True)
class BenchmarkCaseResult:
    case_id: str
    family: str
    expected_on_strategy: str
    expected_influenced: bool
    memory_on_strategy: str
    memory_on_influenced: bool
    memory_off_strategy: str
    memory_off_influenced: bool
    on_matches_target: bool
    off_matches_target: bool
    passed: bool
    advisor_strategy: str | None = None
    advisor_invariant: bool | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    total_cases: int
    benefit_cases: int
    control_cases: int
    passed_cases: int
    overall_accuracy_on: float
    overall_accuracy_off: float
    benefit_target_accuracy_on: float
    benefit_target_accuracy_off: float
    control_preservation_rate_on: float
    failed_retry_repetition_rate_on: float
    failed_retry_repetition_rate_off: float
    successful_strategy_reuse_rate_on: float
    successful_strategy_reuse_rate_off: float
    cross_scope_leakage_rate_on: float
    false_influence_rate_on: float
    advisor_strategy_invariance_rate: float | None


def _episode(
    *,
    episode_id: str,
    scope_id: str,
    situation: str,
    strategy: Strategy,
    outcome: Outcome,
    effectiveness: float,
    confidence: float,
) -> DecisionEpisode:
    return DecisionEpisode(
        episode_id=episode_id,
        scope_id=scope_id,
        situation=situation,
        strategy=strategy,
        outcome=outcome,
        effectiveness=effectiveness,
        confidence=confidence,
        evidence={"benchmark": "phase8"},
        observed_at=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
        recorded_at=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
    )


def build_benchmark_cases(*, variants: int, scope_prefix: str) -> list[BenchmarkCase]:
    if variants <= 0:
        raise ValueError("variants must be positive")

    cases: list[BenchmarkCase] = []
    for index in range(variants):
        suffix = f"v{index:02d}"

        scope = f"{scope_prefix}-failed-generic-{suffix}"
        memory_text = (
            f"payment failed after card replacement; saved payment token is stale {suffix}"
        )
        query = (
            f"payment failed again after card replacement; saved token appears stale {suffix}"
        )
        cases.append(
            BenchmarkCase(
                case_id=f"failed-generic-{suffix}",
                family="failed_generic_adaptation",
                query_scope_id=scope,
                query=query,
                memory_episode=_episode(
                    episode_id=f"00000000-0000-0000-0001-{index:012d}",
                    scope_id=scope,
                    situation=memory_text,
                    strategy=Strategy.GENERIC_RETRY,
                    outcome=Outcome.FAILED,
                    effectiveness=0.1,
                    confidence=0.95,
                ),
                expected_on_strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                expected_influenced=True,
            )
        )

        scope = f"{scope_prefix}-success-refresh-{suffix}"
        memory_text = (
            f"payment token stale after card replacement; refresh payment token resolved issue {suffix}"
        )
        query = (
            f"payment token stale after another card replacement; refresh path relevant {suffix}"
        )
        cases.append(
            BenchmarkCase(
                case_id=f"success-refresh-{suffix}",
                family="successful_refresh_reuse",
                query_scope_id=scope,
                query=query,
                memory_episode=_episode(
                    episode_id=f"00000000-0000-0000-0002-{index:012d}",
                    scope_id=scope,
                    situation=memory_text,
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.95,
                    confidence=0.9,
                ),
                expected_on_strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                expected_influenced=True,
            )
        )

        scope = f"{scope_prefix}-success-billing-{suffix}"
        memory_text = (
            f"billing profile mismatch blocked payment; verifying billing profile fixed payment {suffix}"
        )
        query = (
            f"billing profile mismatch appears to block payment again; verify profile details {suffix}"
        )
        cases.append(
            BenchmarkCase(
                case_id=f"success-billing-{suffix}",
                family="successful_billing_reuse",
                query_scope_id=scope,
                query=query,
                memory_episode=_episode(
                    episode_id=f"00000000-0000-0000-0003-{index:012d}",
                    scope_id=scope,
                    situation=memory_text,
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.9,
                    confidence=0.9,
                ),
                expected_on_strategy=Strategy.VERIFY_BILLING_PROFILE,
                expected_influenced=True,
            )
        )

        scope = f"{scope_prefix}-low-confidence-{suffix}"
        memory_text = (
            f"payment failed after card replacement; saved payment token may be stale {suffix}"
        )
        query = (
            f"payment failed after card replacement; saved payment token may be stale {suffix}"
        )
        cases.append(
            BenchmarkCase(
                case_id=f"low-confidence-{suffix}",
                family="low_confidence_failure_control",
                query_scope_id=scope,
                query=query,
                memory_episode=_episode(
                    episode_id=f"00000000-0000-0000-0004-{index:012d}",
                    scope_id=scope,
                    situation=memory_text,
                    strategy=Strategy.GENERIC_RETRY,
                    outcome=Outcome.FAILED,
                    effectiveness=0.1,
                    confidence=0.4,
                ),
                expected_on_strategy=Strategy.GENERIC_RETRY,
                expected_influenced=False,
            )
        )

        scope = f"{scope_prefix}-weak-success-{suffix}"
        memory_text = (
            f"billing profile mismatch suspected; verification produced weak result {suffix}"
        )
        query = (
            f"billing profile mismatch suspected again; verification may be relevant {suffix}"
        )
        cases.append(
            BenchmarkCase(
                case_id=f"weak-success-{suffix}",
                family="low_effectiveness_success_control",
                query_scope_id=scope,
                query=query,
                memory_episode=_episode(
                    episode_id=f"00000000-0000-0000-0005-{index:012d}",
                    scope_id=scope,
                    situation=memory_text,
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.4,
                    confidence=0.95,
                ),
                expected_on_strategy=Strategy.GENERIC_RETRY,
                expected_influenced=False,
            )
        )

        target_scope = f"{scope_prefix}-cross-scope-target-{suffix}"
        foreign_scope = f"{scope_prefix}-cross-scope-foreign-{suffix}"
        identical = (
            f"payment failed after card replacement; saved payment token definitely stale {suffix}"
        )
        cases.append(
            BenchmarkCase(
                case_id=f"cross-scope-{suffix}",
                family="cross_scope_isolation_control",
                query_scope_id=target_scope,
                query=identical,
                memory_episode=_episode(
                    episode_id=f"00000000-0000-0000-0006-{index:012d}",
                    scope_id=foreign_scope,
                    situation=identical,
                    strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                    outcome=Outcome.SUCCESS,
                    effectiveness=1.0,
                    confidence=1.0,
                ),
                expected_on_strategy=Strategy.GENERIC_RETRY,
                expected_influenced=False,
            )
        )

        scope = f"{scope_prefix}-irrelevant-{suffix}"
        cases.append(
            BenchmarkCase(
                case_id=f"irrelevant-{suffix}",
                family="irrelevant_memory_control",
                query_scope_id=scope,
                query=f"payment token stale after card replacement customer cannot pay {suffix}",
                memory_episode=_episode(
                    episode_id=f"00000000-0000-0000-0007-{index:012d}",
                    scope_id=scope,
                    situation=(
                        f"shipping address typo caused parcel routing delay warehouse queue {suffix}"
                    ),
                    strategy=Strategy.VERIFY_BILLING_PROFILE,
                    outcome=Outcome.SUCCESS,
                    effectiveness=0.95,
                    confidence=0.95,
                ),
                expected_on_strategy=Strategy.GENERIC_RETRY,
                expected_influenced=False,
            )
        )

    return cases


def run_benchmark(
    *,
    store: MemoryStore,
    cases: list[BenchmarkCase],
    advisor: DecisionAdvisor | None = None,
) -> list[BenchmarkCaseResult]:
    results: list[BenchmarkCaseResult] = []
    for case in cases:
        if case.memory_episode is not None:
            store.save(case.memory_episode)

        on = DecisionAgent(memory=store, memory_enabled=True).decide(
            scope_id=case.query_scope_id,
            situation=case.query,
        )
        off = DecisionAgent(memory=store, memory_enabled=False).decide(
            scope_id=case.query_scope_id,
            situation=case.query,
        )

        advisor_strategy: str | None = None
        advisor_invariant: bool | None = None
        if advisor is not None:
            with_advisor = DecisionAgent(
                memory=store,
                memory_enabled=True,
                advisor=advisor,
            ).decide(scope_id=case.query_scope_id, situation=case.query)
            advisor_strategy = with_advisor.strategy.value
            advisor_invariant = with_advisor.strategy == on.strategy

        on_matches = (
            on.strategy == case.expected_on_strategy
            and on.memory_influenced == case.expected_influenced
        )
        off_matches = (
            off.strategy == case.expected_on_strategy
            and off.memory_influenced == case.expected_influenced
        )
        baseline_is_default = (
            off.strategy == Strategy.GENERIC_RETRY and not off.memory_influenced
        )
        passed = on_matches and baseline_is_default
        if advisor_invariant is False:
            passed = False

        results.append(
            BenchmarkCaseResult(
                case_id=case.case_id,
                family=case.family,
                expected_on_strategy=case.expected_on_strategy.value,
                expected_influenced=case.expected_influenced,
                memory_on_strategy=on.strategy.value,
                memory_on_influenced=on.memory_influenced,
                memory_off_strategy=off.strategy.value,
                memory_off_influenced=off.memory_influenced,
                on_matches_target=on_matches,
                off_matches_target=off_matches,
                passed=passed,
                advisor_strategy=advisor_strategy,
                advisor_invariant=advisor_invariant,
            )
        )
    return results


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def summarize_results(results: list[BenchmarkCaseResult]) -> BenchmarkSummary:
    benefit = [item for item in results if item.family in BENEFIT_FAMILIES]
    controls = [item for item in results if item.family not in BENEFIT_FAMILIES]
    failed_generic = [
        item for item in results if item.family == "failed_generic_adaptation"
    ]
    successful_reuse = [
        item
        for item in results
        if item.family in {"successful_refresh_reuse", "successful_billing_reuse"}
    ]
    cross_scope = [
        item for item in results if item.family == "cross_scope_isolation_control"
    ]
    advisor_items = [item for item in results if item.advisor_invariant is not None]

    return BenchmarkSummary(
        total_cases=len(results),
        benefit_cases=len(benefit),
        control_cases=len(controls),
        passed_cases=sum(item.passed for item in results),
        overall_accuracy_on=_rate(
            sum(item.on_matches_target for item in results), len(results)
        ),
        overall_accuracy_off=_rate(
            sum(item.off_matches_target for item in results), len(results)
        ),
        benefit_target_accuracy_on=_rate(
            sum(item.on_matches_target for item in benefit), len(benefit)
        ),
        benefit_target_accuracy_off=_rate(
            sum(item.off_matches_target for item in benefit), len(benefit)
        ),
        control_preservation_rate_on=_rate(
            sum(item.on_matches_target for item in controls), len(controls)
        ),
        failed_retry_repetition_rate_on=_rate(
            sum(item.memory_on_strategy == Strategy.GENERIC_RETRY.value for item in failed_generic),
            len(failed_generic),
        ),
        failed_retry_repetition_rate_off=_rate(
            sum(item.memory_off_strategy == Strategy.GENERIC_RETRY.value for item in failed_generic),
            len(failed_generic),
        ),
        successful_strategy_reuse_rate_on=_rate(
            sum(item.on_matches_target for item in successful_reuse), len(successful_reuse)
        ),
        successful_strategy_reuse_rate_off=_rate(
            sum(item.off_matches_target for item in successful_reuse), len(successful_reuse)
        ),
        cross_scope_leakage_rate_on=_rate(
            sum(item.memory_on_influenced for item in cross_scope), len(cross_scope)
        ),
        false_influence_rate_on=_rate(
            sum(item.memory_on_influenced for item in controls), len(controls)
        ),
        advisor_strategy_invariance_rate=(
            _rate(
                sum(item.advisor_invariant is True for item in advisor_items),
                len(advisor_items),
            )
            if advisor_items
            else None
        ),
    )


def benchmark_payload(
    *,
    backend: str,
    variants: int,
    results: list[BenchmarkCaseResult],
) -> dict[str, Any]:
    return {
        "benchmark": "decisionvault-phase8-memory-ablation",
        "backend": backend,
        "variants_per_family": variants,
        "families": sorted({item.family for item in results}),
        "summary": asdict(summarize_results(results)),
        "cases": [asdict(item) for item in results],
    }
