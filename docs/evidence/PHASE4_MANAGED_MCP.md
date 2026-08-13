# Phase 4 Evidence — CockroachDB Cloud Managed MCP

Date: 2026-08-13

Status: PASS

## Claim boundary

This evidence proves that the real CockroachDB Cloud Managed MCP server was
authenticated with OAuth and actually executed read operations against the
DecisionVault cluster.

No bearer token, OAuth refresh token, SQL password, connection string, service
account key, or cluster ID is stored in this file or elsewhere in the repository.

The OAuth grant was created by a local MCP client and stored in the Ubuntu OS
keyring. The final verification used that grant through a standards-compliant
MCP 2025-06-18 Streamable HTTP client so the evidence reflects the MCP server
itself rather than an agent wrapper.

## MCP handshake

Observed from the real endpoint:

```text
HTTP status: 200
content-type: text/event-stream
MCP session ID returned: yes
protocolVersion: 2025-06-18
serverInfo.name: cockroachdb-cloud
serverInfo.version: 1.0.0
capabilities: logging, tools
```

## Tool discovery

`tools/list` returned 12 tools:

```text
create_database
create_table
explain_query
get_cluster
get_table_schema
insert_rows
list_clusters
list_databases
list_tables
select_query
show_running_queries
show_statement
```

Phase 4 used only read operations.

## Real cluster and schema inspection

The following Managed MCP calls succeeded:

```text
list_clusters: PASS
accessible clusters: 1
configured target cluster visible: true

get_cluster: PASS
CockroachDB version: v26.2.5
cloud provider: AWS
cluster state: CREATED
plan: BASIC

list_databases: PASS
defaultdb visible: true

list_tables: PASS
decision_episodes visible: true

get_table_schema: PASS
VECTOR(64) visible: true
decision_episodes_scope_embedding_vec_idx visible: true
vector_cosine_ops visible: true
```

## Real DecisionVault memory read through MCP

A dedicated Phase 4 episode was persisted in CockroachDB before the MCP read.
`select_query` was then executed through Managed MCP for that isolated scope.

Observed result:

```text
select_query: PASS
rows: 1
strategy: GENERIC_RETRY
outcome: FAILED
effectiveness: 0.1
scope matched requested evidence scope: true
episode ID present: true
```

This proves that Managed MCP inspected DecisionVault application memory rather
than only listing cloud metadata.

## Vector plan through MCP

`explain_query` was executed through Managed MCP for the same scoped vector
nearest-neighbor query used by the DecisionVault recall adapter.

Observed result:

```text
explain_query: PASS
vector search node present: true
decision_episodes_scope_embedding_vec_idx present: true
requested scope prefix present: true
```

This independently confirms through the official Managed MCP surface that the
live database exposes the distributed vector-search plan established in Phase 3.

## Cleanup

The dedicated Phase 4 evidence row was removed after the MCP verification:

```text
phase4_rows_after_cleanup=0
```

## Client compatibility note

During verification, the Codex agent wrapper successfully completed the OAuth
grant but its first agent-driven MCP request encountered an OAuth resource-binding
error in the wrapper transport. The OAuth credential itself was valid: using the
same OS-keyring grant with the standard MCP 2025-06-18 protocol returned HTTP 200,
created an MCP session, discovered the tools, and completed all calls above.

Therefore the Phase 4 claim is specifically that CockroachDB Cloud Managed MCP
OAuth and the real MCP tools were executed successfully. It does not claim that
the Codex agent wrapper path was itself error-free.

## Reproducible Memory Auditor Agent follow-up

The repository now includes `scripts/mcp_memory_auditor.py` and a bounded
`MemoryAuditorAgent`. The agent initializes the official Managed MCP endpoint,
requires the real `select_query` and `explain_query` tools, reads a scoped
DecisionVault episode including `producer_agent_id`, and independently checks the
nearest-neighbor query plan for the distributed vector-search node and
`decision_episodes_scope_embedding_vec_idx`.

The follow-up live run used an OAuth access token refreshed from the existing OS
keyring grant and produced:

```text
server_initialized=True
required_tools_present=True
scope_memory_visible=True
producer_provenance_visible=True
vector_plan_visible=True
vector_index_visible=True
memory_auditor_agent=PASS
auditor_rows_after_cleanup=0
```

This turns Managed MCP from a one-time verification surface into a reproducible
agentic operational/audit workflow without putting any OAuth token or cluster ID
in the repository.
