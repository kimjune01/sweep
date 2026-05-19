---
name: implement
description: Take a prior /investigate artifact that named the fix (file:line + change shape) plus maintainer feedback, IMPLEMENT the named change in the existing PR's branch, verify, and push an amend. Distinct from /investigate (which produces the plan but stops at "pending implementation"). Implement's job is to FINISH.
argument-hint: <repo#pr>
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, Agent
---

# Implement: take the plan to a pushed amend

This skill is called by `implement-actor` in the engagement lane,
AFTER /investigate has already produced an artifact that names the
fix (file:line + change shape) and AFTER a maintainer has either
raised a concern naming a different location, requested changes, or
left an inline comment with explicit direction.

The contract is **finish the work**: read the maintainer feedback +
the prior /investigate artifact, IMPLEMENT the named fix, verify
locally, push an amend commit. Do NOT re-run a hypothesis graph —
/investigate already did that. If the artifact doesn't have a clear
named fix, halt and let the actor escalate back to /investigate.

## Phase order

1. **Read the prior artifact** — `repo-hypotheses/<owner>__<repo>__<issue>.md`.
   It almost certainly names the file, line range, and shape of the
   fix the maintainer wants. If the artifact is missing or doesn't
   contain a clear directive, escalate to /investigate (you can't
   "finish" what hasn't been planned).

2. **Read the maintainer feedback** — inline comments + top-level
   comments + review states. The freshest non-author message is
   authoritative direction. Quote it verbatim in your reasoning.

3. **Re-confirm location** — open the named file in the worktree,
   re-read the relevant lines. The artifact's file:line should still
   match the current code; if drift has occurred (rebase against
   master moved the line), re-locate via `grep`/`Glob`.

4. **Implement** — Edit the file. Apply the named change. Keep diff
   minimal: only what the maintainer asked for. Don't refactor
   surrounding code, don't add tests beyond what's needed to verify
   the fix.

5. **Verify locally** — run the repo's test command. If a test was
   added to the original PR, it should still pass. If new behavior
   needs a test, add one focused on the maintainer-named scenario.
   The fix MUST fail-on-master / pass-on-fix (test_attestation gate).

6. **Amend + force-with-lease push** — amend the existing top commit
   (don't add a new "Address feedback" commit on top — maintainers
   prefer rebased history for substantive reworks). Push to the fork
   branch. Use `--force-with-lease` not `--force`; protects against
   parallel pushes.

7. **Emit decision** — write the per-issue attestation at
   `~/.sweep/attestations/implement/<owner>__<repo>__<issue>.md`
   with `decision: pushed-amend` and the new HEAD SHA.

## Halt conditions (use sparingly)

You may halt and route to operator only when:

- The artifact's named location no longer exists in the current code
  AND grep cannot find a plausible replacement
- The maintainer feedback contradicts itself or is genuinely ambiguous
  (rare — most "I don't know what they want" is laziness; re-read)
- The test_attestation gate fails after the patch — meaning your
  implementation doesn't actually fix the named bug (real failure;
  surface for operator review)
- The push is rejected for reasons beyond `--force-with-lease`
  (auth, branch protection)

Do NOT halt for:

- "I'm not sure if this is what the maintainer meant" — they wrote
  the comment; take it at face value and implement
- "There might be a better approach" — there might be; the maintainer
  chose theirs. Ship what they asked for.
- "The test infrastructure feels brittle" — fix what's named, leave
  the rest

## Output contract

After all narration, the **last printed line** must be a single JSON
object matching this schema:

```json
{
  "decision":      "pushed-amend | halt | escalate-to-investigate",
  "head_sha":      "<10-char SHA if pushed-amend, else empty>",
  "reason":        "short string, ≤200 chars",
  "rejected":      false,
  "reject_reason": null
}
```

`decision: pushed-amend` is the success path. The downstream wrapper
kicks reqa to verify the new SHA against the maintainer's named
behavior; on green, respond posts a brief "addressed feedback at
SHA <head_sha>" to the PR.
