# Least-Privilege Database Runtime Evidence

Date: 2026-08-14

Status: **PASS** for CockroachDB table privileges and the hosted Lambda runtime.

## Problem under test

The original Lambda used the same CockroachDB identity that had been used during
schema work. A red-team privilege check showed that identity had `ALL` on the
application tables. That was unnecessary for the hosted runtime.

## Runtime role

A dedicated CockroachDB user named `decisionvault_runtime` now backs the Lambda
`DATABASE_URL`. Its application privileges are limited to:

```text
decision_episodes:
  SELECT
  INSERT
  DELETE

decision_memory_heads:
  SELECT
  INSERT
  UPDATE
  DELETE
```

DDL remains a separate migration/admin concern.

CockroachDB's `public` schema initially granted `CREATE` to `PUBLIC`, which meant
the first negative privilege test still allowed the runtime user to create a
table. The migration administrator was therefore granted explicit schema CREATE
and schema CREATE was then revoked from `PUBLIC`; schema `USAGE` remains.

The runtime negative test now returns `InsufficientPrivilege` for `CREATE TABLE`.

## Hosted regression

After Lambda `DATABASE_URL` was switched to the runtime account:

```text
judge /demo                  HTTP 200 / PASS / cleaned
judge /governance-demo       HTTP 200 / CONFLICT_ABSTAIN / cleaned
agent /execute               HTTP 200
agent /record                HTTP 201
agent /decide                HTTP 200
decision                     REFRESH_PAYMENT_TOKEN
memory_influenced            true
least_privilege_live_app     PASS
cleanup_rows                 (0, 0)
```

This demonstrates that the smaller privilege set is sufficient for the current
application while DDL is no longer available to the runtime identity.

## Boundary

The runtime role still needs `DELETE` because the hackathon judge demos clean up
their temporary scopes and supersession removes obsolete governed heads. A more
strict production split could move demo cleanup behind a separate privileged
maintenance procedure and reduce the steady-state agent role further.
