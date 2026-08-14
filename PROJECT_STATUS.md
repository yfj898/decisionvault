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
Phase 9 — Demo / Devpost submission: PENDING

Baseline:
8 tests PASS

Current local verification:
58 tests PASS
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
Production semantic DVI `decision_memory_heads_scope_semantic_vec_idx`: PASS
Production semantic hand-authored benchmark: 12/12 PASS
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
