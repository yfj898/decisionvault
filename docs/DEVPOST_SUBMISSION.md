# DecisionVault — Devpost Submission Package

## Project title

DecisionVault

## Tagline

RAG remembers information. DecisionVault remembers whether a decision worked.

## One-sentence pitch

DecisionVault is an outcome-aware shared memory layer for agent teams that stores
what an agent tried, whether it worked, and lets another agent use that evidence
to change the next decision while keeping model output outside the decision
authority boundary.

## Inspiration

Many agent-memory demos prove that an agent can retrieve something from the past.
That is not enough to prove learning. A useful production agent should remember
which strategy it used, whether the action succeeded, how strong the evidence was,
and whether that outcome should change a future decision.

DecisionVault was built around a stricter question:

> Can we prove that persistent memory changed the next action — and also prove
> that weak, irrelevant, or out-of-scope memories did not?

## What it does

DecisionVault stores structured decision episodes in CockroachDB Cloud:

```text
situation
→ strategy
→ outcome
→ effectiveness
→ confidence
→ producer agent provenance
→ semantic embedding
```

When another agent receives a similar future situation, it retrieves scoped
episodes through CockroachDB vector search. A deterministic outcome-aware policy
then decides whether to reuse a successful strategy, avoid a failed strategy, or
ignore weak/irrelevant memory.

For the hosted general API, outcome memory is no longer accepted as a caller
assertion. An authenticated agent first invokes a server-controlled
payment-recovery sandbox through `/execute`; DecisionVault signs the resulting
execution receipt and `/record` verifies that receipt before the outcome can
enter persistent memory. Receipt IDs are unique/idempotent. This is a controlled
hackathon executor, not a claim of integration with a real card network.

The live proof uses two agent identities:

```text
Agent A · recovery-observer
→ records FAILED GENERIC_RETRY
→ CockroachDB shared persistent memory
→ Agent B · recovery-planner
→ semantic recall
→ REFRESH_PAYMENT_TOKEN
```

With Memory OFF, Agent B repeats `GENERIC_RETRY`. With Memory ON, Agent B recalls
Agent A's failed outcome and switches to `REFRESH_PAYMENT_TOKEN`.

The NVIDIA model is explanation-only. The policy commits the strategy before the
model is called, so model failure or model text cannot replace or veto the memory-
based decision.

## How we built it

### CockroachDB Cloud

CockroachDB is the authoritative persistent memory system. Decision episodes are
stored in `decision_episodes` with structured outcome fields, JSONB evidence,
agent provenance, timestamps, and the deterministic `VECTOR(64)` regression
embedding. The hosted semantic path additionally stores the native NVIDIA E5-v5
representation in `semantic_embedding VECTOR(1024)` and maintains governed
current heads in `decision_memory_heads`. Every semantic row also carries
`semantic_embedding_space`, which binds the model ID, vector width, and
query/passage contract so incompatible embedding generations are never compared.

### CockroachDB Distributed Vector Indexing

The original deterministic regression path uses:

```sql
CREATE VECTOR INDEX decision_episodes_scope_embedding_vec_idx
ON decision_episodes (scope_id, embedding vector_cosine_ops);
```

The judge-facing semantic path uses a separate native-1024D index:

```sql
CREATE VECTOR INDEX decision_memory_heads_scope_space_semantic_vec_idx
ON decision_memory_heads (
  scope_id,
  semantic_embedding_space,
  semantic_embedding vector_cosine_ops
);
```

`scope_id` + `semantic_embedding_space` filtering prevents cross-scope and
cross-model retrieval. Authorization is handled separately: `/record`, `/decide`,
`/execute`, and `/revoke` require opaque per-agent tokens whose server-side
SHA-256 digest grants bind agent identity, namespace-bounded scopes,
permissions, and trust. A caller cannot choose its own `agent_id`; revocation
also requires a separate server-side allowlist for that bound agent identity.

### CockroachDB Cloud Managed MCP Server

DecisionVault includes a reproducible `MemoryAuditorAgent`. It connects to the
official Managed MCP Server and uses real `select_query` and `explain_query`
calls to:

- inspect DecisionVault outcome memory and producer provenance;
- verify the nearest-neighbor query uses CockroachDB vector search;
- verify the real Distributed Vector Index is present in the execution plan.

### NVIDIA semantic embeddings

The hosted runtime uses `nvidia/nv-embedqa-e5-v5` with the correct retrieval
modes: `passage` for stored episodes and `query` for future situations. The
provider's native 1024D vector is stored directly in CockroachDB; the hosted path
does not use the former 1024→64 experimental projection. Future embedding-model
changes use an explicit re-embedding migration instead of silently reusing old
vectors in a new space.

### NVIDIA bounded explanation

`meta/llama-3.1-8b-instruct` explains why the already-committed strategy is
consistent with recalled outcome evidence. The model cannot select a different
strategy.

### AWS Lambda

The complete judge-facing application is deployed on AWS Lambda in
`ap-northeast-1` through a Lambda Function URL. Public health/UI routes are
read-only. General agent mutations use server-bound agent tokens; the two
judge-facing demo routes use a separate private demo token.

## What we proved

The project contains both live evidence and systematic ablation:

```text
Local deterministic benchmark:          56 / 56 PASS
CockroachDB Cloud deterministic:         28 / 28 PASS
Cloud + NVIDIA advisor ablation:          7 /  7 PASS
Native 1024D production semantic:        14 / 14 PASS

Benefit target accuracy, Memory ON:      100%
Benefit target accuracy, Memory OFF:       0%
Failed-strategy repetition, Memory ON:     0%
Failed-strategy repetition, Memory OFF:  100%
Successful strategy reuse, Memory ON:    100%
Successful strategy reuse, Memory OFF:     0%
Control preservation, Memory ON:         100%
False influence, Memory ON:                0%
Cross-scope leakage, Memory ON:            0%
Advisor strategy invariance:             100%
```

The `56/56` and `28/28` numbers are deterministic behavioral regression/causal
ablation results, not hosted semantic-retrieval quality. Production semantic
retrieval is evaluated separately with 14 hand-authored paraphrase/adversarial
cases against the native 1024D DVI, including same-scope distractors,
cross-scope filtering, contradictions, stale memory, supersession, and candidate
crowding. The benchmarks deliberately measure decision-memory conformance rather
than claiming a simulated payment/business success rate.

## Challenges we ran into

### Proving causality instead of retrieval

The biggest design challenge was avoiding a weak claim like "the agent retrieved
similar memory." We added a Memory OFF counterfactual and control families so the
submission can show that memory changes behavior only when outcome evidence is
strong enough.

### Keeping the model non-authoritative

LLM output is useful for explanation but makes causal evaluation much harder if
it is also allowed to choose the action. We therefore separated the authority
boundary: CockroachDB memory plus deterministic policy commits the strategy first;
the model may only explain it afterward.

### Red-teaming semantic retrieval instead of preserving a convenient shortcut

The original reproducible baseline used deterministic 64D hashing embeddings.
An early hosted version projected NVIDIA's 1024D embeddings into that 64D space
to avoid a late schema migration. A retrieval red-team showed that this shortcut
could change nearest-neighbor ranking, so we removed it from production, added a
native `VECTOR(1024)` column and DVI, and kept 64D only as a regression baseline.

The same red-team also found that deduplicating *after* ANN top-K could let one
producer crowd another producer out of the candidate set. Production recall now
queries `decision_memory_heads`, which stores one current head per
`(scope_id, producer_agent_id, strategy)` while preserving immutable episodes in
the audit-history table.

### Managed MCP client compatibility

An early agent-wrapper path had an OAuth resource-binding issue. We isolated the
problem, verified the official MCP 2025-06-18 protocol directly, and then added a
repository-owned Memory Auditor Agent that now performs the Managed MCP workflow
reproducibly.

## Accomplishments

- Real CockroachDB Cloud persistent episodic memory.
- Real CockroachDB Distributed Vector Index and EXPLAIN evidence.
- Real CockroachDB Cloud Managed MCP agentic audit workflow.
- Real cross-agent memory provenance and scope isolation.
- Real NVIDIA semantic embeddings in the hosted runtime.
- Native 1024D CockroachDB semantic DVI with no lossy hosted projection.
- Server-bound per-agent identity / scope / permission grants for general APIs.
- Candidate-crowding-resistant governed memory heads.
- First-class non-executable conflict abstention: `strategy=null`,
  `action=ABSTAIN`, `executable=false`, with `/execute` re-checking the current
  deterministic decision before signing a receipt.
- Producer-bound authenticated `/revoke` with append-only CockroachDB revocation
  audit events and idempotent replay behavior.
- Explicit semantic embedding-space isolation plus a CAS-safe re-embedding
  migration utility for future model/version changes.
- Server-signed execution receipts and receipt-id idempotency for hosted outcome
  recording.
- Typed, single-successor correction metadata that only lets an authenticated
  producer supersede its own current governed memory head.
- Dedicated least-privilege CockroachDB runtime identity; schema DDL remains a
  separate migration/admin responsibility.
- Dedicated non-root AWS deployer identity restricted to the existing
  DecisionVault Lambda Get/Update operations.
- AWS Secrets Manager for the hosted database URL, model key, judge token, agent
  grants, and execution-receipt signing key; Lambda env keeps only the secret ARN.
- Separate liveness/readiness endpoints, bounded DB timeouts, and verified
  CockroachDB `40001` full-transaction retry behavior.
- CloudWatch EMF observability for request/error count, latency, memory
  influence/conflict, and idempotent replay without high-cardinality memory data.
- Real AWS Lambda judge-facing application.
- One-click Memory OFF vs Memory ON causal proof.
- Systematic benchmark showing benefit, false-influence, isolation, and model-
  invariance behavior.
- Public open-source repository with MIT license and reproducible evidence.

## What we learned

Long-term memory is not automatically useful just because it is retrievable.
Production agent memory needs three things together:

1. durable structured outcomes;
2. retrieval and scope boundaries;
3. an explicit rule for when memory is allowed to change behavior.

We also learned that multi-agent memory is more robust when agents exchange
durable evidence through a shared system of record rather than relying only on
ephemeral message passing, and that retrieval correctness must be evaluated
before governance: a perfect conflict resolver cannot reason about evidence that
ANN candidate generation has already hidden.

## What's next

- Extend the strategy/action contract beyond the frozen payment-recovery domain.
- Replace the current deterministic payment-recovery sandbox with a real external
  execution gateway / outcome verifier while preserving the signed receipt
  contract.
- Add learned or calibrated relevance thresholds while preserving the current
  deterministic safety gate.
- Add richer operational metrics around recall quality and memory drift.
- Replace the hackathon token grant mechanism with an enterprise identity / IAM
  integration and centrally managed secrets.
- Run sustained high-RPS / long-duration soak tests beyond the bounded concurrent
  replay, supersession, provider-degradation, and distributed rate-limit proofs.

## Built with

CockroachDB Cloud, Distributed Vector Indexing, CockroachDB Cloud Managed MCP,
AWS Lambda, Python, NVIDIA NIM/API, native 1024D semantic embeddings, JSONB,
vector search, agentic memory, multi-agent systems.

## Try it out

Live application:

`https://mfcr7b2k3j7lrwr44u35i5rchq0fbncb.lambda-url.ap-northeast-1.on.aws/`

Public source:

`https://github.com/yfj898/decisionvault`

## Private judge testing instructions

Paste the actual value from local ignored file `.venv/demo-token` into the
Devpost private testing-instructions field. Do **not** put that value in this
repository, screenshots, or the public video.

Suggested private text:

```text
Open the Try it out URL.
Paste this demo token into the "Demo access token" field:

<PASTE PRIVATE DEMO TOKEN HERE>

Click "Run live memory proof".

Expected result:
- Agent B / Memory OFF → GENERIC_RETRY
- Agent B / Memory ON → REFRESH_PAYMENT_TOKEN
- producer_agents includes recovery-observer
- the green PASS banner confirms the temporary scope was cleaned

The UI and /health route are public/read-only. The token protects the mutation
used only for the two atomic judge demonstrations. General `/record` and
`/decide` APIs use separate per-agent tokens and are not part of the judge
instructions.
```

## <3 minute video plan — target 2:42

### 0:00–0:18 — Problem

Show title + one sentence:

> RAG can remember information. DecisionVault remembers whether a decision
> worked — and proves that the outcome changed the next action.

### 0:18–0:38 — Architecture

Show one diagram/frame:

```text
Agent A → CockroachDB outcome memory → Agent B
             ↓ DVI / MCP
         semantic recall
             ↓
        deterministic policy
             ↓
     NVIDIA explanation only
             ↓
          AWS Lambda UI
```

State the tools explicitly: CockroachDB Cloud, Distributed Vector Indexing,
Managed MCP Memory Auditor Agent, AWS Lambda, NVIDIA semantic embeddings.

### 0:38–1:28 — Live causal proof

Open the live page and run the protected demo.

Narrate only what appears:

- Agent A records a failed `GENERIC_RETRY` outcome.
- Agent B with Memory OFF repeats `GENERIC_RETRY`.
- Agent B with Memory ON recalls Agent A's outcome.
- Agent B changes to `REFRESH_PAYMENT_TOKEN`.
- Point to `producer_agents=recovery-observer`.
- Point to the cleanup PASS banner.

### 1:28–1:56 — Conflict safety proof

Click **Run conflict safety proof** and point to:

```text
Agent A outcome conflicts with Agent B outcome
→ Agent C
→ resolution=CONFLICT_ABSTAIN
→ action=ABSTAIN, strategy=null, executable=false
→ memory_conflict=true, memory_influenced=false
```

`CONFLICT_ABSTAIN` is a first-class non-executable decision. The execution
gateway re-runs current policy and refuses to sign a receipt while the
abstention remains active.

### 1:56–2:28 — Production evidence

After the live causal and conflict proofs, scroll to the judge UI's static
**Reproducible submission evidence** panel. Show the current production semantic
schema / DVI evidence with:

```text
semantic_embedding VECTOR(1024)
semantic_embedding_space
decision_memory_heads_scope_space_semantic_vec_idx
vector search
```

Mention that immutable episodes remain in `decision_episodes`, while governed
current heads prevent duplicate candidate crowding. The Memory Auditor Agent can
also inspect the memory/provenance and vector plan through CockroachDB Cloud
Managed MCP. The same panel contains the frozen benchmark numbers, so the video
does not need to switch to a terminal or a second browser tab.

Show only the most important benchmark numbers:

```text
Benefit target accuracy: ON 100% / OFF 0%
Failed-strategy repetition: ON 0% / OFF 100%
False influence: 0%
Cross-scope leakage: 0%
Production semantic benchmark: 14/14
```

Clarify that the `56/56` and `28/28` figures are deterministic regression/
causal-ablation results, while `14/14` is the separate native-1024D production
semantic suite.

### 2:28–2:40 — Close

End with:

> DecisionVault does not just ask whether an agent can remember. It proves when
> remembered outcomes should change behavior — and when they should not.

Do not use copyrighted music. Keep the final exported video below three minutes.
