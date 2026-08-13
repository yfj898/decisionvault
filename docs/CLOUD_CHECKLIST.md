# DecisionVault — Next Cloud Gate Checklist

The deterministic starter is frozen. Cloud phases must preserve the Memory OFF / Memory ON causal baseline and must not claim an integration until real evidence exists.

## Phase 2 — CockroachDB Cloud persistent memory

- [ ] Create a dedicated CockroachDB Cloud cluster for DecisionVault.
- [ ] Apply `scripts/bootstrap.sql` to the real cluster.
- [ ] Persist a real `DecisionEpisode` through `CockroachVectorMemoryStore.save()`.
- [ ] Restart the app/process and prove the episode survives process lifetime.
- [ ] Recall the persisted episode in the same `scope_id` and prove cross-scope isolation.
- [ ] Capture sanitized SQL/query evidence without credentials.

## Phase 3 — Distributed Vector Index

- [ ] Confirm the active CockroachDB Cloud version and current official vector-index syntax.
- [ ] Create the supported distributed vector index on episode embeddings.
- [ ] Run a real nearest-neighbor query for a similar situation.
- [ ] Verify the query plan/index behavior with real evidence.
- [ ] Re-run the Memory OFF / Memory ON behavioral proof against CockroachDB-backed recall.

## Phase 4 — CockroachDB Managed MCP

- [ ] Configure the official Managed MCP Server for the DecisionVault cluster.
- [ ] Use MCP to inspect or query actual DecisionVault memory data.
- [ ] Save sanitized evidence that proves MCP executed, not merely that it was configured.

## Phase 5 — Amazon Bedrock

- [ ] Select the smallest suitable Bedrock model/embedding model.
- [ ] Run at least one real Bedrock invocation.
- [ ] Feed Bedrock output into the untrusted reasoning/embedding layer without bypassing deterministic memory controls.
- [ ] Capture sanitized AWS-side invocation evidence.

## Phase 6 — AWS deployment

- [ ] Choose Lambda + API Gateway or ECS based on the smallest reliable demo path.
- [ ] Deploy a judge-accessible functional demo.
- [ ] Verify the deployed app still uses CockroachDB as persistent memory authority.

## Evidence and security gate

- [ ] No AWS access key or secret key in Git.
- [ ] No CockroachDB password, connection string, service-account key, or MCP bearer token in Git.
- [ ] At least two CockroachDB official tools are demonstrably running in the final submission.
- [ ] At least one AWS service is demonstrably running in the final submission.
- [ ] Every cloud claim has reproducible evidence.
