# Investigation: sourcefrog/conserve#300 (reinvestigate-from-attest)

**PR**: #300 — Show source tree size in backup stats
**Branch**: fix-115-show-source-tree-size @ 053fe296
**Trigger**: attest verdict `fail` → reinvestigate (msg `attest-20260518T065115-sourcefrog-conserve-300`)
**Attest reason**: `test_fails_on_fix — fix is broken` (log truncated to crate-download output)

## H0: The fix is broken — a test fails on the PR branch

**Mode**: induction
**Perturbation**: `docker run --rm -v $worktree:/work -w /work sweep-tester:latest cargo test --lib backup::test`
**Result**:
- 16 passed, 1 failed
- Failure: `backup::test::source_unreadable` — `assertion left == right failed, left: 0, right: 1` at `src/backup.rs:1051`
- Our new test `backup::test::source_tree_size_in_stats` passes

**Trajectory**: divergent against the H0 framing — the failing test is unrelated to our change.

## H1: The failure is caused by our change to `copy_file`

**Mode**: deduction (read the diff + run the test on main)
**Perturbation**: `git checkout main -- src/backup.rs && cargo test --lib backup::test::source_unreadable`
**Result**: Same failure on main:
```
thread 'backup::test::source_unreadable' panicked at src/backup.rs:995:9:
assertion left == right failed, left: 0, right: 1
```
**Trajectory**: divergent against — the test fails identically on master. Our fix does not cause it.

**Kill condition met**: H1 dead. Edge → why does it fail on master?

## H2: `source_unreadable` is environmental — docker-as-root bypasses unix chmod

**Mode**: abduction → deduction
**Reasoning**:
- Test is `#[cfg(unix)]`, uses `tf.make_file_unreadable("b_unreadable")` which chmods the file to 0.
- `docker run ... sweep-tester:latest` runs as `root` (verified: `whoami` → `root`).
- Under POSIX, root can read any file regardless of mode bits (CAP_DAC_READ_SEARCH equivalent).
- Therefore the file is still readable inside the container, no `Error::ReadSourceFile` is produced, `stats.errors` stays at 0 instead of becoming 1.
- Test fixture provenance: `a319f93c` (2019-11-04, sourcefrog) — pre-dates the docker-based attest env by years.

**Trajectory**: convergent. The failure is reproducible on master and orthogonal to PR #300.

**Provenance**:
- Test added: a319f93c "Add failing test for unreadable sources" (Martin Pool, 2019)
- Test still uses chmod-0 fixture as of HEAD; no docker-root carve-out.
- Container `sweep-tester:latest` runs as root by default; no `--user` flag in `sweep project-info` test_cmd.

## Conclusion

PR #300's code change is correct. Attest's verdict is a false positive driven by an environmental skew in the docker test harness (root identity bypasses the unreadable-file fixture). The same `cargo test --lib backup::test` run produces the same `source_unreadable` failure on `main` — the gate's "fail on master, pass on fix" invariant should classify this as no-signal, but the captured failure log was truncated mid-`Downloading crates`, so the gate likely didn't reach the master-side comparison.

Our cherry-pickable test slice (`source_tree_size_in_stats`) passes on the fix branch. There is no code defect in the PR to fix.

## Frontier edges (substrate, not code)

1. **Attest log truncation.** The `attest_failure_reason` payload was cut off in the middle of cargo's download output. The actual test failure line never made it into the reinvestigate card. Fix lives in `sweep/activities/attest.py` (or whoever captures the docker stderr) — capture more than ~700 bytes, or capture the last N lines instead of the head.
2. **Docker-root vs unix-permission tests.** `sweep-tester:latest` runs as root, which silently invalidates any `#[cfg(unix)]` test that depends on chmod-based access denial. Two options: (a) add a non-root user to the image and `--user` it for cargo test runs; (b) accept the env skew and ignore tests that fail identically on master (which is what the master-comparison gate is supposed to do, when the log isn't truncated).
3. **Master-side gate fired? Or short-circuited?** Worth checking the attest activity's log path for this msg_id to confirm whether the master-side `cargo test` actually ran. If it did and also reported `source_unreadable` failing, the verdict logic should have downgraded to "pre-existing failure" rather than `test_fails_on_fix`.

## Halt

**Verdict**: no fix to make on the PR. This is a human-gated decision: the operator needs to choose between (a) overriding the attest verdict for #300 and letting `/drip → /ship` proceed, (b) patching the sweep-tester image to run cargo tests as a non-root user, or (c) patching the attest activity to capture the failure tail rather than the cargo-download head so the master-comparison gate has the data it needs.

awaiting human go/no-go on which remediation to apply — no code change ships from this skill run.
