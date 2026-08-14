from __future__ import annotations

import json
import time
from typing import Any


def emit_request_metric(
    *,
    route: str,
    status_code: int,
    latency_ms: float,
    memory_influenced: bool = False,
    memory_conflict: bool = False,
    idempotent_replay: bool = False,
) -> None:
    """Emit a low-cardinality CloudWatch Embedded Metric Format event.

    Deliberately excluded: scope IDs, episode IDs, agent IDs, situations,
    request bodies, tokens, model text, and database identifiers.
    """

    event: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "DecisionVault",
                    "Dimensions": [["Route"]],
                    "Metrics": [
                        {"Name": "RequestCount", "Unit": "Count"},
                        {"Name": "ErrorCount", "Unit": "Count"},
                        {"Name": "LatencyMs", "Unit": "Milliseconds"},
                        {"Name": "MemoryInfluencedCount", "Unit": "Count"},
                        {"Name": "MemoryConflictCount", "Unit": "Count"},
                        {"Name": "IdempotentReplayCount", "Unit": "Count"},
                    ],
                }
            ],
        },
        "Route": route,
        "StatusCode": int(status_code),
        "RequestCount": 1,
        "ErrorCount": int(status_code >= 400),
        "LatencyMs": round(float(latency_ms), 3),
        "MemoryInfluencedCount": int(memory_influenced),
        "MemoryConflictCount": int(memory_conflict),
        "IdempotentReplayCount": int(idempotent_replay),
    }
    print(json.dumps(event, separators=(",", ":"), sort_keys=True), flush=True)


def emit_memory_metric(
    *,
    event_name: str,
    consolidation_completed: int = 0,
    consolidation_deferred: int = 0,
    promoted: int = 0,
    abstained: int = 0,
    producer_retired: int = 0,
    outbox_backlog: int = 0,
    negative_veto: int = 0,
    cross_layer_conflict: int = 0,
    adaptive_hit: int = 0,
    secret_refresh_failure: int = 0,
    quality_decision_observed: int = 0,
    quality_outcome_observed: int = 0,
    quality_decision_write_failure: int = 0,
    quality_outcome_write_failure: int = 0,
    quality_calibration_run: int = 0,
    quality_calibration_samples: int = 0,
    quality_calibration_recommendation: int = 0,
    quality_calibration_failure: int = 0,
) -> None:
    """Emit fixed-name, low-cardinality memory-health metrics.

    ``event_name`` is supplied only by server-controlled call sites. Scope IDs,
    producers, situations, model text, and credential material are deliberately
    excluded so the metrics remain safe for long-term CloudWatch retention.
    """

    values = {
        "ConsolidationCompletedCount": int(consolidation_completed),
        "ConsolidationDeferredCount": int(consolidation_deferred),
        "GovernedPromotionCount": int(promoted),
        "GovernedAbstentionCount": int(abstained),
        "ProducerRetiredCount": int(producer_retired),
        "ConsolidationOutboxBacklog": int(outbox_backlog),
        "NegativeMemoryVetoCount": int(negative_veto),
        "CrossLayerConflictCount": int(cross_layer_conflict),
        "AdaptiveMemoryHitCount": int(adaptive_hit),
        "SecretRefreshFailureCount": int(secret_refresh_failure),
        "MemoryQualityDecisionObservedCount": int(quality_decision_observed),
        "MemoryQualityOutcomeObservedCount": int(quality_outcome_observed),
        "MemoryQualityDecisionWriteFailureCount": int(quality_decision_write_failure),
        "MemoryQualityOutcomeWriteFailureCount": int(quality_outcome_write_failure),
        "MemoryQualityCalibrationRunCount": int(quality_calibration_run),
        "MemoryQualityCalibrationObservedSamples": int(quality_calibration_samples),
        "MemoryQualityCalibrationRecommendationCount": int(
            quality_calibration_recommendation
        ),
        "MemoryQualityCalibrationFailureCount": int(quality_calibration_failure),
    }
    event: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "DecisionVault",
                    "Dimensions": [["MemoryEvent"]],
                    "Metrics": [
                        {"Name": name, "Unit": "Count"}
                        for name in values
                    ],
                }
            ],
        },
        "MemoryEvent": event_name,
        **values,
    }
    print(json.dumps(event, separators=(",", ":"), sort_keys=True), flush=True)
