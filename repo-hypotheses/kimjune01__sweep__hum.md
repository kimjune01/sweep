# Investigation: why is the sweep pipeline not humming?

**Date:** 2026-05-17
**System under test:** sweep itself (the substrate)
**Triggering observation:** cockpit shows all 11 actor stations at 0/0 queued/in-flight, sift `empty ×8`, sift inbox 7h cold, despite worker + temporal both `up`.

## Phase 1 — Observation (H₀)

**H₀:** DRY mode is suppressing all visible work (the most prominent control flag).

**Null:** dry was just narrowed by commit `5404ccd` (2026-05-17 04:10 -0700) to apply only to ship-actor, not to deliver-to-inbox / route_classified. So downstream actors should still be flowing under DRY — only new-PR-create should be on hold.

**Perturbation:** check `~/.sweep/events.jsonl` event rate over the last 24h and inspect the worker log.

**Trajectory shape: DIVERGENT against H₀.**

Hourly event counts (UTC):

| Hour | Events |
|------|--------|
| 00 | 91 |
| 01 | 207 |
| 02 | 202 |
| 03 | 199 |
| 04 | 195 |
| **05** | **8** ← collapse |
| 06 | 4 |
| 07 | 4 |
| 08 | 8 |
| 10 | 4 |
| 11 | 0 (current) |

Worker process is alive, started ~18 minutes ago (after a `sweep down && sweep up`), but **zero events have fired since restart**. DRY was already narrowed before the collapse window, and the few events that did fire after 04:38 are all `remit_card_deposited` from the notification poller (independent codepath) — not pipeline-driven work. **H₀ killed.** The collapse is upstream of DRY.

**Edge:** what stopped firing at 04:38? Last `prospect_window` events cluster at 04:38; last `scout_cycle` at 03:47; last `prospect_deposited` cluster at 00:29. Scout has been near-silent for ~7h. Why?

## Phase 2 — Fan-out

### H₁: Scout's CLI calls are rate-limited / auth-expired

**Perturbation:** check for `warm_org_search_failed` and `gh` errors.

Found 78 `warm_org_search_failed` events in last 1000, clustered at 01:00:10–01:00:12 UTC. Errors are gh-CLI command failures truncated in the log. Could be a transient gh CLI rate hit.

**Status: PARTIAL.** Real failures, but they predate the 04:38 collapse by ~3h and the search-failure pattern doesn't itself wedge scout — scout retries on its own takt. **H₁ refined into H₁ₐ:** the gh failures alone don't explain a 7h silence. Move on.

### H₂: A downstream signal is being dropped and no one notices

**Perturbation:** `tail` worker.log + grep for errors / exceptions / dropped signals.

Found, repeatedly:

```
ERROR:temporalio.worker._workflow_instance:Failed deserializing signal input
  for `deliver` on workflow SkillActor with ID `rope-actor`
  and run ID …, dropping the signal

TypeError: Expected value to be str, was <class 'NoneType'>
TypeError: Failed converting field `repo` on dataclass <class 'sweep.types.Message'>
RuntimeError: Failed decoding arguments
```

Rope-actor's `deliver` signal is rejecting messages because their `repo` field is `None`, but `Message.repo` is typed `str`. Temporalio's policy on signal-decode failure: log it and **drop the signal**. No retry, no dead-letter, no andon, no observability event. Pipeline silently loses the kick.

**Status: DIVERGENT for. H₂ confirmed.**

### H₂.₁ — Provenance check: where does the bad signal originate?

`grep -rn kick_rope_card` finds the call site in `sweep/activities/rope.py:99`:

```python
async def kick_rope_card(sender: str = "idle") -> str | None:
    ...
    msg = Message(
        msg_id=msg_id,
        sender=sender,
        intent="pull",
        repo=None,            # ← typed `str` on the receiver
        pr=None,
        branch=None,
        payload={},
        ts=ts.isoformat(),
    )
    ...
    return await _signal_actor("rope", msg)
```

`Message.repo: str` (no Optional) in `sweep/types.py:30`. Producer passes `None`; receiver-side temporalio deserialization rejects on type mismatch. Every "I'm idle, take more work" hint that any actor sends to rope is **lost**.

Effect: rope (the PID-style scout-depth controller, added in commit `13ff522`) never gets the idle-signals it's supposed to act on. Scout depth control never tugs scout. Scout doesn't refire. Prospect inbox drains. Sift starves. Cockpit shows all stations idle because… they actually are idle, waiting on inputs that no controller is requesting.

**Causal chain:**

```
qa/investigate/sift finish work
  → kick_rope_card(repo=None)
  → _signal_actor("rope", msg)
  → temporalio signal-decode rejects (repo: str / got None)
  → "dropping the signal" (logged, not observed as event)
  → rope-actor never wakes
  → scout-depth controller never tugs scout
  → scout doesn't refire
  → prospect inbox stays empty
  → sift's empty_streak climbs
  → all downstream stations drain to 0
  → cockpit reads "everything idle"
```

## Phase 4 — Diagnosis

Single root cause, type-conformance bug introduced when rope-actor was added (commit `13ff522`, "PID-style scout-depth controller, replaces takt"). The contract gap: producer says "no repo applies here, this is a pull-hint card" → expressed as `None`. Receiver schema says `repo: str` (no Optional). Temporal silently drops on mismatch. The substrate's existing andon, leakdog, and cockpit surfaces are all blind to dropped signals because dropped-signal IS NOT AN EVENT — it's a log line in worker.log.

## Phase 5 — Fix shape

Two reasonable fixes; pick the second.

| | Fix | Pro | Con |
|---|---|---|---|
| A | Type `Message.repo: str \| None` | One-line change | Widens the contract for every Message consumer; many code paths assume `msg.repo` is a real string |
| B | `kick_rope_card` passes `repo=""` (existing "no repo" sentinel — already used by `leakdog-heartbeat` cards in sift inbox) | Conforms to existing convention; rope's downstream already handles empty-repo cards | Doesn't catch the next caller who passes None |

**Recommended: B.** The codebase already uses `repo=""` as the "no specific repo" sentinel. The fix is local to one file, two lines.

Combined with that, **file two substrate hypotheses (O6, O7) to OPS_HYGRAPH** so the next dropped-signal scenario isn't equally invisible.

## Frontier edges (open after this round)

- E1: confirm `repo=""` is acceptable on the rope-actor receive side (no downstream assumes a real owner/repo string)
- E2: the second-order finding (silent signal drops) deserves its own surface — see O6 below
- E3: the "cockpit-says-idle but worker-isn't-actually-doing-anything" condition needs a heartbeat-staleness chip — see O7 below

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Pipeline event rate collapsed 04:38 → 0 events/hr | Induction (counted) | 99% |
| DRY-narrowing is not the cause | Deduction (read git log + commit time vs collapse time) | 98% |
| Signal-decode failures are dropping rope-kicks | Induction (worker.log grep) | 98% |
| Source of the bad signal is `kick_rope_card` | Deduction (read rope.py:99) | 99% |
| Fix B unblocks the line | Abduction (type-match the producer to consumer convention) | 80%; needs verification by applying fix + observing event resumption |

## Post-fix verification (2026-05-17)

Three bugs found, all instances of the silent-signal-drop failure class catalogued in [[O6]]:

1. `kick_rope_card` passes `repo=None`; receiver rejects on `repo: str` type mismatch → fix: pass `repo=""` + widen `Message.repo` to `str | None` (so Temporal can decode the bad-payload history persisted in workflow state).
2. `_ACTOR_WORKFLOW_IDS` in `pr_state.py` was missing the `"scout": "scout-actor"` entry → every `_signal_actor("scout", …)` call from rope-actor hit the `unwired_actor` branch and emitted `signal_failed` instead of waking scout. Fix: add the entry.
3. `sweep/activities/leakdog.py` imported `SIFT_INBOX` from `sweep.activities.sift`, but the constant lives in `sweep.activities.scout`. Result: leakdog's safety-net scout heartbeat (the bootstrap that keeps the line moving when all actors are idle) silently failed every tick with an ImportError that was logged only into the tick's return dict. Fix: import from `sweep.activities.scout`.

The third bug is the kind that O7's heartbeat-staleness chip would catch — a daemon that ticks fine but does no work, with the failure surface hidden in the daemon's return value rather than emitted as an event.

**Verified humming after all three fixes + worker bounce:**
- `scout_cycle` events firing on leakdog's 60s heartbeat (was zero for 7+ hours)
- `sweep cockpit` shows Sift rate 4.5/h, Scout 1.2/h, no `🩸` chip on the spine
- `sweep leakdog` shows all spine interfaces at 0 leak ✅
- Worker log: zero new `dropping the signal` lines since restart
- Only outstanding surface leak: `approval → posted (1)` — the pre-existing tissue draft that didn't post because `post_disabled` flag is set (intentional operator hold; correct behavior)

Investigation closed.
