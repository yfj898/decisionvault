# Judge testing

## Live application

Open the public AWS Lambda Function URL listed in the Devpost **Try it out** field.

`GET /` and `GET /health` are public and read-only. The one-click causal proof is
protected so the public internet cannot create arbitrary DecisionVault memory.

## Demo access

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

The live runtime uses CockroachDB Cloud persistent memory, CockroachDB Distributed
Vector Indexing, NVIDIA semantic embeddings, AWS Lambda, and the bounded NVIDIA
explanation provider. Managed MCP has a separate reproducible memory-auditor CLI
documented in the repository evidence.

## Security boundary

Do not publish the demo token in README, screenshots, source code, or video. If a
judge needs a replacement token, rotate `DEMO_API_TOKEN` in the Lambda environment
and update the private Devpost testing instructions.
