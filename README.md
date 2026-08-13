# DecisionVault

**Persistent decision memory for autonomous agents.**

DecisionVault is a new project for the **CockroachDB × AWS Hackathon — Build with Agentic Memory**.

The core claim is deliberately narrow and testable:

> An agent should remember not only what happened, but which strategy it used, whether it worked, and how that evidence should change the next decision.

## Frozen MVP

The first vertical slice demonstrates:

1. Session A encounters a payment-support case.
2. With no relevant memory, the agent chooses a generic retry strategy.
3. The strategy fails and the episode is persisted.
4. Session B encounters a semantically similar case.
5. The agent recalls the failed strategy and selects a different recovery strategy.
6. A memory-disabled baseline repeats the inferior strategy.

The local implementation is deterministic so the memory effect is testable before cloud credentials are connected.

## Competition architecture

```text
User / task
   |
   v
Decision Agent
   |
   +----> Amazon Bedrock (reasoning / embeddings adapter)
   |
   v
Memory Retrieval
   |
   +----> CockroachDB VECTOR similarity
   +----> structured episodic state
   |
   v
Outcome-aware policy
   |
   v
Action + verified outcome
   |
   v
CockroachDB persistent episode
```

Planned required competition integrations:

- CockroachDB Distributed Vector Indexing
- CockroachDB Cloud Managed MCP Server
- Amazon Bedrock
- AWS deployment (Lambda or ECS, chosen after the vertical slice is stable)

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
database persistence can be tested independently from model availability. It is
**not** a model-embedding claim; the Bedrock embedding provider belongs to a later
phase.

## Repository status

- [x] New project / isolated codebase
- [x] Frozen MVP
- [x] Deterministic memory-aware vertical slice
- [x] Memory-disabled baseline
- [x] CockroachDB vector schema bootstrap
- [x] CockroachDB memory adapter seam
- [x] Bedrock provider seam
- [ ] Real CockroachDB Cloud cluster
- [ ] Real Distributed Vector Index query evidence
- [ ] Managed MCP connection evidence
- [ ] Real Bedrock invocation evidence
- [ ] AWS hosted demo
- [ ] Public GitHub repository
- [ ] <3 minute demo video

## Security

Never commit:

- CockroachDB connection strings
- service-account API keys
- AWS credentials
- MCP bearer tokens

Use `.env` locally and commit only `.env.example`.

## License

MIT.
