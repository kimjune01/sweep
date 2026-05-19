# open-telemetry/opentelemetry-python#5199 — hypothesis graph (reinvestigate)

PR: `fix/event-logger-deprecation-warning` @ cd113cf3ec0c
Status: **HALT — maintainer redirect**

## H0 — observation

Reinvestigate triggered by attest because CI went red after the user pushed a follow-up commit responding to the first maintainer comment.

Failing checks:
- `changelog` — towncrier check
- `misc / public-symbols-check`
- `check` — aggregator, fails because `misc` failed

`lint`, `tests`, `contrib` all pass.

## H1 — changelog job failure cause

Tail of `changelog` job:

```
subprocess.CalledProcessError: Command '['git', 'diff', '--name-only', 'origin/main...']' returned non-zero exit status 128.
No changelog fragment found for this PR.
```

But `.changelog/5199.fixed` *does* exist at head SHA cd113cf3 (verified via gh contents API). The git diff is failing because the CI checkout fetched only the PR merge ref and doesn't have `origin/main` populated for towncrier's compare-with logic.

- **Reasoning mode:** deduction. 92%.
- **Shape:** convergent — fragment is present, infra-side check broke.
- **Edge (would-be):** look at `.github/workflows/changelog.yml` to confirm fetch-depth/ref args and patch them — but see Phase 4.5 reframe below.

## H2 — public-symbols-check failure

Not pursued. Same workflow file (`misc.yml`) — likely a similar setup issue or a real public-symbol diff problem (i.e. the PR may have changed something callable on `EventLogger.emit`'s signature). Untested.

## Phase 4.5 — reframe (load-bearing)

PR thread review:

> **tammy-baylis-swi** (2026-05-14T22:44:38Z, the day CI went red):
> Hi @kimjune01, thank you for contributing but **this API itself is deprecated**. I recommend picking up an issue to stabilize the new Logging API/SDK if you're interested!

A maintainer has explicitly flagged that the PR is operating on a deprecated module — the `_events` SDK was kept available with a leading underscore precisely because the maintainers don't want it shored up. Fixing a deprecation warning *inside* an already-deprecated, underscore-prefixed module produces no value for them; it just extends the lifetime of code they want gone.

This is a stronger halt signal than CI. Even if we fix the towncrier diff and the public-symbols-check, the PR ends up rejected on the merits with this comment as the receipt. Pushing more commits would:

- Burn a `drip` slot for this repo on a PR that's not going to merge
- Cost maintainer attention to re-review a PR they already redirected
- Anchor on a deprecated codepath instead of moving up the stack to the Logging API/SDK they pointed at

## Decision

**Do not push fixes to this branch.** Surface to the operator with:
- Maintainer redirect (deprecated API)
- The relevant project board they pointed at: open-telemetry project 123 ("Logging API/SDK stabilization")

If we want any contribution into this repo, take an issue from that project and start a fresh PR; this branch should be closed (or the maintainer will close it).

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| `.changelog/5199.fixed` exists at head SHA | deduction (gh API) | 99% |
| towncrier fails due to missing origin/main in checkout | deduction from stack trace | 92% |
| Maintainer redirected the PR to a different API surface | deduction (direct quote) | 99% |
| Fixing CI here is wasted effort | abduction from redirect | 85% |

## Frontier (closed)

No open edges. The reframe retires H1's edge: the towncrier fix is technically known but not worth shipping on this branch.
