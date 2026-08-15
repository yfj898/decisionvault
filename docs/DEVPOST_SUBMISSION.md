# DecisionVault — Final Devpost Submission

## Project title

DecisionVault

## Tagline

**RAG remembers information. DecisionVault remembers whether a decision worked.**

## Elevator pitch

DecisionVault is governed adaptive memory for agent teams. It stores what an
agent tried, whether it worked, and lets later agents use that evidence to change
future decisions — without letting retrieved memory, model output, or a verified
external side effect silently become execution authority or a false business
outcome.

## Inspiration

Most agent-memory demos answer one question:

> Can the agent retrieve something from the past?

We wanted to answer a harder one:

> Can we prove that a past outcome changed the next decision — and prove that
> weak, stale, contradictory, or out-of-scope memory did not?

That matters in production. Remembering an old message is useful. Remembering
that a strategy failed, deciding whether that evidence still applies, and
refusing to execute when memories conflict is much more valuable.

DecisionVault turns long-term memory into governed decision evidence.

## What it does

DecisionVault stores structured decision episodes in CockroachDB Cloud:

```text
situation
→ strategy
→ outcome
→ effectiveness
→ confidence
→ producer provenance
→ semantic embedding
```

When another agent sees a semantically similar situation, DecisionVault retrieves
relevant evidence with CockroachDB Distributed Vector Indexing, applies explicit
scope/applicability/conflict rules, and commits a deterministic decision.

The live demo shows the causal effect directly:

```text
Agent A records: GENERIC_RETRY failed
                    ↓
        CockroachDB persistent memory
                    ↓
Agent B · Memory OFF → GENERIC_RETRY
Agent B · Memory ON  → REFRESH_PAYMENT_TOKEN
```

The agents do not need to share an in-memory conversation. Agent B learns from
durable outcome evidence written by Agent A.

DecisionVault also handles the opposite case. If two governed memories conflict,
the result is not a guess:

```text
CONFLICT_ABSTAIN
action=ABSTAIN
strategy=null
executable=false
```

Memory can influence a decision, but it never gets execution authority by
itself.

## The trust boundary

For execution, DecisionVault binds the chosen strategy to a signed decision
snapshot, revalidates current policy immediately before execution, verifies the
side effect, and signs the resulting receipt.

The project also includes a real external-execution proof using a deterministic
GitHub Contents resource. That proof intentionally returns:

```text
Outcome.UNKNOWN
business_outcome_verified=false
```

Why? Because proving that an external write happened is not the same as proving
that a payment-recovery strategy succeeded. External transport success is
therefore blocked from long-term learning and calibration until an independent
business-outcome verifier proves SUCCESS or FAILED.

Production remains on the bounded sandbox execution provider until a dedicated
least-privilege external credential is available.

## How we built it

### CockroachDB Cloud — authoritative persistent memory

CockroachDB is the system of record for DecisionVault memory, not a secondary
cache. It stores immutable decision episodes, governed current heads, revocation
history, consolidation state, strategy-effectiveness projections, and promoted
procedural/avoidance memory.

The production semantic path stores native NVIDIA E5-v5 embeddings in:

```text
semantic_embedding VECTOR(1024)
semantic_embedding_space
```

The explicit embedding-space identifier prevents incompatible model generations
from being compared silently.

### CockroachDB tool 1 — Distributed Vector Indexing

The judge-facing production path uses a real CockroachDB Distributed Vector
Index over governed current memory heads:

```text
decision_memory_heads_scope_space_semantic_vec_idx
```

The agent uses that index to retrieve semantically relevant outcome evidence
inside the authorized scope. Retrieval happens before deterministic governance,
so stale, superseded, revoked, contradictory, or weak evidence can be rejected
before it affects the next action.

### CockroachDB tool 2 — Cloud Managed MCP Server

DecisionVault includes a reproducible `MemoryAuditorAgent` that connects to the
official CockroachDB Cloud Managed MCP Server.

It uses real MCP `select_query` and `explain_query` calls to:

- inspect DecisionVault memory and producer provenance;
- inspect the vector-search execution plan;
- verify that the real Distributed Vector Index is used.

Managed MCP is deliberately an audit surface rather than hidden application
plumbing: it gives an agent a separate, read-only way to verify what memory the
runtime is relying on and how CockroachDB is retrieving it.

### AWS service — AWS Lambda

The complete judge-facing application runs on AWS Lambda behind a Lambda Function
URL. The public UI and health routes are read-only; protected demo routes use a
separate judge token, while general agent mutations use server-bound per-agent
grants.

Readiness is fail-closed. It checks required production configuration and verifies
that runtime and consolidation connections point to the same CockroachDB
cluster/database before declaring the service ready.

### NVIDIA — semantic retrieval and bounded explanation

`nvidia/nv-embedqa-e5-v5` produces the native 1024D query/passage embeddings used
by CockroachDB vector retrieval.

`meta/llama-3.1-8b-instruct` may explain an already-committed strategy. It cannot
select, replace, or veto the decision. The model is useful, but it is outside the
decision-authority boundary.

## What makes DecisionVault different

### 1. We measure memory by changed behavior, not by retrieval

The demo includes a Memory OFF counterfactual. We show the exact same decision
path with and without persistent memory and verify that the action changes only
when governed outcome evidence justifies it.

### 2. Conflicting memory causes abstention, not confidence theater

Contradictory evidence produces a first-class non-executable decision. The
execution gateway rechecks that decision and refuses to issue a receipt while the
conflict remains active.

### 3. External side-effect verification is not automatic learning

DecisionVault separates "the external operation happened" from "the business
strategy worked." A verified side effect remains `UNKNOWN` until independent
domain evidence proves the outcome.

### 4. Long-term memory is layered and governed

```text
L1 · episodic evidence
L2 · strategy effectiveness
L3 · promoted procedural / AVOID memory
```

L2/L3 knowledge is derived deterministically and promoted only after governance.
An LLM cannot directly write a reusable rule into the execution path.

## Production evidence

DecisionVault is intentionally presented as a tested system, not just a happy
path demo.

```text
257 / 257 tests PASS
Production semantic benchmark: 14 / 14 PASS
Latest 30-minute hosted soak: 0 transport failures
Latest 30-minute hosted soak: 0 validation failures
Post-run business-memory leakage: 0 rows
```

The first sustained soak exposed a real cleanup-vs-consolidation race. We fixed
the ordering, added orphan-derived-row sweeping, proved runtime/consolidator
database co-location fail-closed, and then completed a later 30-minute soak with
zero transport or contract-validation failures.

That failure was useful: it changed the production design instead of being hidden
from the submission.

## Challenges we ran into

### Proving causality instead of similarity

"The agent found a similar memory" is not enough. We added Memory OFF controls,
benefit cases, false-influence controls, scope-isolation cases, and adversarial
semantic retrieval tests so memory influence is observable and falsifiable.

### Keeping retrieval from becoming authority

Semantic search is probabilistic. Execution cannot be. We separated retrieval,
governance, deterministic policy, signed snapshot, revalidation, execution, and
verified outcome into distinct authority boundaries.

### Learning from production failures without weakening the gates

Our sustained soak found a cleanup/consolidation race, and production readiness
later caught an overly privileged co-location check. Both were fixed by making
the invariants stronger, not by making readiness or cleanup more permissive.

## Accomplishments

- Real CockroachDB Cloud persistent multi-agent memory.
- Real Distributed Vector Index retrieval on native 1024D embeddings.
- Real CockroachDB Cloud Managed MCP audit workflow.
- One-click Memory OFF vs Memory ON causal proof.
- First-class `CONFLICT_ABSTAIN` with `executable=false`.
- Signed decision snapshots and provider-bound execution receipts.
- Real external side-effect proof with deterministic idempotency.
- External `UNKNOWN` outcomes blocked from L1 memory and calibration.
- Server-bound agent identity, scope, permission, revocation, and supersession.
- Fail-closed production readiness and CockroachDB serialization retry handling.
- 257/257 tests, 14/14 production semantic benchmark, and clean 30-minute hosted
  soak evidence.

## What we learned

Persistent memory becomes production infrastructure only when three things are
true at the same time:

1. the experience is durable;
2. retrieval is bounded by scope and applicability;
3. there is an explicit rule for when memory is allowed to change behavior.

We also learned that verification needs two levels. Verifying a side effect proves
what happened technically. Verifying a business outcome proves whether the
strategy worked. Treating those as the same event would teach the memory system
the wrong lesson.

## What's next

- Add an independent real business-outcome verifier for external executions.
- Extend the frozen payment-recovery strategy contract into a second business
  domain while preserving the same trust boundary.
- Replace hackathon token grants with enterprise workload identity / OIDC.
- Add multi-region recovery and higher-RPS load testing.
- Allow threshold promotion only after sufficiently diverse real telemetry passes
  the existing sampling, aging, and temporal-drift gates.

## Built with

CockroachDB Cloud, CockroachDB Distributed Vector Indexing, CockroachDB Cloud
Managed MCP Server, AWS Lambda, Python, NVIDIA NIM/API, native 1024D semantic
embeddings, JSONB, vector search, multi-agent systems, governed adaptive memory.

## Try it out

Live application:

`https://mfcr7b2k3j7lrwr44u35i5rchq0fbncb.lambda-url.ap-northeast-1.on.aws/`

Public source:

`https://github.com/yfj898/decisionvault`

## Architecture

Use the simple text diagram in `docs/ARCHITECTURE_SUBMISSION.md`. It is designed
to be readable directly in Markdown and does not require an uploaded image.

## Devpost form — CockroachDB tools used

Select:

- **Cloud Managed MCP Server**
- **Distributed Vector Indexing**

Short explanation to paste into the form:

> Distributed Vector Indexing powers production semantic recall over governed
> current memory heads in CockroachDB. The Cloud Managed MCP Server powers a
> separate MemoryAuditorAgent that inspects memory/provenance with `select_query`
> and verifies the real vector-search plan/index with `explain_query`.

## Devpost form — AWS services used

Select:

- **AWS Lambda**

Short explanation to paste into the form:

> AWS Lambda hosts the complete judge-facing DecisionVault application and trust
> boundary: authenticated decision requests, governed memory retrieval,
> deterministic policy, signed execution receipts, protected live demos, health,
> and fail-closed readiness.

## Devpost form — learning derived from the project

Suggested answer:

> Advanced. The project moved from simple persistent episodic memory to governed
> adaptive memory, native vector retrieval, cross-agent provenance, conflict
> abstention, signed execution receipts, production concurrency hardening, and
> telemetry-driven calibration gates. The most important lesson was that useful
> memory is not just retrievable memory: it needs explicit authority, verification,
> and failure boundaries before it can safely change behavior.

## Private judge testing instructions

Do **not** publish the token below in the repository, screenshots, or video.

Paste the value from local ignored file `.venv/demo-token` into Devpost's private
testing-instructions field:

```text
Open the Try it out URL.

Paste this private demo token into the "Demo access token" field:

<PASTE PRIVATE DEMO TOKEN HERE>

Test 1 — memory changes behavior
Click "Run live memory proof".

Expected:
- Memory OFF → GENERIC_RETRY
- Memory ON → REFRESH_PAYMENT_TOKEN
- producer_agents includes recovery-observer
- PASS banner confirms the temporary scope was cleaned

Test 2 — conflicting memory cannot force execution
Click "Run conflict safety proof".

Expected:
- resolution=CONFLICT_ABSTAIN
- action=ABSTAIN
- strategy=null
- executable=false
- PASS banner confirms cleanup

No installation is required for the primary judge path. The public repository
contains deeper reproducible evidence for Distributed Vector Indexing, Managed
MCP, semantic/adversarial tests, execution receipts, and production soak runs.
```

## Final video

The frozen public demo is defined in `docs/VIDEO_SCRIPT_2M45.md` and operationally
driven by `scripts/run_submission_demo.py`.

Target: **2:45**, 1920×1080, public YouTube/Vimeo, no credential visible, no
copyrighted music, and the CockroachDB memory layer must be visibly demonstrated.
