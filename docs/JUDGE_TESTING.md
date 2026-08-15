# Judge testing

## Live application

Open the public AWS Lambda Function URL listed in the Devpost **Try it out** field.

`GET /` and `GET /health` are public and read-only. The one-click causal proof is
protected so the public internet cannot create arbitrary DecisionVault memory.

## Fast judge path — about 90 seconds

### 1. Prove memory changes behavior

The judge/demo token is supplied separately in the private Devpost testing
instructions. It is intentionally not committed to Git or embedded in the page.

1. Open the live DecisionVault page.
2. Paste the judge/demo token.
3. Click **Run live memory proof**.
4. Observe Agent B with Memory OFF return `GENERIC_RETRY`.
5. Observe Agent B with Memory ON recall Agent A's outcome and return
   `REFRESH_PAYMENT_TOKEN`.
6. Confirm `producer_agents=recovery-observer` in the Memory ON panel and the
   cleanup result in the PASS banner.

This is the causal claim: another agent changes its next decision because of
durable governed outcome evidence in CockroachDB, not because the two agents
shared an in-memory conversation.

### 2. Prove bad/conflicting memory cannot force execution

1. Click **Run conflict safety proof**.
2. Confirm the result shows:

```text
resolution=CONFLICT_ABSTAIN
action=ABSTAIN
strategy=null
executable=false
memory_conflict=true
memory_influenced=false
```

`CONFLICT_ABSTAIN` is a first-class non-executable decision. The execution
gateway re-runs current deterministic policy and will not sign an execution
receipt while that abstention remains active.

### 3. Inspect production evidence without installing anything

Scroll to **Reproducible submission evidence**. The page summarizes the native
CockroachDB `VECTOR(1024)` semantic path, Distributed Vector Index, Managed MCP
audit path, current production semantic benchmark, and production-hardening
evidence.

The strongest current frozen evidence is:

```text
257 / 257 tests
Production semantic benchmark: 14 / 14
30-minute hosted soak: 0 transport failures
30-minute hosted soak: 0 validation failures
Post-run business-memory leakage: 0 rows
```

The repository contains deeper reproducible evidence for judges who want to
inspect the SQL plans, adversarial cases, external-execution proof, and soak
reports. No local installation is required for the primary judging path.

The live runtime uses CockroachDB Cloud persistent memory, CockroachDB Distributed
Vector Indexing, NVIDIA semantic embeddings, AWS Lambda, and the bounded NVIDIA
explanation provider. Managed MCP has a separate reproducible memory-auditor CLI
documented in the repository evidence.

DecisionVault also contains a real external side-effect adapter proven against a
dedicated GitHub Contents sandbox resource. Production intentionally remains on
the bounded sandbox provider pending a dedicated least-privilege GitHub
credential. The external proof is not part of the judge's mutating live path and
does not need to be re-run.

The external receipt contract deliberately uses `Outcome.UNKNOWN` and
`business_outcome_verified=false`: external transport success cannot become
positive long-term memory or a calibration label without an independent business
outcome verifier.

## Security boundary

Do not publish the demo token in README, screenshots, source code, or video. If a
judge needs a replacement token, rotate `DEMO_API_TOKEN` in the Lambda environment
and update the private Devpost testing instructions.
