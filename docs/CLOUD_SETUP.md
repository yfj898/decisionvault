# Cloud setup checklist

## CockroachDB Cloud

1. Create a new CockroachDB Cloud cluster.
2. Record the cluster ID.
3. Create the DecisionVault schema using `scripts/bootstrap.sql`.
4. Verify `decision_episodes.embedding` is a `VECTOR` column.
5. Run a real nearest-neighbor query using cosine distance.
6. Capture sanitized evidence for the submission.

### Phase 2 persistence smoke

After placing the real connection string in `DATABASE_URL` (never in Git):

```bash
uv pip install -e ".[dev,cloud]"
uv run python scripts/cloud_memory_smoke.py run --keep
```

For stronger cross-process evidence, reuse the printed scope in separate commands:

```bash
uv run python scripts/cloud_memory_smoke.py seed --scope <scope>
uv run python scripts/cloud_memory_smoke.py recall --scope <scope>
uv run python scripts/cloud_memory_smoke.py cleanup --scope <scope>
```

The `recall` command constructs a fresh store and agent and must report
`REFRESH_PAYMENT_TOKEN` with memory enabled and `GENERIC_RETRY` with memory disabled.

The Phase 2 schema uses `VECTOR(64)` only for the deterministic hashing embedder.
Treat that dimension as migration-ready: the Bedrock integration phase must update
the schema and stored vectors to the selected model's real embedding dimension.

## Distributed Vector Index

Apply the Phase 3 migration after `decision_episodes` exists:

```sql
CREATE VECTOR INDEX decision_episodes_scope_embedding_vec_idx
ON decision_episodes (scope_id, embedding vector_cosine_ops);
```

The prefix column is intentional: DecisionVault always constrains `scope_id` to a
single value before vector ranking. The cosine opclass matches the `<=>` operator
used by `CockroachVectorMemoryStore.recall()`.

Verify both plan selection and result quality with:

```bash
uv run python scripts/vector_index_smoke.py
```

The indexed ANN result is compared with a forced primary-index exact scan. Cloud
evidence is recorded in `docs/evidence/PHASE3_DISTRIBUTED_VECTOR_INDEX.md`.

## Managed MCP Server

Use the Cloud Console MCP configuration for the DecisionVault cluster.

Do not commit:
- service account API key
- bearer token
- database password

Submission evidence should show the MCP server actually inspecting or querying
DecisionVault memory, not merely being configured.

## Amazon Bedrock

The Bedrock adapter is lazy-imported so local deterministic tests need no AWS
dependency.

Minimum real evidence:
- one successful model invocation
- request metadata / AWS logs where available
- the model output enters the untrusted decision layer
- deterministic memory tests remain runnable offline

## AWS deployment

Prefer the smallest deployment that remains testable through judging:

- Lambda + API Gateway for a compact API, or
- ECS for a containerized web demo.

Do not add AWS services only to increase service count.
