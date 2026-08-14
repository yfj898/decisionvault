from __future__ import annotations

import json

from decisionvault.observability import emit_request_metric


def test_emf_metric_is_low_cardinality_and_contains_no_sensitive_context(capsys):
    emit_request_metric(
        route="/decide",
        status_code=200,
        latency_ms=12.3456,
        memory_influenced=True,
        memory_conflict=False,
        idempotent_replay=False,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["Route"] == "/decide"
    assert payload["RequestCount"] == 1
    assert payload["MemoryInfluencedCount"] == 1
    assert payload["LatencyMs"] == 12.346
    assert payload["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "DecisionVault"
    serialized = json.dumps(payload)
    for forbidden in (
        "scope_id",
        "episode_id",
        "agent_id",
        "situation",
        "token",
        "model_explanation",
    ):
        assert forbidden not in serialized
