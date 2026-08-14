# Performance, Cost, and Long-Term Memory Quality v1

Status: **LOCAL PASS / REAL COCKROACH+NVIDIA PASS / PRODUCTION DEPLOYMENT PENDING**

## Scope

This pass moves DecisionVault from correctness-only hardening into measurable
runtime efficiency and memory-quality calibration without weakening governance.

The changes are intentionally separated into three concerns:

1. **performance** — remove duplicate work from the L1+L3 production recall path;
2. **cost** — measure provider request units and database connection units per
   memory-on decision instead of inventing unstable dollar pricing;
3. **long-term memory quality** — calibrate post-recall thresholds with a
   safety-weighted adversarial suite while freezing SQL-coupled evidence gates.

## Bundled L1 + L3 recall

Before this pass, one memory-enabled decision independently called
`recall_governed()` and `recall_adaptive()`. With semantic retrieval enabled,
that meant the exact same situation was embedded twice and two CockroachDB read
connections were opened.

Production now exposes `recall_governed_and_adaptive()`:

- one NVIDIA query embedding;
- one CockroachDB connection / read transaction;
- the same four production SQL shapes are still executed:
  - L1 ANN DVI;
  - L1 exact governance coverage;
  - L3 ANN DVI;
  - L3 exact support/current-head governance coverage.

No ANN result becomes authoritative. Exact coverage remains the correctness
boundary for both memory layers.

### Real runtime benchmark

The benchmark used the real production CockroachDB runtime identity and NVIDIA
`nvidia/nv-embedqa-e5-v5` embedding revision `decisionvault-prod-r1`. The scope
was unique and read-only; the benchmark created no memory rows.

Five measured decisions per path:

| Metric | Legacy | Bundled | Change |
| --- | ---: | ---: | ---: |
| NVIDIA query embedding requests / decision | 2.0 | 1.0 | **-50%** |
| CockroachDB connections / decision | 2.0 | 1.0 | **-50%** |
| median memory recall latency | 3161 ms | 1751 ms | **-44.6%** |
| measured provider calls | 10 | 5 | **-50%** |
| measured DB connections | 10 | 5 | **-50%** |

The report is committed as `reports/memory-runtime-benchmark.json`.

This is the cost contract for v1: provider-request and connection reductions are
measured directly. Dollar estimates are deliberately not committed because
provider plans and regional cloud prices can change independently of the code.

## Threshold calibration contract

`scripts/calibrate_memory_quality.py` grid-searches only thresholds that can be
changed without silently disagreeing with the current SQL coverage contract.

The safety-weighted objective penalizes a false influence / missed conflict five
times more heavily than a missed optimization opportunity.

### Episodic L1

Current profile:

- minimum similarity: `0.30`;
- minimum signal: `0.12`;
- conflict margin: `0.08`.

Calibration result: **8/8 → 8/8**. No change is recommended.

### Governed adaptive L3

Baseline profile:

- minimum similarity: `0.40`;
- minimum effective confidence: `0.15`;
- conflict margin: `0.08`.

Baseline result: **6/7**, with one safety failure: a high-initial-confidence
operational memory near the end of its lifetime could still influence execution.

Calibrated profile:

- minimum similarity: `0.40`;
- minimum effective confidence: **`0.30`**;
- conflict margin: `0.08`.

Calibrated result: **7/7 / zero safety failures**.

The production default is now `PRODUCTION_ADAPTIVE_MIN_EFFECTIVE_CONFIDENCE =
0.30`.

## Long-term influence window

Hard expiry and execution influence are intentionally different concepts.
Memory can remain auditable after confidence decay makes it too weak to steer a
decision.

For strong evidence (`effectiveness ~= 0.95`) and the default LONG_TERM class
(`365d` hard expiry), the calibrated threshold produces these approximate
execution-influence windows:

| Scope | Baseline 0.15 | Calibrated 0.30 | Hard expiry |
| --- | ---: | ---: | ---: |
| PRIVATE | ~303 d | **~121 d** | 365 d |
| TEAM | 365 d | **~197 d** | 365 d |
| GLOBAL | 365 d | **~228 d** | 365 d |

This preserves the audit record while preventing old high-confidence knowledge
from retaining execution authority merely because it has not reached hard
expiry yet.

## Thresholds deliberately frozen

This pass does **not** change:

- success effectiveness qualification: `>= 0.7`;
- failed evidence confidence qualification: `>= 0.6`;
- adaptive failed-effectiveness qualification: `<= 0.3`;
- episodic freshness coverage: `90 days`.

Those values exist in both resolver/consolidation semantics and SQL coverage.
Changing them requires a coordinated query/resolver migration plus live
semantic/adversarial regression. The calibration script explicitly records this
guardrail.

## Validation

- local suite after performance + calibration changes: **206 passed**;
- bundled-recall contract: **1 query embedding / 1 connection / 4 original SQL
  queries**;
- real runtime benchmark: **PASS**;
- calibration: L1 **8/8**, L3 **6/7 → 7/7**;
- real adaptive CockroachDB + NVIDIA adversarial/concurrency smoke under L3
  confidence `0.30`: **13/13 PASS**;
- adaptive smoke cleanup: **0 temporary rows**;
- production semantic benchmark after calibration: **14/14 PASS**.

## Remaining gate

Before marking this pass production-complete, deploy the exact committed Lambda
source and rerun hosted readiness, demo/governance regression, and final memory
row cleanup. No schema or secret migration is required for this pass.
