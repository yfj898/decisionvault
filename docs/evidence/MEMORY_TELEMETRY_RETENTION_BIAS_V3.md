# Memory Telemetry Retention / Aging / Sampling-Bias v3

Status: **PRODUCTION PASS / CHAMPION UNCHANGED**

This pass hardens the long-running memory-quality calibration loop against a
failure mode that a simple `N >= 30` gate cannot detect: a 90-day sample can be
large while still being dominated by one scope level, one strategy, only fresh
memories, or only the requests that happened to receive a verified outcome.

The calibration revision for this policy is `telemetry-calibration-v3`. No
production threshold is changed by this revision.

## Retention policy

Raw decision/outcome telemetry is bounded to **180 days**. The live calibration
window remains **90 days**, so retention keeps the active 90-day window plus a
second prior window for drift/comparison work without allowing raw join-key
telemetry to grow indefinitely.

Aggregate calibration runs are retained for **730 days**. They contain only
low-cardinality counts, threshold-shadow summaries, distribution audits, and
recommendations; they do not contain raw scope IDs, agents, situations,
episodes, memory IDs, decision snapshot IDs, or execution receipt IDs.

Retention authority remains separated from request authority:

- `decisionvault_runtime`: `SELECT + INSERT` on decision, outcome, and
  calibration telemetry; no `UPDATE` or `DELETE`;
- `decisionvault_consolidator`: `SELECT + DELETE` for bounded retention;
- retention deletes outcome rows first using the parent decision's
  `decided_at` cutoff, then deletes the decision rows, avoiding orphaned
  outcome rows;
- retention runs before the daily calibration write, so a retention failure
  does not advance the durable 24-hour calibration throttle and is retried by
  the existing scheduled path.

Production v10 migration:

```text
memory_quality_sampling_v10_statements=3
memory_quality_sampling_v10_apply=PASS
```

Production grants after migration:

```text
decisionvault_runtime / decisions        = INSERT,SELECT
decisionvault_runtime / outcomes         = INSERT,SELECT
decisionvault_runtime / calibration_runs = INSERT,SELECT

decisionvault_consolidator / decisions        = DELETE,SELECT
decisionvault_consolidator / outcomes         = DELETE,SELECT
decisionvault_consolidator / calibration_runs = DELETE,SELECT
```

A production retention smoke with no expired rows returned:

```text
calibration_runs=0
decisions=0
outcomes=0
```

## Sampling-bias gate

The sampling audit is persisted inside each append-only calibration run as
aggregate `sampling_audit` JSON plus `sampling_gate_pass`.

Promotion requires all of the following in addition to the existing threshold
quality gates:

- at least 80% of memory-exposed decisions have a verified outcome;
- labeled vs all memory-exposed scope/strategy distributions have total
  variation distance no greater than 0.20;
- at least 2 scope levels are represented;
- no scope level contributes more than 80% of observed evidence;
- at least 2 selected strategies are represented;
- no selected strategy contributes more than 80% of observed evidence;
- every represented scope and strategy stratum has at least 5 samples;
- the observed decision evidence spans at least 30 days;
- recent (`<=30d`) and older (`>30d`) evidence each contain at least 5 samples;
- recent-vs-older scope and strategy total-variation distance is at most 0.35;
- every observed threshold sample has a measurable memory-age feature;
- at least 2 memory-age buckets are represented;
- at least 5 observed samples involve memory older than 30 days.

The decision-time memory-age buckets are `0-7d`, `8-30d`, `31-90d`,
`91-180d`, and `181d+`. These are the ages of the memory evidence
used/evaluated at decision time, not the age of the telemetry row itself.

If the raw sample floor is met but the distribution gate is not, the evaluator
returns `INSUFFICIENT_DISTRIBUTION_COVERAGE` and does not produce a challenger
promotion recommendation.

## Per-stratum challenger safety

Overall averages cannot hide localized harm. Every challenger now carries
separate safety summaries for `scope_level`, `selected_strategy`, and
`memory_age_bucket`.

Within every stratum, the challenger must preserve at least 95% of champion
successful outcomes and keep factual harmful rate at or below 5%. A challenger
that looks safe globally but exceeds the harm limit inside one scope, strategy,
or memory-age stratum remains ineligible.

The adversarial unit suite includes a case where global harmful rate is below
5% but harm is concentrated in one scope stratum; promotion is correctly
blocked.

## Current real production distribution

Current retained AGENT_API telemetry is intentionally still tiny:

```text
decision rows=2
outcome rows=2
memory-exposed labeled rows=1
```

The current sample has full label coverage but is not diverse enough:

```text
label_coverage=1.0
scope_counts={'TEAM': 1}
strategy_counts={'REFRESH_PAYMENT_TOKEN': 1}
evidence_span_days=0.0
memory_age_buckets={'0_7d': 1, '8_30d': 0, '31_90d': 0,
                    '91_180d': 0, '181d_plus': 0}
```

Latest production sampling blockers:

```text
scope_coverage
strategy_coverage
evidence_span
memory_age_coverage
temporal_drift_evaluable
temporal_drift
```

The persisted production calibration history remains append-only:

```text
telemetry-calibration-v1: 1 run
telemetry-calibration-v2: 1 run
telemetry-calibration-v3: 1 run
```

Latest v3 result:

```text
observed_samples=1
sampling_gate_pass=False
recommendation=INSUFFICIENT_REAL_TELEMETRY
recommended_profile=None
promotion_status=NO_PROMOTION
automatic_threshold_mutation=False
```

Because the hard sample floor has not been reached, the top-level result remains
`INSUFFICIENT_REAL_TELEMETRY`. Once the sample floor is reached, the new
distribution gate becomes the next mandatory barrier.

## Production regression

Source commit: `d7c815a feat: harden telemetry sampling and retention`.

GitHub CI run `31857083239`: **SUCCESS**.

The Lambda package was built from the exact source commit and its source-file
hashes matched before deployment. Lambda reached `Active / Successful` and the
deployed `CodeSha256` matched the local package.

Hosted readiness after v10 deployment:

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

Hosted behavior remained unchanged:

```text
/demo: HTTP 200 / expected change=True / cross-agent=True / cleaned=True
/governance-demo: HTTP 200 / ABSTAIN / executable=False /
                  CONFLICT_ABSTAIN / cleaned=True
```

Real production semantic benchmark: **14 / 14 PASS**.

Real CockroachDB + NVIDIA adaptive adversarial/concurrency smoke:
**13 / 13 PASS**, cleanup PASS, temporary rows 0.

Final business-memory state is zero across episodes, heads, revocations,
consolidation candidates, strategy effectiveness, governed memories, support,
and consolidation outbox. The privacy-bounded raw telemetry and aggregate
calibration history remain persisted by design.

## Result

The 90-day threshold evaluator is no longer allowed to treat sample count as a
proxy for representativeness. Threshold promotion now requires enough evidence,
enough time, enough memory aging, balanced scope/strategy coverage, acceptable
label-selection bias, stable recent-vs-older distributions, and per-stratum
safety. The production champion remains unchanged until all gates pass.
