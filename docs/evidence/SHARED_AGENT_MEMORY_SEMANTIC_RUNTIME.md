# Shared Agent Memory + Semantic Runtime Evidence

Date: 2026-08-13

Status: **PASS**

## Claim under test

DecisionVault should support durable outcome sharing across agent identities
without turning memory into a global broadcast channel. Agent A may persist an
outcome in a shared scope; Agent B may use that evidence only when it queries the
same scope. Producer provenance must remain visible in the resulting decision.

The hosted runtime should also use a real semantic embedding provider rather than
the deterministic hashing embedder used by the reproducible baseline benchmark.

## Shared memory contract

New outcome episodes record `producer_agent_id` inside the existing `evidence`
JSONB field, so no schema or Distributed Vector Index migration was required.

Observed local and CockroachDB Cloud result:

```text
producer_agent_id=recovery-observer
consumer_agent_id=recovery-planner
shared_strategy=REFRESH_PAYMENT_TOKEN
shared_memory_influenced=True
shared_recalled_producer_agent_ids=recovery-observer
isolated_strategy=GENERIC_RETRY
isolated_memory_influenced=False
shared_agent_memory_smoke=PASS
cloud_shared_memory_rows_cleaned=PASS
```

This demonstrates collaboration through persistent shared evidence rather than
ephemeral message passing.

## Semantic embedding runtime

NVIDIA `nvidia/nv-embedqa-e5-v5` was invoked through the live NVIDIA embedding
endpoint and returned a 1024-dimensional embedding. DecisionVault uses the
provider's required retrieval modes:

- `passage` when persisting an episode;
- `query` when recalling a future situation.

The provider vector is projected through a deterministic signed feature hash into
the frozen CockroachDB `VECTOR(64)` schema. The projection preserves the already
verified Distributed Vector Index contract instead of introducing a late schema
migration.

A real CockroachDB Cloud smoke used a paraphrased future situation rather than a
near-duplicate string. Observed result:

```text
semantic_recalled_count=1
semantic_top_similarity=0.4541
semantic_strategy=REFRESH_PAYMENT_TOKEN
semantic_influenced=True
semantic_producer_ids=recovery-observer
semantic_shared_memory_smoke=PASS
semantic_rows_cleaned=PASS
```

The policy relevance threshold remained `0.30`; it was not lowered to make the
semantic test pass.

## Hosted AWS verification

After deployment, the live Lambda reported semantic embedding configured and the
protected `/demo` returned:

```text
memory_off_strategy=GENERIC_RETRY
memory_on_strategy=REFRESH_PAYMENT_TOKEN
memory_on_influenced=True
producer_ids=recovery-observer
model_provider=nvidia:meta/llama-3.1-8b-instruct
cleaned=True
live_multi_agent_semantic_demo=PASS
```

## Boundary

The payment-recovery scenario is the frozen end-to-end demonstration domain. The
evidence supports a reusable shared outcome-memory pattern; it does not claim
that DecisionVault has already been benchmarked across arbitrary business domains
or that the 64-dimensional projection is equivalent to the provider's full 1024D
embedding space.

No NVIDIA key, CockroachDB connection string, OAuth token, cluster ID, AWS
credential, or demo token is stored in this evidence.
