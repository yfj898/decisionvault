# DecisionVault Status

Phase 0 — Project bootstrap: PASS
Phase 1 — Deterministic memory vertical slice: PASS
Phase 2 — CockroachDB Cloud persistent memory: PASS
Phase 3 — Distributed Vector Index: PASS
Phase 4 — CockroachDB Managed MCP: PASS
Phase 5 — Bounded model integration (NVIDIA live; Bedrock optional): PASS
Phase 6 — AWS Lambda deployment: PASS
Phase 7 — UI / production hardening: PASS
Phase 8 — Benchmark / ablation: PASS
Phase 9 — Demo / Devpost submission: READY FOR RECORDING (final video + submit pending)

Baseline:
8 tests PASS

Current local verification:
113 tests PASS
Production hardening v4: PASS (real production DVI query / shared MCP audit SQL / hot secret refresh / compromised-producer retirement / fail-closed readiness / advisor-free execution / input bounds / long-term receipt replay)
Real CockroachDB production ANN EXPLAIN: `vector search` + `decision_memory_heads_scope_space_semantic_vec_idx` PASS
Production exact-threshold coverage remains unbounded and scope-scanned for correctness: PASS
MCP auditor now imports the same production ANN + coverage SQL builders: PASS
Managed MCP live re-run in this pass: NOT RUN (no MCP API key / cluster ID in current local environment; historical Phase 4 evidence retained)
Secrets Manager warm-process refresh TTL: PASS (default 30s; deterministic refresh regression)
Unknown/retired producer reconciliation: hosted head remaining=0 / revocation audit=1
Readiness security controls: agent auth / receipt signing / demo auth / sandbox all PASS
Hosted `/execute` advisor removed from critical path: model provider/explanation both null
Application request bounds: oversize situation HTTP 400
Recorded receipt replay beyond 15-minute issuance TTL: HTTP 201 / idempotent replay PASS
Post-hardening-v4 production semantic benchmark: 14/14 PASS
Boundary hardening v3: PASS (server-owned sandbox scenario / mandatory memory governance / event-time head ordering / backend-independent revoke / unbounded governance coverage)
Caller-supplied `/execute` scenario rejected: PASS
Caller-supplied `/decide memory_enabled=false` rejected: PASS
Late older execution receipt cannot replace newer governed head: PASS
Late older receipt cannot resurrect a revoked producer head: PASS
Deterministic fallback recall honors revocation audit: PASS
33 governed heads returned by exact-threshold coverage beyond ANN top-32: PASS
Hosted caller scenario override: HTTP 400
Hosted caller memory-disable override: HTTP 400
Hosted reverse-order signed-receipt submission: newer head preserved / old receipt history-only
Hosted revoke → deterministic fallback recall: 0 episodes
Post-boundary-v3 production semantic benchmark: 14/14 PASS
Multi-agent follow-up hardening: PASS (pre-governance candidate filtering / atomic supersession / governed-only advisor evidence)
6+ distinct-head adversarial governance regression: PASS
Stale/revoked crowding regression: PASS
Cloud supersession-vs-normal-write stale correction rejection: PASS
Advisor governed-evidence-only regression: PASS
First-class conflict abstention (`strategy=null`, `action=ABSTAIN`, `executable=false`): PASS
Execution gateway policy re-check / abstention block: PASS
Authenticated producer-bound `/revoke` contract: PASS
CockroachDB revocation audit + idempotent replay Cloud proof: PASS
Namespace-bound scope-prefix authorization (no raw `startswith`): PASS
Wildcard scope grants / duplicate agent identities rejected: PASS
Semantic embedding-space schema migration: PASS
Cross-embedding-space recall fails closed: PASS
CAS-safe semantic re-embedding migration utility: PASS
Real Cloud legacy-space → current-space re-embed proof: PASS
Phase 9 single-page DVI / MCP / benchmark evidence UI: PASS
Phase 9 1920×1080 real-click recording automation: READY
Phase 9 hosted evidence panel deployment: PASS
Phase 9 compressed 1920×1080 Xvfb functional dry-run: PASS
CockroachDB Cloud persistence smoke: PASS
Fresh-process recall changed agent behavior: PASS
Memory-off causal baseline: PASS
Cloud smoke rows cleaned after verification: PASS
CockroachDB Distributed Vector Index created: PASS
EXPLAIN uses vector search + scope prefix: PASS
ANN vs exact recall@5: 1.000
Cross-scope perfect-match isolation: PASS
Phase 3 Cloud rows cleaned after verification: PASS
CockroachDB Managed MCP OAuth initialize: PASS
Managed MCP tools/list: 12 tools discovered
Managed MCP schema/index inspection: PASS
Managed MCP DecisionVault memory SELECT: PASS
Managed MCP EXPLAIN vector-search evidence: PASS
Phase 4 Cloud row cleaned after verification: PASS
Bounded model-advisor contract: PASS
NVIDIA auxiliary live provider authentication: PASS
NVIDIA + CockroachDB Cloud bounded advisor smoke: PASS
Amazon Bedrock provider: OPTIONAL (not a Phase 5 gate)
AWS Lambda Function URL handler contracts: PASS
AWS CLI remote login / STS identity: PASS
AWS Lambda `decisionvault-agent` active in `ap-northeast-1`: PASS
Public Function URL `/health`: HTTP 200
Function URL protected POST without demo token: HTTP 401
Lambda `/record` → CockroachDB Cloud persistence: HTTP 201
Lambda Memory ON decision: `REFRESH_PAYMENT_TOKEN`, influenced=True
Lambda NVIDIA explanation: PASS
Lambda Memory OFF baseline: `GENERIC_RETRY`, influenced=False
Phase 6 Cloud evidence scope cleanup: 0 rows
CloudWatch Lambda log group present: PASS
Public judge UI on AWS Lambda: PASS
Protected atomic `/demo` causal proof: PASS
Phase 7 Memory OFF: `GENERIC_RETRY`, influenced=False
Phase 7 Memory ON: `REFRESH_PAYMENT_TOKEN`, influenced=True
Phase 7 recalled episode count: 1
Phase 7 NVIDIA grounded explanation: PASS
Phase 7 temporary memory cleanup: 0 rows
Unauthorized `/demo`: HTTP 401
Browser DOM smoke (1440x1000 + 390x844): PASS
Security headers (CSP / nosniff / DENY / no-store): PASS
Phase 8 local benchmark: 56/56 PASS
Phase 8 CockroachDB Cloud deterministic benchmark: 28/28 PASS
Phase 8 Cloud + NVIDIA advisor ablation: 7/7 PASS
Phase 8 benefit target accuracy — Memory ON: 100%
Phase 8 benefit target accuracy — Memory OFF: 0%
Phase 8 failed retry repetition — Memory ON: 0%
Phase 8 failed retry repetition — Memory OFF: 100%
Phase 8 successful strategy reuse — Memory ON: 100%
Phase 8 successful strategy reuse — Memory OFF: 0%
Phase 8 control preservation — Memory ON: 100%
Phase 8 false influence rate — Memory ON: 0%
Phase 8 cross-scope leakage rate — Memory ON: 0%
Phase 8 NVIDIA advisor strategy invariance: 100%
Phase 8 Cloud evidence scope cleanup: 0 rows
Shared Agent A → Agent B local memory proof: PASS
Shared Agent A → Agent B CockroachDB Cloud proof: PASS
Shared-memory producer provenance visible: PASS
Shared-memory cross-scope isolation: PASS
Managed MCP Memory Auditor Agent live workflow: PASS
Managed MCP auditor producer provenance visible: PASS
Managed MCP auditor DVI EXPLAIN visible: PASS
Managed MCP auditor Cloud cleanup: 0 rows
NVIDIA `nv-embedqa-e5-v5` live embedding call: PASS (1024D)
Production semantic embedding `passage` / `query` separation: PASS
Hosted semantic retrieval uses native `VECTOR(1024)`: PASS
Legacy 1024D → 64D projection removed from hosted path: PASS
Production semantic DVI `decision_memory_heads_scope_space_semantic_vec_idx`: PASS
Production semantic hand-authored benchmark: 14/14 PASS
Production semantic benefit/control relevance gate calibrated to 0.40: PASS
Semantic paraphrase Cloud recall similarity: 0.4541
Semantic shared-memory strategy change: PASS
Semantic Cloud temporary rows cleanup: PASS
Live AWS Lambda semantic embedding configured: PASS
Live AWS Lambda cross-agent provenance: PASS
Agent API identity derived from server-side token grant: PASS
Caller-supplied `agent_id` rejected: HTTP 400
Valid agent token outside granted scope rejected: HTTP 403
Judge demo token rejected on agent API: HTTP 403
Agent token grants bind identity / scope / permission / trust: PASS
Public GitHub repository `yfj898/decisionvault`: PASS
GitHub repository visibility: PUBLIC
GitHub MIT license detection: PASS
Devpost copy-ready submission package: PASS
Private judge testing-instructions template: PASS
<3 minute video storyboard / narration plan: PASS
Multi-agent conflict governance unit suite: PASS
Balanced contradictory memories → `CONFLICT_ABSTAIN`: PASS
Server-side producer trust resolves winner without hiding conflict: PASS
Stale-memory propagation gate: PASS
Supersession removes obsolete episode from resolution: PASS
Governed-head candidate crowding resistance: PASS
Five duplicate episodes + one independent conflict → 2 governed heads: PASS
Unknown producer trust is conservative when registry is active: PASS
Competing successful strategies can abstain instead of silently picking: PASS
CockroachDB Cloud + NVIDIA semantic governance smoke: PASS
Governance Cloud temporary rows cleanup: PASS
Post-governance Phase 8 local regression: 56/56 PASS
Post-governance Phase 8 deterministic Cloud regression: 28/28 PASS
Protected `/governance-demo` deployed on AWS Lambda: PASS
Hosted contradictory memories → `CONFLICT_ABSTAIN`: PASS
Hosted governance `memory_conflict=True`: PASS
Hosted governance `strategy=null / action=ABSTAIN / executable=false`: PASS
Hosted `/execute` while conflict abstention active: HTTP 409 / no receipt
Hosted `/revoke` current-head removal: HTTP 200 / PASS
Hosted `/revoke` replay: idempotent / same revocation ID
Hosted planner after revoke: `GENERIC_RETRY / NO_SIGNAL`: PASS
Space-aware DVI EXPLAIN uses `decision_memory_heads_scope_space_semantic_vec_idx`: PASS
Unauthorized `/governance-demo`: HTTP 401
Hosted governance temporary rows cleanup: 0 rows
Hosted governance desktop Chrome DOM smoke: PASS
Hosted governance mobile Chrome DOM smoke: PASS
Final red-team P0 remediation evidence: PASS
Verified execution receipt unit contract: PASS
Execution receipt Cloud migration / unique index: PASS
Hosted `/execute` signed sandbox receipt: PASS
Hosted `/record` rejects caller-controlled outcome fields: PASS
Hosted receipt replay returns same episode: PASS
Hosted tampered receipt rejection: HTTP 400
Hosted verified failure still changes planner strategy: PASS
Verified receipt temporary rows cleanup: 0 rows
Typed `supersedes_episode_id UUID` migration: PASS
Partial unique supersession index: PASS
Same-producer current-head validation: PASS
Non-current supersession target rejected: HTTP 409
Hosted typed supersession history/head proof: PASS
Typed supersession temporary rows cleanup: 0 rows
Dedicated CockroachDB `decisionvault_runtime` user: PASS
Runtime `decision_episodes` privileges limited to SELECT / INSERT / DELETE: PASS
Runtime `decision_memory_heads` privileges limited to SELECT / INSERT / UPDATE / DELETE: PASS
Runtime schema CREATE denied with `InsufficientPrivilege`: PASS
Migration-admin schema CREATE preserved separately: PASS
Lambda switched to least-privilege CockroachDB runtime identity: PASS
Least-privilege hosted app regression: PASS
Dedicated non-root AWS `decisionvault-deployer` identity: PASS
Restricted deployer Lambda code/configuration update: PASS
Restricted deployer IAM administration probe: AccessDenied
AWS Secrets Manager runtime secret created: PASS
Lambda execution role scoped `GetSecretValue`: PASS
Lambda sensitive environment keys removed: PASS
Hosted runtime reports `aws-secrets-manager`: PASS
Secrets Manager `/demo` regression: PASS
Secrets Manager `/governance-demo` regression: PASS
Secrets Manager verified execution/record/decision regression: PASS
Secrets Manager temporary rows cleanup: 0 rows
CockroachDB connect timeout: 5s PASS
CockroachDB statement timeout: 8000ms PASS
Real CockroachDB SQLSTATE 40001 retry: PASS (2 attempts)
`/health/live`: HTTP 200 PASS
`/health/ready`: HTTP 200 PASS
Readiness Secrets Manager probe: PASS
Readiness CockroachDB probe: PASS
Readiness E5-v5 probe: PASS
Readiness warm-cache regression: PASS
CloudWatch EMF structured log events: PASS
CloudWatch `DecisionVault` metric namespace: PASS
CloudWatch request/error/latency metrics materialized: PASS
CloudWatch memory-influence/conflict/idempotent-replay metrics materialized: PASS
Observability sensitive/high-cardinality field scan: PASS
Public GitHub Actions deterministic CI workflow: PASS
GitHub Actions run `31767363853` (`b539b3e`): SUCCESS
CI deterministic tests / whitespace / tracked credential-shape scan: PASS
Concurrent execution-receipt replay: 10/10 HTTP 201 → 1 episode, 9 idempotent replays PASS
Concurrent typed supersession: HTTP 201 + HTTP 409 → 1 successor / 1 head PASS
Live semantic-provider degradation: readiness 503 → restore 200 PASS
CockroachDB distributed rate-limit table / runtime DML grants: PASS
Hosted application limiter: 4 concurrent at limit=2 → 2×200 + 2×429 + 0×5xx PASS
Rate-limit `Retry-After` header / response body: PASS
