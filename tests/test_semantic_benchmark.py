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
