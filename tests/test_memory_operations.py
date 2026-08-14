from __future__ import annotations

import json

from scripts.configure_memory_operations import alarm_definitions, dashboard_body


def test_memory_operations_alarms_cover_deferred_secret_and_backlog_failures():
    alarms = alarm_definitions(function_name="decisionvault-agent")
    names = {alarm["MetricName"] for alarm in alarms}
    assert names == {
        "ConsolidationDeferredCount",
        "SecretRefreshFailureCount",
        "ConsolidationOutboxBacklog",
        "MemoryQualityDecisionWriteFailureCount",
        "MemoryQualityOutcomeWriteFailureCount",
    }
    assert all(alarm["Namespace"] == "DecisionVault" for alarm in alarms)
    assert all(alarm["TreatMissingData"] == "notBreaching" for alarm in alarms)
    assert all(len(alarm["Dimensions"]) == 1 for alarm in alarms)


def test_memory_operations_dashboard_contains_request_and_memory_panels():
    payload = json.loads(
        dashboard_body(function_name="decisionvault-agent", region="ap-northeast-1")
    )
    titles = {widget["properties"]["title"] for widget in payload["widgets"]}
    assert "DecisionVault request health" in titles
    assert "Governed adaptive-memory health" in titles
    assert "Consolidation backlog" in titles
    assert "Adaptive-memory use" in titles
    assert "Memory-quality telemetry" in titles
    serialized = json.dumps(payload)
    assert "SecretRefreshFailureCount" in serialized
    assert "CrossLayerConflictCount" in serialized
    assert "AdaptiveMemoryHitCount" in serialized
    assert "MemoryQualityDecisionObservedCount" in serialized
    assert "MemoryQualityOutcomeWriteFailureCount" in serialized
    assert "scope_id" not in serialized
