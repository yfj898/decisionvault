# Governed Adaptive Memory v7 — hardening evidence

Status: **PRODUCTION PASS**

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

- exact full suite: **200 passed**;
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

The expand step did not revoke any old runtime right. Contract narrowing was
performed only after the v7 Lambda proved its distinct consolidator identity.

## AWS managed-secret and signing-key cutover

A governance-authorized AWS session updated the existing Secrets Manager object;
no database credential was placed in Lambda environment variables and the
restricted deployment identity was not widened.

The first secret update added the independent consolidator URL and a keyring
whose active `r1` key was the existing signing secret. This kept the old Lambda
compatible while the v7 code package was deployed. After v7 readiness passed,
the signing key was genuinely rotated:

- pre-rotation active key: `prod-20260814-r1`;
- post-rotation active key: `prod-20260814-r2`;
- retained verification keys: **2** (`r1` + `r2`);
- secret refresh interval temporarily reduced to 1 second during transition and
  restored to 30 seconds afterward;
- post-rotation `/health/ready`: **HTTP 200 / ready / errors=[]**.

No key material is committed in this evidence file.

## Lambda v7 deployment and fail-closed readiness

The v7 Lambda package was rebuilt from pinned Lambda requirements plus the
explicit CockroachDB public CA and deployed to `decisionvault-agent`:

- package required-file audit: **PASS**;
- deployed CodeSha256 matched the built ZIP: **PASS**;
- Lambda state: **Active**;
- Lambda update status: **Successful**;
- runtime: **python3.12**.

Hosted readiness before privilege contract:

- HTTP: **200**;
- status: **ready**;
- runtime database: **PASS**;
- consolidation database: **PASS**;
- runtime/consolidator identity isolation: **PASS**;
- consolidation outbox schema: **PASS**;
- server-owned memory-scope control: **PASS**;
- adaptive schema/currentness: **PASS**;
- semantic embedding + revision/head-space: **PASS**;
- receipt signing / agent auth / demo auth / execution sandbox: **PASS**;
- readiness errors: **0**.

## Production CockroachDB contract

Only after the new Lambda proved the separate consolidator identity was the v7
contract applied:

- `governed_adaptive_memory_v7_contract`: **PASS**;
- statements applied: **7**.

Verified CockroachDB grants after contract:

- request runtime on consolidation candidates: **SELECT only**;
- request runtime on strategy effectiveness: **SELECT only**;
- request runtime on governed-memory support: **SELECT only**;
- request runtime on governed memories: **SELECT + UPDATE** only, preserving the
  synchronous invalidation boundary when supporting L1 evidence changes;
- request runtime on outbox: **SELECT + INSERT + UPDATE**, with no DELETE;
- consolidator on candidates / L2 / governed memories / support: **full DML**;
- consolidator on outbox: **SELECT + UPDATE + DELETE**.

Hosted `/health/ready` remained **HTTP 200 / ready** after contract, including
`consolidation_identity_isolated=true` and zero readiness errors.

## Hosted behavior regression

- `/demo`: **HTTP 200**;
- Memory OFF strategy: `GENERIC_RETRY`;
- Memory ON strategy: `REFRESH_PAYMENT_TOKEN`;
- Memory ON influenced: **true**;
- cross-agent memory used: **true**;
- demo cleanup: **true**;
- `/governance-demo`: **HTTP 200**;
- action: `ABSTAIN`;
- executable: **false**;
- resolution: `CONFLICT_ABSTAIN`;
- conflict: **true**;
- governance-demo cleanup: **true**.

## Durable retry and operations proof

Production operations were provisioned from the committed script:

- EventBridge rule: `decisionvault-agent-consolidation-retry`;
- schedule: **rate(5 minutes)**;
- rule state: **ENABLED**;
- Lambda targets: **1**;
- EventBridge Lambda permission: **present**;
- CloudWatch alarms: **3/3 present**;
- CloudWatch dashboard: `decisionvault-agent-memory-operations`;
- dashboard widgets: **4**.

A real durable retry smoke used the exact post-contract identities:

1. `decisionvault_runtime` inserted one temporary TEAM consolidation obligation;
2. the Lambda Scheduled Event branch claimed it;
3. `decisionvault_consolidator` completed the empty-scope consolidation;
4. the obligation was deleted by the consolidator identity.

Observed result:

- scheduled HTTP status: **200**;
- claimed: **1**;
- completed: **1**;
- deferred: **0**;
- temporary outbox / candidate / L2 / L3 rows: **0**.

## Final production semantic/adaptive regression

After contract and signing-key rotation:

- NVIDIA/CockroachDB production semantic benchmark: **14/14 PASS**;
- adaptive-memory adversarial/concurrency smoke: **13/13 PASS**;
- team promotion / adaptive retrieval / adaptive decision: **PASS**;
- producer crowding blocked: **PASS**;
- independent contradiction abstention + prior-L3 revocation: **PASS**;
- negative promotion + negative veto: **PASS**;
- cross-revision isolation: **PASS**;
- consolidation vs normal-write / supersession / revocation races: **PASS**;
- adaptive governance revision gate: **PASS**.

The v7 identity split required the adaptive cloud smoke itself to use
`DATABASE_URL` for L1 writes and `CONSOLIDATION_DATABASE_URL` for candidate/L2/L3
promotion. Test cleanup continues to use a migration-admin URL rather than
widening either production identity.

## Cleanup defect found and closed during proof

The first post-contract audit found **22 PENDING test-only outbox rows** while all
seven pre-v7 memory tables were already zero:

- adaptive-cloud test scopes: **18**;
- semantic-prod test scopes: **4**;
- max attempt count: **0**.

Root cause: v7 makes every semantic L1 save create a durable consolidation
obligation, but the two older production test cleanup functions did not yet
delete the new outbox table. This result was treated as a failed cleanup, not
hidden or accepted.

The cleanup contracts were fixed so:

- adaptive smoke includes outbox in its remaining-row assertion;
- semantic benchmark uses the migration-admin cleanup identity and removes
  outbox plus any temporary adaptive projection/promotion rows;
- request-runtime privileges remain unchanged.

Both production suites were then rerun from scratch. Final audit:

```text
decision_episodes=0
decision_memory_heads=0
decision_memory_revocations=0
decision_memory_consolidation_candidates=0
decision_strategy_effectiveness=0
decision_governed_memories=0
decision_governed_memory_support=0
decision_memory_consolidation_outbox=0
production_memory_rows_total=0
```

Final production cleanup: **PASS**.

## Security result

The five hardening goals are now live without introducing a second execution
authority path:

- key rotation preserves historical verification while new artifacts bind an
  explicit key ID;
- every L1 mutation creates a durable, generation-safe consolidation obligation;
- request runtime cannot promote or delete governed adaptive authority;
- retry/backlog/secret failures are observable through low-cardinality metrics;
- PRIVATE/TEAM/GLOBAL memory promotion remains a server-owned policy decision;
- readiness fails closed if the separate consolidator identity, outbox schema,
  embedding generation, or governance state is invalid.
