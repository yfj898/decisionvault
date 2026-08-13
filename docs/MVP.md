# DecisionVault — Frozen MVP

## Problem

Most agents retain facts or chat history. They often fail to retain a stronger form of memory:

**situation → decision → evidence → outcome → effectiveness**

Without that loop, an agent can repeat a strategy that already failed in a similar situation.

## Competition proof

The MVP is complete only when a judge can observe this causal chain:

```text
similar situation
→ CockroachDB recalls prior episode
→ prior outcome is visible to the agent
→ agent changes strategy
→ new outcome is persisted
```

A memory-disabled baseline must demonstrate the inferior behavior.

## P0 scope

### Memory model
- user/task scope
- situation text
- chosen strategy
- outcome
- effectiveness
- confidence
- timestamp
- embedding

### Retrieval
- semantic similarity
- recency
- outcome-aware ranking

### Agent behavior
- default strategy when no memory exists
- avoid a strongly relevant failed strategy
- prefer a strongly relevant successful strategy
- explain which memory influenced the decision

### Required external stack
- CockroachDB Cloud
- Distributed Vector Indexing
- CockroachDB Cloud Managed MCP Server
- Amazon Bedrock
- AWS deployment

## Explicit non-goals before submission
- multi-agent orchestration
- mobile client
- complex auth product
- broad CRM platform
- many unrelated workflows
- large evaluation suite before the real cloud vertical slice works

## Demo target

Under 3 minutes:

1. Session 1: no memory → generic retry → failure.
2. Memory record appears.
3. Session 2: similar issue → recalled failure → different strategy → success.
4. Baseline: memory off → generic retry again.
5. CockroachDB vector query / MCP evidence.
6. AWS-hosted app URL.
