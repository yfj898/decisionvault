# Governed Adaptive Memory v7 — hardening evidence

Status: **LOCAL PASS / PRODUCTION EXPAND PASS / PRODUCTION CUTOVER BLOCKED BY AWS SECRET-WRITE AUTH**

## Scope

This hardening pass addresses five post-v6 production gaps without weakening
the existing execution, governance, revocation, embedding-space, or readiness
boundaries:

1. versioned signing-key verification across receipt/snapshot key rotation;
2. a durable L1→L2/L3 consolidation outbox with leases and bounded retry;
3. a distinct CockroachDB consolidator identity and expand/contract least
   privilege rollout;
4. low-cardinality memory-health metrics plus alarm/dashboard provisioning;
5. server-owned PRIVATE / TEAM / GLOBAL adaptive-memory scope control.

## Local gates

- exact full suite: **198 passed**;
- `git diff --check`: **PASS**;
- tracked-file credential-shape scan: **PASS**;
- keyed receipt survives active-key rotation when the old key is retained;
- legacy keyless receipt survives rotation while its historical key is retained;
- keyed artifacts never fall back to a different key ID;
- outbox enqueue/lease/backoff tests: **PASS**;
- v7 expand/contract schema tests: **PASS**;
- memory-operation alarm/dashboard contract tests: **PASS**;
- caller-supplied `memory_scope_level` rejection and namespace-specific
  PRIVATE/TEAM/GLOBAL resolution: **PASS**;
- scheduled consolidation-drain handler: **PASS**.

## Production CockroachDB expand

The safe expand phase was applied before any runtime privilege revocation:

- `governed_adaptive_memory_v7_expand`: **PASS**;
- statements applied: **9**;
- `decision_memory_consolidation_outbox`: **present**;
- outbox monotonic `generation` column: **present**;
- `decisionvault_consolidator`: **present**;
- runtime outbox grants: **visible**;
- consolidator outbox grants: **visible**;
- outbox rows after expand: **0**.

No v7 contract REVOKE has been applied yet. Therefore the currently deployed v6
Lambda remains operational while the v7 secret/deploy cutover is incomplete.

## AWS cutover boundary

The restricted deployment identity can read Lambda configuration but does not
have Secrets Manager read/write authority. The existing governance browser login
cache was stale and a fresh browser login did not complete in this pass.

Accordingly, this pass **did not**:

- place the consolidator database credential in Lambda environment variables;
- widen the deployer IAM policy;
- apply the v7 contract REVOKEs before the Lambda uses the distinct identity;
- deploy a version that would intentionally fail managed readiness.

The remaining production cutover is deliberately ordered:

1. write `CONSOLIDATION_DATABASE_URL` and `EXECUTION_RECEIPT_KEYRING_JSON` into
   the existing managed secret using a governance-authorized session;
2. deploy the v7 Lambda and require `/health/ready` to confirm the distinct DB
   identities and outbox schema;
3. run hosted demo/governance/keyring/outbox regression and cleanup;
4. apply v7 contract privilege narrowing;
5. configure EventBridge retry plus CloudWatch alarms/dashboard;
6. rerun production semantic/adaptive regressions and prove final outbox/memory
   cleanup is zero.

Failing closed here is intentional: bypassing Secrets Manager would undo the
credential-boundary hardening already proven in v6.
