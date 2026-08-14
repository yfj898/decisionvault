# Final Red-Team Remediation Evidence

Date: 2026-08-14

Status: **PASS for the P0 remediation set described below.**

This evidence records issues found by adversarial review after the original
Phase 0–8 gates had already passed. The purpose is to distinguish a successful
happy-path demo from claims that remain valid under hostile or misleading input.

## 1. Lossy semantic projection

### Red-team finding

The first hosted semantic implementation used NVIDIA
`nvidia/nv-embedqa-e5-v5` at 1024 dimensions, then projected the vector into the
existing `VECTOR(64)` schema with a deterministic signed feature hash.

A live NVIDIA ranking probe over 5 queries × 15 candidate passages found:

```text
1024D → 64D top-1 preservation: 60%
mean top-5 overlap:             68%
mean cosine distortion:        0.1015
max cosine distortion:         0.3178
```

At least one payment-recovery query changed its nearest neighbor from the
relevant payment memory in the original 1024D space to an unrelated password-
reset memory after projection.

### Remediation

Production retrieval no longer uses the projection. The Cloud schema now keeps:

```text
decision_episodes.embedding            VECTOR(64)   # deterministic regression
decision_episodes.semantic_embedding   VECTOR(1024) # immutable semantic record
decision_memory_heads.semantic_embedding VECTOR(1024) # production candidates
```

Production DVI:

```text
decision_memory_heads_scope_semantic_vec_idx
```

The old projection helper remains only as historical test code and is not wired
into the Lambda semantic store.

## 2. ANN candidate crowding before duplicate removal

### Red-team finding

The original decision path recalled only top-5 episodes and deduplicated by
producer *after* retrieval. An adversarial producer could therefore insert five
high-similarity duplicate episodes and push an independent conflicting producer
outside top-5.

Observed before remediation:

```text
recall limit = 5
visible producer = duplicate-agent only
strategy = REFRESH_PAYMENT_TOKEN
memory_conflict = false
```

When all six items were supplied to the resolver, the correct result was:

```text
GENERIC_RETRY
CONFLICT_ABSTAIN
memory_conflict = true
```

### Remediation

Production semantic recall now queries `decision_memory_heads`, whose primary
key is:

```text
(scope_id, producer_agent_id, strategy)
```

Immutable history is still written to `decision_episodes`, but only the current
head for a producer/strategy participates in ANN candidate generation.

Follow-up adversarial review found that a fixed top-5 over governed heads could
still hide a sixth independent contradiction when unrelated, stale, revoked, or
otherwise inadmissible heads ranked above it. Production semantic recall now
pre-filters lifecycle/signal-inadmissible heads in SQL and the agent requests a
32-candidate governance pool instead of the old fixed 5. The resolver remains
the authority for similarity, trust, aggregation, and conflict abstention.

Live CockroachDB Cloud adversarial verification:

```text
history episodes = 6
governed heads = 2
distinct producers = 2
strategy = GENERIC_RETRY
resolution = CONFLICT_ABSTAIN
memory_conflict = true
candidate_crowding_regression = PASS
```

## 3. Caller-controlled producer identity

### Red-team finding

The earlier `/record` interface accepted `agent_id` from the request body. Since
producer trust is keyed by agent identity, a caller holding the shared demo token
could claim the identity of a trusted producer.

Observed before remediation:

```text
caller supplied agent_id = trusted-prod
persisted producer_agent_id = trusted-prod
identity bound to authentication = false
```

### Remediation

General `/record` and `/decide` routes now use `X-DecisionVault-Agent-Token`.
Only SHA-256 token digests are stored in `AGENT_AUTH_JSON`. Each grant binds:

```text
agent_id
scope_prefixes
permissions: record / decide
trust
```

The raw tokens exist only in the ignored local deployment workspace. Request
bodies containing `agent_id` are rejected.

Live AWS verification:

```text
agent /record                         HTTP 201
persisted producer                   recovery-observer-api
agent /decide                        HTTP 200
strategy                             REFRESH_PAYMENT_TOKEN
memory influenced                    true
judge demo token on agent API        HTTP 403
caller-supplied agent_id             HTTP 400
valid planner token on other scope   HTTP 403
live_agent_auth_semantic_path        PASS
```

The atomic judge UI demonstrations continue to use the separate
`X-DecisionVault-Token`; that token is deliberately not accepted by the general
agent APIs.

## 4. Unknown-producer trust default

### Red-team finding

When a trust registry existed, an unknown producer previously defaulted to trust
`1.0`, which could make an unregistered producer more influential than a known
producer explicitly configured at `0.8`.

### Remediation

If no trust registry is configured, the historical equal-weight behavior remains
`1.0` for compatibility. Once a registry is active, unknown producers receive a
conservative configurable default (`0.25` in the current resolver) instead of
maximum trust.

Unit coverage verifies that a known `0.8` producer outranks an otherwise equal
unknown producer.

## 5. Deterministic benchmark was not production semantic evidence

### Red-team finding

The original reported suites were:

```text
56/56 local deterministic
28/28 CockroachDB Cloud deterministic
7/7 Cloud + NVIDIA explanation advisor
```

The 28-case Cloud benchmark still used `deterministic_text_embedding`, and the
NVIDIA ablation changed only the explanation provider. These numbers therefore
could not be used as evidence of hosted semantic retrieval quality.

### Remediation

A separate production semantic benchmark was added. It uses:

```text
real NVIDIA E5-v5 query/passage embeddings
native VECTOR(1024)
decision_memory_heads
production semantic DVI
hand-authored cases rather than v00/v01 suffix variants
```

Coverage includes:

```text
failed generic retry adaptation
successful token-refresh reuse
successful billing-profile reuse
low-confidence failure control
low-effectiveness success control
same-scope semantic distractors
cross-scope filtering
balanced contradiction / abstention
stale memory
supersession
duplicate candidate crowding
```

The first run exposed a false influence:

```text
irrelevant memory top similarity = 0.3575
old production gate              = 0.30
result                           = false VERIFY_BILLING_PROFILE influence
```

The production semantic gate was therefore calibrated independently from the
deterministic baseline:

```text
deterministic regression gate = 0.30
production semantic gate      = 0.40
lowest observed benefit       = 0.4810
irrelevant distractor         = 0.3575
```

Final result:

```text
native 1024D production semantic benchmark = 14 / 14 PASS
local deterministic regression             = 56 / 56 PASS
CockroachDB deterministic regression        = 28 / 28 PASS
repository unit/contract suite              = 85 / 85 PASS
```

The semantic suite is a controlled retrieval/governance conformance benchmark,
not an open-domain generalization claim and not a payment business-success
metric.

## 6. Cross-scope filtering vs authorization

The submission now distinguishes two different properties:

```text
retrieval isolation:
WHERE scope_id = requested_scope

authorization:
authenticated agent grant must allow requested scope prefix + permission
```

The old benchmark's zero cross-scope influence proves retrieval isolation only.
The new live agent-token tests separately prove application-level scope
authorization for `/record` and `/decide`.

## 7. Hosted re-verification

After schema migration and Lambda redeployment:

```text
Lambda state                         Active
Lambda last update                  Successful
GET /health                         HTTP 200
judge /demo                         PASS
Memory OFF                          GENERIC_RETRY
Memory ON                           REFRESH_PAYMENT_TOKEN
judge /governance-demo              PASS
conflict resolution                 CONFLICT_ABSTAIN
memory_conflict                     true
general agent auth semantic path    PASS
temporary agent rows                0 heads / 0 episodes
```

## Remaining boundaries not claimed as solved

The P0 remediation does **not** claim that the following production concerns are
fully solved:

- the verified execution path uses a deterministic DecisionVault payment-recovery
  sandbox and signed receipt contract; it is not a real external payment network;
- the token-grant layer is a compact hackathon authorization mechanism, not
  enterprise IAM;
- concurrency, retry, provider-degradation, and distributed rate-limit boundaries
  have bounded live evidence, but sustained high-RPS / long-duration soak testing
  remains future production-hardening work.

Those items must not be represented in the Devpost submission as already solved.
