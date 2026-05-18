---
name: synth-test
description: Write a regression test that captures the behavior described in a bug report. The fix is hidden from you on purpose. Derive the test from the issue and the unfixed code, not from someone else's solution.
argument-hint: <issue-text-path> <unfixed-files-paths> <repo-test-conventions>
allowed-tools: Read, Write, Edit, Bash
---

# Synth-test: TDD from a Bug Report

Write one regression test that captures the behavior the issue describes, against the current (unfixed) code. You are a test author working from the issue, not a reviewer working from a fix.

## What you have

The invoker passed you three inputs:

1. **The issue** — a markdown file with the bug report's title, body, and any reproduction steps. Read it carefully. The user's described behavior is the spec; your test asserts that spec.

2. **The unfixed source files** — the files the bug lives in, at their current (buggy) state on the default branch. These are what you'd see if you cloned the repo right now. Read them to find the entry points your test needs to call.

3. **Test convention examples** — one or two sibling test files from the same repo. Use them to learn: which test framework, which import style, where tests live on disk, how assertions are written, naming conventions.

## What you do NOT have

You do not have the fix. You do not have the fix branch. You do not know how someone else chose to solve the bug. This is deliberate.

If you had the fix, you would write a test that mirrors it — a test that passes only because the fix is what it is, not because the behavior is correct. That is a tautology. The test would not catch a future regression where the fix is reverted or replaced with a different but equally wrong implementation. The whole value of a regression test is asserting the behavior independently of any specific implementation.

So don't ask for the fix. Don't grep for the fix branch. Don't speculate about what the fix looks like. Just read the issue, understand what the user expected to happen, and write a test that asserts that expectation against the unfixed code.

## The test you write

- **Fails on the unfixed code.** This is the implicit contract: the issue describes a bug, so the bug-triggering input should produce wrong output on the current code. Your test asserts the *correct* output. Run mentally: with the unfixed code, would this test fail? If no, the test isn't capturing the bug.
- **Asserts behavior, not implementation.** Don't assert that a particular helper was called or a particular intermediate state was reached. Assert what the user observes: a return value, a rendered output, an absence of error, a file produced.
- **Specific to the bug.** One scenario, the one from the issue. Use the exact input from the issue's reproduction if provided.
- **Follows repo conventions.** Use the test framework the sibling test files use. Use the same fixture/helper patterns. Place the file where similar tests live.
- **Self-contained.** No new dependencies, no setup beyond what sibling tests assume. If the repo's tests need a fixture, define it inline or reuse an existing one.

## Output

Write exactly one test file. Commit it to the current branch with message:

```
test: regression for <short issue summary>

Captures the behavior described in the issue. Test fails on master,
documents the expected post-fix behavior.
```

Do not modify any non-test files. Do not add multiple tests speculating about edge cases the issue did not mention. One issue, one test.

If after reading the issue you cannot identify a concrete behavior to test (issue is vague, no reproduction, no clear expected/actual), write nothing and exit with the marker `SYNTH_PUNTED: <one-line reason>` on stdout. The caller will route the PR to manual handling rather than ship a test that doesn't add evidence.
