# DecisionVault Retrieval Ablation V2

## Goal

Measure whether a fixed semantic Top-K can hide governance-relevant evidence, and
separate the value of current-head deduplication from the production dual-stage
retrieval design.

This is a **controlled deterministic candidate-pressure benchmark**. It does not
call NVIDIA or claim hosted semantic-model quality. Similarity scores are fixed so
the experiment isolates retrieval-stage correctness and candidate crowding.

## Compared retrieval modes

1. `raw_top_k` — scope-filtered raw episodes ranked by similarity, truncated to K,
   then sent to the existing governance resolver.
2. `current_head_top_k` — current producer/strategy heads (including explicit
   supersession cleanup) ranked by similarity and truncated to K.
3. `dual_stage` — current-head Top-K fast path plus exact
   similarity-threshold governance coverage, merged before the existing resolver.

`dual_stage` models the current production architecture. It intentionally leaves
lifecycle/outcome predicates out of the ANN fast path because CockroachDB DVI may
stop being used when those predicates are pushed into the vector query. Exact
coverage carries the correctness contract beyond fixed K.

## Matrix

- scenario families: duplicate crowding, stale/revoked crowding, distinct-head
  conflict crowding, supersession crowding, low-quality crowding, cross-scope
  control;
- crowding pressure: `0, 4, 12, 40`;
- ANN K: `5, 10, 32`;
- scenarios: **24**;
- retrieval-mode runs: **216**;
- semantic qualification threshold: **0.40**.

Reproduce:

```bash
.venv/bin/python scripts/run_retrieval_ablation.py --format markdown
```

## Results

| Retrieval mode | Decision accuracy vs exact oracle | Qualified Recall@K | Governed evidence coverage | Missed-conflict rate | Invalid-candidate decision-change rate |
|---|---:|---:|---:|---:|---:|
| `raw_top_k` | 0.681 | 0.646 | 0.646 | 0.083 | 0.319 |
| `current_head_top_k` | 0.694 | 0.701 | 0.701 | 0.083 | 0.306 |
| `dual_stage` | **1.000** | 0.701 | **1.000** | **0.000** | **0.000** |

### Metric definitions

- **Qualified Recall@K** — fraction of exact-governance-qualified top-K evidence
  also present in the ANN/top-K fast-path candidate set.
- **Governed evidence coverage** — fraction of all exact-governance-qualified
  evidence available to the resolver after retrieval/merge.
- **Missed-conflict rate** — exact coverage requires conflict abstention but the
  tested retrieval mode does not surface enough evidence to abstain.
- **Invalid-candidate decision-change rate** — a retrieval mode disagrees with the
  exact-coverage oracle while its bounded ANN budget contains candidates excluded
  by exact governance coverage.

## Interpretation

Current-head deduplication improves the fast path, but it does not make a fixed K
a correctness boundary. Distinct stale/revoked/unknown/weak heads can still occupy
the ANN budget, and independent contradictory evidence can rank beyond K.

The important production result is therefore **not** that ANN Recall@K becomes
perfect. The result is that the production merge restores **100% governed evidence
coverage and 100% oracle-aligned decisions across this 216-run stress matrix while
keeping ANN Top-K as the performance fast path**.

## Resume-safe claim

> Built a 216-run retrieval ablation across K={5,10,32} and candidate-crowding
> stressors; raw/current-head bounded Top-K reached 68.1%/69.4% oracle-aligned
> decisions, while the production ANN + exact-governance-coverage path reached
> 100% decision accuracy and 0 missed-conflict rate in this controlled benchmark.

Do not describe these numbers as production traffic prevalence or NVIDIA embedding
quality; they are controlled retrieval-pipeline evidence.
