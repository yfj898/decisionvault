# DecisionVault — Cloud Gate Checklist

This checklist reflects the current competition path. The original draft treated
Amazon Bedrock as a Phase 5 requirement; that was a project assumption, not a
competition requirement. The frozen submission path uses NVIDIA for embeddings /
bounded explanation and AWS Lambda for the required AWS deployment.

## Phase 2 — CockroachDB Cloud persistent memory

- [x] Dedicated CockroachDB Cloud cluster used by DecisionVault.
- [x] `scripts/bootstrap.sql` applied.
- [x] Real `DecisionEpisode` persistence through `CockroachVectorMemoryStore`.
- [x] Fresh-process persistence / recall proof.
- [x] Exact-scope retrieval isolation evidence.
- [x] Sanitized evidence stored without credentials.

## Phase 3 — Distributed Vector Index

- [x] Deterministic regression DVI on `decision_episodes.embedding VECTOR(64)`.
- [x] ANN vs exact comparison and `vector search` plan evidence.
- [x] Production semantic DVI on
  `decision_memory_heads.semantic_embedding VECTOR(1024)`.
- [x] Native NVIDIA E5-v5 query/passage path verified without the former 64D
  hosted projection.

## Phase 4 — CockroachDB Managed MCP

- [x] Official Managed MCP Server initialized against the DecisionVault cluster.
- [x] `select_query` used on actual DecisionVault memory.
- [x] `explain_query` used to audit a vector-search plan.
- [x] Repository-owned `MemoryAuditorAgent` supports the current semantic-head
  query contract in addition to the historical deterministic path.

## Phase 5 — Bounded model integration

- [x] Real NVIDIA model invocation.
- [x] Model output constrained to explanation-only authority.
- [x] Strategy invariance verified with and without the advisor.
- [x] Real NVIDIA `nv-embedqa-e5-v5` semantic embeddings.
- [ ] Amazon Bedrock remains an optional provider seam and is **not** part of the
  frozen competition claim or judge path.

## Phase 6 / 7 — AWS deployment and judge UI

- [x] AWS Lambda deployment in `ap-northeast-1`.
- [x] Judge-accessible Function URL and responsive UI.
- [x] CockroachDB remains the persistent memory authority.
- [x] Judge demo token separated from general agent API tokens.
- [x] General agent tokens bind identity, scope prefixes, permissions, and trust.

## Phase 8 / red-team gates

- [x] Deterministic local regression: 56/56.
- [x] Deterministic CockroachDB Cloud regression: 28/28.
- [x] Native-1024D hand-authored production semantic benchmark: 12/12.
- [x] Candidate-crowding adversarial regression.
- [x] Conflict / stale / supersession / cross-scope controls.
- [x] Hosted agent identity and scope-authorization tests.

## Evidence and security gate

- [x] No AWS credential in Git.
- [x] No CockroachDB password, connection string, service-account key, MCP bearer
  token, NVIDIA key, demo token, or raw agent token in Git.
- [x] Two CockroachDB official tools are demonstrated: Distributed Vector Index
  and Cloud Managed MCP.
- [x] AWS Lambda is demonstrably running.
- [x] Public GitHub repository and MIT license are available.
- [ ] Final <3 minute public video and Devpost submission remain Phase 9 work; the hosted single-page evidence UI is deployed and the 1920×1080 recording automation passed its compressed functional dry-run.
