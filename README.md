# DecisionVault

**Outcome-aware shared decision memory for agent teams.**

DecisionVault is a new project for the **CockroachDB × AWS Hackathon — Build with Agentic Memory**.

The core claim is deliberately narrow and testable. DecisionVault is a reusable
outcome-memory pattern, demonstrated end-to-end on a payment-recovery agent team:

> An agent should remember not only what happened, but which strategy it used, whether it worked, and how that evidence should change the next decision.

## Frozen MVP

The first vertical slice demonstrates:

1. Agent A observes a payment-support recovery attempt.
2. With no relevant memory, the default action is a generic retry.
3. That action fails and Agent A persists the outcome plus producer provenance.
4. Agent B later encounters a semantically similar case in the same shared scope.
5. Agent B recalls Agent A's failed outcome and selects a different strategy.
6. A memory-disabled Agent B repeats the inferior default strategy.

The local implementation is deterministic so the memory effect is testable before cloud credentials are connected.

## Competition architecture

```text
Judge / user
   |
   v
AWS Lambda Function URL + DecisionVault UI
   |
   v
CockroachDB Cloud shared persistent memory
   +----> Distributed Vector Index recall
   +----> Managed MCP evidence path
   |
   v
Outcome-aware deterministic policy
   |
   +----> NVIDIA semantic embeddings + explanation-only advisor
   |
   v
Strategy + grounded explanation
```

Verified competition integrations:

- CockroachDB Distributed Vector Indexing
- CockroachDB Cloud Managed MCP Server
- NVIDIA live semantic embeddings + bounded model advisor
- AWS Lambda deployment

## Live demo

Public UI:

https://mfcr7b2k3j7lrwr44u35i5rchq0fbncb.lambda-url.ap-northeast-1.on.aws/

Public repository:

https://github.com/yfj898/decisionvault

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
database persistence can be tested independently from model availability. That
embedder remains the reproducible benchmark baseline in
`decision_episodes.embedding VECTOR(64)`. The hosted production path now keeps the
provider's native NVIDIA `nv-embedqa-e5-v5` 1024-dimensional representation in
`decision_memory_heads.semantic_embedding VECTOR(1024)`, with `passage` mode for
stored episodes and `query` mode for recall. The old 64D projection utility is
retained only for historical regression tests and is not used by the hosted
semantic retrieval path.

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

The current hosted semantic path uses a separate governed-head index so repeated
writes from one producer cannot crowd independent producers out of the ANN
candidate set:

```sql
CREATE VECTOR INDEX decision_memory_heads_scope_semantic_vec_idx
ON decision_memory_heads (scope_id, semantic_embedding vector_cosine_ops);
```

The immutable `decision_episodes` history remains the audit log; the
`decision_memory_heads` table contains at most one active head per
`(scope_id, producer_agent_id, strategy)` for production semantic recall.

## Phase 5 — Bounded model advisor

DecisionVault keeps model output outside the strategy authority boundary. The
agent first recalls CockroachDB memory and commits the deterministic strategy;
an optional model advisor can only add a grounded explanation afterward. A
provider failure is ignored and cannot change or block the committed strategy.

The verified competition model path uses NVIDIA as an explanation-only provider.
Amazon Bedrock remains an optional provider rather than a Phase 5 gate. The AWS
competition requirement is satisfied separately by the Phase 6 Lambda deployment.

An optional Bedrock provider seam remains in the codebase for experimentation,
but it is not part of the submission claim or required judge path.

The NVIDIA provider was verified live against the same bounded advisor contract
and real CockroachDB memory. Model output still cannot select or change strategy.

See `docs/evidence/PHASE5_BOUNDED_MODEL_INTEGRATION.md`.

## Shared agent memory and semantic runtime

DecisionVault now carries producer provenance with each outcome episode. The live
shared-memory proof uses two distinct agent identities:

```text
Agent A · recovery-observer
→ records FAILED GENERIC_RETRY + producer provenance
→ CockroachDB shared scope
→ Agent B · recovery-planner
→ semantic recall
→ REFRESH_PAYMENT_TOKEN
```

The same Agent B in another scope remains on `GENERIC_RETRY`, proving that the
retrieval layer is scope-bounded rather than globally broadcast. The protected
`/record` and `/decide` APIs add a separate authorization boundary: opaque
per-agent tokens are hashed server-side and bind identity, permitted scope
prefixes, permissions, and trust. Callers cannot self-assert `agent_id` in the
request body.

The live CockroachDB Cloud semantic smoke uses NVIDIA
`nvidia/nv-embedqa-e5-v5` at its native 1024D width. A paraphrased future case
produced cosine similarity `0.4541` and crossed the production semantic relevance
gate of `0.40`. A separate hand-authored production semantic benchmark now covers
12 benefit/control/governance cases and passes `12/12`. See
`docs/evidence/SHARED_AGENT_MEMORY_SEMANTIC_RUNTIME.md` and
`reports/production-semantic-benchmark.json`.

## Multi-agent memory governance

Shared memory is not treated as an ungoverned vote pool. Before recalled
episodes can influence a strategy, `ConflictAwareMemoryResolver` applies explicit
governance rules:

- **provenance** — every outcome carries `producer_agent_id`;
- **scope isolation** — vector retrieval remains bound to the requested
  `scope_id`; agent API authorization separately restricts which scope prefixes a
  token may access;
- **staleness** — memories older than the configured age window do not propagate;
- **supersession** — a corrective episode can retire an obsolete governed head
  through typed `supersedes_episode_id UUID` while immutable history remains in
  `decision_episodes`; the target must belong to the same authenticated producer,
  remain the current governed head, and may have only one direct successor;
- **candidate-crowding resistance** — production recall reads
  `decision_memory_heads`, whose primary key keeps one current head per producer
  and strategy, so repeated writes cannot fill the ANN top-K before governance;
- **contradiction surfacing** — similarly strong conflicting memories return
  `CONFLICT_ABSTAIN` instead of silently selecting one side;
- **server-bound identity and trust** — `AGENT_AUTH_JSON` is keyed by SHA-256
  digests of opaque agent tokens and binds `agent_id`, scope prefixes,
  permissions, and trust. Unknown producers receive a conservative default when
  a trust registry is active. Trust may resolve a conflict, but the returned
  decision keeps `memory_conflict=true` so disagreement remains auditable.

The real CockroachDB Cloud + NVIDIA semantic governance smoke verified:

```text
balanced conflict      → GENERIC_RETRY / CONFLICT_ABSTAIN
trusted resolution     → REFRESH_PAYMENT_TOKEN / conflict still visible
120-day stale success  → ignored
superseded success     → old episode no longer participates
duplicate producer     → one governed head; independent conflict remains visible
Cloud cleanup          → PASS
```

The governance layer was then regression-tested against the frozen Phase 8
benchmark: `56/56` local and `28/28` CockroachDB Cloud cases still pass with the
same Memory ON/OFF metrics. Reproduce the Cloud governance path with:

```bash
uv run python scripts/multi_agent_governance_smoke.py --semantic
```

The hosted judge UI also exposes a protected **conflict safety proof**. It writes
two contradictory outcomes from two producer agents into one temporary shared
scope, asks a third agent to decide, and returns:

```text
strategy=GENERIC_RETRY
memory_influenced=false
memory_resolution=CONFLICT_ABSTAIN
memory_conflict=true
```

The temporary scope is deleted after the proof. Missing demo credentials return
HTTP `401`. The deployed control and result copy were verified with headless
Chrome at both desktop and mobile viewport sizes.

See `docs/evidence/MULTI_AGENT_MEMORY_GOVERNANCE.md`.

## Phase 6 — AWS Lambda deployment

DecisionVault is deployed as an AWS Lambda Python 3.12 function in
`ap-northeast-1` with a Lambda Function URL. `GET /health` is public for
availability checks. Judge-only atomic demo routes use the private
`X-DecisionVault-Token`. General `/record` and `/decide` routes instead require
an `X-DecisionVault-Agent-Token` whose digest is mapped server-side to an agent
identity, allowed scope prefixes, permissions, and trust.

The live deployment proved the full hosted causal path:

```text
AWS Lambda /execute
→ server-signed payment-recovery sandbox receipt
→ AWS Lambda /record
→ CockroachDB Cloud persistent episode
→ AWS Lambda /decide
→ CockroachDB vector recall
→ deterministic strategy change
→ NVIDIA bounded explanation
```

General agents cannot submit arbitrary outcome labels to `/record`. `/execute`
derives the outcome from the server-controlled hackathon scenario and signs a
receipt that binds agent identity, scope, situation, strategy, result, and issue
time. `/record` verifies that receipt and persists its unique `receipt_id` as an
idempotency key. Replaying the same receipt returns the original episode rather
than duplicating memory. This is a controlled payment-recovery sandbox, not a
claim of a real payment-processor integration.

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

The frozen deterministic regression suite has seven benchmark families covering failed `GENERIC_RETRY` avoidance, successful
`REFRESH_PAYMENT_TOKEN` reuse, successful `VERIFY_BILLING_PROFILE` reuse,
low-confidence failures, low-effectiveness successes, cross-scope isolation, and
irrelevant-memory controls.

Verified results:

```text
Local deterministic benchmark:        56 / 56 PASS
CockroachDB Cloud deterministic:       28 / 28 PASS
Cloud + NVIDIA advisor ablation:        7 /  7 PASS

Native 1024D production semantic:      12 / 12 PASS

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

The `56/56` and `28/28` suites are intentionally deterministic regression and
causal-ablation tests; they are not presented as hosted semantic retrieval
quality. The current judge-facing retrieval path is tested separately by the
hand-authored `12/12` production semantic benchmark against
`decision_memory_heads.semantic_embedding VECTOR(1024)`, including same-scope
distractors, cross-scope filtering, contradictory outcomes, stale memory,
supersession, and duplicate-crowding controls. All Cloud benchmark rows are
deleted after each run.

Reproduce locally:

```bash
python scripts/benchmark_memory.py \
  --backend local \
  --variants 8 \
  --output reports/phase8-local.json
```

Cloud and advisor runs require their normal runtime credentials and do not store
secrets in the reports. See `docs/evidence/PHASE8_MEMORY_ABLATION.md` and the
post-audit corrections in `docs/evidence/FINAL_RED_TEAM_REMEDIATION.md`.

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

The original live MCP evidence exposed the historical `VECTOR(64)` regression
column and Phase 3 DVI. The repository-owned `MemoryAuditorAgent` now also supports
the production semantic contract: `decision_memory_heads`, native
`semantic_embedding VECTOR(1024)`, and
`decision_memory_heads_scope_semantic_vec_idx`. Run the auditor with
`--semantic` to audit that production query plan. The temporary evidence row is
removed after verification.

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
- [x] Reproducible Managed MCP Memory Auditor Agent
- [x] Bounded model-advisor integration
- [x] NVIDIA auxiliary live advisor evidence
- [x] Real external model invocation evidence (NVIDIA; Bedrock optional)
- [x] Real NVIDIA semantic embedding path (`passage` / `query`)
- [x] Native `VECTOR(1024)` production semantic DVI; no hosted 1024→64 projection
- [x] Cross-agent outcome-memory provenance and scope isolation
- [x] Per-agent token → identity / scope / permission binding for `/record` and `/decide`
- [x] Server-signed `/execute` receipts required by the general `/record` API
- [x] Unique execution receipt idempotency boundary
- [x] Typed/race-safe same-producer supersession boundary
- [x] Conflict-aware multi-agent memory governance
- [x] Staleness / supersession / candidate-crowding controls
- [x] Server-side producer trust weighting with conflict visibility
- [x] AWS Lambda hosted demo
- [x] Responsive public judge UI
- [x] Protected one-click Memory OFF vs Memory ON proof
- [x] Systematic Memory ON vs OFF benchmark / ablation
- [x] Hand-authored native-1024D production semantic benchmark (`12/12`)
- [x] Public GitHub repository
- [ ] <3 minute demo video

## Security

The hosted Lambda uses a dedicated CockroachDB `decisionvault_runtime` identity
rather than the migration/admin account. It has only the table privileges needed
by the current application (`SELECT/INSERT/DELETE` on immutable episodes and
`SELECT/INSERT/UPDATE/DELETE` on governed heads); schema CREATE is denied. Schema
migrations use a separately retained admin connection outside the Lambda
environment.

Never commit:

- CockroachDB connection strings
- service-account API keys
- AWS credentials
- MCP bearer tokens

Use `.env` locally and commit only `.env.example`.

## License

MIT.
