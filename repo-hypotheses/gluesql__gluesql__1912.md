# gluesql/gluesql#1912 — Fix aggregate NULL handling (CI repair)

PR author: `kimjune01` (self-PR). Targets issue #1897 filed by maintainer `devgony`.
State: OPEN, MERGEABLE, UNSTABLE. No reviews. Review requested from devgony, ever0de, panarch, zmrdltl.

## H₀ — Why is CI red?

**Observation.** 3 failing checks out of 15: Clippy, Rustfmt, Coverage. The Coverage failure runs the full test suite under `cargo llvm-cov`, so it likely inherits whichever of Clippy/Rustfmt fail first (or its own compile of the test-suite picks up the same lints). The successful Rust `Run tests` job confirms tests pass on the gluesql-core crate — so this is not a logic regression; the PR's behavior change is sound.

**Perturbation.** Read each failed-job log.

**Trajectory.** Divergent — two clearly named, deterministic failures with auto-generated fixes.

### Failure 1 — Clippy: `single_match_else` (pedantic) at `core/src/executor/aggregate/state.rs:441`

```rust
match group.values[slot].as_mut() {
    Some(aggr_value) => { aggr_value.accumulate(&value)?; }
    None => { /* NULL-skip + AggrValue::new */ }
}
```

Clippy wants `if let Some(aggr_value) = ... { ... } else { ... }`. The lint is enabled via `-D clippy::pedantic`, so the repo treats pedantic as blocking. The clippy output already includes the full rewrite suggestion. Mode: deduction.

### Failure 2 — Rustfmt: 6 hunks across two files

- `test-suite/src/aggregate/null_handling.rs`: five new `g.test(...).await` blocks written one-arg-per-line that fit on a single line, plus the `all_null_aggregates` tuple list that rustfmt wants broken across multiple lines.
- `test-suite/src/lib.rs:106`: one `glue!(aggregate_all_null, ...)` that needs the multi-line form.

Pure formatting — `cargo fmt --all` produces the fix. Mode: deduction.

### Failure 3 — Coverage (inferred)

The job log tail shows MongoDB shutting down cleanly, so the failure isn't connection-related. Most likely the same `clippy::pedantic` -D-warnings setting or a compile error from the unformatted code in cov instrumentation. Diagnosis: collapses into 1+2 — fixing them should green it.

**Provenance.** The clippy violation was introduced by this PR (new `None` arm at state.rs:441 wrapping `AggrValue::new` after the NULL-skip check). The rustfmt violations were introduced by hand-written test cases that didn't see a local `cargo fmt`. Both are mechanical mistakes, not design errors.

**Kill condition for H₀.** A push that runs `cargo fmt --all` + the clippy-suggested `if let` rewrite. Predicted outcome: Clippy green, Rustfmt green, Coverage green (or, if not, a new H₁ for the residual coverage failure).

## Graph state

| Node | Status | Mode | Trajectory |
|------|--------|------|-----------|
| H₀: CI red from mechanical lints | Confirmed | Deduction | Divergent |

## Frontier

| Edge | Perturbation | Predicted shape |
|------|--------------|-----------------|
| Push fmt + clippy fix | `cargo fmt && apply if-let rewrite && git push` | Convergent (all green) |
| (Conditional) Coverage still red | Read fresh coverage log | Divergent → new node |

## Notes

- Self-PR: no maintainer-self-PR halt applies (issue reporter ≠ PR author; devgony filed, kimjune01 implemented).
- Phase 8 ship gate: the push to a public PR is the human-gated action. Ask before pushing.
- No clone of gluesql exists at `~/Documents/gluesql` or equivalents — fixing requires cloning first.
