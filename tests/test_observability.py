from __future__ import annotations

import json

from decisionvault.observability import emit_memory_metric, emit_request_metric


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


def test_memory_health_metric_is_alarm_ready_and_contains_no_scope_identity(capsys):
    emit_memory_metric(
        event_name="consolidation_deferred",
        consolidation_deferred=1,
        outbox_backlog=3,
        cross_layer_conflict=1,
        quality_calibration_run=1,
        quality_calibration_samples=17,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["MemoryEvent"] == "consolidation_deferred"
    assert payload["ConsolidationDeferredCount"] == 1
    assert payload["ConsolidationOutboxBacklog"] == 3
    assert payload["CrossLayerConflictCount"] == 1
    assert payload["MemoryQualityCalibrationRunCount"] == 1
    assert payload["MemoryQualityCalibrationObservedSamples"] == 17
    metrics = payload["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    assert {item["Name"] for item in metrics} >= {
        "ConsolidationDeferredCount",
        "ConsolidationOutboxBacklog",
        "SecretRefreshFailureCount",
        "MemoryQualityCalibrationFailureCount",
    }
    serialized = json.dumps(payload)
    for forbidden in ("scope_id", "agent_id", "episode_id", "situation", "token"):
        assert forbidden not in serialized
