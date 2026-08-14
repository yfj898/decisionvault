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

New outcome episodes record `producer_agent_id` inside the immutable
`decision_episodes.evidence` JSONB audit history. Production semantic recall also
maintains one governed current head per `(scope_id, producer_agent_id, strategy)`
in `decision_memory_heads` so repeated writes cannot crowd independent producers
out of ANN top-K before governance.

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

An earlier hosted version projected the provider vector into `VECTOR(64)`. A
red-team ranking test showed that the 1024→64 projection could change nearest-
neighbor ordering, so the hosted path was migrated to the provider's native
`VECTOR(1024)` representation. Production recall now uses:

```text
decision_memory_heads.semantic_embedding VECTOR(1024)
decision_memory_heads_scope_semantic_vec_idx
```

The original `decision_episodes.embedding VECTOR(64)` and its DVI remain only as
deterministic regression evidence.

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

The deterministic/hash regression path retains its historical `0.30` relevance
gate. Production E5-v5 retrieval uses a separately calibrated `0.40` gate. The
calibration was driven by a hand-authored semantic benchmark: the lowest benefit
case scored `0.4810`, while an irrelevant same-scope distractor scored `0.3575`.
The production semantic suite passes `12/12` at `0.40`.

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

The general hosted `/record` and `/decide` routes now use per-agent opaque tokens.
Only SHA-256 token digests are stored in Lambda configuration; each digest binds
the agent identity, allowed scope prefixes, permissions, and trust. A caller that
supplies its own `agent_id` is rejected, and an otherwise valid agent token is
rejected outside its granted scope.

## Boundary

The payment-recovery scenario is the frozen end-to-end demonstration domain. The
evidence supports a reusable shared outcome-memory pattern; it does not claim
that DecisionVault has already been benchmarked across arbitrary business domains
or that the policy benchmark measures real payment business success. The current
semantic benchmark measures retrieval/governance conformance on hand-authored
cases, not open-domain generalization.

No NVIDIA key, CockroachDB connection string, OAuth token, cluster ID, AWS
credential, or demo token is stored in this evidence.
