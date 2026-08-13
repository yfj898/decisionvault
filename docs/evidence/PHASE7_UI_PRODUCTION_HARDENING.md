# Phase 7 — UI / Production Hardening Evidence

Status: **PASS**

Date: 2026-08-13

## Deployed judge UI

DecisionVault serves a responsive, dependency-free HTML/CSS/JavaScript UI from
the same AWS Lambda Function URL as the API. The page exposes the competition
architecture, deployment health, and a protected one-click causal proof.

Live UI:

`https://mfcr7b2k3j7lrwr44u35i5rchq0fbncb.lambda-url.ap-northeast-1.on.aws/`

Observed live root response:

```text
HTTP 200
content-type: text/html; charset=utf-8
DecisionVault UI present: true
Memory OFF panel present: true
Memory ON panel present: true
X-Frame-Options: DENY
```

## Atomic causal demo

`POST /demo` is protected by the same `X-DecisionVault-Token` boundary as the
existing mutation routes. The server creates a random temporary scope, records a
failed `GENERIC_RETRY` episode, runs the same similar case with Memory OFF and
Memory ON, then deletes the temporary scope in a `finally` cleanup path.

Observed live result:

```text
demo_http=200
expected_change=True
cleaned=True

Memory OFF:
  strategy=GENERIC_RETRY
  memory_influenced=False

Memory ON:
  strategy=REFRESH_PAYMENT_TOKEN
  memory_influenced=True
  recalled_episode_count=1
  model_provider=nvidia:meta/llama-3.1-8b-instruct
  model_explanation_present=True
```

Independent CockroachDB verification after the run:

```text
phase7_demo_rows_remaining=0
cleanup_db_check=PASS
```

## Security / production boundaries

- The demo token is never embedded in HTML or committed to Git.
- `POST /demo` without the token returns `401`.
- Public `GET /health` is read-only.
- Internal-error responses expose exception type only, not secret values.
- No external fonts, scripts, CSS, analytics, or CDN dependencies are used.
- UI response uses `Cache-Control: no-store`.
- CSP is present.
- `X-Content-Type-Options: nosniff` is present.
- `X-Frame-Options: DENY` is present.
- `Referrer-Policy: no-referrer` is present.

## Browser verification

Real headless Google Chrome loaded the deployed Function URL successfully at:

- desktop: `1440x1000`
- mobile: `390x844`

Both DOM runs contained the page title, Run button, Memory OFF and Memory ON
panels, and the JavaScript health check completed to `Live on AWS Lambda`.

## Local gates

- `27` tests PASS.
- `git diff --check` PASS before evidence freeze.
- UI static scan confirms no demo-token literal and no external web assets.

## Claim boundary

Phase 7 proves a live AWS-hosted judge UI and a protected, repeatable causal
memory demonstration. It does not claim the public UI itself is a general-purpose
production authentication system; the token is a deliberately narrow hackathon
demo access boundary.
