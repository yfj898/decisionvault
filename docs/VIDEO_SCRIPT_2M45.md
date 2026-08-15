# DecisionVault — Frozen 2:45 Demo Script

Status: **FROZEN FOR SUBMISSION**

Do not add runtime features or change the story after this point unless a real
recording-blocking defect is found.

Target export: **2:45** at 1920×1080. Keep meaningful margin below the official
three-minute limit.

The video uses the real hosted DecisionVault UI. No generated architecture image
is required.

## 0:00–0:18 — Problem

### Visual

Top of the live DecisionVault page. Keep the title and CockroachDB/AWS badges in
frame.

### Narration

> AI agents can remember past information. But production agents need something
> harder: memory of what actually worked, and rules for when that memory is safe
> to trust. DecisionVault turns long-term agent memory into governed decision
> evidence.

## 0:18–0:34 — Architecture

### Visual

Keep the existing **Authority boundary** card visible. Do not switch tabs and do
not show a generated diagram.

### Narration

> CockroachDB is the authoritative memory layer. Distributed Vector Indexing
> recalls relevant outcome evidence. Deterministic governance commits the action,
> AWS Lambda revalidates execution, and the model only explains the decision — it
> never controls it.

## 0:34–1:20 — Live causal proof

### Visual

Automation clicks **Run live memory proof** and centers the result.

Required visible result:

```text
Memory OFF → GENERIC_RETRY
Memory ON  → REFRESH_PAYMENT_TOKEN
producer_agents=recovery-observer
PASS · temporary scope cleaned
```

### Narration

> Here Agent A records that `GENERIC_RETRY` failed. Now Agent B receives the same
> kind of recovery problem. With memory disabled, it repeats the generic retry.
> With memory enabled, CockroachDB recalls Agent A's governed outcome evidence and
> Agent B changes to `REFRESH_PAYMENT_TOKEN`.
>
> The producer is visible here: `recovery-observer`. The agents did not need to
> share an in-memory conversation. The behavior changed because of durable shared
> memory, and the temporary demo scope is cleaned after the proof.

## 1:20–1:48 — Conflict safety

### Visual

Automation clicks **Run conflict safety proof**.

Required visible result:

```text
resolution=CONFLICT_ABSTAIN
action=ABSTAIN
strategy=null
executable=false
memory_conflict=true
PASS
```

### Narration

> Useful memory also needs a safe failure mode. Here two governed memories
> conflict. DecisionVault does not guess. It returns `CONFLICT_ABSTAIN`, no
> strategy, and `executable=false`. The execution gateway rechecks current policy,
> so conflicting memory cannot force a real action.

## 1:48–2:18 — Execution and learning safety

### Visual

Scroll to **Reproducible submission evidence**. Keep the external execution
safety card visible.

Required visible text:

```text
signed receipt v3
Outcome.UNKNOWN
business_outcome_verified=false
```

### Narration

> DecisionVault also verifies real external side effects with signed execution
> receipts. But a transport success is not automatically a business success.
> A verified external write remains `Outcome.UNKNOWN`, so it cannot enter
> long-term memory or calibration until independent business evidence proves the
> real outcome. Memory can influence execution, but it cannot manufacture its own
> success label.

## 2:18–2:38 — Production proof

### Visual

Stay on the same evidence panel. Point only to the strongest frozen numbers.

```text
257 / 257 tests
14 / 14 production semantic benchmark
30-minute hosted soak · 0 transport failures
30-minute hosted soak · 0 validation failures
0 rows business-memory leakage
```

### Narration

> The current build passes 257 tests and all 14 production semantic adversarial
> cases. The latest 30-minute hosted soak finished with zero transport and zero
> contract-validation failures, and the final database audit found zero leaked
> business-memory rows.

## 2:38–2:45 — Close

### Visual

Automation returns to the title.

### Narration

> DecisionVault makes agent memory useful enough to change decisions — and
> governed enough to trust before execution.

## Recording rules

- Record only the real hosted application.
- No generated image is needed.
- Do not show the private judge token in clear text.
- Do not open AWS, CockroachDB, GitHub credentials, or terminal secrets.
- Do not activate the production GitHub execution provider.
- Do not narrate every benchmark number; keep the story causal and visual.
- No copyrighted music.
- Export below 3:00; target 2:45.

## Acceptance gates

- `Memory OFF → GENERIC_RETRY` visible.
- `Memory ON → REFRESH_PAYMENT_TOKEN` visible.
- `producer_agents=recovery-observer` visible.
- conflict proof shows `CONFLICT_ABSTAIN` and `executable=false`.
- evidence panel shows `257/257`, `14/14`, latest soak zeros, and
  `Outcome.UNKNOWN` learning isolation.
- both live workflows show cleanup PASS.
- token never appears in the video.
- final export is 1920×1080 and less than three minutes.
