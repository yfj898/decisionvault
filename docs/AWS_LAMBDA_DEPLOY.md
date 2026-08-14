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
- `POST /record` and `/decide`: protected by `X-DecisionVault-Agent-Token`, with
  server-side identity / scope / permission grants

Required Lambda environment variables:

- `DATABASE_URL` — CockroachDB Cloud connection string
- `NVIDIA_API_KEY` — NVIDIA API key
- `NVIDIA_MODEL_ID=meta/llama-3.1-8b-instruct`
- `NVIDIA_EMBED_MODEL_ID=nvidia/nv-embedqa-e5-v5`
- `DEMO_API_TOKEN` — random deployment-only token for the atomic judge demos
- `AGENT_AUTH_JSON` — JSON object keyed by SHA-256 digests of opaque agent
  tokens; grants bind `agent_id`, scope prefixes, permissions, and trust
- `EXECUTION_RECEIPT_SECRET` — deployment-only HMAC key used to sign and verify
  payment-recovery sandbox execution receipts

Do not put any credential in source control. Lambda environment variables are
configured at deployment time.

## Endpoints

- `GET /` — public judge UI
- `GET /health`
- `POST /execute` — agent-token authenticated sandbox execution; returns a signed
  receipt
- `POST /record` — agent-token authenticated outcome recording
- `POST /decide` — agent-token authenticated scoped recall/decision
- `POST /demo` — protected atomic Memory OFF vs Memory ON proof with cleanup
- `POST /governance-demo` — protected contradictory-memory abstention proof

The `/decide` response exposes `memory_influenced`, recalled episode IDs, the
committed strategy, and (when available) the bounded model explanation.

The caller does not supply `agent_id` to `/execute`, `/record`, or `/decide`; identity comes
from the authenticated grant. Requests outside the token's allowed scope prefix
or permission are rejected.

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
7. Cleanup of all temporary demonstration memory rows and governed heads.

The deployed function is named `decisionvault-agent` in `ap-northeast-1`.
Committed evidence intentionally omits the AWS account ID, AWS login cache,
database URL, NVIDIA key, demo token, and Function URL hostname.
