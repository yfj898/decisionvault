# Memory Calibration Loop V2 — Production Evidence

Status: **PRODUCTION PASS / CHAMPION UNCHANGED**

This phase turns the initial real memory-quality telemetry pipeline into a
durable calibration-review loop. It does **not** grant telemetry, a model, or a
scheduled worker authority to change production thresholds.

## Authority boundary

The loop is deliberately one-way:

```text
governed decision
→ append decision telemetry
→ verified execution outcome
→ append outcome telemetry
→ aggregate champion/challenger evaluation
→ append calibration run
→ promotion-review artifact
→ human/source-code/CI change only
```

There is no path from a calibration run back into the live resolver. Production
thresholds remain source-controlled constants and require the normal semantic,
adaptive, hosted, and CI gates to change.

## V9 aggregate calibration schema

Production migration:

```text
memory_quality_calibration_v9_statements=4
memory_quality_calibration_v9_apply=PASS
```

New table: `decision_memory_quality_calibration_runs`.

The table contains only aggregate evaluation state: source/revision, lookback
and gates, sample counts, champion success/harm counts, recommendation,
optional challenger profile, challenger aggregate statistics, and generation
time. It contains no scope ID, agent ID, producer ID, situation text, episode
ID, memory ID, decision snapshot ID, execution receipt ID, model text, token, or
credential material.

Production CockroachDB grants were verified as:

```text
decisionvault_runtime      = INSERT, SELECT
decisionvault_consolidator = SELECT
```

Runtime therefore cannot update or delete historical calibration runs.

## Durable 24-hour evaluation cadence

No second EventBridge rule is required. The existing production consolidation
retry Scheduled Event remains the scheduler. The deployed handler keeps the
existing consolidation result contract and additionally performs a durable
calibration due-check.

Default interval:

```text
MEMORY_QUALITY_CALIBRATION_INTERVAL_HOURS=24
```

If the newest persisted `AGENT_API` run is younger than the interval, the
worker returns `NOT_DUE` without writing a row. If due, it evaluates current
telemetry and appends a new immutable aggregate run.

A production-runtime due-check against the real v9 table returned:

```text
production_due_check=PASS
calibration_status=NOT_DUE
calibration_interval_hours=24
```

The existing EventBridge resource was not modified in this phase. Its prior v7
production evidence records it as enabled at `rate(5 minutes)` with one Lambda
target. The restricted deployer intentionally has neither EventBridge write nor
read authority, so this phase does not widen that IAM identity simply to
re-prove an unchanged resource.

## First persisted calibration run

The evaluator was executed with the real production **runtime** CockroachDB
identity, not the migration-admin identity.

```text
persisted_calibration_run=PASS
source=AGENT_API
decision_rows=2
labeled_outcomes=2
observed_samples=1
recommendation=INSUFFICIENT_REAL_TELEMETRY
recommended_profile=NONE
```

The promotion-review artifact correctly returns:

```text
promotion_status=NO_PROMOTION
automatic_threshold_mutation=False
observed_samples=1
minimum_samples=30
minimum_success_retention=0.95
maximum_harmful_rate=0.05
```

The aggregate review is committed at
`reports/memory-calibration-promotion-review.json`.

## Promotion-review contract

`scripts/review_memory_calibration.py` reads only the newest aggregate run and
renders `NO_CALIBRATION_RUN`, `NO_PROMOTION`, or `REVIEW_REQUIRED`.

Even `REVIEW_REQUIRED` is not deployment authority. The artifact requires:

1. human review of the persisted recommendation;
2. explicit source-code threshold change;
3. full local test suite;
4. production semantic benchmark 14/14;
5. adaptive adversarial/concurrency smoke 13/13;
6. hosted readiness HTTP 200;
7. hosted demo/governance regression;
8. GitHub CI success.

## Production deployment

Source commit:

```text
309ab37 feat: automate memory calibration review loop
```

GitHub Actions:

```text
31808893606 SUCCESS
```

The Lambda package was built from that clean commit. All packaged
`src/decisionvault/*.py` files were hash-compared with repository source.

```text
package_exact_source=PASS
Lambda State=Active
LastUpdateStatus=Successful
CodeSha256=matched
```

Hosted readiness after deployment:

```text
HTTP 200
status=ready
memory_quality_telemetry_schema=True
memory_quality_calibration_schema=True
memory_quality_calibration_config=True
consolidation_identity_isolated=True
adaptive_memory_current=True
errors=0
```

## Production decision regressions

Production semantic benchmark, with a live hosted POST concurrently triggering
security reconciliation:

```text
14 / 14 PASS
```

Real CockroachDB + NVIDIA adaptive adversarial/concurrency smoke:

```text
13 / 13 PASS
adaptive_cloud_cleanup=PASS
adaptive_cloud_temporary_rows=0
```

Hosted demo:

```text
HTTP 200
expected_change=True
cross_agent_memory=True
cleaned=True
```

Hosted governance demo:

```text
HTTP 200
action=ABSTAIN
executable=False
memory_resolution=CONFLICT_ABSTAIN
cleaned=True
```

## Final production state

Business memory is clean:

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

Long-lived quality evidence remains intentionally persisted:

```text
quality_decisions=2
quality_outcomes=2
calibration_runs=1
latest_observed_samples=1
latest_recommendation=INSUFFICIENT_REAL_TELEMETRY
latest_recommended_profile=None
latest_minimum_samples=30
latest_success_retention=0.95
latest_max_harmful_rate=0.05
```

## Operations metrics

The Lambda now emits fixed-name low-cardinality metrics for calibration runs,
observed sample coverage, recommendations, and calibration failures. The
operations configuration source also defines a calibration-failure alarm and
dashboard series.

The restricted deployer cannot provision CloudWatch/EventBridge operations
resources. The additional dashboard/alarm visualization therefore still needs
a future governance-authenticated operations refresh. This does **not** block
the calibration loop because cadence piggybacks on the already-existing
production consolidation Scheduled Event and CockroachDB state is the durable
24-hour throttle.

## Current decision

**Keep the champion.** Real memory-exposed verified outcomes remain `1 / 30`.
Future evidence can now accumulate and be evaluated automatically, but no
promotion can be recommended before the real-data floor and all safety and
retention constraints are satisfied.
