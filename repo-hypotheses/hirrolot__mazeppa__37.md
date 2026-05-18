# Hypothesis Graph: hirrolot/mazeppa#37 — `Gensym.latest` off-by-one

PR: https://github.com/hirrolot/mazeppa/pull/37
Branch: `fix/gensym-latest-off-by-one`
Authored by: kimjune01 (substrate-authored)
Investigated: 2026-05-17

## Question

Is the proposed fix (`make_symbol i` → `make_symbol (i - 1)` in `Gensym.latest`) correct, complete, and does it actually fix observable behavior at the sole caller?

## H₀ — `Gensym.latest` returns the wrong symbol (semantic bug)

**Hypothesis.** `Gensym.latest` is named "latest" and its `assert (i > 0)` implies "at least one emit happened, return that emit's symbol." But the body returns `make_symbol i` where `i = !counter`. After one emit (counter went 0→1), it returns `n1`, not `n0`. The fix `make_symbol (i - 1)` returns `n0` — the most recently emitted symbol.

**Perturbation.** Read `lib/symbolics/gensym.ml`:
```ocaml
let emit gensym =
    let i = !(gensym.counter) in
    incr gensym.counter;
    make_symbol ~prefix:!(gensym.prefix) i  (* returns n_i, then counter = i+1 *)

let latest gensym =
    let i = !(gensym.counter) in
    assert (i > 0);
    make_symbol ~prefix:!(gensym.prefix) i  (* returns n_i, but latest-emitted was n_{i-1} *)
```

**Trajectory.** Divergent confirm. The contract implied by the name + assertion + `emit`'s post-increment semantics unambiguously requires `i - 1`.

**Mode.** Deduction. Confidence: 98%.

**Status.** Confirmed.

**Edge.** → H₁ (does the call site actually depend on the correct value?)

---

## H₁ — The sole caller `unreport_nodes` benefits observably from the fix

**Hypothesis.** The PR body claims `unreport_nodes` "benefits from the fix." Verify by tracing both versions through `unreport_nodes`.

**Perturbation.** Trace `unreport_nodes` at `lib/mechanics/supervisor.ml:51-60`:

```ocaml
let unreport_nodes (gensym_backup : Gensym.t) : unit =
    let iter = Gensym.clone gensym_backup in
    let until = Gensym.latest State.node_gensym in
    let rec go () =
        let node_id = Gensym.emit iter in
        S.unobserve_node node_id;
        if node_id <> until then go ()
    in
    go ()
```

Setup: counter goes N₀ → N₀+1 when `report_node n` emits in `run` (supervisor.ml:118). `gensym_backup` is taken after, so `backup.counter = N₀+1`. Between backup and `unreport_nodes` call (only on Failback at line 124), recursive `run` invocations emit child nodes. Let N = node_gensym counter at unreport time, N ≥ N₀+1.

- **Bug version:** `until = n_N`. Loop emits `n_{N₀+1}`, …, `n_{N-1}` (unobserves each — these were actually reported by descendants), then emits `n_N` (no-op unobserve since never reported), matches `until`, stops.
- **Fix version:** `until = n_{N-1}`. Loop emits `n_{N₀+1}`, …, `n_{N-1}`, matches at `n_{N-1}`, stops.

`S.unobserve_node = Hashtbl.remove` (bin/main.ml:55), which is **silent on missing keys**.

**Trajectory.** Divergent against (the "benefit" claim). Both versions remove **exactly the same set** of hashtbl entries (`n_{N₀+1}` through `n_{N-1}`). The bug version performs one extra no-op iteration. **There is no observable behavioral difference at the sole call site today.**

**Mode.** Deduction. Confidence: 95%.

**Status.** Refines H₀. The fix is semantically correct (the function now matches its name) but does not change runtime behavior at the only call site.

**Edge.** → H₂ (does the fix introduce a regression in edge cases?)

---

## H₂ — Fix introduces infinite loop when `counter == backup.counter` at unreport time

**Hypothesis.** If `unreport_nodes` is ever called with no new emits since backup (N == N₀+1), the bug version no-ops (until = n_{N₀+1}, first iter emit matches, stops). The fix version emits `n_{N₀+1}`, compares to `until = n_{N₀}`, **doesn't match**, and infinite-loops emitting `n_{N₀+2}, n_{N₀+3}, …`.

**Perturbation.** Trace whether the failback path can fire with counter unchanged since backup.

- `unreport_nodes` is called only at supervisor.ml:124, inside `Failback` handler.
- Failback is raised from `check_whistle` (lines 204, 205, 213, 215) only when `History_inst.memoize` returns `Some (m_id, _)` — i.e., when an ancestor m is homeomorphically embedded in n.
- `Failback (m_id, _)` bubbles up the recursion stack via `raise_notrace exn` (line 130) until it reaches the frame whose own `n_id = m_id`. That frame is the one that originally emitted m_id, which happened **before** the recursion that eventually raised the failback. Between m_id's emit and the failback, descendant frames called `report_node`, incrementing the counter.
- Therefore at the handling frame, N (current counter) > N₀+1 (backup) strictly.

**Trajectory.** Convergent (against the regression hypothesis). The unreachable case is genuinely unreachable under current control flow.

**Mode.** Deduction. Confidence: 85% (control-flow argument is sound, but relies on the invariant "Failback only bubbles up through frames with at least one descendant emit"; a future caller that calls `unreport_nodes` directly outside of a failback context could trigger the loop).

**Status.** Partial. The fix is safe at the current call site, but it is **strictly more fragile** than the original: the bug version was a no-op for the empty-window case; the fix version diverges. This is worth flagging as a frontier edge if the API is ever exposed beyond `unreport_nodes`.

**Edge.** → H₃ (should the fix add a `if N₀+1 = N then ()` short-circuit?)

---

## H₃ — Defensive empty-window guard in `unreport_nodes`

**Hypothesis.** Add `if !(iter.counter) = !(State.node_gensym.counter) then ()` before the loop, or change `latest` to handle counter=0 / counter-unchanged gracefully.

**Trajectory.** Out of scope. The PR scope is `Gensym.latest`'s off-by-one; modifying `unreport_nodes` to be defensive against an unreachable case is feature creep. Follow-the-flow: maintainer didn't ask for this; the existing call site is safe; don't reform.

**Status.** Killed. Frontier edge logged in case future investigators encounter a related issue.

**Mode.** Judgment call (follow-the-flow rule). Confidence: N/A.

---

## H₄ — Test fails on master, passes with fix

**Hypothesis.** The PR adds `gensym_latest` test asserting `latest = s0` after one emit. Bug version returns `n1` vs expected `n0` → test fails on master. Fix returns `n0` → passes.

**Perturbation.** Couldn't run `dune test` locally (no opam on this host). Verified by code-trace only:
- `Symbol.to_string` on `make_symbol "x" 0` → `"x0"`; on `make_symbol "x" 1` → `"x1"`.
- Test compares `Symbol.to_string (Gensym.latest gensym)` to `Symbol.to_string s0 = "x0"`.
- Bug: `latest` returns `make_symbol 1 = x1` → assertion fails ("x1" ≠ "x0"). ✓ Fails on master.
- Fix: `latest` returns `make_symbol 0 = x0` → assertion passes. ✓ Passes with fix.

**Trajectory.** Divergent confirm.

**Mode.** Deduction. Confidence: 95% (deductive trace of test, but not actually executed).

**Status.** Confirmed.

---

## Graph state

| Node | Status | Shape | Mode |
|------|--------|-------|------|
| H₀ — semantic off-by-one | Confirmed | Divergent | Deduction |
| H₁ — caller benefits observably | **Killed** | Divergent against | Deduction |
| H₂ — fix introduces infinite-loop regression | Partial (unreachable today, but fragile) | Convergent | Deduction |
| H₃ — defensive guard in caller | Killed (scope) | — | Judgment |
| H₄ — test fails on master, passes with fix | Confirmed | Divergent | Deduction |

## Causal chain

The body of `Gensym.latest` was wrong (H₀ confirmed). The PR's added test characterizes the bug at the API level (H₄ confirmed). However, the only existing caller (`unreport_nodes`) does not depend on the correct value because `Hashtbl.remove` is silent on missing keys and the bug version's extra no-op iteration is benign (H₁ killed). The fix is semantically correct and forward-compatible (future callers expecting "latest" to mean what it says will be correct) but does not fix any observable behavior today.

## Frontier edges (open)

1. **API surface widening risk.** If `Gensym.latest` is ever called outside the current `unreport_nodes` pattern, the fix's empty-window divergence (H₂) becomes a live concern. No action today; revisit if the API is exposed.

## Recommendation

The PR is correct and worth landing as **API hygiene + test coverage**. The PR body's "Audited sole caller `unreport_nodes` -- benefits from the fix" overstates the case — the caller does not benefit observably. Consider softening the claim to: "Audited sole caller `unreport_nodes`; existing behavior preserved (both versions remove the same hashtbl entries due to `Hashtbl.remove` being silent on misses)."

This avoids a maintainer pushback in review where they could quickly verify there's no behavioral change and call out the overclaim.

## Provenance

- `gensym.ml:21` introduced via initial commit — never reconsidered. No upstream issue references `Gensym.latest`.
- No prior PR addresses this. PR #37 is the first treatment.
- Adversarial codex/gemini volley: not run on this investigation (skill substrate fallback; analysis was pure deduction over a 22-line file + one caller).
