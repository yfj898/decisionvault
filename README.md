# DecisionVault

[![CI](https://github.com/yfj898/decisionvault/actions/workflows/ci.yml/badge.svg)](https://github.com/yfj898/decisionvault/actions/workflows/ci.yml)

**Governed adaptive memory and decision infrastructure for agent teams.**

DecisionVault is a new project for the **CockroachDB × AWS Hackathon — Build with Agentic Memory**.

DecisionVault turns verified multi-agent experience into reusable knowledge while
preserving provenance, conflict awareness, scope isolation, and execution safety.
The payment-recovery agent team remains the deterministic end-to-end proof:

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
L1 governed episodic memory
   |
   +----> deterministic consolidation candidate
   +----> independent promotion governance
   |
   v
L2 semantic effectiveness + L3 procedural/avoidance memory
   |
   v
Applicability + negative veto + hard-conflict governance
   |
   v
Deterministic policy
   |
   +----> NVIDIA semantic embeddings + explanation-only advisor
   |
   v
Strategy + grounded explanation
```

## Governed Adaptive Memory

The production memory model is intentionally layered rather than "more vectors":

```text
L0 Working Memory       request-local context; never persisted
L1 Episodic Memory      immutable DecisionEpisode + governed current heads
L2 Semantic Memory      strategy × situation-class effectiveness projection
L3 Procedural Memory    promoted reusable rule or AVOID rule
```

L2/L3 knowledge is never written directly by an LLM. `MemoryConsolidator`
produces only deterministic candidates. `MemoryConsolidationGovernor` then
revalidates the candidate against current heads, distinct producers, explicit
applicability, embedding generation, evidence freshness, revocation/supersession,
and independent contradiction before promotion. Team knowledge needs at least
two distinct producers; global knowledge needs at least three. Repeated writes
from one producer do not increase promotion confidence.

Promoted knowledge stores the evidence window, supporting episode IDs, producer
set, positive/negative evidence, confidence, governance revision, semantic
embedding space, applicability preconditions/exclusions, and supersession or
revocation lineage. Negative memory is a veto (`AVOID strategy X WHEN Y`) and is
applied before positive ranking. Semantic similarity alone is never sufficient:
applicability and governance must also pass.

The final decision carries a deterministic governance trace and selected L1/L3
IDs. That provenance is committed into the decision-state digest, copied into the
signed Decision Snapshot, copied again into the signed Execution Receipt, and
persisted with the verified outcome episode. The explanation-only advisor may
describe this committed trace but cannot alter it.

Apply the production v6 schema with a migration-admin connection and explicit
public CockroachDB CA input. The migration runner commits each CockroachDB schema
change separately and does not require expanding the Lambda runtime role beyond
table-level DML:

```bash
python scripts/apply_governed_adaptive_memory_v6.py \
  --database-url-file /path/to/migration-database-url \
  --ca-file /path/to/cockroach-cloud-root.crt
```

After the migration, the real adaptive-memory adversarial/concurrency smoke uses
the normal runtime `DATABASE_URL`, NVIDIA embedding configuration, and always
cleans its temporary scopes in `finally`. When the runtime correctly lacks
DELETE on append-only revocation audit, provide
`DECISIONVAULT_CLEANUP_DATABASE_URL` as a migration-admin connection **only for
test cleanup** rather than widening runtime privileges:

```bash
python scripts/adaptive_memory_cloud_smoke.py
```

The production v6 migration, 13/13 live adversarial/concurrency smoke, adaptive
DVI, read-only Managed MCP auditor, Lambda hosted regression, 14/14 semantic
benchmark, and final zero-row cleanup are recorded in
`docs/evidence/GOVERNED_ADAPTIVE_MEMORY_V6.md`.

Governed Adaptive Memory v7 hardens long-running operations around that v6
authority model: signed snapshots/receipts support explicit signing-key IDs and
retained verification keys; every current-head mutation creates a durable
consolidation obligation; a separately authenticated CockroachDB consolidator
owns L2/L3 promotion while request runtime retains only the synchronous L3
invalidation rights required for correctness; PRIVATE/TEAM/GLOBAL promotion
levels are server-owned; and fixed-name memory-health metrics feed a scheduled
retry worker plus CloudWatch alarms/dashboard. Production rollout is deliberately
expand/contract so runtime rights are not revoked until the new Lambda proves a
distinct consolidator identity. Current v7 rollout evidence is recorded in
`docs/evidence/GOVERNED_ADAPTIVE_MEMORY_V7.md`.

The next optimization pass keeps those governance boundaries intact while
reducing semantic-runtime work. Production L1+L3 recall now shares one query
embedding and one CockroachDB connection per memory-enabled decision instead of
duplicating both. A real CockroachDB+NVIDIA benchmark measured a 50% reduction in
query-embedding requests, a 50% reduction in DB connections, and a 44.6% median
memory-recall latency reduction. Long-term L3 influence is also calibrated by
effective confidence: the production minimum is now 0.30 so aging knowledge can
remain auditable without retaining execution influence until hard expiry.
Evidence and calibration reports are in
`docs/evidence/PERFORMANCE_COST_MEMORY_QUALITY_V1.md` and `reports/`.

DecisionVault now also records a privacy-bounded, append-only memory-quality
telemetry loop from signed decision snapshots to verified execution outcomes.
Each production decision evaluates nine **monotone-stricter** threshold shadows,
but the shadows are non-authoritative and never enter the signed execution
artifact. Historical telemetry cannot safely identify looser thresholds, and a
shadow that would choose a different executable strategy is explicitly treated
as an unobserved counterfactual rather than being scored with the champion's
outcome. Automatic recommendation is gated on at least 30 memory-exposed
verified outcomes, >=95% successful-outcome retention, <=5% factual harmful
rate, and zero executable counterfactuals; the report cannot mutate runtime
thresholds. The first real production sample is intentionally reported as
`INSUFFICIENT_REAL_TELEMETRY`, so the current champion stays unchanged. Evidence
is in `docs/evidence/MEMORY_QUALITY_TELEMETRY_V1.md` and
`reports/memory-telemetry-calibration.json`.

That telemetry now feeds a durable **calibration-review loop**. Aggregate
champion/challenger runs are append-only in CockroachDB, and the existing
production consolidation Scheduled Event performs a persisted 24-hour due-check
before running the evaluator. No second scheduler and no threshold-mutation
authority are introduced. Promotion remains a separate human/source-code/CI
operation; the current real sample count is still `1 / 30`, so the latest
promotion review is `NO_PROMOTION` and the champion is unchanged. Production
evidence is in `docs/evidence/MEMORY_CALIBRATION_LOOP_V2.md` and
`reports/memory-calibration-promotion-review.json`.

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
CREATE VECTOR INDEX decision_memory_heads_scope_space_semantic_vec_idx
ON decision_memory_heads (
  scope_id,
  semantic_embedding_space,
  semantic_embedding vector_cosine_ops
);
```

The immutable `decision_episodes` history remains the audit log; the
`decision_memory_heads` table contains at most one active head per
`(scope_id, producer_agent_id, strategy)` for production semantic recall.

Production governed recall deliberately uses two query stages. The ANN fast path
uses the DVI-compatible query shape containing only the exact scope prefix,
`semantic_embedding_space`, vector ordering, and top-k. Governance lifecycle,
outcome, revocation, and exact similarity-threshold coverage are evaluated in a
second scope-exact query plus the deterministic resolver. This preserves both a
real CockroachDB `vector search` node in the production path and completeness
beyond the ANN top-k boundary. `MemoryAuditorAgent` imports the same SQL builders
used by `CockroachVectorMemoryStore`, so its ANN/coverage EXPLAIN requests cannot
silently drift to a simplified query contract.

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
`/record`, `/decide`, `/execute`, and `/revoke` APIs add a separate authorization boundary: opaque
per-agent tokens are hashed server-side and bind identity, permitted scope
namespaces, permissions, and trust. Callers cannot self-assert `agent_id` in the
request body.

The live CockroachDB Cloud semantic smoke uses NVIDIA
`nvidia/nv-embedqa-e5-v5` at its native 1024D width. A paraphrased future case
produced cosine similarity `0.4541` and crossed the production semantic relevance
gate of `0.40`. A separate hand-authored production semantic benchmark now covers
14 benefit/control/governance cases and passes `14/14`. See
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
- **authenticated revocation** — `/revoke` requires both an authenticated
  producer capability (`revoke`, or the already-deployed `record` capability as
  a compatibility bridge) and an independent server-side `REVOKE_AGENT_IDS`
  allowlist opt-in; an authorized producer may remove only its own current head;
  immutable outcome history remains in `decision_episodes` and an append-only
  `decision_memory_revocations` event records who revoked which episode and why;
- **embedding-space isolation** — semantic heads and immutable semantic records
  carry `semantic_embedding_space`; production retrieval filters by model +
  dimension + query/passage contract before vector ranking, so a model change
  cannot silently compare incompatible vectors;
- **candidate-crowding resistance** — production recall reads
  `decision_memory_heads`, whose primary key keeps one current head per producer
  and strategy, so repeated writes cannot fill the ANN top-K before governance;
- **contradiction surfacing** — similarly strong conflicting memories return
  `CONFLICT_ABSTAIN` with `strategy=null`, `action=ABSTAIN`, and
  `executable=false`; the execution gateway re-runs the current deterministic
  policy and will not sign an execution receipt while the abstention is active;
- **server-bound identity and trust** — `AGENT_AUTH_JSON` is keyed by SHA-256
  digests of opaque agent tokens and binds `agent_id`, scope prefixes,
  permissions, and trust. Unknown producers receive a conservative default when
  a trust registry is active. Trust may resolve a conflict, but the returned
  decision keeps `memory_conflict=true` so disagreement remains auditable.

The real CockroachDB Cloud + NVIDIA semantic governance smoke verified:

```text
balanced conflict      → strategy=null / action=ABSTAIN / CONFLICT_ABSTAIN
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
strategy=null
action=ABSTAIN
executable=false
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
`X-DecisionVault-Token`. General `/record`, `/decide`, `/execute`, and `/revoke` routes instead require
an `X-DecisionVault-Agent-Token` whose digest is mapped server-side to an agent
identity, namespace-bounded scope permissions, and trust. `/revoke` additionally
requires the server-controlled `REVOKE_AGENT_IDS` allowlist.

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
derives the outcome from the server-controlled `EXECUTION_SANDBOX_SCENARIO` and
rejects any caller-supplied `scenario`, then signs a receipt that binds agent
identity, scope, situation, strategy, result, and issue time. `/record` verifies
that receipt and persists its unique `receipt_id` as an
idempotency key. Replaying the same receipt returns the original episode rather
than duplicating memory. This is a controlled payment-recovery sandbox, not a
claim of a real payment-processor integration.

The general `/decide` API likewise keeps memory governance server-controlled:
callers cannot submit `memory_enabled=false`. Memory OFF remains available only
inside the protected judge demo and offline ablation/benchmark harnesses.

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

The later final red-team pass also added verified execution receipts with
idempotent replay, typed race-safe supersession, least-privilege database and AWS
deployment identities, AWS Secrets Manager runtime secrets, real liveness /
readiness probes, CockroachDB serialization retry, CloudWatch EMF metrics, and a
CockroachDB-backed per-principal rate limiter. Concurrent receipt/supersession,
semantic-provider degradation, and bounded overload cases were exercised against
the hosted runtime. See
`docs/evidence/CONCURRENCY_DEGRADATION_RATE_LIMIT.md` and the other final
red-team evidence files.

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

Native 1024D production semantic:      14 / 14 PASS

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
hand-authored `14/14` production semantic benchmark against
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
`decision_memory_heads_scope_space_semantic_vec_idx`. Run the auditor with
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
- [x] Explicit embedding generation/revision contract; cross-revision recall is fail-closed
- [x] Fixed NVIDIA credential-bearing provider origin with redirect rejection
- [x] Cross-agent outcome-memory provenance and scope isolation
- [x] Per-agent token → identity / scope / permission binding for `/execute`, `/record`, `/decide`, and `/revoke`
- [x] Server-signed `/execute` receipts required by the general `/record` API
- [x] Signed decision snapshot binding across `/decide` → `/execute`; stale snapshots fail HTTP 409
- [x] Decider/executor role separation preserved; receipts audit both decision and execution identities
- [x] Unique execution receipt idempotency boundary
- [x] Typed/race-safe same-producer supersession boundary
- [x] Conflict-aware multi-agent memory governance
- [x] Staleness / supersession / candidate-crowding controls
- [x] Explicit `observed_at` event time and `recorded_at` ingestion/audit time
- [x] Server-side producer trust weighting with conflict visibility
- [x] AWS Lambda hosted demo
- [x] Responsive public judge UI
- [x] Protected one-click Memory OFF vs Memory ON proof
- [x] Systematic Memory ON vs OFF benchmark / ablation
- [x] Hand-authored native-1024D production semantic benchmark (`14/14`)
- [x] Public GitHub repository
- [ ] <3 minute demo video

## Security

The hosted Lambda uses a dedicated CockroachDB `decisionvault_runtime` identity
rather than the migration/admin account. It has only the table privileges needed
by the current application (`SELECT/INSERT/DELETE` on immutable episodes and
`SELECT/INSERT/UPDATE/DELETE` on governed heads); schema CREATE is denied. Schema
migrations use a separately retained admin connection outside the Lambda
environment.

Routine AWS Lambda updates also use a dedicated `decisionvault-deployer` IAM
identity whose policy is scoped to Get/Update operations on the existing
`decisionvault-agent` function. IAM administration is denied. Initial AWS
bootstrap still required a privileged account; the restricted deployer is used
for subsequent routine releases.

Sensitive hosted runtime configuration is stored in AWS Secrets Manager rather
than directly in Lambda environment variables. The Lambda execution role can
read only the single DecisionVault runtime secret; the function environment
contains the secret ARN plus non-sensitive model/runtime settings.

`NVIDIA_BASE_URL` is not an arbitrary egress knob: DecisionVault accepts only
the canonical `https://integrate.api.nvidia.com/v1` value, constructs only the
known chat/embedding endpoints, and rejects redirects for bearer-authenticated
requests. `NVIDIA_EMBED_REVISION` is an operator-owned generation contract; it
is part of `semantic_embedding_space`, so the same model ID cannot silently mix
vectors from two provider generations. Readiness fails closed if the revision is
missing, the provider origin is invalid, or current governed heads are in a
different embedding space.

Managed secret refresh is serialized per warm process so one refresh generation
cannot interleave environment hydration with another. Decision episodes retain
both `observed_at` (event ordering) and `recorded_at` (system ingestion/audit
time); only `observed_at` may advance a producer/strategy current head.

CockroachDB connections use bounded connect/statement timeouts, and the memory
store retries a complete transaction on CockroachDB SQLSTATE `40001` without
repeating the external embedding call. `/health/live` exposes dependency-free
liveness; `/health/ready` actively probes Secrets Manager, CockroachDB, and the
production E5-v5 embedding endpoint and caches the result for 30 seconds per warm
Lambda process.

Within the hosted 30-second Lambda deadline, semantic provider calls are clamped
to at most 12 seconds and the explanation-only advisor to at most 5 seconds.
This leaves deterministic DB/serialization margin and keeps a slow advisor from
turning its intended graceful degradation into a platform-level timeout.

Each hosted request also emits a low-cardinality CloudWatch EMF event under the
`DecisionVault` namespace. Request/error counts, latency, memory influence,
conflict abstention, and idempotent replay are measurable without logging scope
IDs, episode IDs, agent identities, situations, tokens, or model text.

Never commit:

- CockroachDB connection strings
- service-account API keys
- AWS credentials
- MCP bearer tokens

Use `.env` locally and commit only `.env.example`.

## License

MIT.
