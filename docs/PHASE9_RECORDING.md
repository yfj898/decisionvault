# Phase 9 — Final recording runbook

DecisionVault is code-complete through Phase 8. Phase 9 is intentionally limited
to the public <3 minute video and the final Devpost submission.

## Frozen recording target

- canvas: 1920×1080;
- browser: Google Chrome kiosk mode;
- automation target: about 160 seconds, leaving a few seconds to start/stop the
  recorder while keeping the exported video below 3 minutes;
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

> RAG can remember information. DecisionVault remembers whether a decision
> worked, and proves when that outcome should change another agent's next action.

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

### 1:56–2:28 — production evidence

The automation centers the static **Reproducible submission evidence** panel.

Call out only the evidence already frozen in the repository:

- native `semantic_embedding VECTOR(1024)`;
- model/version-bound `semantic_embedding_space`;
- `decision_memory_heads_scope_space_semantic_vec_idx`;
- authenticated, producer-bound `/revoke` with append-only audit evidence;
- CockroachDB Cloud Managed MCP Memory Auditor;
- Memory ON benefit target accuracy `100%`;
- failed-strategy repetition `0%`;
- false influence `0%`;
- cross-scope leakage `0%`;
- production semantic benchmark `14/14`.

### 2:28–2:40 — close

The automation returns to the title.

> DecisionVault does not just ask whether an agent can remember. It proves when
> remembered outcomes should change behavior — and when they should not.

## Acceptance gates

- script exits `0`;
- all three terminal gates print `PASS`;
- compressed functional dry-run on an isolated 1920×1080 Xvfb display passes;
- no token or credential appears in the video;
- exported duration is below 3 minutes;
- exported resolution is 1920×1080;
- final Devpost private judge instructions contain the token, while the public
  description/video/repository do not.
