# Concurrency, Provider Degradation, and Rate-Limit Evidence

Date: 2026-08-14

Status: PASS for bounded production red-team cases against the hosted AWS Lambda
and real CockroachDB Cloud runtime.

This evidence does not claim a sustained high-volume soak test. It verifies the
specific race, provider-failure, and overload boundaries identified during the
final red-team audit.

## Concurrent execution-receipt replay

One server-signed execution receipt was submitted to the hosted `/record` route
from ten concurrent callers.

```text
HTTP 201 responses                  10 / 10
unique returned episode IDs         1
idempotent replay responses          9
CockroachDB episode rows             1
distinct execution receipt IDs       1
```

The unique receipt index remains the race-safe final boundary even when callers
pass the application-level pre-check concurrently.

## Concurrent supersession

Two different verified correction receipts attempted to supersede the same
current episode concurrently.

```text
responses                           HTTP 201 + HTTP 409
history rows                         2
successors of original target        1
current governed heads               1
```

The losing correction is surfaced as an explicit conflict rather than a 500 or
a second successor.

## Semantic-provider degradation

For a controlled live test, only the non-sensitive `NVIDIA_BASE_URL` Lambda
configuration was temporarily changed to an invalid endpoint. The runtime secret
and database configuration were not changed.

```text
degraded /health/ready   HTTP 503
database                 true
semantic_embedding       false
errors                    present

restored /health/ready   HTTP 200
semantic_embedding       true
```

This makes the dependency contract explicit:

- explanation advisor failure is fail-open for the already committed strategy;
- semantic embedding is retrieval-critical and therefore fails readiness closed.

The original Lambda configuration was restored in `finally` and re-verified.

## Distributed application rate limit

The AWS account's current regional concurrency quota is too small to reserve a
positive per-function concurrency value while retaining the platform's required
unreserved minimum. DecisionVault therefore does not claim reserved concurrency
as its rate limiter.

Instead, protected application routes use a CockroachDB-backed fixed-minute
bucket keyed by server-bound principal and route group. The counter is atomic,
shared across Lambda instances, and protected by CockroachDB serialization
retry.

Runtime grants on `decision_rate_limits` are limited to:

```text
SELECT
INSERT
UPDATE
DELETE
```

The authenticated agent API was temporarily configured to `2 requests/minute`
and four requests were issued concurrently, below the AWS account-level
concurrency boundary:

```text
HTTP 200                              2
HTTP 429                              2
HTTP 5xx                              0
rate_limited JSON responses           2
Retry-After response header           present
retry_after_seconds response field    present
CockroachDB bucket count              4
```

The official agent limit was restored afterward (default 60/minute), and the
test principal's rate-limit rows were deleted.

An earlier 20-request burst produced platform-level Lambda throttling as well as
successful responses. Because AWS account throttling can occur before the
function executes, that burst is deliberately **not** used as evidence for the
application limiter.

## Remaining boundary

This is bounded production-hardening evidence, not a long-duration load study.
DecisionVault does not claim sustained high-RPS soak testing, multi-region load
testing, or an adaptive/token-bucket rate-control algorithm.
