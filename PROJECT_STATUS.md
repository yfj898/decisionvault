# DecisionVault Status

Phase 0 — Project bootstrap: PASS
Phase 1 — Deterministic memory vertical slice: PASS
Phase 2 — CockroachDB Cloud persistent memory: PASS
Phase 3 — Distributed Vector Index: PASS
Phase 4 — CockroachDB Managed MCP: PASS
Phase 5 — Amazon Bedrock: PENDING
Phase 6 — AWS deployment: PENDING
Phase 7 — UI / production hardening: PENDING
Phase 8 — Benchmark / ablation: PENDING
Phase 9 — Demo / Devpost submission: PENDING

Baseline:
8 tests PASS

Current local verification:
17 tests PASS
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
