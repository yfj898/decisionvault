# Readiness, Timeout, and Cockroach Retry Evidence

Date: 2026-08-14

Status: **PASS** for local contract, real CockroachDB timeout/retry behavior, and
the hosted AWS readiness endpoints.

## Database time budgets

Every new psycopg connection now applies bounded defaults:

```text
connect_timeout=5 seconds
statement_timeout=8000 ms
```

These values remain configurable through non-sensitive runtime settings. A real
CockroachDB Cloud probe returned `statement_timeout=8000`, confirming the server
accepted the connection options.

## Serialization retry

`CockroachVectorMemoryStore` retries the **entire database transaction** only for
SQLSTATE `40001`. Embedding calls happen outside the retry closure, so a
Cockroach transaction retry does not repeat the external NVIDIA request.

Other failures such as unique/idempotency violations are not generically retried
because they have separate application semantics.

A real CockroachDB conflict probe forced one transaction to read a value, allowed
a competing transaction to commit, and then attempted the stale update. Observed:

```text
real_retry_attempts=2
observed_retry_sqlstate=40001
retry_result=11
final_value=11
real_cockroach_serialization_retry=PASS
```

The temporary probe table was dropped afterward.

## Liveness vs readiness

DecisionVault now exposes separate endpoints:

```text
GET /health/live
  process-level liveness only

GET /health/ready
  AWS Secrets Manager load
  CockroachDB SELECT 1
  NVIDIA E5-v5 1024D embedding probe
```

The explanation advisor is deliberately not required for readiness because it is
non-authoritative: advisor failure does not block the deterministic memory
decision path.

Hosted result:

```text
/health/live      HTTP 200  status=live

/health/ready #1  HTTP 200  status=ready
Secrets Manager   true
database          true
semantic embedding true
errors            []
elapsed           ~4.0s

/health/ready #2  HTTP 200  status=ready
elapsed           ~0.28s
```

The readiness result is cached for 30 seconds per warm Lambda process so a public
readiness check does not amplify NVIDIA API traffic on every refresh.

## Boundary

Timeout and `40001` handling cover the current CockroachDB memory transaction
path. They are not a substitute for a full load test, provider rate-limit policy,
or multi-region chaos test; those remain larger-scale production exercises.
