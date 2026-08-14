# Governed Adaptive Memory v6 — Production Evidence

Date: 2026-08-14

Status: PASS

## Claim boundary

This evidence verifies the production upgrade to **Governed Adaptive Memory**
without creating a second execution authority path. L2 effectiveness statistics
remain non-authoritative; only governed L3 procedural/avoidance memory may enter
the deterministic policy, and hard conflict still produces a non-executable
abstention.

No database URL, password, AWS access key, NVIDIA API key, MCP OAuth token,
cluster identifier, demo token, or Secrets Manager value is stored here.

## Local gates

```text
pytest                                      178 / 178 PASS
Phase 8 local benchmark                     56 / 56 PASS
git diff --check                            PASS
v6 migration contract                       PASS
```

## CockroachDB Cloud migration

The v6 migration was applied with the migration-admin identity one statement per
transaction. After the normal online schema-propagation window, all four new
tables, the adaptive DVI, and the least-privilege runtime table grants were
visible.

```text
decision_memory_consolidation_candidates     present / 0 rows
decision_strategy_effectiveness              present / 0 rows
decision_governed_memories                   present / 0 rows
decision_governed_memory_support             present / 0 rows
adaptive DVI                                 present
decisionvault_runtime table DML grants       present
```

An immediate post-DDL probe observed one expected SQLSTATE 40001 descriptor
change while the online schema update propagated. Fresh-connection verification
then passed.

## Real adaptive concurrency smoke

Business operations ran with `decisionvault_runtime`; migration-admin was used
only for test cleanup. Runtime privileges were not widened.

```text
team promotion                              PASS
adaptive retrieval                         PASS
adaptive decision                          PASS
single-producer crowding blocked            PASS
independent contradiction abstains          PASS
post-promotion contradiction revokes L3     PASS
negative memory promoted                    PASS
negative-memory veto                        PASS
cross embedding revision blocked            PASS
consolidation vs normal write               PASS
consolidation vs supersession               PASS
consolidation vs revocation                 PASS
governance revision                         PASS
adaptive cloud checks                       13 / 13 PASS
adaptive cloud cleanup                      PASS
temporary rows                              0
```

This gate exposed a harness bug: cleanup reused the runtime identity and tried to
delete the append-only revocation audit table. The harness now supports a
separate migration-admin cleanup connection instead of expanding runtime grants.

## Adaptive DVI and exact coverage

A dedicated two-producer scope was promoted to L3 and inspected with the same
production SQL builders used by the runtime.

```text
promotion                                  PASS
adaptive ANN vector search                 PASS
adaptive DVI index                         PASS
coverage support-lineage join              PASS
coverage current-head join                 PASS
cleanup rows                               0
```

The observed vector-search plan used
`decision_governed_memories_scope_space_semantic_vec_idx`.

## Managed MCP

The expired prior OAuth grant was replaced through the official CockroachDB
Cloud MCP authorization flow. Only **Read Data** was authorized; optional
**Write Data** remained disabled.

The first v6 audit exposed a Managed MCP integration limit: `explain_query`
rejects queries over 16,384 characters. A 1024D vector rendered at fixed decimal
precision was repeated in the production SQL and exceeded that limit, causing a
false missing-plan result before CockroachDB received the EXPLAIN.

The fix changes only the MCP **plan probe literal** to a compact sign-preserving
1024D vector. Runtime retrieval/decision embeddings are unchanged, and the MCP
auditor still imports the exact production ANN/coverage SQL builders.

```text
cluster discovery                          PASS
seed L3 promotion                          PASS
server initialized                         true
required tools present                     true
L1 scope memory visible                    true
L1 producer provenance visible             true
L1 vector plan/index visible               true
L1 exact coverage visible                  true
L3 adaptive memory visible                 true
L3 producer/support provenance visible     true
L3 vector plan/index visible               true
L3 exact coverage visible                  true
memory auditor agent                       PASS
cleanup rows                               0
```

## AWS Lambda and hosted regression

The existing restricted `decisionvault-deployer` identity performed a code-only
Lambda update. Secrets Manager permissions and sensitive environment values were
not expanded or reintroduced.

```text
AWS STS restricted deployer                 PASS
Lambda state                               Active
Lambda last update                         Successful
runtime                                    python3.12
embedding revision                         decisionvault-prod-r1
Secrets Manager runtime                    configured
```

The first hosted v6 demo run found a second least-privilege bug: runtime demo
cleanup attempted `DELETE` on `decision_memory_revocations`, which production
correctly denies. The fix removes that deletion from runtime cleanup rather than
granting DELETE. A regression test now locks this boundary. The failed demo rows
were removed with migration-admin before redeployment.

After redeployment:

```text
/health/ready               HTTP 200 / ready
adaptive_memory_schema      true
adaptive_memory_current     true
readiness errors            []

/demo                       HTTP 200
expected memory change      true
cross-agent memory used     true
cleaned                     true

/governance-demo            HTTP 200
action                      ABSTAIN
executable                  false
resolution                  CONFLICT_ABSTAIN
memory conflict             true
cleaned                     true

hosted demo temporary rows  0
```

## Production semantic regression and final cleanup

```text
production semantic benchmark               14 / 14 PASS
embedding revision                           decisionvault-prod-r1
```

Final production memory/audit row counts after all migration, race, DVI/MCP,
hosted-demo, and benchmark probes:

```text
decision_episodes                           0
decision_memory_heads                       0
decision_memory_revocations                 0
decision_memory_consolidation_candidates    0
decision_strategy_effectiveness             0
decision_governed_memories                  0
decision_governed_memory_support            0
total                                       0
```

This closes the v6 production evidence while retaining fail-closed readiness,
append-only revocation audit, embedding-revision isolation, signed
snapshot/receipt execution binding, and deterministic conflict abstention.

## GitHub CI

The first v6 push reached GitHub successfully but CI failed during pytest
collection because Actions invokes `uv run --frozen pytest -q`: the project root
was not explicitly present in pytest `pythonpath`, so three tests importing
top-level `scripts.*` helpers could not resolve that package. This matched the
earlier local `uv run pytest` environment difference and was not a runtime or
test-logic failure.

`pyproject.toml` now declares both `src` and `.` in pytest `pythonpath`. The exact
CI command was reproduced locally before the follow-up push:

```text
uv sync --frozen --extra dev                 PASS
uv run --frozen pytest -q                    178 / 178 PASS
tracked credential-shape scan                PASS
```

Follow-up GitHub Actions evidence:

```text
run                                         31792492469
commit                                      5e5c3f0
workflow                                    CI
conclusion                                  SUCCESS
```
