from __future__ import annotations

from decisionvault.benchmark import (
    build_benchmark_cases,
    run_benchmark,
    summarize_results,
)
from decisionvault.domain import Decision, RecalledEpisode
from decisionvault.memory.inmemory import InMemoryEpisodeStore


class ExplanationOnlyAdvisor:
    provider_name = "test:advisor"

    def explain(
        self,
        *,
        situation: str,
        decision: Decision,
        recalled: list[RecalledEpisode],
    ) -> str:
        return "explanation only"


def test_memory_benchmark_separates_benefits_and_controls():
    cases = build_benchmark_cases(variants=2, scope_prefix="unit-bench")
    results = run_benchmark(store=InMemoryEpisodeStore(), cases=cases)
    summary = summarize_results(results)

    assert summary.total_cases == 14
    assert summary.passed_cases == 14
    assert summary.benefit_cases == 6
    assert summary.control_cases == 8
    assert summary.benefit_target_accuracy_on == 1.0
    assert summary.benefit_target_accuracy_off == 0.0
    assert summary.control_preservation_rate_on == 1.0
    assert summary.failed_retry_repetition_rate_on == 0.0
    assert summary.failed_retry_repetition_rate_off == 1.0
    assert summary.successful_strategy_reuse_rate_on == 1.0
    assert summary.successful_strategy_reuse_rate_off == 0.0
    assert summary.cross_scope_leakage_rate_on == 0.0
    assert summary.false_influence_rate_on == 0.0


def test_advisor_ablation_cannot_change_strategy():
    cases = build_benchmark_cases(variants=1, scope_prefix="advisor-bench")
    results = run_benchmark(
        store=InMemoryEpisodeStore(),
        cases=cases,
        advisor=ExplanationOnlyAdvisor(),
    )
    summary = summarize_results(results)

    assert summary.passed_cases == summary.total_cases
    assert summary.advisor_strategy_invariance_rate == 1.0
