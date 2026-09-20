from __future__ import annotations

from decisionvault.retrieval_ablation import (
    build_scenarios,
    evaluate_matrix,
    exact_governance_coverage,
)


def test_retrieval_ablation_matrix_exposes_bounded_top_k_failures() -> None:
    report = evaluate_matrix()

    assert report["scenario_count"] == 24
    assert report["run_count"] == 216
    assert report["summary"]["dual_stage"]["decision_accuracy"] == 1.0
    assert report["summary"]["dual_stage"]["governed_evidence_coverage"] == 1.0
    assert report["summary"]["raw_top_k"]["decision_accuracy"] < 1.0
    assert report["summary"]["current_head_top_k"]["decision_accuracy"] < 1.0
    assert (
        report["summary"]["current_head_top_k"]["decision_accuracy"]
        >= report["summary"]["raw_top_k"]["decision_accuracy"]
    )
    assert report["summary"]["raw_top_k"]["missed_conflict_rate"] > 0.0
    assert report["summary"]["dual_stage"]["missed_conflict_rate"] == 0.0


def test_exact_coverage_excludes_stale_revoked_unknown_and_weak_rows() -> None:
    scenarios = {scenario.family: scenario for scenario in build_scenarios(pressures=(12,))}

    stale_coverage = exact_governance_coverage(scenarios["stale_revoked_crowding"])
    assert [item.episode.episode_id for item in stale_coverage] == [
        "fresh-generic-failure"
    ]

    conflict_coverage = exact_governance_coverage(scenarios["distinct_head_conflict"])
    assert {item.episode.episode_id for item in conflict_coverage} == {
        "refresh-success",
        "refresh-failure",
    }

    weak_coverage = exact_governance_coverage(scenarios["low_quality_crowding"])
    assert [item.episode.episode_id for item in weak_coverage] == [
        "qualified-generic-failure"
    ]
