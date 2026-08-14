# Memory Quality Telemetry v1 — production evidence

Status: **PRODUCTION PIPELINE PASS / REAL CALIBRATION INSUFFICIENT SAMPLE / OPS VISUALIZATION UPDATE PENDING GOVERNANCE REAUTH**

## Goal

This pass moves memory-quality calibration from synthetic-only grids to a real
decision → verified-outcome telemetry loop without giving telemetry, a model, or
an offline report authority to change production thresholds.

The production champion remains:

- episodic minimum similarity: `0.30`;
- episodic minimum signal: `0.12`;
- episodic conflict margin: `0.08`;
- adaptive minimum similarity: `0.40`;
- adaptive minimum effective confidence: `0.30`;
- adaptive conflict margin: `0.08`.

## Append-only telemetry contract

CockroachDB v8 adds two independent append-only relations:

- `decision_memory_quality_decisions`: one row per signed decision snapshot;
- `decision_memory_quality_outcomes`: one verified execution outcome per
  decision snapshot.

`decisionvault_runtime` receives only `SELECT + INSERT` on both relations. It
has no telemetry `UPDATE` or `DELETE` authority. Decision and outcome rows are
joined by the server-issued `decision_snapshot_id`; the public caller cannot
supply a replacement agent identity or direct outcome fields.

Telemetry is deliberately outside the signed snapshot provenance. This keeps
the existing execution artifact/request-size contract unchanged. A telemetry
write failure is best-effort and cannot change `/decide`, `/execute`, or
`/record`; separate low-cardinality failure metrics make such loss visible.

## Privacy boundary

`quality_features` stores only bounded quality attributes needed for threshold
evaluation, including:

- server-owned scope level, not raw scope ID;
- selected layer (`L1`, `L3`, `BOTH`, `NONE`);
- champion threshold values;
- candidate counts;
- similarity / confidence / memory-age buckets and bounded aggregates;
- nine shadow-policy outcomes.

It does **not** store raw situation text, scope IDs, agent IDs, episode IDs,
memory IDs, receipt IDs, or snapshot IDs inside `quality_features`. Primary-key
snapshot/receipt identifiers exist only in the telemetry table linkage columns.
The committed aggregate calibration report contains no raw identifiers or
context.

## Shadow calibration contract

Historical production telemetry evaluates only monotone-stricter challengers.
The v1 shadow set contains nine profiles spanning:

- episodic similarity `0.35 / 0.40`;
- episodic minimum signal `0.16`;
- episodic conflict margin `0.12`;
- adaptive similarity `0.45 / 0.50`;
- adaptive minimum effective confidence `0.35 / 0.40`;
- adaptive conflict margin `0.12`.

Looser thresholds are intentionally not evaluated from historical telemetry:
production recall has already truncated evidence below the live retrieval
boundary, so those counterfactuals are not identifiable from the stored sample.

If a challenger would choose a **different executable strategy**, its outcome is
marked `COUNTERFACTUAL_UNOBSERVED`. The observed champion result is never
pretended to be the challenger's result.

A profile is recommendation-eligible only when all of the following hold:

1. at least **30 memory-exposed verified outcomes** are available;
2. there are zero executable unobserved counterfactuals for that profile;
3. retained successful outcomes are at least **95%** of champion successes;
4. factual retained harmful-outcome rate is at most **5%**;
5. it does not retain more harmful outcomes than the champion;
6. it actually suppresses at least one observed harmful outcome.

The calibration command is recommendation-only. It has no code path that
mutates Lambda configuration, Secrets Manager, or resolver thresholds.

Pure default-policy requests where L1 and L3 candidate counts are both zero are
excluded from threshold calibration. They are operational outcomes, but they
contain no information about a memory threshold and would otherwise inflate
success retention / dilute harmful rates.

## Production rollout

The v8 migration was applied before the Lambda code cutover. Verified real DB
state after migration:

- decision telemetry table: present;
- outcome telemetry table: present;
- initial rows: `0 / 0`;
- runtime decision telemetry grants: `SELECT + INSERT` only;
- runtime outcome telemetry grants: `SELECT + INSERT` only.

Source rollout commits and CI:

- `86a346c` — `feat: add memory quality telemetry calibration` — CI
  `31804114321` SUCCESS;
- `58cd5bf` — exclude no-memory requests from calibration — CI
  `31804558974` SUCCESS;
- `5c41804` — enforce 95% success-retention / 5% harmful-rate guardrails — CI
  `31805379963` SUCCESS;
- `f63af3a` — isolate production semantic benchmark producers from security
  reconciliation — CI `31806122547` SUCCESS.

The currently deployed Lambda package was built from `f63af3a`. Package source
hash comparison passed for every DecisionVault source file and deployed
`CodeSha256` matched the local ZIP. Lambda reached `Active / Successful`.

Hosted readiness after deployment:

- HTTP `200`;
- `status=ready`;
- `memory_quality_telemetry_schema=True`;
- `consolidation_identity_isolated=True`;
- `consolidation_outbox_schema=True`;
- `memory_scope_control=True`;
- `adaptive_memory_current=True`;
- readiness errors: `0`.

## First real labeled telemetry

A real protected agent flow was executed with the existing planner and observer
grants:

1. first decision had no admissible memory and selected `GENERIC_RETRY`;
2. sandbox execution produced a verified `FAILED / 0.10` outcome and wrote L1;
3. a paraphrased second request recalled that governed outcome and selected
   `REFRESH_PAYMENT_TOKEN` with `memory_influenced=True`;
4. sandbox execution produced a verified `SUCCESS / 0.95` outcome.

Resulting persistent telemetry:

- decision rows: **2**;
- verified outcome rows: **2**;
- joined AGENT_API labeled rows: **2**;
- memory-exposed labeled rows relevant to threshold calibration: **1**;
- shadow evaluations on each decision: **9**.

The first real calibration report therefore correctly returns:

```text
observed_samples=1
recommendation=INSUFFICIENT_REAL_TELEMETRY
recommended_profile=NONE
minimum_samples=30
minimum_success_retention=0.95
maximum_harmful_rate=0.05
```

No threshold was changed. The report is committed at
`reports/memory-telemetry-calibration.json`.

## Production regression and benchmark-race hardening

The first final semantic run exposed a pre-existing production-benchmark race:
one hand-authored benchmark producer was retired by the normal
compromised-producer reconciliation while hosted traffic was running. Direct
NVIDIA E5-v5 verification showed the failed billing seed still had cosine
similarity `0.524528`, above the unchanged `0.40` threshold, and a single-case
Cockroach reproduction recalled it correctly.

The fix does **not** disable security reconciliation. The semantic harness maps
its descriptive producers onto six explicit server-owned benchmark producer
IDs. Public agent routes still cannot supply `agent_id`.

After deploying that fix, the production semantic benchmark was deliberately
run concurrently with repeated POST requests that trigger runtime security
reconciliation. Final result:

- production semantic benchmark: **14 / 14 PASS**;
- successful billing case: `VERIFY_BILLING_PROFILE`, similarity `0.5245`;
- conflict/crowding controls: PASS.

Additional real gates after telemetry rollout:

- adaptive CockroachDB + NVIDIA adversarial/concurrency smoke: **13 / 13 PASS**;
- adaptive temporary rows after smoke: **0**;
- hosted `/demo`: HTTP `200`, expected memory change=True, cross-agent=True,
  cleaned=True;
- hosted `/governance-demo`: HTTP `200`, `ABSTAIN`, executable=False,
  `CONFLICT_ABSTAIN`, cleaned=True.

Final business-memory state:

```text
decision_episodes=0
decision_memory_heads=0
decision_memory_revocations=0
decision_memory_consolidation_candidates=0
decision_strategy_effectiveness=0
decision_governed_memories=0
decision_governed_memory_support=0
decision_memory_consolidation_outbox=0
```

The telemetry rows are intentionally retained (`2` decisions / `2` outcomes)
so real evidence can accumulate over time.

## Operations state

The application now emits low-cardinality metrics for telemetry decisions,
outcomes, and decision/outcome telemetry write failures. The operations script
also defines a combined telemetry-write-failure alarm and a memory-quality
telemetry dashboard panel.

The existing restricted deployer correctly cannot update EventBridge/CloudWatch
operations resources. The previously authorized governance console-login
session has now expired, so the **new alarm/dashboard provisioning is pending a
fresh governance login**. Existing v7 EventBridge retry and memory-health
operations remain in place; this pending visualization update does not block
telemetry persistence or calibration.

## Next real calibration gate

Keep the current champion thresholds until at least 30 memory-exposed verified
outcomes have accumulated. At that point rerun:

```bash
python scripts/calibrate_memory_telemetry.py \
  --database-url-file /path/to/admin-database-url \
  --ca-file /path/to/cockroach-cloud-root.crt \
  --minimum-samples 30
```

Even when a challenger becomes eligible, promotion remains a separate human / CI
change with the full semantic, adaptive, readiness, and hosted governance gates.
