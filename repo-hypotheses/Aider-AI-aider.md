# Triage Graph: Aider-AI/aider (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 3702 | --no-verify-ssl fails for gemini/openrouter | OPEN | 8.45 | Small (2 lines) | paul-gauthier labeled "priority" | INVESTIGATED |

## T3702: --no-verify-ssl fails for gemini/openrouter backends

### Root Cause

`aider/main.py:522` sets `os.environ["SSL_VERIFY"] = ""` (empty string). Providers using litellm's shared `client_session` work because aider also sets `httpx.Client(verify=False)`. But gemini, openrouter, and anthropic create per-request httpx clients via litellm's `get_ssl_verify()`, which reads `SSL_VERIFY` from env. Empty string falls through `str_to_bool("")` as `None`, so `""` is passed to `httpx.Client(verify="")` — httpx interprets that as a CA-bundle path, triggering `CERTIFICATE_VERIFY_FAILED`.

### Fix (2 lines production, +2/-1 test)

1. `aider/main.py:522`: Change `os.environ["SSL_VERIFY"] = ""` → `os.environ["SSL_VERIFY"] = "False"`
2. `aider/main.py` after 523: Add `litellm._lazy_module.ssl_verify = False` (belt-and-suspenders)
3. `tests/basic/test_ssl_verification.py:68`: Update assertion to match `"False"` + add `ssl_verify` check

### PR Viability: HIGH

- paul-gauthier labeled "priority" — he wants this fixed
- 2-line production change, net-zero complexity
- Existing test file covers this exact path
- **Risk:** diverdale posted diagnosis Apr 30 with a thumbs-down reaction. Check for competing PRs before submitting.

---

*Dry run — no remote side effects.*

---

## Reinvestigate: PR #5124 (2026-05-18)

### H₀: PR CI broke and needs a patch

**Trigger:** attest verdict `test_fails_on_fix — bash: line 1: pytest: command not found` routed this PR to reinvestigate.

**Perturbation:** read live PR state + attest failure_reason + Docker test env.

**Observations:**
- `gh pr view 5124` — `mergeable: MERGEABLE`, `reviewDecision: ""`, statusCheckRollup = `license/cla SUCCESS` (only check). No failing CI on GitHub.
- Worktree clean at head `a57c268f1`, diff is the intended 2-line change (`SSL_VERIFY="False"`) + matching test assertion update.
- `docker run sweep-tester:latest python3 -m pytest --version` → `No module named pytest`. Container has no pytest installed; aider's `requirements/requirements-dev.txt` carries pytest but isn't installed in the sweep-tester image.

**Classification:** divergent against H₀. The reinvestigate trigger is an attest env defect (sweep-tester image lacks pytest for aider's tooling), not a PR code defect. The fix is logically correct and CI is green upstream.

**Kill condition met:** PR is healthy, nothing to patch.

### Decision

**No code change.** Halt — would only churn a clean PR. The env gap belongs in the substrate (install dev requirements before running aider's pytest, or mark this repo as needing a `test_setup_cmd`), not in the PR. Logged the failure mode here so a future retro can fold it into the attest preflight.

---

## Reinvestigate #2: PR #5124 (2026-05-19)

**Trigger:** attest re-routed PR to reinvestigate. Context pack shows 0 failing checks.

**Perturbation:** `gh pr view 5124` — `mergeable: MERGEABLE`, `reviewDecision: ""`, statusCheckRollup unchanged (`license/cla SUCCESS` only). Head SHA `a57c268f` unchanged since prior reinvestigate.

**Classification:** convergent with prior diagnosis. Same trigger, same upstream state, no new evidence. The attest env gap (sweep-tester lacks pytest for aider) keeps re-firing reinvestigate cycles on a healthy PR — this is the pattern, not a new symptom.

**Frontier edge (substrate, not PR):** attest should detect "test_cmd produces `command not found`" and route to substrate maintenance, not to reinvestigate. Two consecutive reinvestigates with no new info is the signal.

**Decision:** halt. No PR change.
