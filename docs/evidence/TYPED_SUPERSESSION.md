# Typed Supersession Evidence

Date: 2026-08-14

Status: **PASS** for local contract, CockroachDB migration, and hosted AWS path.

## Problem under test

The earlier governance implementation carried `supersedes_episode_id` only in
JSON evidence. That was sufficient for a controlled read-time demonstration, but
it did not prevent an invalid target, cross-producer correction, repeated
replacement of an already-obsolete target, or a concurrent double successor.

## Remediation

CockroachDB now stores typed correction metadata:

```text
decision_episodes.supersedes_episode_id UUID
decision_memory_heads.supersedes_episode_id UUID
decision_episodes_supersedes_uidx
```

The partial unique index allows at most one direct successor for a non-null
supersession target.

Before accepting a correction, the hosted API verifies that the target:

1. is a valid UUID;
2. exists in the same requested scope;
3. was produced by the same authenticated agent;
4. is still the current governed head.

Targets that are no longer current return HTTP `409`. The database unique index
is the final race-safe boundary if two corrections compete concurrently.

## Hosted proof

The live test used two independently signed execution receipts from the same
authenticated producer:

```text
Episode A
strategy=GENERIC_RETRY
verified outcome=FAILED

Episode B
strategy=REFRESH_PAYMENT_TOKEN
verified outcome=SUCCESS
supersedes_episode_id=A
```

Observed result:

```text
episode_a_http=201
episode_b_http=201
stale_supersession_http=409

history_rows=2
B typed supersedes A=True

governed heads=1
current head strategy=REFRESH_PAYMENT_TOKEN
current head supersedes=A

live_typed_supersession=PASS
cleanup_rows=(0, 0)
```

Immutable history therefore keeps both observations, while production recall
uses only the corrected current head.

## Boundary

This correction contract is scoped to the authenticated producer's own current
memory. It does not implement an organization-wide approval workflow for one
agent to revoke another agent's evidence; such cross-producer correction would
require a separate privileged governance role and audit policy.
