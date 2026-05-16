# Hypothesis Graph: tinygrad/tinygrad#16228

**Issue:** Conv-backward gradient norm hangs the Metal GPU (rangeify over-fusion)
**Reporter:** sw1sh (Nikolay Murzin) — repro and diagnosis "AI-assisted, hand-verified"
**Filed:** 2026-05-16
**State at investigation:** OPEN, no comments

## Gating context (read before any ship action)

- **Cooldown active** until 2026-05-22 (today: 2026-05-16). geohot on PR #16113: "You are close to getting banned. A PR means I have spent serious human time reading this and 100% believe you are ready to just click merge." See `repo-hypotheses/tinygrad-tinygrad.md`.
- **Phase 8 is hard-blocked.** This investigation produces a graph + prework only. Even if the diagnosis converges and a clean fix exists, no PR is opened before 2026-05-22, and only if the fix clears the "100% ready-to-merge" bar.
- **Reporter has already published a fix sketch** in the issue body. Any PR we open after the cooldown ends would be reproducing their public work; the polite move is to let sw1sh send their own PR, and only contribute if it doesn't land.

## H₀ — Reporter's diagnosis is mechanically correct

**Hypothesis:** `remove_bufferize` in `tinygrad/schedule/rangeify.py` has no op-count or reduce-extent cap, so a chain of conv-backward reduces collapses into one mega-kernel that crosses the Metal watchdog.

**Null:** Some existing guard (3-buffer cap, `buffer_in_reduce`, PCONTIG out/in ratio) already gates the fusion in this case; the hang is somewhere else (codegen, scheduler ordering, Metal driver).

**Perturbation (read-only):** Read `tinygrad/schedule/rangeify.py:234-298` and enumerate every guard that can return `None` from `remove_bufferize`.

**Observation:**
- L240: `ALWAYS_RUN_OPS or not buf.arg.removable` — user contiguous. Inapplicable; intermediate grads are not user-contiguous.
- L266: `len(accessed_buffers) > 3 and not (PCONTIG > 2)` — 3-buffer cap. Counts only `GLOBAL` STAGE + MSTACK + PARAM at the top of the walk; descendants already removed by earlier `remove_bufferize` rounds are no longer STAGE nodes, so accessed_buffers undercounts a transitively-fused chain. Mechanism explained: the cap is structural (live buffer references), not work-volume.
- L268-292: `buffer_in_reduce` — if any reduce reads a STAGE/PARAM, keep. After upstream bufferizes have been substituted away, the reduce reads ranges, not stages → guard is False → does not fire.
- L278: `out_in_ratio < 10` — only under `PCONTIG > 2`, default `PCONTIG=0` (helpers.py:259), so inert in the default config.

**Trajectory:** Divergent in favor. Every guard reachable from the default config either does not apply or has a structural rather than cost-based threshold. The op-count / reduce-extent cap the reporter names is genuinely absent.

**Provenance:**
- `remove_bufferize` introduced as part of the BUFFERIZE→STAGE rename and partial-contig work; predecessor PR #16125 (`daed602`).
- Shallow-clone history limit: deeper provenance (who first wrote the 3-buffer cap, why no work cap) not retrieved here. Low value-add; the structural absence is sufficient.

**Status:** CONFIRMED (deduction, ~98% confidence — read straight from the source).

## H₁ — Loop-invariant code motion is the precise framing

**Hypothesis:** The reporter's secondary framing is the load-bearing one. The bug is not "fused kernel too big" (a size symptom) but "an inner reduce's operand that is invariant to outer reduce ranges gets substituted *inside* them, so its compute is recomputed every outer-iter, compounding multiplicatively per layer."

**Null:** A size-only cap (e.g., `if len(reduces) > N: keep buffer`) is sufficient. The invariance framing is decorative.

**Perturbation (thought experiment over source):**
- L297: `replaced = {k:v for k,v in zip(buf.src[1:], idx.src[1:]) ...}` — substitutes RANGE-for-RANGE blindly across the boundary.
- After substitution, when the outer kernel later builds nested loops, the inner reduce body is emitted inside outer ranges it does not depend on. No subsequent LICM pass exists in rangeify (grep: no "invariant" / "hoist" / "licm" tokens in `tinygrad/schedule/` or `tinygrad/codegen/`).
- The size symptom (loop factor `_256_6_6_16_4_4_256_3_3_32_16_4_4_16_4`) is the *consequence* of repeated unhoistable substitution, not the cause.

**Trajectory:** Convergent. The size cap suppresses the worst case but is a proxy; the invariance check is the underlying signal. Both frames produce the same fix surface (refuse this `remove_bufferize` call), but the invariance framing extends to cases that pass a size cap yet still recompute.

**Edge:** Split — H₁ₐ "size cap is sufficient for this issue" vs H₁ᵦ "only invariance-aware guard generalizes."

**Status:** PARTIAL. Both fixes plug the repro; the invariance one is theoretically tighter. The reporter calls invariance "the precise version" and ships size-cap-style guard as the minimal patch. Agree.

## H₂ — Contiguous-on-each-grad is the canonical workaround, not on `gn`

**Hypothesis (from reporter, validated by reading):** Putting `.contiguous()` on the L2-norm output does not insert the barrier on the reduce chain because `remove_bufferize` runs bottom-up from the index; the barrier has to sit on each `w.grad` so the inner reduce produces a STAGE node that the outer reduce's `red_gate` then sees as a buffer access → triggers L276 (`buffer_in_reduce`) → returns None.

**Null:** `.contiguous()` placement is incidental; either works.

**Perturbation:** Trace `red_gate` on L248-260: it walks `src` (the would-be-fused body) and collects STAGE/PARAM as buffers. A `.contiguous()` on `w.grad` becomes a STAGE node in the reduce body. A `.contiguous()` on the final `.sqrt()` is below the reduce, never traversed by `red_gate`.

**Trajectory:** Divergent in favor. The asymmetry is a structural consequence of the existing `buffer_in_reduce` guard, exactly as reporter claims.

**Status:** CONFIRMED. Useful side-evidence that the existing guards are doing their job *when there is a buffer to see* — the bug is that an already-removed bufferize leaves no buffer behind for the next round.

## H₃ — Reframe: this is a [[prework_blocked]] case, not a ship case

**Hypothesis:** The right output of this investigation is the graph, not a PR.

**Reasons:**
1. Reporter has published the diagnosis + fix shape publicly; the issue is now self-documenting. The maintainer-facing value of our PR is marginal vs the cost (cooldown, ban risk).
2. The "10-line guard" the reporter describes is judgment-heavy: the cap threshold (op-count × reduce-extent) is a parameter that needs tuning against the existing scheduler test suite. A submission that picks the wrong threshold is exactly the kind of "didn't think hard enough" PR the cooldown was about.
3. The precise fix (LICM-style) is a meaningful refactor of rangeify, not a one-liner. Submitting either the cheap version or the precise version during cooldown is bad timing.

**Null:** Wait, write the patch, ship after 2026-05-22 if sw1sh has not.

**Recommendation:** Hold. Watch the issue. If sw1sh posts a PR, link this graph as commentary in the prework dir and close out. If 2026-05-22 passes with the issue still open and no PR from sw1sh, revisit Phase 5 with a properly-tuned threshold and Metal hardware to run `test_schedule.py` against.

**Status:** REFRAME confirmed. Phase 8 stays gated regardless of fix quality.

## Graph state

| Node | Mode | Status | Confidence |
|------|------|--------|------------|
| H₀ no work-cap in remove_bufferize | Deduction | Confirmed | 98% |
| H₁ LICM is precise framing | Deduction | Partial (both frames valid) | 90% |
| H₂ contiguous-on-grad workaround mechanism | Deduction | Confirmed | 95% |
| H₃ ship-gated by cooldown + reporter-overlap | Abduction | Confirmed-by-context | 90% |

## Frontier (open if cooldown clears and reporter does not PR)

- F₁: Find a threshold for `op_count × reduce_extent` that triggers on the conv-backward chain but not on legitimate fusions (matmul epilogues, simple reduces). Requires running `test_schedule.py` and the LLaMA/SDXL benches.
- F₂: Sketch an invariance check: in `red_gate`, when crossing a REDUCE, record the outer reduce's ranges; if a substituted index references none of them, the operand is hoistable — keep the bufferize so codegen sees the boundary.
- F₃: Repro on hardware. Without Metal, we can't run the original program; we can only confirm `extract.py`-equivalent output (DEBUG=4 dump of kernel loop factors) on CPU and trust the watchdog claim.

## Pruning log

- "Maybe Metal driver bug, not scheduler" — killed by reporter's own evidence: `DEBUG=2` shows the over-fused kernel every run, hang is correlated with kernel size, manual barrier fixes it on the same GPU.
- "Maybe `accessed_buffers > 3` should already fire" — killed by reading L266 and the substitute mechanism: after substitution, fewer STAGE nodes remain in the body than the original chain has reduces.

## Reasoning-mode ledger

- Deductive (read source, traced control flow): H₀, H₁, H₂.
- Abductive (proposed from cooldown + outreach context): H₃.
- Inductive (ran the repro and measured): none — no Metal hardware accessible in this session.

## Blind-blind pushout: NOT RUN

Skipped because (a) reporter has already published a converged diagnosis, so the meaningful disagreement is between us and them, not between two of our own models; (b) ship is gated by cooldown, so the marginal value of pushout-driven hypothesis sharpening is low. If we re-enter post-cooldown for Phase 5, run pushout then.
