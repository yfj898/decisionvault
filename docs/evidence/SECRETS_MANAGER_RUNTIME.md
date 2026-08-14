# AWS Secrets Manager Runtime Evidence

Date: 2026-08-14

Status: **PASS** for the hosted Lambda runtime.

## Problem under test

Sensitive values were already excluded from Git, but the Lambda function still
stored its database URL, NVIDIA API key, judge token, agent grants, and execution
receipt signing key directly in Lambda environment configuration.

## Remediation

The hosted function now keeps those values in one AWS Secrets Manager secret.
The Lambda environment contains only the secret ARN and non-sensitive runtime
knobs such as model IDs, base URL, and timeout.

Managed secret keys:

```text
DATABASE_URL
NVIDIA_API_KEY
DEMO_API_TOKEN
AGENT_AUTH_JSON
EXECUTION_RECEIPT_SECRET
```

Lambda environment after migration:

```text
DECISIONVAULT_SECRET_ARN
NVIDIA_BASE_URL
NVIDIA_EMBED_MODEL_ID
NVIDIA_MODEL_ID
NVIDIA_TIMEOUT_SECONDS
```

The Lambda execution role has `secretsmanager:GetSecretValue` only for the single
DecisionVault runtime secret. The application loads the secret once per warm
process and hydrates only missing sensitive process values; local development can
still use direct environment variables without requiring AWS.

## Live verification

AWS configuration inspection confirmed that the Lambda environment no longer
contains `DATABASE_URL`, `NVIDIA_API_KEY`, `DEMO_API_TOKEN`, `AGENT_AUTH_JSON`, or
`EXECUTION_RECEIPT_SECRET`.

Hosted behavior after the switch:

```text
health_http=200
runtime_secret_source=aws-secrets-manager
runtime_secret_reference_configured=true

demo_http=200
expected_change=true
cleaned=true

governance_http=200
expected_abstention=true
cleaned=true

execute_http=200
receipt_signed=true
record_http=201
verified_receipt=true
decide_http=200
strategy=REFRESH_PAYMENT_TOKEN
memory_influenced=true

secrets_manager_live_runtime=PASS
cleanup_rows=(0, 0)
```

## Boundary

Managed values are now refreshed in warm Lambda processes on a bounded TTL
(`SECRET_REFRESH_SECONDS`, default 30 seconds) and replace the stale managed
process value rather than using `setdefault`. Agent grant reconciliation runs on
a similar bounded interval before authenticated POST handling: current heads
owned by producers absent from the active grant set are removed and a revocation
audit event is appended. This bounds credential-revocation latency in warm
containers and prevents a removed producer's current memory head from continuing
to influence decisions.

This is application-level bounded refresh/reconciliation, not a claim of AWS
Secrets Manager automatic rotation scheduling or enterprise incident-response
orchestration.
