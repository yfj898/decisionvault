# Cloud setup checklist

## CockroachDB Cloud

1. Create a new CockroachDB Cloud cluster.
2. Record the cluster ID.
3. Create the DecisionVault schema using `scripts/bootstrap.sql`.
4. Verify the deterministic regression column
   `decision_episodes.embedding VECTOR(64)`.
5. Apply `scripts/semantic_memory.sql` and verify
   `decision_memory_heads.semantic_embedding VECTOR(1024)` plus the semantic DVI.
6. Run real cosine nearest-neighbor queries on both the historical regression
   path and the production semantic path.
7. Capture sanitized evidence for the submission.

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
That column remains intentionally frozen as regression evidence. Hosted semantic
retrieval uses the separate native NVIDIA E5-v5 1024D schema applied by
`scripts/semantic_memory.sql`; production does not project E5-v5 into 64D.

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

The current production semantic index is:

```sql
CREATE VECTOR INDEX decision_memory_heads_scope_space_semantic_vec_idx
ON decision_memory_heads (
  scope_id,
  semantic_embedding_space,
  semantic_embedding vector_cosine_ops
);
```

`decision_memory_heads` contains one current row per
`(scope_id, producer_agent_id, strategy)` so repeated writes from one producer do
not crowd independent evidence out of ANN top-K. Immutable history remains in
`decision_episodes`.

## Managed MCP Server

Use the Cloud Console MCP configuration for the DecisionVault cluster.

Phase 4 was verified with OAuth against the real CockroachDB Cloud Managed MCP
endpoint. The successful evidence path used the MCP 2025-06-18 Streamable HTTP
protocol and executed `list_clusters`, `get_cluster`, `list_databases`,
`list_tables`, `get_table_schema`, `select_query`, and `explain_query`.

The evidence demonstrates that MCP can inspect the live DecisionVault schema,
read an actual persisted decision episode, and obtain the vector-search query
plan. See `docs/evidence/PHASE4_MANAGED_MCP.md`.

Do not commit:
- service account API key
- bearer token
- database password

Submission evidence should show the MCP server actually inspecting or querying
DecisionVault memory, not merely being configured.

## Optional Amazon Bedrock provider seam

Bedrock is **not** part of the frozen competition claim or judge path. The
adapter remains lazy-imported as an optional provider seam. The actual verified
competition model path uses NVIDIA for semantic embeddings and bounded
explanation, while the AWS requirement is satisfied by the Lambda deployment.

Optional experimental smoke only:

```bash
export AWS_BEARER_TOKEN_BEDROCK="<Bedrock API key>"
uv run python scripts/model_advisor_smoke.py bedrock --cloud-memory
```

Never treat this optional command as submission evidence unless a real successful
Bedrock invocation is captured separately. Never commit AWS credentials.

The non-authoritative model boundary is already verified with NVIDIA: the memory
policy commits strategy before the explanation provider is called.

## AWS deployment

The frozen deployment is an AWS Lambda Python 3.12 function in
`ap-northeast-1` using a Lambda Function URL. `GET /` and `/health` are public;
the two atomic judge demos use `X-DecisionVault-Token`; general `/record` and
`/decide` use `X-DecisionVault-Agent-Token` with server-side digest grants that
bind identity, scope prefixes, permissions, and trust.

Raw demo/agent tokens, database credentials, and NVIDIA keys must remain outside
Git. See `.env.example` and `docs/AWS_LAMBDA_DEPLOY.md` for configuration names.
