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
agent provenance, timestamps, and `VECTOR(64)` embeddings.

### CockroachDB Distributed Vector Indexing

The production memory lookup uses a scope-prefixed distributed vector index:

```sql
CREATE VECTOR INDEX decision_episodes_scope_embedding_vec_idx
ON decision_episodes (scope_id, embedding vector_cosine_ops);
```

The scope prefix prevents cross-agent/team memory leakage while cosine search
retrieves relevant episodes inside the authorized scope.

### CockroachDB Cloud Managed MCP Server

DecisionVault includes a reproducible `MemoryAuditorAgent`. It connects to the
official Managed MCP Server and uses real `select_query` and `explain_query`
calls to:

- inspect DecisionVault outcome memory and producer provenance;
- verify the nearest-neighbor query uses CockroachDB vector search;
- verify the real Distributed Vector Index is present in the execution plan.

### NVIDIA semantic embeddings

The hosted runtime uses `nvidia/nv-embedqa-e5-v5` with the correct retrieval
modes: `passage` for stored episodes and `query` for future situations. The 1024D
provider embedding is projected deterministically to the frozen `VECTOR(64)`
contract, preserving the already-verified CockroachDB index schema.

### NVIDIA bounded explanation

`meta/llama-3.1-8b-instruct` explains why the already-committed strategy is
consistent with recalled outcome evidence. The model cannot select a different
strategy.

### AWS Lambda

The complete judge-facing application is deployed on AWS Lambda in
`ap-northeast-1` through a Lambda Function URL. Public health/UI routes are
read-only; mutation/demo endpoints require a private judge/demo token.

## What we proved

The project contains both live evidence and systematic ablation:

```text
Local deterministic benchmark:          56 / 56 PASS
CockroachDB Cloud benchmark:             28 / 28 PASS
Cloud + NVIDIA advisor ablation:          7 /  7 PASS

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

The benchmark deliberately measures behavioral correctness rather than claiming
a simulated payment/business success rate.

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

### Preserving the verified vector-index contract while adding real embeddings

The original reproducible baseline used deterministic 64D hashing embeddings.
Rather than migrate the proven CockroachDB schema late in the project, we added a
deterministic 1024D→64D semantic projection and retained the same Distributed
Vector Index.

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
ephemeral message passing.

## What's next

- Extend the strategy/action contract beyond the frozen payment-recovery domain.
- Add learned or calibrated relevance thresholds while preserving the current
  deterministic safety gate.
- Add memory lifecycle policies for aging, supersession, and conflicting
  outcomes from multiple agents.
- Add richer operational metrics around recall quality and memory drift.
- Evaluate the full 1024D semantic embedding space versus the compact 64D
  projection.

## Built with

CockroachDB Cloud, Distributed Vector Indexing, CockroachDB Cloud Managed MCP,
AWS Lambda, Python, NVIDIA NIM/API, semantic embeddings, JSONB, vector search,
agentic memory, multi-agent systems.

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
used only for the live causal demonstration.
```

## <3 minute video plan — target 2:35

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

### 1:28–1:52 — CockroachDB memory layer

Show the `decision_episodes` schema / DVI evidence or terminal capture with:

```text
VECTOR(64)
decision_episodes_scope_embedding_vec_idx
vector search
```

Mention that the Memory Auditor Agent also verifies the same memory/provenance
and vector plan through CockroachDB Cloud Managed MCP.

### 1:52–2:18 — Benchmark

Show only the most important four numbers:

```text
Benefit target accuracy: ON 100% / OFF 0%
Failed-strategy repetition: ON 0% / OFF 100%
False influence: 0%
Cross-scope leakage: 0%
```

### 2:18–2:35 — Close

End with:

> DecisionVault does not just ask whether an agent can remember. It proves when
> remembered outcomes should change behavior — and when they should not.

Do not use copyrighted music. Keep the final exported video below three minutes.
