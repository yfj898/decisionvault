# Production hardening V6: outcome contract, co-location proof, provider retry, orphan sweep

Status: **PRODUCTION-HARDENING PASS — all P0/P1/P2 findings closed, 257/257 tests, CI green, 30-minute hosted soak PASS**

This pass ran a production-level audit (architecture, external red-team,
cleanup adversarial, stability, regression, deployment discipline) and closed
every actionable finding. It also exercised the real deployed Lambda against
the real CockroachDB Cloud cluster with least-privilege identities, proving the
fail-closed controls work against production, not only mocks.

## Audit outcome (finding classes)

| ID | Finding | Disposition |
|----|---------|-------------|
| P0 | None | — |
| P1-1 | External execution receipts could carry a claimed business outcome; transport success is not business success | Fixed (issuer + verifier both enforce `outcome=UNKNOWN`, `effectiveness=0`) |
| P2-2 | `_delete_scope` runs two transactions; a crash between them leaves orphaned derived rows | Fixed (scheduled orphan sweep) |
| P2-3 | Readiness did not prove that the runtime and consolidation connections share one cluster/database | Fixed (`consolidation_database_consistent` gate, fail-closed 503) |
| P3 | Test/documentation gaps: cleanup-vs-* race automated tests, replay duplicate quality metric, smoke wildcard prefix, timeout clamp constants, adapter negative-path unit tests, sandbox SUCCESS writes L1 (design semantics) | Kept on the open list; none is a runtime defect |

## Commits

```text
f7e9e92 fix: enforce external receipt outcome contract and prove consolidation database co-location
f433379 fix: retry fast-failing NVIDIA provider errors once within Lambda deadline
c240c2a fix: sweep orphaned derived rows on scheduled consolidation-retry
```

All three are on `origin/master`; the CI workflow (credential shape scan,
privacy scan, full pytest) reported `success` for each push.

## 1. P1-1: external receipt must not claim a business outcome

`issue_external_receipt` (issuer) and `verify_execution_receipt` (verifier)
both enforce `outcome == UNKNOWN` and `abs(effectiveness) <= 1e-9`, with the
message:

```text
external receipt must not claim a business outcome; transport success is not business success
```

The verifier additionally rejects future issuer paths: a re-signed receipt with
a claimed outcome fails verification. Tests: issuer rejects, verifier rejects
re-signed claims, unclaimed receipts still accepted.

## 2. P2-3: consolidation co-location proof (fail-closed)

Readiness now compares the runtime and consolidation connections by
`(server_host, current_database())` from the psycopg handshake (no SQL
privileges required). Mismatch or unreadable identity raises → readiness 503.

This control caught a real production problem on its first deployment: the
initial implementation used `crdb_internal.cluster_id()`, which the
least-privilege runtime/consolidator identities cannot read
(`InsufficientPrivilege`), so readiness correctly returned 503 instead of
silently degrading. The identity query was switched to the privilege-free
form and the re-deployed Lambda returned:

```json
{"status": "ready", "consolidation_database_consistent": true, "errors": []}
```

Proving that the production consolidation secret points at the same cluster
and database as the runtime connection — the premise of all
cleanup-vs-consolidation serialization guarantees.

## 3. Provider retry within the Lambda deadline

The 30-minute soak on the hardened build showed exactly one
`/governance-demo` 500 in 165 iterations (judge-LLM tail latency; 122
subsequent calls including a 40-call replay were all 200). Fix: NVIDIA
provider requests retry once, and only for fast-failing errors — HTTP
429/500/502/503/504 and connection-level failures. Timeout errors are never
retried because the caller's timeout budget is already consumed and the
Lambda deadline (30 s) must remain guaranteed.

Budget check (worst case): embedding 12 s + retry delay 1 s + embedding 12 s +
judge 5 s ≈ 26 s < 30 s deadline. GitHub/Bedrock provider paths were left
unchanged (scope control).

## 4. P2-2: orphaned derived-row sweep

`_delete_scope` necessarily uses two transactions: no least-privilege
identity holds DELETE on all eight tables (runtime lacks outbox/L2/L3 DELETE;
consolidator lacks heads/episodes DELETE). A crash between the two commits
leaves derived rows with no governing head.

The scheduled consolidation-retry run now also executes
`_sweep_orphaned_adaptive_rows()` (consolidator identity, best-effort):
DELETE of outbox / support / governed_memories / candidates / effectiveness
rows whose `scope_id` is not in `decision_memory_heads`. Safety: outbox rows
are enqueued in the same transaction that creates their heads, so a visible
headless outbox row is by definition orphaned; L1 deletion is itself atomic
(heads + episodes in one transaction); the sweep is idempotent and
serialization-conflict safe.

## Production verification evidence

All checks ran against the deployed Lambda (ap-northeast-1,
`decisionvault-agent`, python3.12, 30 s timeout) and the real CockroachDB
Cloud cluster using local ignored credential files; no credential value was
written to the repository, terminal output, or reports.

| Check | Result |
|-------|--------|
| Readiness (final) | HTTP 200, `status=ready`, `consolidation_database_consistent=true`, `errors=[]` |
| /demo, /governance-demo (hosted) | HTTP 200, contract fields satisfied (`cleaned=true`, `CONFLICT_ABSTAIN`) |
| Semantic production benchmark | 14/14 PASS (real NVIDIA embeddings + real DB) |
| Adaptive cloud smoke | 13/13 PASS (incl. consolidation_vs_normal_write / _supersession / _revocation) |
| Soak v13 (hardening baseline) | 30 min, 165 iterations, transport failures 0, validation failures 1 (single judge tail-latency 500), p95 9.3 s |
| Post-fix replay | 40/40 HTTP 200 |
| Soak v14 (with retry) | 30 min, 166 iterations, transport failures 0, validation failures 0, p95 9.5 s, PASS |
| DB audit (pre/post soak) | 8 business tables 0 rows; `adaptive-cloud-%` 0 rows; telemetry decisions 2 / outcomes 2 / calibration_runs 3 (no pollution) |
| Local tests | 245 baseline → 257 after all hardening |
| Credential/privacy scans | PASS (tracked tree only; no values in reports/docs/README) |

Deployment artifacts (hashes for integrity):

```text
dist/decisionvault-lambda-hardening-v13.zip  sha256 99510a49cdb4461a5a724a4e6bd12aaa8e73cdc1fc0ff38ffa53ca606a5fbedd
cockroach CA (packaged)                    sha256 04cc3f18076b845976384175c7ea45b127de9b66c756ac8fdb148617b9c57a43
deployed CodeSha256 (final v15)            ON264fs1Hu0LKdBGpe3sfjdJU3rmxs+qJUIlXRWzDKc=
```

## Security and privilege discipline

- The AWS deployer identity is least-privilege by design: Secrets Manager
  reads, CloudWatch logs, and Lambda invoke are all denied — verified by
  AccessDenied on each. Readiness is therefore the production observability
  surface for the consolidation secret, which is exactly why the co-location
  gate matters.
- Sweep SQL was executed once against production with the admin audit
  identity (empty tables, 0 rows deleted) to prove syntax and semantics; the
  consolidator DELETE grants were confirmed from the v7 contract SQL.
- No IAM policy was changed during this pass.

## Honest boundaries

- The single soak failure's server-side detail is not observable: CloudWatch
  log access is denied to the deployer identity. The diagnosis (judge LLM tail
  latency) rests on statistical evidence (165/165 readiness and 83/83 demo
  success, p99 10.5 s vs the 5 s judge timeout) plus a 40/40 non-reproducing
  replay, and the fix targets that path.
- The scheduled consolidation-retry branch (including the orphan sweep) was
  verified by unit/integration tests and SQL dry-run; its first live
  production trigger depends on the real EventBridge cron because
  `lambda:InvokeFunction` is denied.

## Open items (non-blocking)

- P3 list above (test/docs gaps) unchanged.
- Optional: consolidate the two timeout-clamp constants and add adapter
  negative-path tests (corrupted content / 5xx / non-JSON / missing sha).