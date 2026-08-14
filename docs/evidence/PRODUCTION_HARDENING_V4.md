# Production Hardening v4 Evidence

Date: 2026-08-14

Status: **PASS** for the five boundaries targeted in this hardening pass.

## 1. Production DVI and MCP audit-query parity

`CockroachVectorMemoryStore.recall_governed()` and `MemoryAuditorAgent` now
import the same SQL builders from `decisionvault.memory.governed_query`.

The production semantic path is intentionally two-stage:

```text
DVI-compatible ANN top-32
  scope_id + semantic_embedding_space + vector ORDER/LIMIT

plus

exact threshold coverage
  revocation + lifecycle + qualified outcome + similarity gate

→ merge by episode_id
→ deterministic governance resolver
```

Real CockroachDB Cloud EXPLAIN against a temporary 200-head scope:

```text
production_ann_vector_search = true
production_ann_space_dvi     = true
coverage_scope_scan          = true
```

The temporary scope was removed afterward. The current local environment does
not contain a Cockroach Managed MCP API key or cluster ID, so this pass did not
pretend to perform a new live MCP call. Unit coverage captures both EXPLAIN SQL
requests and verifies the auditor uses the production ANN and coverage shapes.
Historical live Managed MCP Phase 4 evidence remains separate.

## 2. Hot secret refresh and compromised-producer retirement

Managed Secrets Manager values now refresh on a bounded warm-process TTL
(`SECRET_REFRESH_SECONDS`, default 30s) and replace stale managed environment
values. Authenticated POST handling periodically reconciles current memory heads
with active agent grants.

Real CockroachDB Cloud retirement proof:

```text
retired_heads                = 1
compromised_head_remaining   = 0
revocation_audit_rows        = 1
```

Hosted Lambda proof with an injected unknown producer head:

```text
/decide                      HTTP 200
compromised head remaining   0
revocation audit             1
```

## 3. Fail-closed readiness

Readiness now requires all of:

```text
Secrets Manager hydration
CockroachDB connectivity
memory-governance schema
semantic embedding provider
parseable non-empty agent grants
valid execution receipt signing secret
non-empty demo authentication token
valid server-owned sandbox scenario
```

Hosted result after deployment:

```text
/health/ready                HTTP 200 / ready
agent_auth                   true
execution_receipt_signing    true
demo_auth                    true
execution_sandbox            true
```

## 4. Execution latency boundary and input limits

The general `/execute` route still performs semantic memory retrieval and the
deterministic policy gate, but removes the explanation-only advisor from that
request's critical path before `decide()` is called.

Hosted result:

```text
/execute                     HTTP 200
policy model_provider        null
policy model_explanation     null
```

Application limits are enforced before external POST work:

```text
request body                 <= 16 KiB
scope_id                     <= 256 characters
situation                    <= 4096 characters
```

A 4097-character hosted situation returned HTTP 400.

## 5. Long-term receipt replay semantics

The normal 15-minute receipt TTL still prevents a previously unseen stale
receipt from creating new memory. An already-recorded, correctly signed receipt
ID can now be replayed after that issuance TTL and returns the existing episode.

Hosted proof using a pre-existing receipt row and a correctly signed receipt
issued 20 minutes earlier:

```text
/record                      HTTP 201
idempotent_replay            true
same existing episode        true
```

## Regression gates

```text
local deterministic tests              113 / 113 PASS
production semantic conformance         14 / 14 PASS
hosted Lambda                           Active / Successful
temporary audit rows after cleanup      0
```
