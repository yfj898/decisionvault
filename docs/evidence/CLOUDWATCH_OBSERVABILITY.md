# CloudWatch Structured Observability Evidence

Date: 2026-08-14

Status: **PASS** for hosted Lambda logs and materialized CloudWatch metrics.

## Design

Every Lambda response emits one CloudWatch Embedded Metric Format (EMF) JSON
event. The metric namespace is `DecisionVault` and the only dimension is the
low-cardinality route name.

Metrics:

```text
RequestCount
ErrorCount
LatencyMs
MemoryInfluencedCount
MemoryConflictCount
IdempotentReplayCount
```

The event intentionally excludes scope IDs, episode IDs, agent identities,
situation/request text, tokens, model explanations, and database identifiers.
Observability failures are non-authoritative and cannot alter the API response.

## Hosted verification

Live requests were made to:

```text
/health/ready
/demo
/governance-demo
```

After CloudWatch Logs ingestion, three EMF events were parsed:

```text
emf_event_count=3
emf_routes=/demo,/governance-demo,/health/ready
conflict_seen=True
influenced_seen=True
cloudwatch_emf_logs=PASS
```

The parsed JSON was scanned to confirm that no high-cardinality/sensitive context
fields were present.

CloudWatch metric discovery then returned:

```text
ErrorCount
IdempotentReplayCount
LatencyMs
MemoryConflictCount
MemoryInfluencedCount
RequestCount

cloudwatch_emf_metrics=PASS
```

This proves that structured Lambda output is not merely printed locally: AWS
CloudWatch has materialized the `DecisionVault` metric namespace.
