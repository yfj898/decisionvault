# GitHub Actions CI Evidence

Date: 2026-08-14

Status: PASS.

DecisionVault now runs a public, secret-free deterministic CI workflow on each
push to `master` and on pull requests.

The workflow uses Python 3.12 and `uv`, then executes:

```text
frozen dependency sync
→ deterministic pytest suite
→ git diff --check
→ tracked-file credential-shape scan
```

No CockroachDB, AWS, NVIDIA, MCP, demo, agent, or execution-signing credential
is provided to the public CI job. Cloud proofs remain separately captured as
sanitized evidence.

The first run exposed a scanner self-false-positive caused by the documented
`USER:PASSWORD@HOST` placeholder. The scanner was corrected without excluding
itself or lowering the scan surface: it now ignores only the explicit
placeholder match and continues scanning every tracked text file.

Verified successful run:

```text
GitHub Actions run: 31767363853
commit: b539b3e
workflow: CI
job: deterministic-gates
conclusion: success

checkout                         PASS
uv installation                  PASS
Python 3.12                      PASS
frozen environment sync          PASS
deterministic test suite         PASS
git diff --check                 PASS
tracked credential-shape scan    PASS
```

The public workflow is `.github/workflows/ci.yml` and the repository README
surfaces its badge.
