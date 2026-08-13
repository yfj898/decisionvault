# Phase 6 — AWS Lambda Deployment Evidence

Status: **PASS**

Date: 2026-08-13

## AWS deployment

- Service: AWS Lambda
- Region: `ap-northeast-1`
- Function: `decisionvault-agent`
- Runtime: Python 3.12
- Architecture: `x86_64`
- Memory: 512 MB
- Timeout: 30 seconds
- Function state: `Active`
- Function URL auth mode: `NONE`
- POST application guard: `X-DecisionVault-Token`
- CloudWatch log group: `/aws/lambda/decisionvault-agent`

AWS account ID, principal ARN, login cache, and Function URL hostname are omitted
from committed evidence.

## Public health proof

The deployed Function URL returned:

```text
GET /health
HTTP 200
service=decisionvault
status=ok
database_configured=True
nvidia_advisor_configured=True
```

An unauthenticated POST request was rejected:

```text
POST /decide
HTTP 401
```

## Hosted causal-memory proof

A unique Phase 6 scope was exercised only through the deployed Lambda Function
URL.

### Persist failed episode

```text
POST /record
HTTP 201
episode_id present=True
strategy=GENERIC_RETRY
outcome=FAILED
effectiveness=0.1
```

### Memory ON

```text
POST /decide
HTTP 200
strategy=REFRESH_PAYMENT_TOKEN
memory_influenced=True
model_provider=nvidia:meta/llama-3.1-8b-instruct
model_explanation_present=True
```

### Memory OFF control

```text
POST /decide
HTTP 200
strategy=GENERIC_RETRY
memory_influenced=False
```

This proves the deployed AWS-hosted agent changes behavior because CockroachDB
recalls the persisted failed outcome. The NVIDIA provider only explains the
already-committed strategy.

## Cleanup

The temporary Phase 6 scope was removed from CockroachDB Cloud after verification:

```text
phase6_rows_after_cleanup=0
```

## Secret handling

- `DATABASE_URL`, NVIDIA API key, and demo token were injected only as Lambda
  environment variables during deployment.
- AWS CLI login state is stored only in ignored local runtime data.
- No AWS credential, database password, NVIDIA key, demo token, or account ID is
  committed.
