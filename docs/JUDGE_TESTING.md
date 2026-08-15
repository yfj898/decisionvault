# Judge Testing — 90-Second Path

The primary judge experience requires no clone, install, terminal, database
credential, or model key.

## Open the live app

Use the public AWS Lambda Function URL from the Devpost **Try it out** field.

The page and health endpoint are public/read-only. The two proof actions require
the private judge token supplied in Devpost testing instructions.

## Test 1 — prove memory changes behavior

1. Paste the private judge token into **Demo access token**.
2. Click **Run live memory proof**.
3. Confirm:

```text
Memory OFF → GENERIC_RETRY
Memory ON  → REFRESH_PAYMENT_TOKEN
producer_agents=recovery-observer
PASS · temporary scope cleaned
```

What this proves:

> Agent B changed its next decision because of durable outcome evidence written
> by Agent A into CockroachDB — not because the agents shared an in-memory chat.

## Test 2 — prove conflicting memory cannot force execution

1. Click **Run conflict safety proof**.
2. Confirm:

```text
resolution=CONFLICT_ABSTAIN
action=ABSTAIN
strategy=null
executable=false
memory_conflict=true
memory_influenced=false
PASS
```

What this proves:

> Memory is allowed to influence a decision, but governance remains authoritative.
> When evidence conflicts, DecisionVault refuses to execute.

## Test 3 — inspect the production proof

Scroll to **Reproducible submission evidence** and confirm the page shows:

```text
257 / 257 tests
14 / 14 production semantic benchmark
30-minute hosted soak · 0 transport failures
30-minute hosted soak · 0 validation failures
0 rows post-run business-memory leakage
```

The same panel also shows the production CockroachDB semantic path and the
external-learning safety boundary:

```text
semantic_embedding VECTOR(1024)
Distributed Vector Index
Managed MCP
Outcome.UNKNOWN
business_outcome_verified=false
```

## What is actually running

- **CockroachDB Cloud** — authoritative persistent multi-agent memory.
- **Distributed Vector Indexing** — production semantic recall.
- **Cloud Managed MCP Server** — separate MemoryAuditorAgent path for memory,
  provenance, and vector-plan inspection.
- **AWS Lambda** — hosted decision/execution trust boundary and judge UI.
- **NVIDIA embeddings** — native 1024D semantic retrieval.
- **NVIDIA LLM** — explanation only, never the final strategy authority.

## External execution boundary

DecisionVault contains a real external side-effect adapter proven against a
dedicated deterministic GitHub Contents resource. Judges do **not** need to rerun
that mutating proof.

Production intentionally remains on the bounded sandbox execution provider until
a dedicated least-privilege external credential is available.

The important invariant is:

```text
external side effect verified
≠
business outcome verified
```

A verified external receipt therefore remains `Outcome.UNKNOWN` and cannot create
positive long-term memory or calibration evidence.

## Optional deep inspection

For judges who want to inspect implementation evidence after the 90-second path:

- `docs/evidence/PHASE3_DISTRIBUTED_VECTOR_INDEX.md`
- `docs/evidence/PHASE4_MANAGED_MCP.md`
- `docs/evidence/REAL_EXTERNAL_EXECUTION_SOAK_V11.md`
- `docs/evidence/PRODUCTION_HARDENING_V6.md`

The primary judging path does not require any local setup.

## Security / availability

- Never publish the demo token in README, screenshots, video, or source.
- Keep the hosted application and private judge token active through the full
  judging period.
- If the judge token must be rotated, update the private Devpost testing field at
  the same time.
- Do not activate the production GitHub execution provider for judging.
