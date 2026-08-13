# Cloud setup checklist

## CockroachDB Cloud

1. Create a new CockroachDB Cloud cluster.
2. Record the cluster ID.
3. Create the DecisionVault schema using `scripts/bootstrap.sql`.
4. Verify `decision_episodes.embedding` is a `VECTOR` column.
5. Run a real nearest-neighbor query using cosine distance.
6. Capture sanitized evidence for the submission.

CockroachDB documents `VECTOR(n)` columns and the `<=>` cosine-distance operator.
The final implementation should use a vector index appropriate for the active
CockroachDB Cloud version and verify the plan with the current official docs.

## Managed MCP Server

Use the Cloud Console MCP configuration for the DecisionVault cluster.

Do not commit:
- service account API key
- bearer token
- database password

Submission evidence should show the MCP server actually inspecting or querying
DecisionVault memory, not merely being configured.

## Amazon Bedrock

The Bedrock adapter is lazy-imported so local deterministic tests need no AWS
dependency.

Minimum real evidence:
- one successful model invocation
- request metadata / AWS logs where available
- the model output enters the untrusted decision layer
- deterministic memory tests remain runnable offline

## AWS deployment

Prefer the smallest deployment that remains testable through judging:

- Lambda + API Gateway for a compact API, or
- ECS for a containerized web demo.

Do not add AWS services only to increase service count.
