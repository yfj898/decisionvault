# Phase 8 — Memory Benchmark / Ablation Evidence

Status: **PASS**

Date: 2026-08-13

## Question

Does persistent decision memory systematically change DecisionVault behavior in
the intended direction compared with the same agent running with memory disabled?

This benchmark measures **behavioral target accuracy**. It does not claim a real
payment, billing, or customer-support success rate because no downstream business
system is executed in this benchmark.

## Experimental design

Every benchmark case runs the same policy twice:

1. **Memory ON** — recall is enabled.
2. **Memory OFF** — the same memory store exists, but recall is disabled.

The Memory OFF agent therefore provides a causal control for the memory layer
rather than a different policy or model.

Seven families are included.

### Benefit families

1. `failed_generic_adaptation`
   - prior strategy: `GENERIC_RETRY`;
   - prior outcome: `FAILED`;
   - expected Memory ON behavior: avoid the failed retry and choose
     `REFRESH_PAYMENT_TOKEN`.
2. `successful_refresh_reuse`
   - prior strategy: `REFRESH_PAYMENT_TOKEN`;
   - prior outcome: high-effectiveness `SUCCESS`;
   - expected Memory ON behavior: reuse the successful strategy.
3. `successful_billing_reuse`
   - prior strategy: `VERIFY_BILLING_PROFILE`;
   - prior outcome: high-effectiveness `SUCCESS`;
   - expected Memory ON behavior: reuse the successful strategy.

### Control families

4. `low_confidence_failure_control`
   - a failed retry exists, but confidence is below the policy threshold;
   - expected: memory must not influence the decision.
5. `low_effectiveness_success_control`
   - a successful episode exists, but effectiveness is below the reuse threshold;
   - expected: memory must not influence the decision.
6. `cross_scope_isolation_control`
   - a perfect memory match exists in a different `scope_id`;
   - expected: no cross-scope influence.
7. `irrelevant_memory_control`
   - a high-quality but unrelated successful episode exists in the same scope;
   - expected: no influence.

## Metrics

- **Benefit target accuracy** — fraction of benefit cases where the selected
  strategy and `memory_influenced` flag match the expected memory-aware behavior.
- **Failed retry repetition rate** — fraction of failed-generic cases that still
  select `GENERIC_RETRY`.
- **Successful strategy reuse rate** — fraction of high-quality success cases
  that reuse the successful strategy.
- **Control preservation rate** — fraction of control cases that remain on the
  safe default without memory influence.
- **False influence rate** — fraction of control cases where memory incorrectly
  changes behavior.
- **Cross-scope leakage rate** — fraction of isolation cases where foreign-scope
  memory influences the decision.
- **Advisor strategy invariance** — fraction of representative cases where adding
  the real NVIDIA explanation-only advisor leaves the committed strategy exactly
  unchanged.

## Run A — deterministic local benchmark

Configuration:

- backend: `InMemoryEpisodeStore`;
- variants per family: 8;
- total cases: 56.

Result:

```text
total_cases=56
passed_cases=56
overall_accuracy_on=1.0000
overall_accuracy_off=0.5714
benefit_target_accuracy_on=1.0000
benefit_target_accuracy_off=0.0000
control_preservation_rate_on=1.0000
failed_retry_repetition_rate_on=0.0000
failed_retry_repetition_rate_off=1.0000
successful_strategy_reuse_rate_on=1.0000
successful_strategy_reuse_rate_off=0.0000
cross_scope_leakage_rate_on=0.0000
false_influence_rate_on=0.0000
phase8_benchmark=PASS
```

Sanitized machine-readable report: `reports/phase8-local.json`.

## Run B — real CockroachDB Cloud benchmark

Configuration:

- backend: real `CockroachVectorMemoryStore`;
- storage: the competition CockroachDB Cloud `decision_episodes` table;
- retrieval: the same scoped vector recall path used by the hosted application;
- variants per family: 4;
- total cases: 28.

Result:

```text
total_cases=28
passed_cases=28
overall_accuracy_on=1.0000
overall_accuracy_off=0.5714
benefit_target_accuracy_on=1.0000
benefit_target_accuracy_off=0.0000
control_preservation_rate_on=1.0000
failed_retry_repetition_rate_on=0.0000
failed_retry_repetition_rate_off=1.0000
successful_strategy_reuse_rate_on=1.0000
successful_strategy_reuse_rate_off=0.0000
cross_scope_leakage_rate_on=0.0000
false_influence_rate_on=0.0000
phase8_benchmark=PASS
cloud_rows_after_cleanup=0
```

Sanitized machine-readable report: `reports/phase8-cloud.json`.

## Run C — real NVIDIA advisor ablation on CockroachDB Cloud

One representative case from each benchmark family was rerun with the real
NVIDIA explanation-only advisor enabled.

Configuration:

- backend: CockroachDB Cloud;
- advisor: `meta/llama-3.1-8b-instruct` through NVIDIA API;
- cases: 7.

Result:

```text
total_cases=7
passed_cases=7
advisor_strategy_invariance_rate=1.0000
benefit_target_accuracy_on=1.0000
control_preservation_rate_on=1.0000
false_influence_rate_on=0.0000
cross_scope_leakage_rate_on=0.0000
cloud_rows_after_cleanup=0
```

The advisor produced explanatory text but did not change a single committed
strategy.

Sanitized machine-readable report:
`reports/phase8-cloud-nvidia-ablation.json`.

## Causal interpretation

The most direct comparison is the benefit subset:

```text
Memory ON target accuracy   100%
Memory OFF target accuracy    0%
```

For previously failed generic retries:

```text
Memory ON repeats failed retry     0%
Memory OFF repeats failed retry  100%
```

For prior successful strategies:

```text
Memory ON reuses success   100%
Memory OFF reuses success    0%
```

At the same time, the control families show no safety regression:

```text
control preservation       100%
false influence              0%
cross-scope leakage           0%
```

This supports the narrow DecisionVault claim: persisted outcome memory changes
future decision behavior when evidence is sufficiently relevant and trustworthy,
while weak, irrelevant, or foreign-scope memories do not change the decision.

## Limitations

- The benchmark is a controlled policy benchmark, not a production business
  outcome trial.
- The current 64-dimensional deterministic hashing embedder is used so the memory
  effect remains reproducible and independent of model-provider availability.
- The scenario families intentionally exercise the documented policy boundaries;
  they should not be represented as an open-domain generalization benchmark.
- The NVIDIA ablation tests strategy invariance, not answer quality scoring.

These limits are intentional. Phase 8 is evidence for the memory-aware behavioral
contract, not evidence that every future task or embedding model will produce the
same metrics.

## Secret handling

The committed benchmark reports contain no database URL, SQL password, NVIDIA
API key, AWS credential, CockroachDB Cloud API key, cluster ID, Function URL
hostname, or demo token.
