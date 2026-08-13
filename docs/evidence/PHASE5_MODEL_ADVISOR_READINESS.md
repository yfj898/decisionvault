# Phase 5 — Model Advisor Readiness Evidence

Status: **BEDROCK LIVE INVOCATION PENDING**

## Authority boundary

The model is intentionally non-authoritative.

1. CockroachDB memory is recalled first.
2. `OutcomeAwarePolicy` commits the strategy.
3. The optional model advisor receives the already-committed decision plus the
   recalled outcome evidence.
4. The model can return only explanatory text.
5. Any provider exception or empty response is ignored; the strategy is unchanged.

This keeps CockroachDB as the persistent memory authority and prevents a model
provider from bypassing the deterministic memory-aware policy.

## Local contract verification

- 20 tests PASS.
- Advisor text can be attached to a committed decision.
- Provider failure leaves the committed strategy unchanged.
- Memory-disabled behavior remains independent of the advisor.

## Auxiliary NVIDIA live evidence

The existing NVIDIA credential from a sibling project was read only at runtime;
it was not copied into DecisionVault and was not committed.

Provider authentication check:

- NVIDIA API: HTTP 200.
- Visible model catalog: 102 models.

Fast-model live call:

- Model: `meta/llama-3.1-8b-instruct`.
- HTTP status: 200.
- Explanation returned: yes.
- Observed latency: 1.37 seconds.

End-to-end bounded advisor smoke with real CockroachDB Cloud memory:

```text
memory_source=cockroachdb-cloud
strategy=REFRESH_PAYMENT_TOKEN
memory_influenced=True
model_provider=nvidia:meta/llama-3.1-8b-instruct
model_explanation_present=True
bounded_model_advisor_smoke=PASS
cloud_smoke_rows_cleaned=PASS
```

This NVIDIA evidence is auxiliary only and is **not** represented as Amazon
Bedrock evidence.

## Bedrock competition path

The implemented default is:

- provider: Amazon Bedrock Runtime;
- API: `Converse`;
- model: `amazon.nova-lite-v1:0`;
- region: `ap-northeast-1`;
- credential options: `AWS_BEARER_TOKEN_BEDROCK` or a standard AWS SDK credential
  source.

The live Bedrock gate remains pending because no AWS credential source is present
in the current runtime. Phase 5 must not be marked PASS until a real Bedrock
response is received through this same `--cloud-memory` path.

## Secret handling

- No NVIDIA key is stored in DecisionVault.
- No AWS key is stored in DecisionVault.
- No CockroachDB connection string is stored in DecisionVault.
- Evidence contains no bearer token, SQL password, Cluster ID, or private key.
