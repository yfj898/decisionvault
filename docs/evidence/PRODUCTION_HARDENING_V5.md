# Production Hardening V5 Evidence

Date: 2026-08-14

Status: **PASS** for the implemented production runtime boundaries described
below. CockroachDB Managed MCP live authentication was not re-run because the
current local environment does not contain a Managed MCP API key / cluster ID;
the repository-owned auditor remains code-level synchronized with the exact
production ANN and governance-coverage SQL builders.

## Credential-bearing outbound HTTP

- NVIDIA bearer requests accept only
  `https://integrate.api.nvidia.com/v1/{embeddings,chat/completions}`.
- A mutable Lambda `NVIDIA_BASE_URL` can no longer redirect `NVIDIA_API_KEY` to
  another origin, scheme, port, path, query, or userinfo target.
- Credential-bearing NVIDIA, Managed MCP, and optional Bedrock HTTP paths reject
  redirects.
- Managed MCP bearer traffic is fixed to `https://cockroachlabs.cloud/mcp`.

## Reproducible Lambda package

- `requirements-lambda.txt` pins `psycopg[binary]==3.3.4`.
- The public CockroachDB Cloud CA is an explicit `--ca-file` /
  `COCKROACH_CA_FILE` build input.
- A missing/non-PEM CA or CA input containing private-key material fails before
  a deployment ZIP is produced.
- A clean Git archive independently resolved `psycopg==3.3.4` and
  `psycopg-binary==3.3.4`, then produced a ZIP containing the explicit public CA.

## Embedding generation isolation

The semantic space now includes an operator-owned generation contract:

```text
nvidia/nv-embedqa-e5-v5|revision=decisionvault-prod-r1|dim=1024|contract=query-passage-v1
```

Different revisions are distinct recall spaces. Current-head migration performs
a compare-and-swap against the previous embedding space before replacing the
head and immutable episode vector. Readiness fails closed if a revision is
missing or a current governed head belongs to another space.

## Event time and ingestion time

`DecisionEpisode` now carries:

- `observed_at`: verified event/observation time used for current-head ordering.
- `recorded_at`: DecisionVault ingestion time retained for immutable audit.

Late receipts remain history but cannot replace a newer current head because
ordering and supersession compare only `observed_at`. Legacy `created_at` rows
are conservatively backfilled into both fields because the historical ingestion
instant cannot be reconstructed after the fact.

The real CockroachDB v5 migration was applied one statement per transaction to
respect CockroachDB online-schema visibility. Its schema-migration statement
timeout is separately bounded at 120 seconds; the Lambda runtime statement
timeout remains 8000 ms.

## Decision snapshot / TOCTOU boundary

Executable `/decide` results include a server-signed decision snapshot binding
the authorized decider identity, scope, situation, strategy, semantic space,
deterministic policy/memory digest, contract revision, and issuance time.

Before issuing a sandbox execution receipt, `/execute` re-evaluates the current
advisor-free deterministic decision and recomputes the digest. An expired or
changed snapshot fails with HTTP 409 and no receipt. Replaying the same valid
snapshot yields the same sandbox receipt ID.

Decision and execution roles remain separate: an authorized planner may issue a
snapshot that a separately authorized executor consumes within the same scope.
The resulting receipt audits both `decision_agent_id` and the actual executor
`agent_id`. This is a sandbox execution boundary; it is not a claim that a real
payment network is connected.

## Real gates

```text
local deterministic tests                  138 / 138 PASS
production semantic conformance             14 / 14 PASS
production ANN EXPLAIN                       vector search PASS
production space DVI                         PASS
runtime schema CREATE                        denied PASS
Cloud temporary rows                         0 / 0 / 0
hosted /health/ready                         HTTP 200 PASS
hosted /demo                                 HTTP 200 PASS / cleaned
hosted /governance-demo                      HTTP 200 PASS / cleaned
hosted cross-role snapshot execution         PASS / cleaned
Lambda state / last update                   Active / Successful
```

The restricted AWS deployer was used for the Lambda code/configuration update;
no additional Secrets Manager permission was granted and sensitive runtime
values remain outside Lambda environment variables.

The final timeout audit also separated provider budgets inside the hosted
30-second function deadline: semantic embedding calls are clamped to 12 seconds
and the non-authoritative advisor to 5 seconds. The CockroachDB runtime statement
timeout remains 8 seconds, preventing a slow explanation provider from consuming
the whole Lambda deadline before graceful deterministic fallback can run.
