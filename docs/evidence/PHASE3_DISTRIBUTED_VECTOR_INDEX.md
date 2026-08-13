# Phase 3 — CockroachDB Distributed Vector Index Evidence

Date: 2026-08-13

## Gate

Phase 3 is PASS only if the real CockroachDB Cloud cluster demonstrates all of
the following:

1. A vector index exists on the persistent episode table.
2. The index uses `scope_id` as a prefix isolation column.
3. The index uses the cosine opclass required by the application's `<=>` query.
4. `EXPLAIN` shows an actual `vector search` node using that index.
5. Indexed ANN results agree with an exact primary-index baseline on the test set.
6. A better vector match from another scope cannot leak into the scoped result.

## Real Cloud environment

- CockroachDB Cloud server version: `26.2.5`
- `feature.vector_index.enabled`: `true`
- Episode vector column: `VECTOR(64)`
- Vector index: `decision_episodes_scope_embedding_vec_idx`
- Index key: `(scope_id, embedding vector_cosine_ops)`

No database URL, SQL password, Cloud host, service-account secret, or MCP token is
stored in this evidence file.

## Optimizer evidence

The indexed query was:

```sql
SELECT episode_id, strategy, outcome
FROM decision_episodes
WHERE scope_id = $scope
ORDER BY embedding <=> $query_vector::VECTOR
LIMIT 5;
```

`EXPLAIN` selected:

```text
vector search
table: decision_episodes@decision_episodes_scope_embedding_vec_idx
target count: 5
prefix spans: [/<requested scope> - /<requested scope>]
```

The exact comparison query explicitly forced
`decision_episodes@decision_episodes_pkey`. Its plan contained no vector-search
operator and used a full primary-index scan before filtering/ranking.

## ANN correctness and isolation evidence

The reproducible smoke inserted:

- 1 relevant failed memory episode in the requested scope.
- 192 unrelated distractor episodes in that same scope.
- 1 episode in another scope whose situation and vector exactly matched the query.

Observed results:

```text
same_scope_rows=193
ann_top1_distance=0.427922
exact_top1_distance=0.427922
recall_at_5=1.000
ann_top1_is_target=True
exact_top1_is_target=True
foreign_perfect_match_excluded=True
ann_plan_vector_search=True
ann_plan_vector_index=True
exact_plan_vector_search=False
exact_plan_primary_index=True
phase3_vector_index_smoke=PASS
rows_after_cleanup=0
```

This establishes both index usage and causal scope isolation. The foreign-scope
row was a perfect vector match, so excluding it demonstrates that prefix filtering
is not merely incidental to the ranking result.

## Reproduction

With a valid `DATABASE_URL` supplied only through the runtime environment:

```bash
uv run python scripts/vector_index_smoke.py
```

The script reuses the existing index if present, constructs the evaluation rows,
compares ANN and exact top-5 results, checks the two query plans, and deletes all
temporary rows in a `finally` cleanup path.

## Claim boundary

Phase 3 proves CockroachDB Distributed Vector Index creation and indexed retrieval.
The current 64-dimensional vectors are still deterministic Phase 2/3 smoke-test
embeddings. This phase does **not** claim Amazon Bedrock embeddings; that remains a
separate Phase 5 requirement.
