# fronzbot/blinkpy#1144 — Timezones improperly handled when retrieving clips

**Issue:** `get_videos_metadata(since=...)` returns empty results unless `since` is shifted by ~local_offset hours. UTC-5 user reports needing `timedelta(hours=6)` to surface a clip from 30 minutes ago.

**Investigation:** depth-1 fix. Bug is a single-line, mechanically reproducible inconsistency in `blinkpy/helpers/util.get_time`.

---

## H₀ — `get_time` returns a timestamp string with inconsistent date and offset

**Hypothesis.** `get_time(t)` emits `<UTC date>T<UTC time><LOCAL offset>`. The date/time fields come from `time.gmtime(t)` (UTC), but the `%z` token in `TIMESTAMP_FORMAT` is filled in by `time.strftime` from the *system local* timezone, because `gmtime`'s struct_time has no tz info. Result: a string that decodes as `local_offset` hours in the future of the intended instant.

**Null.** `time.strftime("%z", time.gmtime(...))` already yields `+0000` regardless of local zone.

**Perturbation (induction).**
```
$ TZ='America/New_York' python3 -c '
import time
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
t = 1732286866
print(time.strftime(TIMESTAMP_FORMAT, time.gmtime(t)))'
2024-11-22T14:47:46-0500
```
14:47:46 is the *UTC* clock for `t`, but the appended offset is `-0500`. As an absolute instant, that string is `t + 5h`. Match also confirmed against the issue's own example: user in UTC-5, `get_time(now_utc)` returns `…-0500`, server reads it as 5h in the future, `since=now-1h` to `since=now-5h` all evaluate to "future" relative to the most recent clip ⇒ empty list. The user needs `timedelta(hours=6)` because that is the first `since` value that ends up *before* the actual recording instant after the 5h shift.

**Trajectory.** Divergent. Single perturbation produces the exact symptom the bug report describes; mode count = 1.

**Kill condition.** Would need either: (a) `time.gmtime` returning local time, (b) `%z` reading from gmtime's intent rather than the system, or (c) the API somehow ignoring the offset. None hold.

**Reasoning mode.** Deduction (read the stdlib semantics) + induction (one-shot repro). Confidence 97%.

### Provenance

- Origin: `58ce1095` (Kevin Fronczak, 2019-05-21) — commit message **"Use UTC for time conversions"**, changed `time.localtime` → `time.gmtime`. The intent is explicit. The bug is that `TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S%z"` was left in place; `%z` on a tz-less struct_time falls through to the local offset. Half-done migration.
- Upstream history: #604 (2022) reports the same symptom from a UTC-4 user, never fixed. Maintainer comment on #1144: *"There 100% is a time zone handling bug that I've never been able to track down."* He guessed it was an API quirk; it's a stdlib quirk on his own side.
- Existing mechanism overlooked: none. There's no alternative formatter in the codebase to switch to.

---

## H₁ — Maintainer's regional-differences caveat invalidates a pure-UTC fix

**Hypothesis.** From #604 and #1144 maintainer comments: *"My initial implementation used UTC only which worked in the Americas, but not Europe (if I remember correctly...might have that reversed), for example."* If true, sending `+0000` may break for some users even though it fixes others.

**Null.** The recollection is stale (5+ years). Blink's API today accepts UTC offset timestamps uniformly.

**Perturbation.** Cannot run live without Blink credentials; degraded to deduction over the API contract. Two facts:
1. The current buggy output is *already* a string with an offset suffix (`-0500`, `+0200`, etc.) that contradicts the date component. If Blink were sensitive to the *value* of the offset, the bug would already cause failures of a different shape (e.g. wrong-direction shift). The reported symptom is a uniform-direction "future shift = empty" — consistent with Blink trusting the offset literally.
2. Issue reporter notes Blink's responses use `+00:00` exclusively. The server normalizes to UTC.

**Trajectory.** Convergent. H₁ does not survive: a coherent UTC timestamp cannot be worse than the current inconsistent one. Whatever regional issue the maintainer hit in 2019–2021 was either resolved server-side or was a different bug entirely (the `localtime`-era code in #604 era already had this same `%z`-on-gmtime hazard from May 2019).

**Reasoning mode.** Abduction over contracts. Confidence 80% — pending live test on Blink's API.

**Kill condition.** Live run (post-PR, in CI or by maintainer) showing the fix breaks a region.

---

## H₂ — `stop` parameter off-by-one is a separate, agreed bug

**Hypothesis.** `for page in range(1, stop)` excludes `stop`; `stop=10` (default) fetches pages 1–9, `stop=2` fetches page 1 only. Docstring says "Page to stop on" implying inclusive.

**Perturbation.** Read `blinkpy/blinkpy.py:413`. Maintainer comment: *"Yep agreed with that."*

**Trajectory.** Divergent. Confirmed by both reporter and owner.

**Fix.** `range(1, stop + 1)`.

**Reasoning mode.** Deduction. Confidence 99%.

---

## H₃ — `updated_at` vs `created_at` server filtering

**Hypothesis.** Reporter's further digging suggests Blink's `since` filters on `updated_at`, not `created_at`. This is a server-side semantics issue.

**Trajectory.** Out of scope for #1144. Even if true, it does not explain the original symptom (which is fully accounted for by H₀). File as a follow-up frontier edge; do not bundle into the fix.

---

## Graph state

| Node | Status | Shape | Mode | Conf |
|------|--------|-------|------|------|
| H₀ (offset/date mismatch) | confirmed | divergent | deduction+induction | 97% |
| H₁ (regional API quirk blocks UTC fix) | killed | convergent | abduction | 80% |
| H₂ (`stop` off-by-one) | confirmed | divergent | deduction | 99% |
| H₃ (`updated_at` filter) | deferred | — | — | n/a |

## Frontier edges

- **F₁.** Post-merge: if a European user reports regression, re-open H₁ with their TZ + a fresh server trace. Currently no evidence this will fire.

## Fix shape

`blinkpy/helpers/util.py:69`
```python
def get_time(time_to_convert=None):
    """Create blink-compatible UTC timestamp."""
    if time_to_convert is None:
        time_to_convert = time.time()
    return datetime.datetime.fromtimestamp(
        time_to_convert, tz=datetime.timezone.utc
    ).strftime(const.TIMESTAMP_FORMAT)
```
(Requires `import datetime` — already imported in caller modules; add to util.py.)

`blinkpy/blinkpy.py:413`
```python
for page in range(1, stop + 1):
```

`tests/test_util.py:194` — replace the tautological self-comparison with a pinned, tz-independent assertion:
```python
def test_get_time(self):
    # 2024-11-22T14:47:46Z
    self.assertEqual(get_time(1732286866), "2024-11-22T14:47:46+0000")
```
This test fails on master under any non-UTC TZ and passes after the fix. Add a TZ-forcing wrapper if CI doesn't already pin TZ=UTC.

## Pruning log

- H₁ pruned: maintainer's regional caveat is from a code era that already had the same `%z`-on-gmtime hazard; the symptom they remember was likely the same family of bugs, not evidence against UTC.
- H₃ deferred: separate semantic concern; not the cause of #1144's symptom.
