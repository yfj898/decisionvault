# DecisionVault

**Persistent decision memory for autonomous agents.**

DecisionVault is a new project for the **CockroachDB × AWS Hackathon — Build with Agentic Memory**.

The core claim is deliberately narrow and testable:

> An agent should remember not only what happened, but which strategy it used, whether it worked, and how that evidence should change the next decision.

## Frozen MVP

The first vertical slice demonstrates:

1. Session A encounters a payment-support case.
2. With no relevant memory, the agent chooses a generic retry strategy.
3. The strategy fails and the episode is persisted.
4. Session B encounters a semantically similar case.
5. The agent recalls the failed strategy and selects a different recovery strategy.
6. A memory-disabled baseline repeats the inferior strategy.

The local implementation is deterministic so the memory effect is testable before cloud credentials are connected.

## Competition architecture

```text
Judge / user
   |
   v
AWS Lambda Function URL + DecisionVault UI
   |
   v
CockroachDB Cloud persistent memory
   +----> Distributed Vector Index recall
   +----> Managed MCP evidence path
   |
   v
Outcome-aware deterministic policy
   |
   +----> NVIDIA explanation-only advisor
   |
   v
Strategy + grounded explanation
```

Verified competition integrations:

- CockroachDB Distributed Vector Indexing
- CockroachDB Cloud Managed MCP Server
- NVIDIA live bounded model advisor
- AWS Lambda deployment

## Live demo

Public UI:

https://mfcr7b2k3j7lrwr44u35i5rchq0fbncb.lambda-url.ap-northeast-1.on.aws/

The page contains no credentials. A judge/demo token is supplied separately to
run the protected live causal proof.

## Run local vertical slice

```bash
python -m pytest
python -m decisionvault.demo
```

The local store is a competition-safe development fallback only. The submission version must prove the same behavior with CockroachDB Cloud.

## Phase 2 — CockroachDB Cloud persistence

Install the cloud extra and provide the CockroachDB Cloud connection string only
through the environment:

```bash
uv pip install -e ".[dev,cloud]"
export DATABASE_URL="<CockroachDB Cloud connection string>"
uv run python scripts/cloud_memory_smoke.py run
```

The smoke test bootstraps the schema, writes a failed decision episode, creates a
fresh store/agent, recalls that persisted episode, verifies that Memory ON changes
the strategy, and verifies that Memory OFF still repeats the default strategy.
It removes the smoke scope unless `--keep` is supplied.

Phase 2 intentionally uses a deterministic dependency-free hashing embedding so
database persistence can be tested independently from model availability. It is
**not** a model-embedding claim; the Bedrock embedding provider belongs to a later
phase.

## Phase 3 — Distributed Vector Index

DecisionVault now uses a real CockroachDB Distributed Vector Index whose prefix
column matches the memory isolation boundary and whose opclass matches the cosine
distance operator used by the recall adapter:

```sql
CREATE VECTOR INDEX decision_episodes_scope_embedding_vec_idx
ON decision_episodes (scope_id, embedding vector_cosine_ops);
```

Reproduce the Cloud verification after setting `DATABASE_URL` locally:

```bash
uv run python scripts/vector_index_smoke.py
```

The smoke creates one relevant failed episode, 192 same-scope distractors, and a
perfect vector match in a different scope. It compares the indexed ANN top-5 with
a primary-index exact scan, verifies the optimizer emits a `vector search` node,
checks scope isolation, and removes all smoke rows afterward.

Verified Cloud result: ANN and exact search selected the same top-1 episode,
`recall@5` was `1.000`, and the perfect match from the foreign scope was excluded.
See `docs/evidence/PHASE3_DISTRIBUTED_VECTOR_INDEX.md`.

## Phase 5 — Bounded model advisor

DecisionVault keeps model output outside the strategy authority boundary. The
agent first recalls CockroachDB memory and commits the deterministic strategy;
an optional model advisor can only add a grounded explanation afterward. A
provider failure is ignored and cannot change or block the committed strategy.

The verified competition model path uses NVIDIA as an explanation-only provider.
Amazon Bedrock remains an optional provider rather than a Phase 5 gate. The AWS
competition requirement is satisfied separately by the Phase 6 Lambda deployment.

```bash
AWS_BEARER_TOKEN_BEDROCK="<local secret>" \
uv run python scripts/model_advisor_smoke.py bedrock --cloud-memory
```

The NVIDIA provider was verified live against the same bounded advisor contract
and real CockroachDB memory. Model output still cannot select or change strategy.

See `docs/evidence/PHASE5_BOUNDED_MODEL_INTEGRATION.md`.

## Phase 6 — AWS Lambda deployment

DecisionVault is deployed as an AWS Lambda Python 3.12 function in
`ap-northeast-1` with a Lambda Function URL. `GET /health` is public for
availability checks. Production POST routes require an
`X-DecisionVault-Token` value configured only in the Lambda environment.

The live deployment proved the full hosted causal path:

```text
AWS Lambda /record
→ CockroachDB Cloud persistent episode
→ AWS Lambda /decide
→ CockroachDB vector recall
→ deterministic strategy change
→ NVIDIA bounded explanation
```

The live Memory ON call returned `REFRESH_PAYMENT_TOKEN` with
`memory_influenced=true`; the Memory OFF control returned `GENERIC_RETRY` with
`memory_influenced=false`. The temporary evidence scope was deleted afterward.
See `docs/evidence/PHASE6_AWS_LAMBDA.md`.

## Phase 7 — UI / production hardening

The same AWS Lambda Function URL now serves a responsive judge-facing UI at `/`.
The page contains no database/model credentials and asks for the demo token only
when the user runs the protected live proof.

`POST /demo` performs one atomic causal experiment:

```text
temporary failed GENERIC_RETRY episode
→ Memory OFF on the same similar situation
→ Memory ON on the same similar situation
→ compare strategies
→ delete temporary scope
```

The deployed run returned `GENERIC_RETRY` with Memory OFF and
`REFRESH_PAYMENT_TOKEN` with Memory ON, with one recalled episode and a bounded
NVIDIA explanation. The temporary Phase 7 scope was independently verified as
fully cleaned afterward.

Hardening verified online includes protected POST routes, `401` for a missing
demo token, CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and
`Cache-Control: no-store`. Headless Chrome DOM smoke passed at desktop and mobile
viewport sizes. See `docs/evidence/PHASE7_UI_PRODUCTION_HARDENING.md`.

## Phase 8 — Memory benchmark and ablation

DecisionVault now includes a reproducible behavioral benchmark that compares the
same cases with Memory ON and Memory OFF. The benchmark deliberately measures
**decision behavior**, not simulated business success. Its target is whether the
agent correctly uses outcome memory when evidence is strong and correctly ignores
memory when evidence is weak, irrelevant, or belongs to another scope.

Seven benchmark families cover failed `GENERIC_RETRY` avoidance, successful
`REFRESH_PAYMENT_TOKEN` reuse, successful `VERIFY_BILLING_PROFILE` reuse,
low-confidence failures, low-effectiveness successes, cross-scope isolation, and
irrelevant-memory controls.

Verified results:

```text
Local deterministic benchmark:        56 / 56 PASS
CockroachDB Cloud benchmark:           28 / 28 PASS
Cloud + NVIDIA advisor ablation:        7 /  7 PASS

Benefit target accuracy, Memory ON:    100%
Benefit target accuracy, Memory OFF:     0%
Failed retry repetition, Memory ON:      0%
Failed retry repetition, Memory OFF:   100%
Successful strategy reuse, Memory ON:  100%
Successful strategy reuse, Memory OFF:   0%
Control preservation, Memory ON:       100%
False influence rate, Memory ON:         0%
Cross-scope leakage rate, Memory ON:     0%
NVIDIA advisor strategy invariance:    100%
```

The Cloud benchmark uses the same CockroachDB `decision_episodes` table and
vector recall path as the hosted application. All Phase 8 Cloud rows are deleted
after each run; the final residual-row check is zero.

Reproduce locally:

```bash
python scripts/benchmark_memory.py \
  --backend local \
  --variants 8 \
  --output reports/phase8-local.json
```

Cloud and advisor runs require their normal runtime credentials and do not store
secrets in the reports. See `docs/evidence/PHASE8_MEMORY_ABLATION.md`.

## Phase 4 — CockroachDB Cloud Managed MCP

DecisionVault has also been verified through the real CockroachDB Cloud Managed
MCP server using OAuth. A standards-compliant MCP 2025-06-18 client initialized
`https://cockroachlabs.cloud/mcp`, discovered the server tools, and performed
read-only calls against the same DecisionVault cluster.

Verified MCP calls include:

- `list_clusters` and `get_cluster`
- `list_databases` and `list_tables`
- `get_table_schema` for `decision_episodes`
- `select_query` for a real persisted DecisionVault episode
- `explain_query` for the scoped vector nearest-neighbor query

The MCP schema result exposed the `VECTOR(64)` column, the real distributed
vector index, and its cosine opclass. The MCP SELECT returned the expected failed
`GENERIC_RETRY` episode, and the MCP EXPLAIN contained both the vector-search node
and the DecisionVault vector index. The temporary evidence row was removed after
verification.

No OAuth token, SQL password, connection string, or cluster ID is stored in this
repository. See `docs/evidence/PHASE4_MANAGED_MCP.md`.

## Repository status

- [x] New project / isolated codebase
- [x] Frozen MVP
- [x] Deterministic memory-aware vertical slice
- [x] Memory-disabled baseline
- [x] CockroachDB vector schema bootstrap
- [x] CockroachDB memory adapter seam
- [x] Bedrock provider seam
- [x] Real CockroachDB Cloud cluster
- [x] Real CockroachDB persistent episode write + fresh-process recall
- [x] Real Distributed Vector Index query evidence
- [x] Managed MCP connection evidence
- [x] Bounded model-advisor integration
- [x] NVIDIA auxiliary live advisor evidence
- [x] Real external model invocation evidence (NVIDIA; Bedrock optional)
- [x] AWS Lambda hosted demo
- [x] Responsive public judge UI
- [x] Protected one-click Memory OFF vs Memory ON proof
- [x] Systematic Memory ON vs OFF benchmark / ablation
- [ ] Public GitHub repository
- [ ] <3 minute demo video

## Security

Never commit:

- CockroachDB connection strings
- service-account API keys
- AWS credentials
- MCP bearer tokens

Use `.env` locally and commit only `.env.example`.

## License

MIT.
