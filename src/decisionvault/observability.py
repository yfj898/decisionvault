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
