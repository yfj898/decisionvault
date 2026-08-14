# Verified Execution Receipt Evidence

Date: 2026-08-14

Status: **PASS** for the hosted DecisionVault payment-recovery sandbox.

## Problem under test

Before this hardening step, the general `/record` API accepted caller-supplied
`outcome`, `effectiveness`, and `confidence`. That was a valid integration seam,
but it meant the memory layer itself could not distinguish a verified execution
result from a caller assertion.

DecisionVault now separates execution from recording:

```text
authenticated agent
→ POST /execute
→ server-controlled payment-recovery sandbox scenario
→ HMAC-signed execution receipt
→ POST /record
→ signature / agent / scope / TTL verification
→ unique execution_receipt_id
→ persistent outcome memory
```

This is explicitly a hackathon payment-recovery sandbox, not a claim that the
receipt came from a real payment processor.

The general execution request does not accept a scenario selector. The hosted
fixture is selected through non-secret server configuration
`EXECUTION_SANDBOX_SCENARIO`; a request containing `scenario` is rejected. This
prevents an authenticated caller from choosing which outcome table row the
server will sign.

## Receipt binding

The signed payload binds:

```text
receipt_id
scope_id
agent_id
situation
strategy
scenario
outcome
effectiveness
confidence
issued_at
```

Changing any signed field invalidates the HMAC. A receipt is also rejected when
used by a different authenticated agent, in a different scope, or after its TTL.

## Idempotency boundary

`decision_episodes.execution_receipt_id` has a partial unique index:

```text
decision_episodes_execution_receipt_uidx
```

The API checks for an existing receipt before writing and the database unique
index remains the race-safe final boundary. Replaying a valid receipt returns the
original episode with `idempotent_replay=true` rather than creating duplicate
memory. Receipt TTL applies before a **new** record is accepted. For an already
persisted receipt ID, DecisionVault first verifies the signed agent/scope/payload
contract without the issuance-age gate, returns the existing episode if found,
and only applies the normal TTL when no prior record exists. This allows delayed
network/queue retries to remain idempotent beyond the 15-minute issuance window.

## Live AWS + CockroachDB verification

Observed hosted result:

```text
execute_http=200
outcome=FAILED
effectiveness=0.1
receipt_signed=True

record_http=201
episode_created=True
idempotent=False
verified_receipt=True

replay_http=201
same_episode=True
idempotent=True

decide_http=200
strategy=REFRESH_PAYMENT_TOKEN
memory_influenced=True
producer=recovery-observer-api

tampered_receipt_http=400

receipt_episode_rows=(1, 1)
governed_heads=1
live_verified_execution_idempotency=PASS
cleanup_rows=(0, 0)
```

The remembered failure therefore came from a server-signed execution result and
still caused the later planner agent to change strategy.

The receipt `issued_at` is also the observation/event time persisted for memory
ordering. Immutable history provides the producer/strategy event-time
high-watermark: a late older receipt is retained as history but cannot replace a
newer governed head, including after the newer head was revoked.

## Boundary

This closes caller-controlled outcome labels for the hosted general agent API,
but it does not claim integration with a real card network or payment processor.
A production vertical would replace the deterministic sandbox executor with an
external execution gateway / receipt verifier while keeping the same signed
receipt and idempotency contract.
