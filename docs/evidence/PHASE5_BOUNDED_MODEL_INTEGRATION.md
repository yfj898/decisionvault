# Phase 5 — Bounded Model Integration Evidence

Status: **PASS**

## Authority boundary

The model is intentionally non-authoritative.

1. CockroachDB memory is recalled first.
2. `OutcomeAwarePolicy` commits the strategy.
3. The optional model advisor receives the already-committed decision plus the
   recalled outcome evidence.
4. The model can return only explanatory text.
5. Any provider exception or empty response is ignored; the strategy is unchanged.

This preserves CockroachDB as the persistent memory authority. The model cannot
select, replace, or veto the committed strategy.

## Contract verification

- 20-test bounded-advisor gate: PASS at Phase 5 freeze.
- Advisor text can be attached to a committed decision.
- Provider failure leaves the committed strategy unchanged.
- Memory-disabled behavior remains independent of the advisor.

## NVIDIA live provider evidence

The NVIDIA credential was loaded at runtime from a sibling project's ignored
environment file. It was not copied into DecisionVault and is not committed.

Provider authentication:

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

The same model-advisor boundary is also exercised by the Phase 6 AWS Lambda
deployment.

## Bedrock boundary

Amazon Bedrock support remains implemented as an optional provider seam. A
CockroachDB Cloud service-account key was correctly rejected by Bedrock and is
not represented as Bedrock evidence. Bedrock is not required for the frozen
Phase 5 claim.

## Secret handling

- No NVIDIA key is stored in Git.
- No AWS credential is stored in Git.
- No CockroachDB connection string is stored in Git.
- Evidence contains no bearer token, SQL password, cluster ID, or private key.
