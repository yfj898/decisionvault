# DecisionVault — Final Submission Architecture

This is the final architecture diagram for README/Devpost/video narration.

It is intentionally simple. Do not replace it with a decorative generated image.
The goal is for a judge to understand the memory and authority boundaries in
about 15 seconds.

## Primary diagram

```text
 Agent A / Agent B
       │
       │ authenticated request + bounded scope
       ▼
┌──────────────────────────── DecisionVault on AWS Lambda ────────────────────────────┐
│                                                                                     │
│   Governed retrieval ──→ deterministic policy ──→ signed decision snapshot          │
│          ▲                         │                         │                       │
│          │                         │                         ▼                       │
│          │                         │                current-policy revalidation      │
│          │                         │                         │                       │
│          │                         │                         ▼                       │
│          │                         │                  execution adapter              │
│          │                         │                         │                       │
│          │                         │                         ▼                       │
│          │                         │               side-effect verification          │
│          │                         │                         │                       │
│          │                         │                         ▼                       │
│          │                         └────────────── signed execution receipt v3        │
│          │                                                   │                       │
└──────────┼───────────────────────────────────────────────────┼───────────────────────┘
           │                                                   │
           │                                                   ▼
           │                                      business outcome verified?
           │                                         │ YES         │ UNKNOWN
           │                                         ▼             └──X no learning
           │                                   verified experience
           │                                         │
           ▼                                         │
┌────────────────────────────── CockroachDB Cloud ───┴────────────────────────────────┐
│                                                                                     │
│  L1 episodic evidence + governed heads                                               │
│        │                                                                            │
│        ├── Distributed Vector Index ──→ semantic recall                              │
│        │                                                                            │
│        └── deterministic consolidation ──→ L2 effectiveness ──→ L3 procedure/AVOID  │
│                                                                                     │
│  Managed MCP Memory Auditor ── read-only audit of memory, provenance, and DVI plan  │
└─────────────────────────────────────────────────────────────────────────────────────┘

 NVIDIA embeddings → semantic vectors
 NVIDIA LLM        → explanation only; never decision authority
```

## The four things a judge should notice

1. **CockroachDB is the memory system of record.** It stores the durable evidence
   and the governed adaptive-memory state.
2. **Distributed Vector Indexing makes memory useful.** It recalls semantically
   relevant outcome evidence for future agents.
3. **Memory is influential, not authoritative.** Deterministic governance can
   reject weak evidence or return non-executable `CONFLICT_ABSTAIN`.
4. **Learning requires verified business outcome.** A verified external side
   effect can remain `UNKNOWN` and is blocked from long-term memory.

## 15-second architecture narration

> CockroachDB is the authoritative memory layer. Distributed Vector Indexing
> recalls relevant outcome evidence, then deterministic governance decides whether
> that memory may influence the next action. AWS Lambda binds execution to a
> signed snapshot and verified receipt. Only independently verified business
> outcomes can return to long-term memory, while Managed MCP provides a separate
> audit path.

## Devpost caption

**DecisionVault separates memory from authority.** CockroachDB Cloud stores the
durable outcome memory, Distributed Vector Indexing recalls relevant evidence,
deterministic governance commits the action, AWS Lambda revalidates execution,
and only verified business outcomes can be learned. Managed MCP independently
audits memory provenance and the vector-search plan.

## Video usage

Do not switch to a generated diagram during the live video. Use the existing
judge page's **Authority boundary** card for the first 34 seconds and use this
diagram only as the canonical README/Devpost reference.
