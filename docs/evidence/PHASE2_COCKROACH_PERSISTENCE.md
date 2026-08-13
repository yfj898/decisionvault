# Phase 2 Evidence — CockroachDB Cloud Persistent Memory

Date: 2026-08-13

Status: **PASS**

## Claim under test

DecisionVault must prove that an outcome episode is persisted outside the agent
process, recalled by a fresh agent in a similar future situation, and causally
changes the next strategy. A memory-disabled baseline must continue to select the
inferior default strategy.

## Environment

- Real CockroachDB Cloud cluster
- TLS certificate verification enabled (`sslmode=verify-full`)
- Psycopg DB-API connection
- `decision_episodes.embedding` stored as `VECTOR(64)` for the deterministic
  Phase 2 hashing embedder
- No database credentials stored in the repository

The deterministic hashing embedder is only a Phase 2 persistence test seam. It is
not presented as a model-embedding integration; Amazon Bedrock remains Phase 5.

## Verification sequence

The smoke was executed with separate Python processes for seed and recall:

```text
bootstrap schema
→ seed process writes failed GENERIC_RETRY episode
→ fresh recall process queries CockroachDB
→ Memory ON selects REFRESH_PAYMENT_TOKEN
→ Memory OFF selects GENERIC_RETRY
→ direct SQL query verifies the persisted failed row
→ cleanup removes the smoke row
```

## Sanitized observed results

```text
bootstrap=PASS

seed_strategy=GENERIC_RETRY
rows_after_seed=1

memory_on_strategy=REFRESH_PAYMENT_TOKEN
memory_on_influenced=True
recalled_episode_ids=<same persisted episode id>

memory_off_strategy=GENERIC_RETRY
memory_off_influenced=False

persisted_rows=1
persisted_strategy=GENERIC_RETRY
persisted_outcome=FAILED
persisted_effectiveness=0.1
cockroach_server=PASS

rows_after_cleanup=0
```

## Causal interpretation

The seed and recall operations did not share in-process episode state. The recall
process constructed a new `CockroachVectorMemoryStore` and a new `DecisionAgent`,
then retrieved the prior failed episode from CockroachDB Cloud. With memory
enabled, that recalled outcome changed the selected strategy. With memory disabled
against the same database, the agent repeated the default `GENERIC_RETRY` strategy.

This satisfies the Phase 2 persistent-memory causal gate.

## Security note

The SQL connection string, password, Cloud host, and other credentials are
intentionally excluded from this evidence file and from Git.
