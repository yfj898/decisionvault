# Phase 9 — Final recording runbook

DecisionVault is code-complete through the latest production-hardening pass.
Phase 9 is intentionally limited to the public <3 minute video and final Devpost
submission; do not add runtime features during recording closeout.

## Frozen recording target

- canvas: 1920×1080;
- browser: Google Chrome kiosk mode;
- target exported duration: about 2:45, leaving meaningful margin below the
  three-minute hard limit;
- live application: the AWS Lambda Function URL already listed in the project
  metadata and Devpost package;
- secret handling: `.venv/demo-token` is read locally and is never printed,
  committed, or rendered in clear text.

## Before recording

From the DecisionVault repository:

```bash
uv run pytest -q
bash scripts/start_submission_browser.sh
```

Confirm the browser fills the 1920×1080 recording canvas and that the health line
says the application is live on AWS Lambda.

For a non-recording functional dry-run, the same automation can compress only
the narration pauses while keeping all live endpoint waits and PASS gates:

```bash
DECISIONVAULT_DEMO_TIMING_SCALE=0.05 python3 scripts/run_submission_demo.py
```

## Record

1. Start Ubuntu's built-in recorder or OBS.
2. Run:

```bash
python3 scripts/run_submission_demo.py
```

3. Do not touch the mouse while the automation is running.
4. Stop recording when the script prints `PASS: submission automation complete`.

The automation performs only two live mutating actions: the repository's existing
protected `/demo` and `/governance-demo` workflows. Both use temporary scopes and
clean them after the proof. The two buttons are clicked through real X11 input.
CDP is used for read-only gates/scrolling and to place the private token into the
password field without exposing it on screen or in logs.

## Frozen visual sequence

### 0:00–0:38 — problem + architecture

Keep the title, CockroachDB/AWS badges, and authority-boundary card visible.

Narration focus:

> AI agents can remember past information. But can we trust remembered outcomes
> to influence real actions? DecisionVault turns long-term memory into governed
> decision evidence.

Use `docs/ARCHITECTURE_SUBMISSION.md` as the architecture frame. Focus on the
authority boundary rather than implementation tables: CockroachDB governed
memory → DVI recall → deterministic decision → signed snapshot → revalidated
execution → verified receipt → independently verified outcome → memory.

### 0:38–1:28 — live causal proof

The automation clicks **Run live memory proof** and then centers the result.

Required visible result:

```text
Memory OFF → GENERIC_RETRY
Memory ON  → REFRESH_PAYMENT_TOKEN
producer_agents=recovery-observer
PASS · temporary scope cleaned
```

### 1:28–1:56 — conflict safety

The automation clicks **Run conflict safety proof**.

Required visible result:

```text
resolution=CONFLICT_ABSTAIN
action=ABSTAIN
strategy=null
executable=false
memory_conflict=true, memory_influenced=false
PASS
```

`CONFLICT_ABSTAIN` is now a first-class non-executable decision. The execution
gateway re-runs the current deterministic policy and will not sign an execution
receipt while this abstention is active.

### 1:56–2:23 — execution / learning safety

Center the external-execution evidence card and call out only:

```text
signed snapshot
→ deterministic external resource
→ exact-path verification
→ signed receipt v3
→ Outcome.UNKNOWN
→ business_outcome_verified=false
```

Narration focus:

> DecisionVault can verify a real external side effect, but transport success is
> not business success. UNKNOWN outcomes are blocked from long-term memory and
> calibration until an independent business verifier proves the outcome.

Do not activate the production GitHub provider for the video.

### 2:23–2:40 — production evidence

The automation centers the static **Reproducible submission evidence** panel.

Call out only the evidence already frozen in the repository:

- `257 / 257` tests;
- production semantic benchmark `14 / 14`;
- latest 30-minute hosted soak: `0` transport failures;
- latest 30-minute hosted soak: `0` validation failures;
- final business-memory leakage: `0` rows.

### 2:40–2:45 — close

The automation returns to the title.

> DecisionVault makes agent memory useful enough to change decisions — and
> governed enough to trust before execution.

## Acceptance gates

- script exits `0`;
- all three terminal gates print `PASS`;
- compressed functional dry-run on an isolated 1920×1080 Xvfb display passes;
- no token or credential appears in the video;
- exported duration is below 3 minutes;
- exported resolution is 1920×1080;
- final Devpost private judge instructions contain the token, while the public
  description/video/repository do not.
