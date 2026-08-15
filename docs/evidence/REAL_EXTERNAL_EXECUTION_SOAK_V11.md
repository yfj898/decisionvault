# Real external execution + sustained hosted soak

Status: **PRODUCTION-HARDENING PASS / EXTERNAL PROVIDER READY BUT HOSTED ACTIVATION WITHHELD**

This pass closed the two highest-value post-memory-hardening gaps that can be
addressed with the current project resources:

1. prove a real, externally visible side effect outside the DecisionVault
   payment sandbox; and
2. run a sustained hosted stability test long enough to expose cleanup and
   scheduled-consolidation races.

The external provider code is deployed, but production remains deliberately on
the deterministic sandbox until a dedicated least-privilege GitHub credential
is provisioned. The broad local GitHub CLI credential used for the one-time
proof was never copied into AWS, source control, or a report.

## External execution contract

Source commit:

```text
c6c64bd feat: add verified external execution adapter
```

The general execution flow is now provider-aware:

```text
governed /decide
→ signed decision snapshot
→ server-selected ExecutionAdapter
→ external side effect
→ external read-back verification
→ signed execution receipt v3
```

The real adapter is source-bound to:

```text
yfj898/decisionvault-execution-sandbox
```

Callers cannot choose the provider, repository, URL, title, body, or other
external target fields.

## Idempotency defect found during the real proof

The first implementation used GitHub Issues with an exact title/body snapshot
marker. A live replay created two issues for one snapshot because a just-created
issue was not immediately visible through the issue-list path.

That implementation was rejected rather than treated as acceptable eventual
consistency. The two pre-hardening test issues were closed and retained only as
audit evidence of the failed design.

The final adapter uses the GitHub Contents API with one deterministic path per
snapshot:

```text
decisionvault-executions/<decision-snapshot-id>.json
```

This path is the external idempotency key. A replay reads the exact path. A
concurrent second create can only conflict on that same path and is reconciled by
exact GET. A timeout after a possibly committed PUT also performs exact-path
reconciliation and never blindly repeats the PUT.

GitHub also showed a short read-after-write propagation interval on the Contents
API, so the adapter performs a bounded exact-GET retry after create. The retry
does not repeat the side effect.

## Real external proof

The final live proof created a real repository file, read it back, replayed the
same snapshot, and verified that the replay referred to the same external blob.

Evidence:

```text
reports/github-execution-smoke.json
```

Result:

```text
provider=github-contents-v1
first_execution_verified=PASS
idempotent_replay=PASS
external_receipt_v3=PASS
business_outcome_verified=False
automatic_memory_success_claim=False
github_execution_smoke=PASS
```

The signed external operation id binds the allowlisted repository, deterministic
resource path, and verified Git blob SHA.

## Side-effect success is not business success

A successful GitHub write proves only that the external operation happened. It
does not prove that `REFRESH_PAYMENT_TOKEN`, `VERIFY_BILLING_PROFILE`, or another
business strategy succeeded.

Therefore the GitHub adapter produces:

```text
Outcome.UNKNOWN
effectiveness=0.0
```

and `/record` rejects that external receipt with:

```text
HTTP 422
business_outcome_unverified
```

before any L1 episode is written. Calibration independently counts only factual
`SUCCESS` / `FAILED` outcomes. Thus a transport/write success cannot become a
false positive memory or crowd governed recall.

Targeted failure-injection tests cover:

- provider unavailable → HTTP 503 / no receipt;
- timeout-after-success → exact-path reconciliation / no duplicate PUT;
- concurrent create collision → exact-path reconciliation;
- stale decision snapshot → HTTP 409 / no receipt;
- abstained decision → no execution;
- GitHub provider without secret → fail-closed configuration;
- external `UNKNOWN` receipt → HTTP 422 / no decision-memory write.

Targeted failure-injection result:

```text
7 / 7 PASS
```

## Source verification and hosted deployment

Before source commit:

```text
245 / 245 tests PASS
credential_shape_scan=PASS
github_execution_report_privacy_scan=PASS
git diff --check=PASS
```

GitHub Actions:

```text
31859278177 / c6c64bd / SUCCESS
```

The Lambda ZIP was built from the exact source tree and every
`src/decisionvault/*.py` hash was compared with the ZIP before deployment.

Deployment result:

```text
Lambda state=Active
LastUpdateStatus=Successful
CodeSha256 matched the c6c64bd package
execution_provider=sandbox
```

The production provider intentionally stayed on `sandbox`; no GitHub execution
credential was added to AWS.

Hosted readiness after deployment:

```text
HTTP 200
status=ready
execution_provider=sandbox
execution_provider_config=True
execution_sandbox=True
errors=0
```

Hosted causal paths remained valid:

```text
/demo: HTTP 200 / expected_change=True / cross_agent=True / cleaned=True
/governance-demo: HTTP 200 / ABSTAIN / executable=False /
                  CONFLICT_ABSTAIN / cleaned=True
```

Real semantic benchmark after deployment:

```text
14 / 14 PASS
```

## 30-minute sustained hosted route soak

The soak deliberately avoided `/decide`; it exercised only readiness and the two
self-cleaning judge workflows so it would not manufacture calibration samples.

Report:

```text
reports/production-soak.json
```

Route-level result:

```text
duration=30 minutes
iterations=165
HTTP requests=330

/health/ready       165 / 165 HTTP 200
/demo                83 / 83  HTTP 200
/governance-demo     82 / 82  HTTP 200

transport_failures=0
validation_failures=0

overall p50=4490.836 ms
overall p95=9819.796 ms
overall p99=10902.335 ms

readiness p95=3930.074 ms
demo p95=10698.885 ms
governance-demo p95=10062.485 ms
```

The route-level soak was successful, but the required post-soak database audit
found one residual `decision_strategy_effectiveness` row. All other business
memory/outbox tables were zero.

The residual row was classified without exposing a raw scope identifier:

```text
phase7 demo projection rows=0
governance-demo projection rows=1
```

This converted the soak from a simple performance proof into a useful
concurrency finding.

## Cleanup-vs-consolidation race and fix

Root cause: `_delete_scope()` deleted derived adaptive rows and the consolidation
outbox before deleting authoritative L1 heads/episodes. A scheduled worker that
had already claimed the scope could therefore read the still-present L1 heads
and repopulate the L2 strategy-effectiveness projection after the first cleanup
phase completed.

Fix commit:

```text
f6a208f fix: serialize demo cleanup before adaptive deletion
```

The cleanup order is now:

```text
1. delete authoritative L1 heads + episodes and commit
2. delete outbox + L2/L3/adaptive rows and commit
```

Because consolidation reads current heads `FOR UPDATE` under CockroachDB
SERIALIZABLE isolation, a worker that started earlier must serialize before the
L1 deletion completes and its derived rows are removed by phase 2. A worker that
starts after L1 deletion sees no evidence and cannot recreate the projection.

The unit contract asserts that the runtime L1 transaction commits before any
adaptive cleanup statement starts.

Verification:

```text
245 / 245 tests PASS
GitHub Actions 31860957000 / f6a208f / SUCCESS
Lambda Active / Successful
deployed CodeSha256 matched f6a208f package
execution_provider remained sandbox
```

The single historical governance-demo projection discovered by the soak was
then removed using the admin identity, leaving all eight business tables at
zero before the post-fix stress.

## Post-fix cleanup stress

A 6-minute high-density hosted stress was run from a clean database state,
crossing at least one 5-minute scheduled consolidation interval.

Report:

```text
reports/cleanup-stress.json
```

Result:

```text
duration=6 minutes
iterations=36
/health/ready       36 / 36 HTTP 200
/demo               18 / 18 HTTP 200
/governance-demo    18 / 18 HTTP 200
transport_failures=0
validation_failures=0
overall p95=10609.033 ms
```

Post-stress production database audit:

```text
decision_episodes=0
decision_memory_heads=0
decision_memory_revocations=0
decision_memory_consolidation_candidates=0
decision_strategy_effectiveness=0
decision_governed_memories=0
decision_governed_memory_support=0
decision_memory_consolidation_outbox=0
business_memory_rows_total=0
```

Long-term calibration telemetry remained unchanged:

```text
quality_decisions=2
quality_outcomes=2
calibration_runs=3
```

## Adaptive smoke cleanup hardening

The final adaptive regression itself exposed another concurrency condition in
the **test cleanup helper**, not in DecisionVault decision logic. All 13 adaptive
checks passed, but the helper hit CockroachDB SQLSTATE `40001` while deleting the
test prefix concurrently with production activity.

The helper now:

- deletes authoritative L1 first;
- retries the entire cleanup transaction on CockroachDB serialization failures,
  using the same bounded retry primitive as production;
- uses up to five attempts.

The first successful rerun also exposed an audit weakness: it verified only its
new random run prefix, so 74 rows left by the previously aborted run were still
present globally even though the new run reported `temporary_rows=0`. A global
classification query showed that **all 74 / 74 rows** belonged to the reserved
`adaptive-cloud-*` test namespace and no other business namespace contributed a
row.

The smoke now treats `adaptive-cloud-*` as a reserved test namespace: it removes
stale rows from that namespace before starting a new run and verifies the entire
namespace is empty at the end, not merely the current UUID prefix. This makes an
interrupted prior smoke self-healing on the next invocation.

Rerun result:

```text
adaptive_cloud_checks=13/13
adaptive_cloud_cleanup=PASS
adaptive_cloud_temporary_rows=0
exit=0
```

Final global database audit after the namespace-hardened rerun:

```text
decision_episodes=0
decision_memory_heads=0
decision_memory_revocations=0
decision_memory_consolidation_candidates=0
decision_strategy_effectiveness=0
decision_governed_memories=0
decision_governed_memory_support=0
decision_memory_consolidation_outbox=0
business_memory_rows_total=0

quality_decisions=2
quality_outcomes=2
calibration_runs=3
```

The final semantic benchmark on the deployed cleanup-race source also remained:

```text
14 / 14 PASS
```

## Final result

DecisionVault now has real external-side-effect evidence without confusing
transport success with business success, plus a sustained hosted stability test
that actually found and eliminated a cleanup/consolidation race. The production
external provider remains intentionally disabled until a dedicated
least-privilege GitHub credential is available; this is a credential-activation
boundary, not an unimplemented execution-contract boundary.
