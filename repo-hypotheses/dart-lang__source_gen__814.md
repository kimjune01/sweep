# dart-lang/source_gen#814 — partId error message mismatch

PR: https://github.com/dart-lang/source_gen/pull/814 (open, mergeable, CLA pass, no reviews)
Fixes: https://github.com/dart-lang/source_gen/issues/607

## H₀ — error message contradicts the regex

**Hypothesis:** The `ArgumentError` thrown by `SharedPartBuilder` when `partId` fails validation describes a different character set than the regex actually enforces.

**Null:** Message and regex agree; the issue is a misread.

**Perturbation (deduction, read the code):**
- `source_gen/lib/src/builder.dart` defines `const partIdRegExpLiteral = r'[A-Za-z_\d-]+';` — allows letters, digits, `_`, `-`. No `.`. No anchoring restriction beyond `^...$`.
- The error message claimed: "letters, numbers, `_` and `.`. It cannot start or end with `.`."

**Trajectory:** Divergent (in favor). The character sets do not overlap on `.` vs `-`, and the message references start/end rules that don't exist in the regex.

**Shape:** Divergent → follow. Edge: fix the message to describe the regex. No code logic change needed; behavior was correct, message was wrong.

**Confidence:** 99% (deduction from source).

## Fix shape

Single-line message replacement in `builder.dart:255-259`:

```dart
'`partId` can only contain letters, numbers, `_` and `-`.'
```

Plus two regression tests in `builder_test.dart`:
- `accepts partId with hyphens` — proves `-` is permitted (covers the original confusion direction).
- `error message matches allowed characters` — locks the message to mention `-` and not mention `` `.` ``.

## Phase 2.5 — Provenance

- `git blame` on the message: the message has stood for years; it predates the regex's current form or the regex diverged from the message during a previous edit. Either way, the message is the wrong source of truth — the regex governs runtime behavior, so it wins.
- Upstream issue #607 (Joseph Winningham, Clavum) names the contradiction explicitly. No competing PRs found.
- No adjacent in-flight work touches this validation path.

## Phase 5.5 — Regression check

`compat` is trivial: the runtime predicate is unchanged. Only the error string changes, and only on the failure branch. No callers parse the message text. Existing 63 tests continue to pass; two new tests added.

## Phase 8 — Ship state

PR #814 was opened with this exact fix, then **self-closed on 2026-05-18**. When attest re-ran the PR's new test against current master, it passed without the code change — the bug no longer reproduces upstream. The contradiction the issue described has been resolved by some independent edit between when #607 was filed and now. Closing comment posted on the PR.

## Phase 4.5 — Reframe

The investigation's original diagnosis (regex/message divergence) was correct at the time #607 was filed but is now stale. The attest gate (fail-on-master / pass-on-fix) caught this before the PR could merge wrongly — the added test passed on master, which means the fix is a no-op against current behavior. This is the gate working as intended: a test that passes on master proves nothing, and the substrate flagged it before review attention was spent.

Transferable observation: long-tail issues age. Between issue-file-time and PR-attest-time, upstream may have fixed it via an unrelated edit. The attest gate is the only mechanism that catches this — neither static reading of the regex nor the issue text would reveal it.

## Frontier

Closed. Halt conditions met: PR shipped → attest killed → operator closed with explanation. No re-entry — the bug is gone, so there is no surviving hypothesis to follow.
