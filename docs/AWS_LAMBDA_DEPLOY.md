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
- `NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1`
- `NVIDIA_TIMEOUT_SECONDS`
- `DATABASE_CONNECT_TIMEOUT_SECONDS=5`
- `DATABASE_STATEMENT_TIMEOUT_MS=8000`
- `READINESS_CACHE_SECONDS=30`
- `REVOKE_AGENT_IDS` — comma-separated server-bound agent IDs allowed to invoke
  revocation after normal token/scope capability checks; contains no raw token
- `EXECUTION_SANDBOX_SCENARIO=stale_payment_token` — non-secret server-owned
  sandbox fixture; general `/execute` callers cannot override it

The referenced secret stores `DATABASE_URL`, `NVIDIA_API_KEY`, `DEMO_API_TOKEN`,
`AGENT_AUTH_JSON`, and `EXECUTION_RECEIPT_SECRET`. The Lambda execution role is
granted `secretsmanager:GetSecretValue` only on that secret ARN.

Do not put any credential in source control. Local ignored deployment files may
hold bootstrap copies, but the hosted function resolves sensitive values from
Secrets Manager at runtime.

## Endpoints

- `GET /` — public judge UI
- `GET /health`
- `GET /health/live` — process liveness only
- `GET /health/ready` — active Secrets Manager + CockroachDB governance-v2
  schema + E5-v5 readiness
- `POST /execute` — agent-token authenticated sandbox execution; returns a signed
  receipt only if the current deterministic policy is executable and commits the
  requested strategy; caller-supplied `scenario` is rejected
- `POST /record` — agent-token authenticated outcome recording
- `POST /decide` — agent-token authenticated scoped recall/decision
- `POST /revoke` — producer-bound current-head revocation with append-only audit
  record and idempotent replay
- `POST /demo` — protected atomic Memory OFF vs Memory ON proof with cleanup
- `POST /governance-demo` — protected contradictory-memory abstention proof

The `/decide` response exposes `memory_influenced`, recalled episode IDs,
`strategy`, `action`, `executable`, and (when available) the bounded model
explanation. A conflict abstention is `strategy=null`, `action=ABSTAIN`, and
`executable=false`.

The general `/decide` route always runs with memory governance enabled and
rejects a caller-supplied `memory_enabled` override. Memory OFF exists only in
the protected judge demo and offline ablation harnesses.

The caller does not supply `agent_id` to `/execute`, `/record`, `/decide`, or
`/revoke`; identity comes from the authenticated grant. Requests outside the
token's namespace boundary or permission are rejected. Revocation additionally
requires that server-bound identity in `REVOKE_AGENT_IDS`.

Verified receipt `issued_at` is persisted as the observation/event time. Current
heads advance monotonically by that event time, using immutable producer/strategy
history as a high-watermark, so delayed older receipts remain auditable without
replacing newer state or reappearing after a revoke.

`/record` does not accept direct `outcome` / `effectiveness` / `confidence`
fields. It requires the signed receipt returned by `/execute`; the receipt ID is
stored under a unique CockroachDB index to make replay idempotent.

## Build

```bash
python scripts/build_lambda_package.py
```

This writes `dist/decisionvault-lambda.zip`. The `dist/` directory is ignored by
Git.

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
