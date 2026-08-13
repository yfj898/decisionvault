# AWS Lambda deployment

DecisionVault uses an AWS Lambda Function URL as its smallest public AWS-hosted
surface. CockroachDB Cloud remains the persistent memory authority. NVIDIA is an
optional explanation-only model provider and cannot change the committed strategy.

## Runtime

- AWS Lambda Python 3.12
- Architecture: `x86_64`
- Handler: `lambda_function.lambda_handler`
- Suggested region: `ap-northeast-1`
- Memory: 512 MB
- Timeout: 30 seconds
- Function URL: public `NONE` for hackathon demo availability; POST routes use
  the application-level `X-DecisionVault-Token` guard

Required Lambda environment variables:

- `DATABASE_URL` — CockroachDB Cloud connection string
- `NVIDIA_API_KEY` — NVIDIA API key
- `NVIDIA_MODEL_ID=meta/llama-3.1-8b-instruct`
- `DEMO_API_TOKEN` — random deployment-only token required by POST routes

Do not put any credential in source control. Lambda environment variables are
configured at deployment time.

## Endpoints

- `GET /` — public judge UI
- `GET /health`
- `POST /record`
- `POST /decide`
- `POST /demo` — protected atomic Memory OFF vs Memory ON proof with cleanup

The `/decide` response exposes `memory_influenced`, recalled episode IDs, the
committed strategy, and (when available) the bounded model explanation.

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
3. A real `/record` followed by `/decide` against CockroachDB Cloud.
4. The returned decision showing `memory_influenced=true`.
5. Cleanup of the demonstration memory scope.

The deployed function is named `decisionvault-agent` in `ap-northeast-1`.
Committed evidence intentionally omits the AWS account ID, AWS login cache,
database URL, NVIDIA key, demo token, and Function URL hostname.
