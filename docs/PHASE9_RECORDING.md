# Phase 9 — Final Recording Runbook

DecisionVault runtime is frozen for submission. This phase is limited to
recording, video validation, Devpost entry, and final submission checks.

Canonical narration and timing:

`docs/VIDEO_SCRIPT_2M45.md`

Canonical simple architecture:

`docs/ARCHITECTURE_SUBMISSION.md`

## Frozen recording target

- 1920×1080;
- Google Chrome kiosk mode;
- target export: about 2:45;
- hard limit: below 3:00;
- real hosted AWS Lambda application;
- no generated architecture image;
- `.venv/demo-token` stays local and never appears in logs or on screen.

## Before recording

From the DecisionVault repository:

```bash
uv run pytest -q
bash scripts/start_submission_browser.sh
```

Confirm:

- Chrome fills the 1920×1080 recording canvas;
- the page health line says the application is live on AWS Lambda;
- the evidence panel contains `257/257`, `14/14`, `Outcome.UNKNOWN`, and the
  latest soak zero-failure markers.

For a compressed non-recording dry-run:

```bash
DECISIONVAULT_DEMO_TIMING_SCALE=0.05 python3 scripts/run_submission_demo.py
```

## Record

Preferred formal path — fully automated, matching the prior BridgeSAT-style
isolated 1920×1080 recording workflow but without requiring manual recorder
start/stop:

```bash
bash scripts/record_submission_video.sh
```

The script:

1. starts an isolated `1920x1080x24` Xvfb display;
2. starts Chrome in kiosk mode on the live AWS Lambda app;
3. records that display at 30 fps through GStreamer `ximagesrc → x264enc → mp4mux`;
4. runs `scripts/run_submission_demo.py` with the frozen 2:45 timeline;
5. cleanly sends EOS to the MP4 recorder;
6. verifies H.264 / 1920×1080 / 30 fps / `<3:00` with `ffprobe`;
7. writes the accepted master to:

```text
recordings/DecisionVault_Submission_Demo_2m45s.mp4
```

The screen master is intentionally narration-free. Add the frozen narration
from `docs/VIDEO_SCRIPT_2M45.md` in the voiceover stage, as with the previous
submission workflow.

## Recorded screen master

Formal automated capture completed successfully on August 15, 2026:

```text
file: recordings/DecisionVault_Submission_Demo_2m45s.mp4
duration: 166.763333 s (2:46.76)
codec/profile: H.264 High
pixel format: yuv420p
resolution: 1920×1080
nominal frame rate: 30 fps
decoded frames: 5003
full-file decode errors: 0
size: 58,992,581 bytes
sha256: f0d079f0ab4e63d6ac2d28484b244f8c32de587b357e4303cbdb72121c992dcd
```

The same master is copied outside the repository to:

```text
/home/bili-guo/Videos/录屏/DecisionVault_Submission_Demo_2m47s.mp4
```

All four recording gates passed during the formal run. Post-record production
cleanup was also verified: all eight business memory/outbox tables were empty,
`adaptive-cloud-*` rows were zero, and retained quality telemetry remained
`2 / 2 / 3`.

## Frozen visual timeline

```text
0:00–0:18  title / problem
0:18–0:34  existing Authority boundary card
0:34–1:20  live Memory OFF vs Memory ON proof
1:20–1:48  live conflict safety proof
1:48–2:18  external execution / UNKNOWN learning boundary
2:18–2:38  production evidence
2:38–2:45  return to title / close
```

The automation performs only the two existing protected judge mutations:

- `/demo`
- `/governance-demo`

Both use temporary scopes and clean up after themselves. CDP is used only for
read-only gates/scrolling and for placing the private token into the password
field without exposing it in clear text.

## Required visible proof

### Causal memory

```text
Memory OFF → GENERIC_RETRY
Memory ON  → REFRESH_PAYMENT_TOKEN
producer_agents=recovery-observer
PASS · temporary scope cleaned
```

### Conflict safety

```text
resolution=CONFLICT_ABSTAIN
action=ABSTAIN
strategy=null
executable=false
PASS
```

### Learning safety / production evidence

```text
Outcome.UNKNOWN
business_outcome_verified=false
257 / 257 tests
14 / 14 production semantic benchmark
30-minute hosted soak · 0 transport failures
30-minute hosted soak · 0 validation failures
0 rows post-run business-memory leakage
```

## Final acceptance

- automation exits `0`;
- all browser gates print `PASS`;
- no credential appears in the recording;
- video is 1920×1080;
- video is below three minutes;
- public video is uploaded to YouTube or Vimeo;
- Devpost private judge instructions contain the current demo token;
- hosted app remains available through judging;
- no runtime feature work is introduced during submission closeout.
