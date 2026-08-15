# AWS Lambda deployment

DecisionVault uses an AWS Lambda Function URL as its smallest public AWS-hosted
surface. CockroachDB Cloud remains the persistent memory authority. NVIDIA
provides the production semantic embeddings and an explanation-only advisor; the
advisor cannot change the committed strategy.

## Runtime

- AWS Lambda Python 3.12
- Architecture: `x86_64`
- Handler: `lambda_function.lambda_handler`
- Suggested region: `ap-northeast-1`
- Memory: 512 MB
- Timeout: 30 seconds
- Function URL: public `NONE` for hackathon demo availability
- `POST /demo` and `/governance-demo`: protected by `X-DecisionVault-Token`
- `POST /execute`, `/record`, `/decide`, and `/revoke`: protected by
  `X-DecisionVault-Agent-Token`, with server-side identity / namespace /
  permission grants; `/revoke` also requires `REVOKE_AGENT_IDS`

Hosted Lambda environment variables:

- `DECISIONVAULT_SECRET_ARN` — ARN of the single AWS Secrets Manager JSON object
  containing the sensitive runtime values
- `NVIDIA_MODEL_ID=meta/llama-3.1-8b-instruct`
- `NVIDIA_EMBED_MODEL_ID=nvidia/nv-embedqa-e5-v5`
- `NVIDIA_EMBED_REVISION=decisionvault-prod-r1` — explicit operator-controlled
  embedding generation; bump before re-embedding when provider weights change
- `NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1` — fixed compatibility
  assertion, not a caller/deployer-selectable credential destination
- `NVIDIA_TIMEOUT_SECONDS` — operator ceiling; Lambda clamps semantic embedding
  calls to at most 12s and the non-authoritative advisor to at most 5s so the
  30s platform timeout still has room for bounded CockroachDB work and response
  handling
- `DATABASE_CONNECT_TIMEOUT_SECONDS=5`
- `DATABASE_STATEMENT_TIMEOUT_MS=8000`
- `READINESS_CACHE_SECONDS=30`
- `SECRET_REFRESH_SECONDS=30` — bounded Secrets Manager refresh interval for
  warm Lambda processes; managed secret values replace stale process values
- `SECURITY_RECONCILE_SECONDS=30` — interval for reconciling current memory heads
  against the active authenticated producer set
- `DEFAULT_MEMORY_SCOPE_LEVEL=TEAM` — server-owned adaptive-memory scope level;
  `PRIVATE`, `TEAM`, and `GLOBAL` require 1, 2, and 3 distinct producers
- `MEMORY_SCOPE_LEVELS_JSON` — optional namespace-prefix map to server-owned
  `PRIVATE` / `TEAM` / `GLOBAL` levels; longest namespace-bound prefix wins
- `CONSOLIDATION_LEASE_SECONDS=120` — durable outbox worker lease
- `CONSOLIDATION_RETRY_BATCH_SIZE=10` — scheduled retry batch size, capped by
  the application at 50 scopes
- `REVOKE_AGENT_IDS` — comma-separated server-bound agent IDs allowed to invoke
  revocation after normal token/scope capability checks; contains no raw token
- `EXECUTION_PROVIDER=sandbox` — server-owned execution provider selector. The
  hosted production default remains `sandbox`; callers cannot override it.
- `EXECUTION_SANDBOX_SCENARIO=stale_payment_token` — non-secret server-owned
  sandbox fixture; general `/execute` callers cannot override it
- `GITHUB_EXECUTION_REPOSITORY=yfj898/decisionvault-execution-sandbox` — the
  only source-allowlisted repository accepted by the optional real GitHub
  Contents adapter
- `GITHUB_EXECUTION_TIMEOUT_SECONDS=8` — bounded GitHub API timeout, clamped by
  the application to at most 8 seconds

The referenced secret stores `DATABASE_URL`, `NVIDIA_API_KEY`, `DEMO_API_TOKEN`,
`AGENT_AUTH_JSON`, and `EXECUTION_RECEIPT_SECRET`. Governed Adaptive Memory v7
also accepts `CONSOLIDATION_DATABASE_URL` for a distinct CockroachDB
consolidator identity and `EXECUTION_RECEIPT_KEYRING_JSON` for versioned signing
keys with retained verification-only history. `GITHUB_EXECUTION_TOKEN` is an
optional secret used only when `EXECUTION_PROVIDER=github_contents`; readiness
fails closed if that provider is selected without the token or with a repository
other than the source-allowlisted test repo. Do not reuse a broad personal token
for hosted activation; provision a dedicated least-privilege credential first.
Managed readiness fails closed if
the consolidator credential is absent or resolves to the same database identity
as request runtime. The Lambda execution role is granted
`secretsmanager:GetSecretValue` only on that secret ARN.

Do not put any credential in source control. Local ignored deployment files may
hold bootstrap copies, but the hosted function resolves sensitive values from
Secrets Manager at runtime.

## Endpoints

- `GET /` — public judge UI
- `GET /health`
- `GET /health/live` — process liveness only
- `GET /health/ready` — active Secrets Manager + CockroachDB governance-v2
  schema + E5-v5 readiness
- `POST /execute` — agent-token authenticated server-selected execution. The
  current hosted provider is the deterministic payment sandbox. The optional
  `github_contents` provider writes exactly one test-only repository resource at
  `decisionvault-executions/<snapshot-id>.json`, reads that exact path back, and
  then signs an external receipt v3. The route returns a receipt only if the
  caller supplies the signed `/decide` snapshot and the current deterministic
  policy/memory digest still matches it; stale snapshots return HTTP 409 and no
  receipt. Caller-supplied provider/target/payload fields are rejected.
- `POST /record` — agent-token authenticated outcome recording
- `POST /decide` — agent-token authenticated scoped recall/decision
- `POST /revoke` — producer-bound current-head revocation with append-only audit
  record and idempotent replay
- `POST /demo` — protected atomic Memory OFF vs Memory ON proof with cleanup
- `POST /governance-demo` — protected contradictory-memory abstention proof

The `/decide` response exposes `memory_influenced`, recalled episode IDs,
`strategy`, `action`, `executable`, and (when available) the bounded model
explanation. Executable decisions also carry a server-signed decision snapshot
binding the authorized decider identity, scope, situation, strategy,
deterministic policy/memory digest, embedding space, and decision-contract
revision. A separately authorized executor may consume that snapshot within the
same scope; the execution receipt records both `decision_agent_id` and the actual
executor `agent_id`. A conflict abstention is `strategy=null`, `action=ABSTAIN`,
and `executable=false`.

External execution receipts deliberately separate **side-effect verification**
from **business-outcome verification**. The GitHub test adapter proves that the
external resource exists and binds its repository/path/blob SHA into the signed
receipt, but its business outcome is `UNKNOWN` with zero effectiveness. `/record`
rejects that receipt with HTTP 422 `business_outcome_unverified` rather than
creating an L1 decision episode; memory calibration also counts only factual
`SUCCESS`/`FAILED` outcomes as a second defensive boundary. This prevents a
successful transport/write from being mislearned as a successful
payment-recovery strategy or from crowding governed recall candidates.

`GET /health/ready` is fail-closed for the security control plane as well as
CockroachDB/NVIDIA dependencies. A ready response requires parseable non-empty
agent grants, a valid execution receipt signing secret, a non-empty demo token,
and a valid server-owned execution sandbox scenario. Managed v7 additionally
requires the consolidation outbox schema, valid memory-scope configuration, a
working consolidator connection, and distinct runtime/consolidator DB identities.

The general `/decide` route always runs with memory governance enabled and
rejects a caller-supplied `memory_enabled` override. Memory OFF exists only in
the protected judge demo and offline ablation harnesses.

The caller does not supply `agent_id` to `/execute`, `/record`, `/decide`, or
`/revoke`; identity comes from the authenticated grant. Requests outside the
token's namespace boundary or permission are rejected. Revocation additionally
requires that server-bound identity in `REVOKE_AGENT_IDS`.

Verified receipt `issued_at` is persisted as `observed_at`, the observation/event
time. `recorded_at` separately records when DecisionVault accepted the immutable
episode. Current heads advance monotonically only by `observed_at`, using
immutable producer/strategy history as a high-watermark, so delayed older
receipts remain auditable without replacing newer state or reappearing after a
revoke.

`/record` does not accept direct `outcome` / `effectiveness` / `confidence`
fields. It requires the signed receipt returned by `/execute`; the receipt ID is
stored under a unique CockroachDB index to make replay idempotent. The 15-minute
receipt TTL gates **first-time recording**; once a receipt ID has already been
recorded, a correctly signed replay can return that existing episode after the
issuance TTL rather than creating a duplicate or failing a delayed retry.

## Build

```bash
python scripts/build_lambda_package.py \
  --ca-file /path/to/public/cockroach-cloud-root.crt
```

This writes `dist/decisionvault-lambda.zip`. Lambda dependencies are exactly
pinned. The public CockroachDB CA is an explicit build input; a missing/non-PEM
CA or any CA input containing private-key material fails the build before a ZIP
is produced. The `dist/` directory is ignored by Git.

## Governed Adaptive Memory v7 rollout

Use an expand/contract migration so the old Lambda never loses adaptive write
rights before the new Lambda has switched to the consolidator identity:

```bash
python scripts/apply_governed_adaptive_memory_v7.py \
  --phase expand \
  --database-url-file /path/to/admin-database-url \
  --ca-file /path/to/cockroach-cloud-root.crt

# Update the existing managed secret with the consolidator credential and
# signing keyring, deploy v7, then require /health/ready to pass.

python scripts/apply_governed_adaptive_memory_v7.py \
  --phase contract \
  --database-url-file /path/to/admin-database-url \
  --ca-file /path/to/cockroach-cloud-root.crt
```

The contract phase removes candidate/L2/support mutation from
`decisionvault_runtime` and removes L3 INSERT/DELETE. L3 UPDATE remains only for
the synchronous correctness boundary that invalidates governed memory when a
supporting current head is replaced, revoked, or retired. Runtime can enqueue a
durable consolidation obligation but cannot delete it.

After the cutover, configure periodic retry and memory-health operations:

```bash
python scripts/configure_memory_operations.py \
  --function-name decisionvault-agent \
  --region ap-northeast-1 \
  --schedule-minutes 5
```

This provisions an EventBridge retry schedule, CloudWatch alarms for deferred
consolidation / secret-refresh failure / backlog growth, and a low-cardinality
memory-operations dashboard.

## Competition proof

The verified Phase 6 evidence includes:

1. Lambda function ARN and region (account ID redacted in committed evidence).
2. Successful Function URL `/health` request.
3. A real agent-token-authenticated `/record` followed by `/decide` against the
   native `VECTOR(1024)` CockroachDB semantic path.
4. The returned decision showing `memory_influenced=true` and producer
   provenance.
5. Rejection of caller-supplied `agent_id`, demo-token use on agent routes, and a
   valid agent token outside its granted scope.
6. `/demo` and `/governance-demo` live judge proofs.
7. Hosted `/execute` rejects active conflict abstention with HTTP 409 and no
   receipt.
8. Hosted `/revoke` removes the producer's current head, replays idempotently,
   and returns the same revocation audit ID.
9. Cleanup of all temporary demonstration memory rows, governed heads, and
   revocation rows.

The deployed function is named `decisionvault-agent` in `ap-northeast-1`.
Committed evidence intentionally omits the AWS account ID, AWS login cache,
database URL, NVIDIA key, demo token, and Function URL hostname.
