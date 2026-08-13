# DecisionVault Status

Phase 0 — Project bootstrap: PASS
Phase 1 — Deterministic memory vertical slice: PASS
Phase 2 — CockroachDB Cloud persistent memory: PASS
Phase 3 — Distributed Vector Index: PASS
Phase 4 — CockroachDB Managed MCP: PASS
Phase 5 — Bounded model integration (NVIDIA live; Bedrock optional): PASS
Phase 6 — AWS Lambda deployment: PASS
Phase 7 — UI / production hardening: PENDING
Phase 8 — Benchmark / ablation: PENDING
Phase 9 — Demo / Devpost submission: PENDING

Baseline:
8 tests PASS

Current local verification:
25 tests PASS
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
