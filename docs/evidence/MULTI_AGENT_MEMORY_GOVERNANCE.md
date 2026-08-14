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

DecisionVault keeps `decision_episodes` as immutable audit history and preserves
the original deterministic `VECTOR(64)` contract for regression evidence. The
hosted semantic path now uses a separate `decision_memory_heads` table with one
current row per `(scope_id, producer_agent_id, strategy)` and a native
`semantic_embedding VECTOR(1024)` Distributed Vector Index. This was introduced
after red-team testing showed that deduplicating only after ANN top-K could allow
one producer's repeated writes to crowd independent evidence out of the candidate
set.

## Governance contract

`ConflictAwareMemoryResolver` applies these rules before memory can affect a
decision:

1. similarity must meet the embedding-family gate: `0.30` for deterministic
   regression tests and `0.40` for the hosted E5-v5 semantic path;
2. `memory_status=REVOKED` observations are inadmissible;
3. an episode named by another episode's `supersedes_episode_id` is retired;
4. unpinned memory older than the configured age window (90 days by default) is
   ignored;
5. production ANN retrieval reads the governed-head table, whose primary key
   keeps only one current candidate per producer + strategy before ANN ranking;
   production recall also pre-filters revoked, stale, UNKNOWN, low-confidence
   failure, and low-effectiveness success heads before ranking, then over-fetches
   up to 32 governed candidates so the resolver is not constrained by the old
   top-5 boundary;
6. successful and failed outcome evidence are aggregated separately;
7. producer identity/scope/permission/trust comes from a server-side token grant,
   never from a caller-supplied `agent_id`; unknown producers receive a
   conservative trust default when a trust registry is active;
8. a close contradiction returns `CONFLICT_ABSTAIN` with `strategy=null`,
   `action=ABSTAIN`, and `executable=false` rather than exposing an executable
   fallback strategy;
9. the `/execute` gateway re-runs the current deterministic policy and refuses
   to sign an execution receipt if the current action is `ABSTAIN` or the caller
   asks to execute a strategy other than the policy-committed strategy;
10. authenticated `/revoke` requires a token-bound producer capability plus a
   second server-controlled `REVOKE_AGENT_IDS` allowlist. New grants may carry
   the distinct `revoke` capability directly; the existing hosted observer uses
   its `record` capability only because its bound `agent_id` is independently
   allowlisted. The transaction removes only that producer's current governed
   head while appending a `decision_memory_revocations` audit event;
11. semantic candidates are labeled with `semantic_embedding_space` (model,
   dimensions, and query/passage contract) and recall filters by that space
   before vector ranking;
12. when trust or stronger evidence resolves the winner, `memory_conflict` remains
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
policy output                                       → strategy=None / action=ABSTAIN
execution attempt while abstained                    → blocked before receipt signing
producer-bound current-head revoke                  → audited + idempotent
cross-embedding-space candidate                     → not recalled
```

After the governance implementation, the full repository test suite is:

```text
101 passed
```

## Real CockroachDB Cloud + semantic embedding smoke

The live smoke used the same CockroachDB Cloud `decision_memory_heads` governed
candidate table and native NVIDIA `nvidia/nv-embedqa-e5-v5` 1024D production
embedding path as the hosted application. Immutable source episodes remained in
`decision_episodes`.

Observed output:

```text
balanced_conflict_strategy=NONE
balanced_conflict_action=ABSTAIN
balanced_conflict_executable=False
balanced_conflict_influenced=False
balanced_conflict_resolution=CONFLICT_ABSTAIN

trusted_resolution_strategy=REFRESH_PAYMENT_TOKEN
trusted_resolution_conflict=True

stale_strategy=GENERIC_RETRY
stale_resolution=NO_SIGNAL

supersession_strategy=REFRESH_PAYMENT_TOKEN
supersession_old_recalled=False

duplicate_vote_strategy=NONE
duplicate_vote_action=ABSTAIN
duplicate_vote_conflict=True

multi_agent_governance_smoke=PASS
governance_cloud_rows_cleaned=PASS
```

This establishes that the governance behavior is not only an in-memory test
contract: it operates after real semantic recall from CockroachDB Cloud.

An additional candidate-crowding red-team seeded five high-similarity repeated
episodes from one producer plus an independent conflicting producer. The history
table retained all six episodes, while the governed-head table exposed only two
current candidates (one per producer/strategy). The resulting decision correctly
returned `CONFLICT_ABSTAIN` instead of hiding the independent conflict.

## Regression against the original memory claim

Adding governance must not erase the original causal benefit of persistent
memory. The frozen Phase 8 benchmark was therefore re-run after the resolver was
inserted into the policy path.

```text
Local deterministic benchmark:        56 / 56 PASS
CockroachDB Cloud deterministic:       28 / 28 PASS
Native 1024D production semantic:      14 / 14 PASS

Benefit target accuracy, Memory ON:  100%
Benefit target accuracy, Memory OFF:   0%
Failed retry repetition, Memory ON:    0%
Failed retry repetition, Memory OFF: 100%
False influence, Memory ON:            0%
Cross-scope leakage, Memory ON:         0%
```

The first two suites are deterministic regression/causal-ablation evidence. The
separate `14/14` production semantic suite is hand-authored and covers same-scope
distractors, cross-scope filtering, contradictions, stale memory, supersession,
and candidate crowding. The safety layer therefore preserves the original Memory
ON/OFF behavioral advantage while also being exercised on the hosted retrieval
representation.

## Correction path

The protected `/record` API now accepts an optional `supersedes_episode_id`.
This provides a persistent correction handle without deleting immutable history:
the replacement episode remains in history while the obsolete governed head is
removed from future production recall. The final current-head check is enforced
inside the same CockroachDB write transaction as the history insert/head UPSERT:
the old head is conditionally deleted by `(scope_id, producer_agent_id,
episode_id) ... RETURNING`, so a concurrent normal write that already replaced
the target turns the correction into an explicit conflict instead of allowing a
stale supersession to commit.

The explanation-only advisor receives only the episode IDs surfaced by the
governance result. Raw ANN candidates rejected by relevance/lifecycle governance
are not passed to the model explanation layer.

Follow-up live verification on the real CockroachDB Cloud + NVIDIA semantic path
also exercised the previously unsafe supersession interleaving:

```text
prevalidated old head                         PASS
normal write replaced that head               PASS
late supersession rejected by transactional CAS PASS
stale correction history rows                 0
cloud supersession-vs-normal-write             PASS
```

The production semantic suite was expanded from 12 to 14 hand-authored cases.
The two new cases cover six distinct heads with a lower-ranked independent
contradiction, and stale/revoked candidate crowding ahead of fresh admissible
evidence. The complete real Cloud + native-1024D suite passes `14/14`, and all
temporary benchmark rows are cleaned afterward.

## Revocation path

`POST /revoke` is separate from correction/supersession. Authorization is
double-bound: the request must authenticate as a producer with an applicable
record/revoke capability and that server-bound `agent_id` must be present in
`REVOKE_AGENT_IDS`. This allowed the production deployer to enable revocation by
agent ID without copying opaque tokens out of Secrets Manager. The request then
supplies `scope_id`, a UUID `episode_id`, and an audit reason. The CockroachDB transaction first checks
for an existing revocation (making retries idempotent), then conditionally
deletes the current head by `(scope_id, producer_agent_id, episode_id)` and
inserts an append-only `decision_memory_revocations` row. The immutable source
episode is not rewritten or deleted.

Real CockroachDB Cloud verification:

```text
revoke_before_recall             1
revoke_after_recall              0
first revoke idempotent          false
replayed revoke idempotent       true
replayed revocation ID identical true
cloud_revoke_contract            PASS
```

## Embedding-space migration boundary

Production semantic rows now carry:

```text
nvidia/nv-embedqa-e5-v5|dim=1024|contract=query-passage-v1
```

The DVI is `decision_memory_heads_scope_space_semantic_vec_idx` with
`scope_id` and `semantic_embedding_space` as prefix columns. An intentionally
re-labeled legacy-space head with a perfect semantic vector produced zero recall
under the current runtime. `scripts/migrate_semantic_embedding_space.py` then
re-embedded that current head into the configured space and recall returned one
candidate again. The migration uses an episode-ID/current-head CAS so a
concurrent replacement is skipped rather than overwritten.

## Trust boundary

General `/record`, `/decide`, `/execute`, and `/revoke` callers authenticate with opaque per-agent tokens.
Only SHA-256 token digests are stored in Lambda configuration via
`AGENT_AUTH_JSON`; each grant binds an agent identity, allowed scope prefixes,
permissions, and trust. A caller that sends `agent_id` in the request body is
rejected. Trust affects resolution weight only; it does not suppress the fact
that contradictory qualified evidence exists.

## Scope / authentication boundary

The memory adapter enforces exact `scope_id` filtering, while the general agent
API independently checks whether the authenticated agent token grants access to
the requested namespace boundary and permission. Prefix matching is no longer a
raw `startswith`: a grant for `team-a` allows `team-a`, `team-a/demo`, or
`team-a-demo`, but not `team-admin`. Wildcards and duplicate agent identities are
rejected while loading grants. Live verification showed: a judge demo
token is rejected on `/decide`, a caller-supplied `agent_id` is rejected, and a
valid planner token is rejected outside its granted scope. The two atomic judge
demo routes intentionally keep a separate hackathon demo token. This is still a
compact application grant mechanism, not a claim of enterprise IAM integration.

## Hosted conflict proof

The protected `/governance-demo` endpoint and UI control are deployed on the
same AWS Lambda Function URL as the normal Memory ON/OFF proof. The hosted run
seeds two contradictory producer outcomes, asks a third agent to decide, and
then deletes the temporary scope.

Observed hosted result:

```text
governance_demo_http=200
governance_strategy=null
governance_action=ABSTAIN
governance_executable=false
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
