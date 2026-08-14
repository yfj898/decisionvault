# Multi-Agent Memory Governance Evidence

Date: 2026-08-14

Status: PASS for local contract, real CockroachDB Cloud semantic path, and the
hosted AWS Lambda conflict proof.

## Problem under test

Once multiple agents can write to the same persistent memory, simple vector
retrieval is not enough. A useful shared-memory contract must preserve who wrote
an observation, prevent repeated writes from one producer from becoming fake
consensus, avoid propagating stale or explicitly replaced knowledge, and surface
contradictions rather than collapsing them invisibly.

DecisionVault keeps the existing `decision_episodes` table and Distributed
Vector Index unchanged. Governance happens between recall and the deterministic
policy, so the previously verified persistence and vector contracts remain
intact.

## Governance contract

`ConflictAwareMemoryResolver` applies these rules before memory can affect a
decision:

1. similarity must meet the existing `0.30` relevance gate;
2. `memory_status=REVOKED` observations are inadmissible;
3. an episode named by another episode's `supersedes_episode_id` is retired;
4. unpinned memory older than the configured age window (90 days by default) is
   ignored;
5. only the newest active observation for a given producer + strategy receives a
   vote, preventing duplicate amplification;
6. successful and failed outcome evidence are aggregated separately;
7. producer trust is optional server-side configuration and is never taken from
   the producer's own episode payload;
8. a close contradiction returns `CONFLICT_ABSTAIN` and the policy falls back to
   `GENERIC_RETRY`;
9. when trust or stronger evidence resolves the winner, `memory_conflict` remains
   true so the disagreement is still visible to the caller.

## Local adversarial contract

The dedicated unit suite covers:

```text
balanced cross-agent success/failure contradiction → abstain
trusted producer vs lower-trust contradiction       → resolve, conflict visible
120-day-old successful memory                       → ignored
explicit supersession                               → obsolete episode removed
same-producer repeated writes                       → no vote amplification
two equally strong successful strategies            → abstain
policy output                                       → safe default + conflict metadata
```

After the governance implementation, the full repository test suite is:

```text
42 passed
```

## Real CockroachDB Cloud + semantic embedding smoke

The live smoke used the same CockroachDB Cloud `decision_episodes` table and
NVIDIA `nvidia/nv-embedqa-e5-v5` production embedding path as the hosted
application.

Observed output:

```text
balanced_conflict_strategy=GENERIC_RETRY
balanced_conflict_influenced=False
balanced_conflict_resolution=CONFLICT_ABSTAIN

trusted_resolution_strategy=REFRESH_PAYMENT_TOKEN
trusted_resolution_conflict=True

stale_strategy=GENERIC_RETRY
stale_resolution=NO_SIGNAL

supersession_strategy=REFRESH_PAYMENT_TOKEN
supersession_old_recalled=False

duplicate_vote_strategy=GENERIC_RETRY
duplicate_vote_conflict=True

multi_agent_governance_smoke=PASS
governance_cloud_rows_cleaned=PASS
```

This establishes that the governance behavior is not only an in-memory test
contract: it operates after real semantic recall from CockroachDB Cloud.

## Regression against the original memory claim

Adding governance must not erase the original causal benefit of persistent
memory. The frozen Phase 8 benchmark was therefore re-run after the resolver was
inserted into the policy path.

```text
Local benchmark:        56 / 56 PASS
CockroachDB Cloud:      28 / 28 PASS

Benefit target accuracy, Memory ON:  100%
Benefit target accuracy, Memory OFF:   0%
Failed retry repetition, Memory ON:    0%
Failed retry repetition, Memory OFF: 100%
False influence, Memory ON:            0%
Cross-scope leakage, Memory ON:         0%
```

The safety layer therefore preserves the already-demonstrated Memory ON/OFF
behavioral advantage.

## Correction path

The protected `/record` API now accepts an optional `supersedes_episode_id`.
This provides a persistent correction handle without deleting immutable history:
the replacement episode remains visible while the obsolete episode is excluded
from future resolution.

## Trust boundary

Optional producer trust comes from `AGENT_TRUST_JSON` in deployment
configuration. An agent cannot raise its own trust by writing a field into its
memory episode. Trust affects resolution weight only; it does not suppress the
fact that contradictory qualified evidence exists.

## Scope / authentication boundary

The memory adapter enforces exact `scope_id` filtering and the existing benchmark
continues to show zero cross-scope recall. That is a memory-isolation property,
not a claim that the hackathon demo token is enterprise per-agent IAM. The hosted
demo still uses a deliberately narrow application token for protected mutation
routes. A production deployment would bind agent identity and scope membership to
an external authentication / authorization system.

## Hosted conflict proof

The protected `/governance-demo` endpoint and UI control are deployed on the
same AWS Lambda Function URL as the normal Memory ON/OFF proof. The hosted run
seeds two contradictory producer outcomes, asks a third agent to decide, and
then deletes the temporary scope.

Observed hosted result:

```text
governance_demo_http=200
governance_strategy=GENERIC_RETRY
governance_influenced=False
governance_resolution=CONFLICT_ABSTAIN
governance_conflict=True
governance_expected_abstention=True
governance_cleaned=True
governance_unauthorized_http=401
live_conflict_governance=PASS
live_demo_rows_remaining=0
live_cleanup_db_check=PASS
```

The deployed UI was also loaded through real headless Chrome at `1440×1000` and
`390×844`. Both DOM runs contained the normal memory-proof button, the conflict
safety button, `CONFLICT_ABSTAIN` explanation, Memory OFF/ON panels, and the
executed Lambda health status.

```text
desktop governance DOM smoke=PASS
mobile governance DOM smoke=PASS
browser_governance_smoke=PASS
```

The normal hosted shared-memory proof was re-run after deployment and continued
to produce `GENERIC_RETRY` with Memory OFF and `REFRESH_PAYMENT_TOKEN` with
Memory ON, so conflict governance did not erase the original positive memory
effect.

No database URL, SQL password, NVIDIA key, AWS credential, OAuth token, demo
token, cluster ID, or private Function URL credential is stored in this file.
