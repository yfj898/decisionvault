from decisionvault.domain import DecisionAction
from decisionvault.semantic_benchmark import production_semantic_cases


def test_production_semantic_benchmark_is_hand_authored_and_covers_governance():
    cases = production_semantic_cases()
    assert len(cases) == 14
    assert len({case.query for case in cases}) == len(cases)
    assert not any("v00" in case.query or "v01" in case.query for case in cases)
    case_ids = {case.case_id for case in cases}
    assert "distinct-head-conflict-crowding" in case_ids
    assert "stale-revoked-crowding" in case_ids
    families = {case.family for case in cases}
    assert "failed_generic_adaptation" in families
    assert "cross_scope_control" in families
    assert "conflict_control" in families
    assert "candidate_crowding_control" in families
    assert "supersession_control" in families
    abstain_cases = {
        case.case_id: case
        for case in cases
        if case.expected_resolution == "CONFLICT_ABSTAIN"
    }
    assert set(abstain_cases) == {
        "balanced-conflict-control",
        "duplicate-crowding-control",
        "distinct-head-conflict-crowding",
    }
    assert all(case.expected_strategy is None for case in abstain_cases.values())
    assert all(
        case.expected_action == DecisionAction.ABSTAIN
        for case in abstain_cases.values()
    )
