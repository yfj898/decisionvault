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
245 tests PASS
Real external execution v11: PASS / deterministic GitHub Contents side effect + exact-path replay + signed receipt v3
External execution safety: caller cannot select provider/repository/URL/payload / provider failure 503 without receipt / external UNKNOWN outcome cannot enter L1 memory or calibration
Real GitHub proof: first execution verified / idempotent replay verified / business_outcome_verified=false / broad local CLI token never copied into AWS
Production execution provider: still sandbox by design pending a dedicated least-privilege GitHub credential
GitHub Actions run `31859278177` (`c6c64bd`): SUCCESS for external-execution source commit
Post-c6 hosted readiness/demo/governance: PASS / execution_provider=sandbox / errors=0
Post-c6 semantic benchmark: 14/14 PASS
30-minute hosted route soak: 165 iterations / 330 requests / all HTTP 200 / transport failures 0 / validation failures 0 / overall p95 9819.796ms
30-minute post-soak audit found one governance-demo L2 strategy projection residue; cleanup-vs-consolidation race reproduced by ordering review and fixed
Cleanup race fix: `f6a208f` / authoritative L1 delete commits before adaptive/outbox delete
GitHub Actions run `31860957000` (`f6a208f`): SUCCESS / Lambda Active+Successful / deployed CodeSha matched
Post-fix 6-minute cleanup stress: 36 iterations / 72 requests / all HTTP 200 / failures 0 / crossed scheduled consolidation interval
Post-fix final business memory/outbox rows: all 8 tables = 0 / retained quality telemetry unchanged 2 decisions + 2 outcomes + 3 calibration runs
Adaptive smoke cleanup now retries Cockroach SQLSTATE 40001 transactions and self-heals the reserved `adaptive-cloud-*` namespace; final rerun 13/13 PASS / cleanup PASS / global business rows 0
Evidence: `docs/evidence/REAL_EXTERNAL_EXECUTION_SOAK_V11.md`, `reports/github-execution-smoke.json`, `reports/production-soak.json`, `reports/cleanup-stress.json`
Telemetry retention / aging / sampling-bias v3: PRODUCTION PASS / champion unchanged
V10 sampling schema: 3 statements PASS / sampling audit persisted / runtime still SELECT+INSERT only
Telemetry retention: raw decision+outcome pairs 180d / aggregate calibration runs 730d / consolidator-only DELETE
Sampling gate: label coverage >=80% / label-distribution TVD <=0.20 / scope+strategy diversity / >=5 per represented stratum / evidence span >=30d
Long-term aging gate: >=2 memory-age buckets / >=5 samples with memory age >30d / recent-vs-older drift segments >=5 each / temporal TVD <=0.35
Per-stratum challenger safety: scope / strategy / memory-age buckets each require >=95% success retention and <=5% harmful rate
Latest production calibration revision: telemetry-calibration-v3 / observed=1 / sampling_gate_pass=false / NO_PROMOTION
Latest sampling blockers: scope_coverage / strategy_coverage / evidence_span / memory_age_coverage / temporal drift not yet evaluable
Production calibration history: v1=1 / v2=1 / v3=1 append-only runs
Post-v10 semantic benchmark: 14/14 PASS
Post-v10 adaptive CockroachDB+NVIDIA adversarial/concurrency smoke: 13/13 PASS / cleanup 0
Post-v10 hosted readiness: HTTP 200 / calibration schema+config=True / errors=0
Post-v10 hosted demo/governance: PASS / final business memory rows=0
GitHub Actions run `31857083239` (`d7c815a`): SUCCESS for retention/sampling source commit
Memory calibration loop v2: PRODUCTION PASS / champion unchanged
V9 aggregate calibration schema: 4 statements PASS / runtime SELECT+INSERT only / consolidator SELECT only
Persisted production calibration run: decision rows=2 / labeled outcomes=2 / memory-exposed observed=1 / INSUFFICIENT_REAL_TELEMETRY
Promotion review: NO_PROMOTION / automatic threshold mutation=false / required real sample floor=30
Durable calibration cadence: existing consolidation Scheduled Event + persisted 24h due-check / no second EventBridge rule required
V9 hosted readiness: HTTP 200 / telemetry schema=True / calibration schema=True / calibration config=True / identity isolated=True / errors=0
Post-v9 production semantic benchmark with concurrent security reconciliation: 14/14 PASS
Post-v9 adaptive CockroachDB+NVIDIA adversarial/concurrency smoke: 13/13 PASS / cleanup 0
Post-v9 hosted demo/governance: PASS / final business memory rows=0 / quality telemetry retained 2+2 / calibration runs=1
GitHub Actions run `31808893606` (`309ab37`): SUCCESS for calibration-loop source commit
Real memory-quality telemetry calibration v1: PRODUCTION PIPELINE PASS / threshold change correctly withheld at N=1 memory-exposed verified outcome
CockroachDB v8 telemetry: append-only decision + verified-outcome tables / runtime SELECT+INSERT only / no UPDATE+DELETE
Telemetry privacy boundary: no raw situation/scope/agent/episode/memory identifiers inside quality_features; aggregate report privacy scan PASS
Champion/challenger shadow evaluation: 9 monotone-stricter profiles / executable alternate strategy => COUNTERFACTUAL_UNOBSERVED
Real calibration gate: minimum 30 memory-exposed outcomes / success retention >=95% / factual harmful rate <=5% / no automatic threshold mutation
First real hosted telemetry loop: 2 decisions + 2 verified outcomes / 1 memory-exposed labeled sample / GOVERNED_MEMORY REFRESH_PAYMENT_TOKEN -> SUCCESS 0.95
Real telemetry calibration report: INSUFFICIENT_REAL_TELEMETRY / recommended_profile=NONE / production champion unchanged
Telemetry Lambda readiness: HTTP 200 / memory_quality_telemetry_schema=True / errors=0 / deployed CodeSha256 matched source
Live semantic benchmark security-reconciliation race found and fixed without disabling reconciliation
Post-fix semantic benchmark under concurrent security reconciliation: 14/14 PASS
Post-telemetry adaptive CockroachDB+NVIDIA adversarial/concurrency smoke: 13/13 PASS / cleanup 0
Post-telemetry hosted demo/governance: HTTP 200 / memory change + cross-agent PASS / ABSTAIN CONFLICT_ABSTAIN PASS / cleaned
Final business memory/outbox rows: 0; retained anonymous quality telemetry: 2 decisions / 2 outcomes
Telemetry write-failure alarm + dashboard definitions: PASS; live CloudWatch reprovision pending fresh AWS governance login (restricted deployer intentionally not widened)
GitHub Actions run `31806122547` (`f63af3a`): SUCCESS for final telemetry + benchmark isolation source
Performance / cost / memory-quality calibration v1: LOCAL + REAL DATA PATH PASS
Bundled L1+L3 semantic recall: 1 NVIDIA query embedding + 1 CockroachDB connection / decision while preserving 4 ANN+exact SQL queries
Real 5× runtime benchmark: provider requests 2→1 (-50%) / DB connections 2→1 (-50%) / median recall 3161ms→1751ms (-44.6%)
L1 threshold calibration: current 0.30 similarity / 0.12 signal / 0.08 conflict = 8/8; unchanged
L3 threshold calibration: minimum effective confidence 0.15→0.30 / synthetic safety score 6/7→7/7
LONG_TERM strong-memory influence window at calibrated 0.30: PRIVATE≈121d / TEAM≈197d / GLOBAL≈228d before 365d hard expiry
Post-calibration real adaptive CockroachDB+NVIDIA smoke: 13/13 PASS / cleanup 0
Post-calibration production semantic benchmark: 14/14 PASS
Performance / quality production deployment: PASS / exact source commit `82ed977` / Lambda Active + Successful / CodeSha256 matched
Performance / quality hosted readiness: HTTP 200 / identity isolated=True / outbox schema=True / scope control=True / adaptive current=True / errors=0
Performance / quality hosted `/demo`: HTTP 200 / GENERIC_RETRY→REFRESH_PAYMENT_TOKEN / influenced=True / cross-agent=True / cleaned
Performance / quality hosted `/governance-demo`: HTTP 200 / ABSTAIN / executable=false / CONFLICT_ABSTAIN / cleaned
Performance / quality final production memory rows: all 8 memory/outbox tables = 0
GitHub Actions run `31801887048` (`82ed977`): SUCCESS for performance/cost/memory-quality source commit
Governed Adaptive Memory v7 local hardening: PASS
Governed Adaptive Memory v7 production cutover: PASS
Signing-key ID + retained verification keyring / legacy-keyless compatibility: PASS
Real hosted signing-key rotation: r1 → r2 / 2 retained verification keys / post-rotation readiness HTTP 200
Durable consolidation outbox / lease / exponential retry: PASS
Distinct runtime vs consolidator CockroachDB identity contract: PASS
PRIVATE / TEAM / GLOBAL server-owned memory-scope control: PASS
Memory-health EMF + EventBridge/CloudWatch provisioning contracts: PASS
Real CockroachDB v7 expand migration: PASS (9 statements / generation-safe outbox + consolidator role)
Lambda v7 deployment: Active / Successful / deployed package CodeSha256 matched
Hosted v7 `/health/ready`: HTTP 200 / consolidator DB=True / identity isolated=True / outbox schema=True / scope control=True / errors=[]
Real CockroachDB v7 contract migration: PASS (7 statements / runtime candidate+L2+support writes revoked / L3 INSERT+DELETE revoked)
Post-contract runtime outbox authority: SELECT+INSERT+UPDATE only / no DELETE
Post-contract consolidator adaptive authority: full DML on candidate/L2/L3/support + outbox completion
Hosted v7 `/demo`: HTTP 200 / expected change=True / cross-agent memory=True / cleaned
Hosted v7 `/governance-demo`: HTTP 200 / `CONFLICT_ABSTAIN` / executable=false / cleaned
EventBridge consolidation retry: ENABLED / rate(5 minutes) / 1 Lambda target / invoke permission present
CloudWatch memory operations: 3 alarms / 4-widget dashboard PASS
Real durable retry smoke: runtime enqueue → scheduled Lambda claim=1 → consolidator completed=1 / deferred=0 / cleanup=0
Post-v7 production semantic benchmark: 14/14 PASS
Post-v7 adaptive adversarial/concurrency smoke: 13/13 PASS with runtime L1 + consolidator L2/L3 + admin cleanup identities
V7 test-cleanup outbox gap found and fixed: initial 22 test-only PENDING obligations → final rerun outbox=0
Post-v7 production memory rows: episodes=0 / heads=0 / revocations=0 / candidates=0 / strategy-stats=0 / governed-memories=0 / support=0 / outbox=0
Post-adaptive Phase 8 local benchmark: 56/56 PASS
GitHub Actions run `31795994868` (`91ac96b`): SUCCESS for v7 hardening base commit
Governed Adaptive Memory v6 local implementation: PASS
L0 request-local Working Memory: PASS
L1 governed DecisionEpisode/current-head evidence remains authoritative: PASS
L2 strategy × situation-class effectiveness projection: PASS
L3 governed procedural + avoidance memory: PASS
Deterministic candidate → independent governance → promote/abstain contract: PASS
Distinct-producer promotion thresholds / producer-crowding resistance: PASS
Explicit applicability preconditions + exclusions before adaptive reuse: PASS
Negative-memory veto before positive-memory ranking: PASS
Independent contradiction invalidates prior active L3 rule: PASS
Memory-class-specific expiry + confidence decay: PASS
Legacy episodes without explicit applicability cannot auto-generalize: PASS
Cross-scope / cross-embedding-revision consolidation isolation: PASS
Late/stale evidence cannot reactivate or supersede newer governed knowledge: PASS
Consolidation-vs-normal-write / supersession / revocation revalidation suite: PASS
Decision governance trace → signed snapshot → signed receipt → outcome provenance: PASS
L2 semantic statistics cannot directly select execution strategy: PASS
Advisor receives committed governance trace only and remains non-authoritative: PASS
Adaptive DVI fast-path + exact support/current-head coverage SQL: PASS
Managed MCP adaptive auditor imports the same production SQL builders: PASS
Adaptive readiness schema/revision/current-support checks fail closed: PASS
Governed Adaptive Memory v6 migration parse: 15 statements / 4 runtime DML grants / 1 DVI PASS
Real CockroachDB Governed Adaptive Memory v6 migration: PASS
Real v6 tables / runtime table-level DML grants / adaptive DVI visibility: PASS
Real adaptive-memory CockroachDB + NVIDIA adversarial/concurrency smoke: 13/13 PASS
Real consolidation-vs-normal-write / supersession / revocation concurrency: PASS
Real adaptive smoke cleanup: 0 temporary rows
Real adaptive L3 EXPLAIN: `vector search` + `decision_governed_memories_scope_space_semantic_vec_idx` PASS
Real adaptive exact coverage includes support + current-head lineage: PASS
Managed MCP OAuth re-authorized with read-only data permission: PASS
Managed MCP L1 + L3 provenance / DVI / exact-coverage auditor: PASS / cleanup 0
Managed MCP 16,384-character EXPLAIN request bound: fixed with plan-only compact vector literal; production SQL builders unchanged
AWS restricted deployer STS identity recovery: PASS (`decisionvault-deployer`)
Lambda v6 deployment: Active / Successful
Hosted v6 `/health/ready`: HTTP 200 / adaptive schema=True / adaptive current=True
Hosted v6 `/demo`: HTTP 200 / expected memory change=True / cross-agent memory=True / cleaned
Hosted v6 `/governance-demo`: HTTP 200 / `CONFLICT_ABSTAIN` / executable=false / cleaned
Hosted demo least-privilege cleanup regression: fixed without granting runtime DELETE on append-only revocation audit
Post-v6 production semantic benchmark: 14/14 PASS (`decisionvault-prod-r1`)
Post-v6 production memory rows: episodes=0 / heads=0 / revocations=0 / candidates=0 / strategy-stats=0 / governed-memories=0 / support=0
Production hardening v5: PASS (fixed NVIDIA/MCP bearer destinations / reproducible Lambda CA+dependency build / explicit embedding revision / observed-vs-recorded audit time / signed decision snapshot TOCTOU binding / decider-executor role separation)
NVIDIA credential-bearing origin allowlist + redirect rejection: PASS
Embedding generation `decisionvault-prod-r1` included in semantic space: PASS
Cross-revision recall isolation + CAS migration regression: PASS
Real CockroachDB production-memory-v5 migration: 19/19 statements PASS
Real CockroachDB observed/recorded columns: NOT NULL + compatibility defaults PASS
Real CockroachDB current rows after v5 verification: episodes=0 / heads=0 / revocations=0
Post-v5 production ANN EXPLAIN: `vector search` + `decision_memory_heads_scope_space_semantic_vec_idx` PASS
Post-v5 production semantic benchmark: 14/14 PASS
Clean git-archive Lambda dependency resolution: psycopg/psycopg-binary 3.3.4 PASS
Clean git-archive Lambda package includes explicit public CockroachDB CA: PASS
Hosted readiness revision/head-space/provider-origin checks: HTTP 200 / PASS
Hosted `/demo`: HTTP 200 / PASS / cleaned
Hosted `/governance-demo`: HTTP 200 / `CONFLICT_ABSTAIN` / cleaned
Hosted cross-role planner snapshot → observer execute/record → planner recall: PASS / cleaned
Hosted outcome serialization exposes distinct `observed_at` + `recorded_at`: PASS
Lambda post-v5 deployment: Active / Successful
Lambda provider deadline budget: semantic <=12s / advisor <=5s inside 30s function timeout PASS
Managed MCP v5 live re-run: NOT RUN (no current MCP API key / cluster ID configured locally); code-level auditor uses the same production ANN + coverage SQL builders and exact fixed Cockroach MCP endpoint
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
