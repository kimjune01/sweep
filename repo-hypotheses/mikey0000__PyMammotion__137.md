# Hypothesis graph: mikey0000/PyMammotion#137 — login_v2 "Access denied" for shared account

## H₀ — Default `App-Version` header is server-rejected

- **Hypothesis**: `MammotionHTTP(...).login_v2()` with no `ha_version` produces `App-Version: NOT HA,2.3.4.22`, which the Mammotion cloud rejects with `{"code":200,"msg":"Access denied"}`.
- **Null**: server denies for a different reason (creds, shared-account status, signature).
- **Perturbation**: reporter re-ran identical login with `ha_version="3.4.22"` → header becomes `HA,2.3.4.22` → `code=0, msg='Request success'`.
- **Trajectory**: divergent confirm. The only thing that changed between failure and success is the `App-Version` string.
- **Shape**: divergent.
- **Edge**: which header-prefix tokens the server accepts/rejects (`HA,...` vs `NOT HA,...` vs `ALIYUN DEMO,...`).
- **Mode**: induction (real-user A/B). Confidence ~95%.

## H₁ — Provenance: the rejecting default is deliberate

`pymammotion/http/http.py:148` blame trail:

| Commit | Default when `ha_version` is None |
|---|---|
| `83de56e` | `ALIYUN DEMO,{ha_version}` |
| `bcb1003` | `ALIYUN DEMO,{APP_VERSION}` ("blocked header causing no login issues again") |
| `50c2890` | `ALIYUN DEMO,{APP_VERSION}` (kept) |
| `91c9d49` | unchanged default |
| `a7dcda2` | **`NOT HA,{APP_VERSION}`** ("authentication fixes") ← current |

The current `NOT HA,...` prefix was introduced deliberately in a commit titled "authentication fixes." Combined with the maintainer's issue comment on 2026-05-07 ("Put the mammotion ha release version in") and 2026-05-13 ("interesting that ALIYUN DEMO,2.3.4.22 -> Access denied was denied, will tweak that"), the signal is unambiguous: the maintainer wants callers to pass `ha_version` explicitly and is already iterating on the prefix taxonomy.

- **Mode**: deduction from git history + maintainer comments. Confidence ~95%.

## H₂ — A "sensible default" PR would fight the maintainer's design

Considered fix: when `ha_version is None`, fall back to `f"HA,{APP_VERSION}"` (which is `HA,2.3.4.22`, the exact value the reporter's workaround produces).

- **Kill condition**: the current code produces `NOT HA,{APP_VERSION}` by intentional change in `a7dcda2`. A PR that reverts the prefix to `HA,...` argues against a deliberate design choice the maintainer just made. The maintainer's response to the reporter ("Put the mammotion ha release version in") confirms callers are expected to pass `ha_version`. Per `/investigate` "Go with the flow" rule, contributors imitate maintainer intent — don't reform it.
- **Trajectory**: divergent against this PR shape.

## H₃ — Maintainer has WIP

2026-05-13 comment: "will tweak that." The maintainer is actively iterating on the App-Version header. Any PR landing now risks colliding with their in-progress tweak; the thrash already shows 5 distinct prefix variants in recent history.

## Reframe (Phase 4.5)

Original question reframes from "what's the bug, write a fix" to "is there a fix to ship?" — and the answer is no:

1. The defect is real and well-characterized (H₀).
2. The maintainer authored the rejecting default deliberately (H₁) and signaled they'll tweak it themselves (H₃).
3. The "obvious" fix (default to `HA,{APP_VERSION}`) fights that design (H₂).

No PR. The remaining value is reporting the provenance back to the maintainer as a tissue comment so they can land their own tweak with the audit trail in hand.

## Frontier (open)

- What server-side classifier rejects `NOT HA,...` and `ALIYUN DEMO,...` but accepts `HA,...`? Not investigable from the client.

## Verdict

**no_fix_to_ship** — defer to maintainer's announced tweak. Route to `/tissue` with provenance summary.
