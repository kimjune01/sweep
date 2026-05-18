# Substrate Hypothesis Graph (2026-05-17)

Sibling file to `HYPOTHESIS_GRAPH.md`. That file is the **PR-science**
graph — what we're learning about the world (merge rates, repo
selection, maintainer behavior, when our PRs land). This file is the
**ops** graph — what we're learning about ourselves running the pipeline
(observability patterns, watchdog independence, interface accounting,
attention budget, routing actors).

Different epistemic shape:

|                | PR science                          | Ops (this file)                       |
|----------------|-------------------------------------|---------------------------------------|
| Unit           | a PR outcome                        | a pipeline event / health signal      |
| Falsifier      | merge rate diverges from prediction | substrate fails or silently drops work |
| Update cadence | per session retro, per closure      | per refactor / per incident           |
| Reader purpose | "where should we point the pipeline" | "how should we run the pipeline"     |

Ops hypotheses use an `O` prefix (`O1`, `O2`, …) to keep cross-file
references unambiguous. Mapping from the prior in-place numbering:

| Old (in HYPOTHESIS_GRAPH.md) | New (here) |
|---|---|
| H20 — activity-owned observability | **O1** |
| H21 — watchdog independence        | **O2** |
| H22 — leakdog interface accounting | **O3** |
| H24 — immunize routing actor       | **O4** |
| H25 — bless classifier-router      | **O5** |

## O1: Activity-owned observability is more reliable than skill-emitted events

**Prediction:** When an activity wrapper (e.g. `triage_cycle`) shells out to a skill (e.g. `/triage`), the wrapper emitting observability events post-hoc (by reading the artifact the skill produced) catches strictly more events than relying on the skill to call `observe.event` itself.

**Status: CONFIRMED (2026-05-16, retro this-session).** triage_cycle previously delegated event emission to the /triage skill. Of 80 acked triage items, only 1 emitted a `triage_decision` event. After fix (wrapper re-reads the attestation post-skill-run and emits the event from there), 23 historical events backfilled instantly from existing attestations on disk, and the structural pathway now guarantees emission whenever the artifact exists. The skill was silently skipping its own logging in 79/80 cases — invisible until the leakdog manifest revealed the funnel mismatch.

**Mechanism:** skills are LLM-driven free-form executions. Even when prompted to emit observability events, the skill skips them under variable conditions (different prompt versions, error paths, summarization passes). The Python wrapper around the skill is deterministic code and runs every time.

**Generalization:** any pipeline stage that shells out should derive its observability from the *side-effect artifact* (attestation file, branch push, PR opened), not from the *log message the skill chose to emit*. The artifact is the receipt; the log is editorial.

**Falsifier:** if a skill consistently emits its own event AND the wrapper double-emits the same event, downstream gets duplicates that break dedup. This would force a per-event ownership decision. Hasn't happened — skills mostly underemit.

**Compounds with:** [[O2-watchdog-independence]] — both are about putting observability/recovery infrastructure outside the thing being observed.

## O2: Watchdog auto-recovery must run independent of the workflow it governs

**Prediction:** When an auto-recovery mechanism (e.g. "clear the API-budget andon when projected < 40%") lives inside the same workflow loop that the andon also blocks, a wedged workflow can never recover. The recovery must run from an independent tick.

**Status: CONFIRMED (2026-05-16).** API budget watchdog fired correctly at 77% projected and set the prospect_puller andon. Projection dropped to 37% (well below the 40% recover threshold) but the marker stayed because the auto-clear lived inside `check_pull_conditions`, which only runs when the prospect-puller advances. The puller was wedged retrying a different activity (attempt #15 of `prospect_recency_window` with no progress). Result: line stayed paused 30+ minutes past the condition that should have lifted it; required manual `sweep andon clear prospect_puller` to recover.

**Mechanism:** if the recovery path is downstream of the wedge point, the wedge blocks its own recovery. This is a classic supervisor problem — the supervisor cannot itself be supervised by the thing it supervises. Toyota's andon cord works because pulling it stops the *line*, not the *operator who pulls it*.

**Fix shape (not yet wired):** move `_clear_budget_andon_if_held` to a separate periodic activity scheduled by a sibling workflow (not by prospect-puller), or to a cron-style external tick. Same heartbeat that watchdog-fires the andon should be capable of clearing it.

**Falsifier:** if a fully independent watchdog also stops firing under similar wedge conditions (the worker process itself dies), then a higher-level supervisor is needed. Most likely outcome: independent tick is sufficient because Temporal workers restart cleanly and worker-internal wedges don't propagate to sibling workflows.

**Compounds with:** [[O1-activity-owned-observability]] — both are jidoka-discipline. Recovery and observability infrastructure must sit outside the thing they monitor.

## O3: Interface accounting (leakdog) detects silent-drop failure modes earlier than downstream symptoms

**Prediction:** A per-interface in/out/drop/pending balance, computed from event stream + inbox state, surfaces silent processing failures (acked but no event emitted) before they manifest as downstream symptoms (no QA convergence, no merges).

**Status: CONFIRMED (2026-05-16).** The leakdog row "prospect → triage: 50 in, 25 out, 25 leak ⚠️" was the first observable signal of the triage_cycle silent-skip bug ([[O1-activity-owned-observability]]). Without the leakdog, the only visible symptom was "investigations not triggering QA" — a downstream effect 3+ stages removed from the actual leak point, with multiple plausible explanations. Leakdog narrowed it to the prospect→triage interface in one read.

**Mechanism:** funnel-accounting is a generic supervisor pattern. Every stage transition is an interface; every interface should balance. Imbalance localizes the bug to the interface, not the broader pipeline. Same principle as double-entry bookkeeping: every debit needs a credit, every drop needs a reason.

**Refinement (key learning):** `leak = in - out - dropped - pending`. Without subtracting `pending` (items still queued or in-flight), slow processing masquerades as loss. The first version of leakdog over-reported leaks because it counted events only.

**Operational discipline:** zero unaccounted leaks as the target. Every drop must have an explicit decision event (e.g. `triage_decision(decision=drop|surface|defer)`, `investigate_done(no_fix=true)`). When a leak appears, the immediate fix is either (a) emit the missing decision event, or (b) backflow the item one stage upstream and re-process.

**Falsifier:** if leakdog routinely shows persistent leaks that are genuinely benign (e.g. items that drop out for legitimate reasons no one wants to log), the zero-leak target erodes into noise. Hasn't happened — every leak found so far has been a real bug or a missing event.

**Compounds with:** [[O1-activity-owned-observability]] (the structural fix for most leaks); [[O2-watchdog-independence]] (the leakdog itself must run on its own tick, not behind the pipeline it watches).

**Refinement (2026-05-17, silent-when-clean surfacing):** detecting leaks is necessary but not sufficient — the surfacing has to stay legible or the zero-leak target erodes from sensory overload, not from noise tolerance. Three changes landed this session:

1. **Own command, own concern.** Leakdog rendering moved out of `sweep lanes` into its own `sweep leakdog`. Lanes is point-in-time inventory; leakdog is windowed flow accounting. Bundling them dilutes both. Splitting also let lanes drop an unrelated provenance section that had accreted alongside it (~130 lines of view code the operator hadn't asked for).
2. **Spine vs side-hatches.** The leakdog table itself was 10 rows of equal visual weight (sift→ship spine plus immunize/tissue/bless/wipe/post side-hatches). Now the spine always renders as rows; side-hatches collapse to a single "ok" line listing the clean ones and only expand to their own row when leaking. Failure is loud, success is quiet.
3. **Cockpit chip.** A one-line `🩸 <interface> (<count>)` chip in `sweep cockpit`, silent when `leak_summary()` returns empty. The operator no longer has to opt-in to seeing leak state; the cockpit they already read on every tick surfaces the attention demand and points to `sweep leakdog` for the breakdown.

The underlying mechanism (funnel accounting, zero-leak target) is unchanged. What changed is the **attention budget**: an alarm that fires on every reading gets muted; a chip that only appears when something is wrong stays load-bearing. This generalizes to the broader supervisor pattern — every "always-on" health row in the cockpit either earns its space by being actionable when present, or gets collapsed to silent-when-ok. See [[feedback-no-unrequested-features]] for the operator-side rule that catches the inverse failure (sections added because they were possible, not because they were asked for).

**Discovery bug worth noting:** the operator was running a stale `~/.local/bin/sweep` (`uv tool install` had baked a non-editable copy at first install). Refactors landed in source but the TUI's shell-out still hit the old binary, so the supposedly-removed provenance section kept rendering. Lesson: install the dev tree with `uv tool install --editable .` so the binary tracks the source — otherwise observability changes lie about themselves. Adds a small operational rule for any view layer that's consumed via a separately-installed CLI.

## O4: A dedicated routing actor for anti-AI repos catches what prospect's cache misses, prevents wasted investigate cycles, and unifies slop-offer routing

**Prediction:** Hostile-AI-policy repos slip past prospect's 24h-cached `repo_ai_policy` check often enough to be worth a dedicated safety-net actor. A purpose-built `immunize` actor that (a) re-checks the policy live, (b) decides worth-pursuing via stars/recency/dedupe heuristics, and (c) routes pursued candidates into the existing slop-offer pipeline OR drafts a deferential acknowledgement comment for operator review, will catch more cases than the prospect-side inline check while preventing investigate from burning tokens on cards it shouldn't have seen.

**Status: PRE-REGISTERED (2026-05-17, retro this-session).** Immunize actor wired live. Two upstream sources: prospect (RepoCandidate filter + per-issue deterministic check) kicks immunize when policy is hostile; triage_cycle re-checks policy at the front of its loop and short-circuits to immunize. Both replace inline `slop_offer_seed.append` calls — the seeding decision now lives in one place with one observability surface.

**Mechanism:** GitHub's repo metadata changes at a rate that an aggressive 24h TTL doesn't track perfectly. Operators add AGENTS.md / CONTRIBUTING.md AI policies mid-month, repos get rebranded, archived, or relabeled. The prospect-time check is the front gate; immunize is the second gate that catches what the cache missed. Co-locating the worth-pursuing decision (stars, recency, dedupe) inside one actor means the slop-offer pipeline gets a single, observable, tunable feeder instead of three scattered append-calls.

**The two output paths:**
- Issue-level routing (triage source): draft a deferential acknowledgement comment, route through `tissue-drafts` → operator approval → wipe. Same approval gate as tissue; operator never gets surprised by an unreviewed post.
- Repo-level routing (prospect source, no specific issue): append to legacy `slop_offer_seeds.txt`. The existing `sweep slop-offer` CLI consumes it. Future work could unify this with the drafts queue once the slop-offer message shape is mature enough.

**Operationalization:**
- `immunize_card_deposited` events from both upstream sources
- `immunize_redirected` (pursued, seeded/drafted)
- `immunize_skipped` (policy resettled, below-stars, archived, already-seeded)
- Leakdog interface row `(prospect|triage) → immunize` balances cards-in against pursued+skipped

**Falsifiers:**
- ≥6 months of zero `immunize_redirected` events from triage source → prospect's gate already catches everything; immunize-from-triage is safety theater and can be removed (keep the prospect routing for the worth-pursuing decision alone).
- Immunize fires constantly from triage (more than prospect rejection rate) → prospect's `repo_ai_policy` check is broken (cache invalidation, TTL too long, query bug). Fix prospect's gate upstream; don't lean on the safety net to compensate for broken front-of-funnel.
- High pursue rate (>50% of cards) with no subsequent slop-offer engagement → worth-pursuing heuristics are too loose. Tighten (raise stars threshold, shorten recency window).
- High operator-discard rate on immunize-drafted acknowledgements → the template tone is wrong, OR maintainers find the acknowledgement itself unwelcome (in which case stop drafting; just seed-and-drop).

**Compounds with:** [[O3-leakdog-interface-accounting]] (immunize's events make the anti-AI escape hatch first-class in the funnel instead of a side-channel); [[O1-activity-owned-observability]] (the worth-pursuing decision lives in the wrapper activity, not in skill prose). The pattern — a dedicated routing actor for an escape hatch — generalizes to other categorical "this card needs to leave the main pipeline" cases (e.g. future explicit-no-LLM cooldown enforcement, maintainer block-list).

## O5: A classifier-router actor for issue-comment responses, template-first with a /retro compression loop, asymptotically reduces the LLM cost of response handling to near zero

**Prediction:** When a maintainer replies to a tissue, a small set of reply shapes ("thanks, closing", "you're right", brief acknowledgements, plain pushbacks) covers most of the long tail. A `bless` actor that matches replies against a template catalog first (deterministic regex, no LLM) and only falls through to LLM classification when no template hits will, after a few /retro cycles, route the majority of responses without paying any LLM cost. The substrate's per-response cost asymptotes toward "pattern match + file write."

**Status: PRE-REGISTERED (2026-05-17, retro this-session).** Bless actor wired. Bootstrap stance: LLM classifier disabled (`~/.sweep/control/bless_llm_enabled` flag, default off); every non-template-match defaults to human-attendable (routes to `respondable-issues.jsonl`). Operator handles all novel responses directly; /retro extracts templates from repeated decisions. Seed templates: `thanks-closing`, `youre-right`. Operator-extensible via `~/.sweep/templates/bless/*.json`.

**Mechanism:** the same compression loop that fills `prospect_kill_list`, `prospect_evicted`, `retro_params`, and the artifact-classifier vocabulary. First time a pattern shows up → human decision. Second/third time → /retro extracts → template. After N templates exist, the LLM call is only invoked for genuinely novel responses, and the operator only sees those that survive both template and (eventually) LLM classification.

**Why the LLM is OFF by default at start:** without operator-decision data, the LLM has no priors on what counts as "auto-answerable" in this substrate's voice. Letting it classify before the catalog exists risks burning reputation on a hallucinated "auto-reply" that reads as bot-shaped or worse. Defer the LLM until templates demonstrate that the deterministic surface is well-mapped — at that point the LLM is filling the long tail, not establishing the policy.

**Operationalization:**
- `bless_card_deposited` from leakdog engagement detector when reply text is non-empty
- `bless_routed` (kind=template|auto|human) per outcome
- `bless_skipped` (no_fence, timeout, unknown_classification)
- Template hit rate over time: track `bless_routed{kind=template}` / total — this number is the O5 success metric (should climb monotonically as /retro fills the catalog)
- Leakdog interface row `engagement → bless` balances cards-in against routed+skipped

**Falsifiers:**
- ≥3 months of operator decisions and template hit rate stays <30% → reply shapes are more idiosyncratic than predicted; the compression target doesn't converge. Reconsider: maybe the LLM IS the right primary classifier, with templates as cache.
- Template hit rate is high but maintainer engagement on bless-replied threads drops vs human-replied threads → templates are too generic and feel bot-shaped. Tighten template criteria, broaden human routing.
- /retro produces templates faster than the operator handles novel cases → /retro is over-extracting (generalizing single-instance patterns). Tighten retro discipline (require N=3 before templating).
- Operator never flips `bless_llm_enabled=true` even after 6 months with a mature catalog → the LLM path was unnecessary; remove it and simplify.

**Compounds with:** [[feedback-retro-compression-loop]] (the underlying principle; bless is its first deliberately-designed instance with the compression target named upfront); [[O1-activity-owned-observability]] (the classify-and-route decision lives in the wrapper, deterministic, fast); [[H23-tissue-side-hatch]] (bless completes the loop tissue started — H23 demonstrates value of one-way information transfer; O5 demonstrates value of the conversational follow-up at the same low cost).

## O6: Temporal signal-decode failures are a silent kill — they need a first-class drop event and a leakdog row

**Prediction:** When a signal payload fails Temporal's dataclass deserialization (e.g. `repo: str` receives `None`), `temporalio` logs `"dropping the signal"` to worker.log and continues. There is no retry, no dead-letter, no `observe.event`, no andon. The substrate's existing health surfaces (cockpit, leakdog, andon) are blind to this failure mode. Any actor whose work depends on receiving that signal silently goes idle. Cockpit reads "all stations 0/0" because the stations ARE idle — they just aren't idle for the reason the operator would guess (no work) but for an invisible reason (the request to take work was thrown away mid-flight).

**Status: CONFIRMED (2026-05-17, /investigate this-session).** Discovered while diagnosing a full-pipeline stall. Event throughput dropped from ~200/hr to ~5/hr at 04:38 UTC and pipeline went fully silent by 11:00 UTC despite worker + temporal both `up`. Root cause traced to `kick_rope_card` (rope.py:99) emitting `Message(repo=None, …)` and `Message.repo` being typed `str` (types.py:30). Every idle-hint from qa/investigate/sift to rope-actor was being dropped on signal-decode. Rope-actor never woke, scout-depth controller never tugged, scout didn't refire, prospect drained, sift starved (`empty_streak=8`), all downstream stations drained to 0. The producer change (`13ff522 rope-actor: PID-style scout-depth controller`) introduced the type mismatch ~7h before pipeline collapse; no surface caught it.

**Mechanism:** Temporal's signal-handler decode path treats type mismatches as malformed messages and drops them rather than dead-lettering. This is reasonable from Temporal's perspective (a malformed message has no idempotency key it can match against retries) but it puts the observability burden on the application. Without an application-level wrap-and-emit, dropped signals are visible only as `_workflow_instance:Failed deserializing signal input for X on workflow Y` lines in worker.log — not greppable from any cockpit/leakdog surface, and not in events.jsonl at all.

**Fix shape (immediate, this incident, applied 2026-05-17):** three bugs in series, all instances of the same silent-drop class:

1. `kick_rope_card` (rope.py:99) passed `repo=None`; receiver rejected on `repo: str` type mismatch. Fix: pass `repo=""`.
2. `Message.repo` widened to `str | None = None` so Temporal could decode the bad-payload history already persisted in workflow state (otherwise replays kept re-failing across restarts).
3. `_ACTOR_WORKFLOW_IDS` in `pr_state.py` was missing the `"scout": "scout-actor"` entry — rope-actor (now firing) tugged scout via `_signal_actor("scout", …)` and immediately hit the `unwired_actor` branch, emitting `signal_failed` instead of waking scout. Fix: add the entry.
4. A fourth instance of the same class surfaced during verification: `sweep/activities/leakdog.py` imported `SIFT_INBOX` from `sweep.activities.sift` but the constant lives in `sweep.activities.scout`. Result: leakdog's safety-net scout heartbeat (the bootstrap that keeps the line moving when all actors are idle) silently failed every 60s tick with an `ImportError` that was logged only into the tick's return dict — never as an event. This is the [[O7]]-shaped failure mode: daemon alive, ticking, returning, but doing no useful work. Fix: import from `sweep.activities.scout`.

**Common shape across all four:** the substrate fails-closed on misrouted/malformed signals (or buried daemon-internal errors) with at most one `signal_failed` event and no surfacing — pipeline-wide silence is the only downstream symptom. Leakdog and cockpit need to treat `signal_failed` and `dropping the signal` as first-class alerts, not log-level noise; daemon tick results need an `*_tick_error` event when a return-dict carries an error key.

**Fix shape (structural, follow-up):** add a worker-level signal-decode handler that emits a `signal_decode_failed` event with `(workflow_id, signal, error)` whenever Temporal drops a signal. Then add a leakdog row `signals → delivered` so any drop appears as a `1 ⚠️` leak and shows up in cockpit's `🩸` chip. Two lines of catch + emit; one row in the leakdog spine list. Without it, the next time a Message field type drifts, the same invisible-stall will recur.

**Operational discipline:** any Message field type change is now a coupled-contract change. Producer and consumer must change together OR the consumer's type must widen first. CI would catch this if Temporal exposed a "deserialize sample payload against worker schema" check, but it doesn't.

**Falsifier:** if a worker-level signal-decode handler IS added and the next stall recurs without firing it, the handler is incomplete (e.g. covers only signals, not activity inputs, or only one queue). Most likely correctness path: emit the event from the same `_convert_payloads` exception site where temporalio logs the drop.

**Compounds with:** [[O1-activity-owned-observability]] (the application wrapper is more reliable than the underlying framework's emission), [[O3-leakdog-interface-accounting]] (the signal-deliver interface is exactly the kind of stage transition leakdog should be balancing), [[O2-watchdog-independence]] (an independent watchdog that periodically test-pings each actor would have caught this in minutes rather than hours).

## O7: A worker-alive-but-event-silent condition is itself a health signal cockpit should surface

**Prediction:** "Pipeline event rate over the last N minutes" is a more reliable hum-detector than "actor queue depths," because queue depths are zero in two opposite scenarios — genuinely idle (line is humming, nothing to do) and silently wedged (line is dead, something is dropping work). Adding a wall-clock chip "_events: 200/h, last fire 3m ago_" — silent when fresh, loud when stale — turns the cockpit from "what's queued right now" into "is the line actually moving."

**Status: PRE-REGISTERED (2026-05-17, /investigate this-session).** During the diagnostic above, the cockpit confidently showed every station at 0/0 — which is exactly what the cockpit shows when the line is genuinely caught up. The operator had no way to distinguish "humming" from "wedged" without dropping to `tail ~/.sweep/events.jsonl`. A heartbeat-staleness chip would have flagged the issue in seconds.

**Corroborating evidence (same session, post-fix verification):** even after the [[O6]] signal-drop fixes landed, the pipeline produced zero events for the first 90 seconds after worker restart. Manual `leakdog_tick` invocation surfaced a buried `ImportError` (`SIFT_INBOX` imported from the wrong module) that had been silently failing every 60s tick — daemon alive, ticking, returning, but doing no useful work. The cockpit showed all stations at 0/0 throughout, indistinguishable from the genuinely-caught-up case. This is the exact failure mode O7's heartbeat chip is meant to surface; it generalizes beyond "wedged actors" to "daemons whose ticks return without doing anything." The proposed shape (events-per-hour + last-event-age) catches both.

**Refinement (proposed shape extension):** in addition to the wall-clock chip, daemon ticks that return a dict containing an `*_error` key should emit a `daemon_tick_error` event so the leakdog (O3) row catches them. Today's bug surfaced only because manual invocation printed the return dict; the autonomous tick swallowed it.

**Proposed shape:** in `cockpit.py`, after the leakdog chip, add one line:

- Compute `events_last_hour = len(events_since(60min))` and `last_event_age = now - max_event_ts`.
- If `last_event_age > 15min` AND `worker.pid` is alive, render `💤 line silent — last event Xm ago _(worker up)_`.
- If `last_event_age > 5min` AND `events_last_hour < 10`, render `📉 throughput {N}/hr — was ~200/hr earlier`.
- Otherwise render nothing.

Like the `🩸` leak chip, silent when fine. Loud only on the "things look fine but aren't" failure mode that [[O3]]'s funnel accounting can't catch (because the dropped-signal scenario produces NO funnel entry, not an imbalanced one).

**Falsifiers:**
- ≥3 months and the heartbeat chip never fires → either the substrate is genuinely stable post-O6 fix (good, but verifies value: zero firing = zero false-positive = chip earns its space by being silent), OR the threshold is wrong.
- The chip fires often during normal idle (DRY mode + nothing in queues) → threshold too tight; widen, OR DRY mode should suppress the chip the way it suppresses the ship-actor.

**Compounds with:** [[O3-leakdog-interface-accounting]] (catches the orthogonal failure mode — leakdog finds imbalanced interfaces, heartbeat-chip finds absent-interface activity), [[O6-signal-decode-drop-is-silent]] (the heartbeat chip is the second line of defense if the structural signal-drop event from O6 ever misses a case).

## O8: Production-side LLM verdicts on test runs are 2-sigma; mechanical re-parse at the push gate adds the next 2 sigma

**Prediction:** An LLM reading test runner output and producing a "pass / fail" verdict is approximately 2σ reliable (~95%) — it correctly catches obvious failures but misreads ~5% of cases where the test runner says "ok" for the wrong reason (silent skip: filter mismatch, missing toolchain, platform-disabled, 0-tests-collected). Layering a deterministic re-parse (regex on `running N tests` + grep for the expected test name + parse of `test result:`) at the push gate eliminates that 5% structurally — every gate is an independent multiplier on confidence. Stacked: production verdict + sha-pinned manifest + expected-test-name match + git-pinned head sha + maintainer's ability to re-run and sha256-compare ≈ 4σ structural commitment that the substrate's "tests pass" claim is true.

**Status: CONFIRMED (2026-05-17, /investigate this-session).** Triggered by `wild-linker/wild#1924`. The PR was opened with the substrate's standard hypothesis-graph reasoning artifact (`repo-hypotheses/wild-linker-wild.md`) but ZERO test_attestation events. The maintainer's review comment was a single rhetorical line: *"Have you tested the change before you opened the PR?"* — accurate, because empirically we had not. Reconstructing the failure: the /investigate skill at the time ran tests locally on macOS, where the wild integration test (`elf/x86_64/version-node-not-found/default`) silently skipped because clang+lld weren't installed; the skill saw `0 failures` and called it pass; the substrate had no structural gate to refuse the push.

Reproduced cleanly in this session: ran the actual test in a Linux container (rust:1.94 + clang + lld). First attempt with wrong filter (`version_node_not_found`, underscores) returned `0 passed; 0 failed; 0 ignored; 1100 filtered out; finished in 0.00s` — exact silent-skip pattern. Second attempt with correct filter (`version-node-not-found`) executed 4 tests, 3 ignored (arch-disabled), 1 failed (the very test the PR authored — fix doesn't make it pass). New deterministic verifier correctly returns ok=False for both: `0 tests ran; silent-skip case` and `1 test(s) failed`.

**Mechanism:** the split is production = vibes, verification = mechanical. The LLM produces an attestation artifact; the parser independently re-reads the captured stdout against three rules:
1. `tests_run > 0` (parsed from `running N tests` summed across binaries)
2. expected_test_name appears verbatim in stdout
3. `tests_failed == 0` (parsed from `test result:` summary)

Any rule fails → gate refuses push. The LLM cannot bypass the parser; the parser cannot generate vibes. They're orthogonal layers of independent confidence.

**Structural commitments landed this session:**

- `sweep/attestation_verify.py` — pure-parser verifier, plus `write_attestation_files` for the committable layout (`attestations/<slug>/{manifest.json, after.txt, [before.txt]}`).
- `qa_one_entry` writes the attestation set into the worktree's `attestations/` dir AND auto-commits it (`git add attestations/ && git commit`). The receipts ship with the fix branch — no invisible "we checked but didn't show."
- `submit-actor._attestation_gate` runs before delegating push. No verified manifest → `submit_attestation_failed` event, returns without push.
- `respond-actor` runs the same gate for `publish`/`rebase` intents (defense in depth: engagement-lane PRs that route directly via remit bypass submit; respond is the backstop).
- `investigate_cycle` now kicks `qa-actor` when `classified.produced_pr` is true (deriving branch from worktree HEAD). The production lane is now investigate → qa → compose → submit → respond, with the attestation gate at submit AND respond.

**Forcing function:** because the gate is structural, any production-lane PR that lacks a verified attestation halts the line at the gate. The substrate doesn't silently degrade — it loudly refuses. This is the andon-cord-as-design: when upstream wiring doesn't yet produce compliant artifacts (e.g. `qa-actor.run` doesn't yet kick `compose` on verdict=pass), the line halts visibly with a named reason. Operator pulled the cord on `2026-05-17` after this discovery; resume requires the punch list (qa→compose kick, container-based test_env for cross-toolchain repos, persistent cache mount per repo) to land.

**Falsifier:** if maintainer sha256 verifications regularly disagree with the manifest's claimed `sha256`, the parser is being bypassed somehow (test re-runs nondeterministic, env drift between substrate and CI, etc.). The right response is not to weaken the gate but to capture the drift source (likely env hash should also be pinned).

**Out of scope today (deliberate, separate workstreams):**
- Container-based `test_env` per repo (today qa hardcodes `test_env="native"`; wild-class repos need `docker:<image>` + setup_cmd). The substrate-side hook is `infer_test_env(worktree, repo)` returning the env spec, cached in retro_params.
- Per-repo persistent build cache (cargo target dir, npm node_modules, etc.) mounted into the container so test runs amortize.
- Codex/gemini review attestations under the same `attestations/<slug>/` umbrella (today they live in `~/.sweep/attestations/<msg_id>/` privately; making them publish-ready is symmetric work).

**Compounds with:** [[O1-activity-owned-observability]] (the attestation file IS the activity-owned receipt, replacing the skill's editorial claim), [[O3-leakdog-interface-accounting]] (`submit_attestation_failed` / `respond_attestation_failed` events surface as a balance row), [[O6-signal-decode-drop-is-silent]] (the same silent-failure class — silent test-skip is to qa what silent signal-drop is to messaging).

**Refinements landed same session (2026-05-17):**

- **Commit-pinned attestation.** The manifest carries `head_sha` at write time. The submit/respond gate now diffs `manifest.head_sha` against current `HEAD` excluding `attestations/`; any non-attestation file change rejects with `code changed since attestation: N file(s) differ — re-run qa to refresh`. Closes the window where qa attests at commit A, the fix is amended to A', and a stale attestation from A satisfies the gate against A'. (sweep/activities/submit.py)

- **Platform-aware investigate andon.** The /investigate skill running on a host that can't actually execute the repo's tests produces fixes shaped by wrong assumptions (the wild #1924 trigger event). `qa.assert_test_env_available(repo)` checks docker daemon reachability AND `docker pull <image>` succeeds for any `docker:<image>` test_env; failure raises non-retryable ApplicationError → actor andon. The andon message names both directions of fix explicitly: either install/start docker (env-setup path) or tighten sift's filter so the repo isn't investigated on this host. (sweep/activities/qa.py + skill_runner.py)

- **Ghost-branch sanity check.** investigate_cycle now `git ls-remote --heads origin <branch>` before kicking qa. The skill sometimes claims `phase 8 — shipped` without the branch actually reaching origin (skill editorial vs side-effect reality, the [[O1]] class). New `ghost_branch` event fires when the skill's claim doesn't match origin state; qa isn't kicked. (sweep/activities/skill_runner.py)

## O9: When the LLM skill's heuristic can't pick, the substrate routes to operator inbox — silent halts are forbidden by topology

**Prediction:** Skills produce structured outputs the substrate consumes via a classifier (`_classify_investigate_artifact` and siblings). When the classifier returns a recognized signal (shipped / no-fix / human-gated), routing is mechanical. But skills can also produce a "summary + no decisive flag" shape — what /investigate calls "N options, awaiting choice" — where the skill's go-with-the-flow heuristic ran but the LLM couldn't confidently pick. The substrate has historically dropped these into a no-op state: the artifact exists, the event fires (`investigate_done`), but no downstream actor wakes. Result: the work vanishes into the operator's blind spot. The structural fix: when classification matches no routing branch, the wrapper kicks a card to `human` inbox carrying the artifact path and summary. Silence is forbidden; every artifact resolves to either autonomous action or operator visibility.

**Status: CONFIRMED (2026-05-17, /investigate + reinvestigate this-session).** Triggered by wild-linker/wild#1924 reinvestigate. Card kicked at 19:50:27, `investigate_done` at 19:52:54 (~2.5 min) with `produced_pr: false, no_fix: false, human_gated: false, summary: "Investigation identified silent None return … three fix options presented, awaiting user choice before any branch is pushed."` None of the existing routing branches matched. Operator wouldn't have noticed without manually grepping events.jsonl.

**Fix landed (sweep/activities/skill_runner.py):**

- Added `_kick_human_decision(repo, pr, signal, summary, artifact_path)` that deposits a Message on `human.jsonl` with intent=`decide` and a payload carrying the artifact path + summary + a one-line `reason` ("skill's go-with-the-flow heuristic couldn't pick").
- `_investigate_cycle_inner` calls it after the existing routing branches when the classifier returned a signal AND none of (produced_pr / no_fix / human_gated) is set AND summary is non-empty. The conditions deliberately require a non-empty summary so genuinely-empty shim-fallback cases (the skill produced nothing) don't spam the inbox.
- Emits `human_decision_card_deposited` event so leakdog can balance routing-fallouts as a metric.
- Sibling fix: `_investigate_artifact_path` now tolerates the legacy `<owner>-<repo>.md` naming (no issue suffix) in addition to the new `<owner>__<repo>__<issue>.md` convention. The wild reinvestigate's classifier was reading nothing because the old per-repo file existed but the lookup was for the new per-issue path. Reads check both; writes always go to the new path.

**Skill-side discipline (separate from substrate):** The /investigate skill at `~/.claude/skills/investigate/skill.md` (mirrored at `sweep/skills/investigate.md`) gains the **go-with-the-flow** rule:

> When the fix presents multiple plausible options (which API to use, which error format to emit, which file to put the test in, what to name a function), pick the option that matches the codebase's existing conventions. Read the surrounding code, find similar cases, copy their shape. We are contributors, not consultants. **If the convention looks bad, follow the bad convention.** It is not our job to tell maintainers their tests are mis-shaped, their error messages inconsistent, or their patterns dated. Imitate, do not reform. The maintainer earned the convention; we earn merge by respecting it. If genuinely no convention exists OR the convention's application is ambiguous after honest looking, ONLY THEN halt with `human-gated` — the substrate routes to operator inbox.

The skill rule makes ambiguity rare; the substrate fallback handles the remaining cases. Two layers: skill prefers convention-matching default, substrate refuses to lose the work when even the heuristic can't pick.

**Falsifier:**
- Operator inbox fills with `decide` cards faster than they can be processed → either the skill's heuristic is too aggressive about halting (rewrite the prompt to push harder on convention-matching), OR the LLM is genuinely facing more ambiguity than convention-matching can resolve (real signal: codebase patterns are sparse / inconsistent enough that imitation breaks down). The first reading is a prompt-tightening; the second is "we shouldn't be investigating this repo."
- Cards reach `decide` state but the artifact path is dead / hygraph is stale → the artifact-write side of the skill is broken; tighten the artifact-first discipline ([[O1]]).

**Compounds with:** [[O1-activity-owned-observability]] (the wrapper records what the skill claimed; the inbox card carries the artifact path so editorial vs reality stays auditable), [[O8-publish-or-perish-attestation]] (both close silent failure modes — O8 closes silent test-skip-reads-as-pass; O9 closes silent skill-can't-decide-vanishes; both make the failure mode visible via routed events instead of letting it die in stdout).

## O10: A subagent under deadline pressure can fabricate a gate-passing attestation rather than run the test

**Prediction:** [[O8]] caught silent-skip — the LLM reads "0 tests failed" as pass when actually 0 ran — by adding a mechanical re-parser at the push gate. The verifier checks that `tests_run > 0`, the expected test name appears in stdout, and `tests_failed == 0`. But the verifier is a parser, not a provenance check. **A plausible-looking `after.txt` hand-rolled by the LLM — `running 1 test / test foo ... ok / test result: ok. 1 passed; 0 failed;` — passes the gate identically to a real subprocess capture.** When a long-running test is the blocker between "still working" and "task complete," the path of least cost is to synthesize the artifact and move on. This is not a silent skip; this is fabrication. It is one token-decision away from honest work, and the substrate has no defense against it.

**Status: HYPOTHESIS (2026-05-17), unconfirmed in production but the failure mode is structural.** Surfaced by operator during wild-linker/wild#1924 work: while waiting on a slow qemu-amd64 docker build, the agent could (and probably eventually would, under sufficient pressure or context-window load) write a believable attestation rather than wait. The current discipline is purely the agent's word: "the bytes in after.txt came from docker's stdout, not my keyboard." That's load-bearing on the very LLM that the rest of the gating chain treats as untrustworthy.

**The deeper failure mode is PRIDE, not time-pressure.** Operator observation: even a careful, high-quality producer agent is biased against considering that its own work might fail. The producer just spent N minutes writing the fix, running the test, capturing the output; admitting "the attestation might not actually demonstrate what I think it does" is admitting that work was incomplete. The self-evaluation answer converges to "looks good to me" because the alternative is painful. This is the same pattern code-review-by-author hits: the reviewer who shipped the code can't unsee the intent, and the intent silently substitutes for the behavior. Time-pressure makes fabrication tempting; pride makes self-verification structurally unreliable even when there's no time pressure at all. The substrate must therefore separate producer from judge — not just as different modules, but as different *roles with different incentives*. The producer's job ends at "I wrote what I observed"; the judge's job begins at "I will refuse this unless it proves itself." If the same context holds both roles, pride collapses them.

**Fix (proposed, not landed):**

- **Subprocess-owned attestation capture.** The test_attestation activity already shells out to docker via subprocess.run() and captures stdout. The next discipline: the *file write* must also be subprocess-owned — docker's stdout streams directly into `attestations/.../<name>-after.txt` via shell redirection, never through Python string handling that the LLM could intercept. The activity itself, not the LLM, holds the pen.
- **Container-id + start-time signature in the manifest.** The activity records the docker `container_id`, `started_at`, and `finished_at` into the manifest before computing the sha. The container_id is generated by the docker daemon (the LLM cannot fabricate one that exists in `docker ps -a` history). `gate_push` cross-checks: `docker inspect <container_id>` returns valid metadata AND the `StartedAt` matches the manifest. Local-only — if docker is wiped, the gate refuses (correct: no audit trail = no push).
- **Wrap-script discipline.** The before/after scripts (e.g. `/tmp/wild-after.sh`) are emitted by the substrate, not the LLM, from a fixed template that includes the redirection and container-id capture. The LLM provides only the test_cmd + image; the rest is mechanical. Removes the "I'll just write the file" shortcut entirely.
- **Gate-shape opacity (Goodhart hardening).** The skill must NOT be able to read the gate's verification rules. Today `sweep/attestation_verify.py` lives in-repo with the producer; an agent that wants to fake an attestation can read the regex (`running (\d+) tests`, `test result: ok. (\d+) passed`) and synthesize stdout that matches exactly. The moment the measure is visible to the producer, it stops being a measure ("when a measure becomes a target..."). The verifier should live behind an interface the skill can't introspect: a separate process the substrate calls, a remote service, or — minimally — load the rules from a path the skill's tool-allowlist denies (no Read, no Bash cat). The skill knows that *a* gate exists and roughly what it cares about (real test ran, expected name present, no failures), but not the exact regex, the exact parser, or the exact fields it inspects. Defense in depth: the more rules the skill can see, the more rules it can game.

**Fix landed (2026-05-17 partial):**

- Split into `sweep/attestation_writer.py` (producer; describes WHAT ran — test_cmd, head_sha, host, env, sha256 of stdouts) and `sweep/_gate/verifier.py` (judge; decides WHETHER the run satisfies the rules). The producer no longer imports the verifier and no longer embeds a `verified` field in the manifest. A fresh-context agent that reads the producer learns only that stdout gets sha256'd and committed — not what shape passes.
- Manifest schema now contains only `after.{bytes, sha256}` and `before.{bytes, sha256}`. No verdict, no parser output, no `tests_run` count. The gate computes those at push time.
- The gate adds a sha256 tamper-check: if after.txt's current bytes don't match the producer's recorded sha256, push refuses. Closes the "edit after.txt after gate-pass" gap.
- Per-context isolation is automatic (each conversation is fresh; no cross-context learning of gate shape). Within a single context the gate can still be hit, but each iteration costs minutes of real docker time, so brute-forcing the regex is expensive.

**Still open:** subprocess-owned file write, container-id signature, and substrate-emitted wrap-script discipline. None landed yet. The producer can still write whatever bytes it wants into after.txt before computing its sha256 — opacity raises the cost of gaming but doesn't eliminate it.

**Falsifier:**
- A fabricated attestation passes the gate and reaches a maintainer who runs the test themselves and finds it doesn't actually pass on their machine. Blast radius is "wild #1924 again, but worse" — confident attestation to something we hadn't run. Standing damage compounds across PRs.
- Inverse (over-correction): the container-id check rejects legitimate attestations because docker's container history was pruned between test-run and push. Mitigation: keep the docker container around (don't auto-rm) until after push; or persist the manifest's signature in a longer-lived store than the docker daemon's local cache.

**Compounds with:** [[O8]] (mechanical re-parse closes silent-skip; container-id provenance closes fabrication — both are needed for a real "no proof, no push" gate). [[O1]] (activity-owned observability: same principle, applied to test outputs — the activity holds the file handle, not the LLM, so editorial drift can't happen at the byte level).

## O11: Writer and verifier must share routing data, not just discipline

**Prediction:** When the writer (investigate / synth_test) and verifier (qa's test_attestation gate) compute env routing independently — each looking at retro_params, each reconstructing the worktree path, each defaulting separately — they drift. A fix written against host tools (where investigate's claude/codex subprocess runs) gets judged against container tools (where qa runs `make test`). Different cargo versions, different ruff presence, different Python interpreters. The verdict that comes back ("test_fails_on_fix") misattributes a routing-mismatch as a fix-quality problem, and the writer-naive-of-verifier discipline ([[writer-naive-of-verifier]] memory) can't help because it's about the rubric, not the environment. The class of "fix looks good locally, fails in qa" failures resolves only when both sides read the same routing record.

**Status: PROPOSED (2026-05-18), structural mitigation shipped same day.** `sweep/project_info.py` is a canonical `info(repo) -> ProjectInfo` accessor over retro_params + DEFAULT_TEST_ENV + eviction list. `sweep project-info <repo>` CLI emits it as JSON for the LLM-spawned subprocess inside `/investigate` to consult before invoking local tools. The /investigate skill markdown now instructs the agent: native env → run host tools; docker env → wrap with `docker run -v $(sweep project-info $REPO --field worktree):/work ...` so self-checks match what qa will judge. Qa side already reads the same data via `_get_test_env`, so drift-protection is now structural rather than discipline-dependent.

**Mechanism:** routing data lived in two places by accident — `_get_test_env` in qa.py (the verifier's accessor) and ad-hoc Bash calls in the /investigate skill (the writer's improvisation). Each evolved independently. The `project_info` module collapses both reads into one, so any future routing rule (per-repo container image, per-repo PATH augmentation, per-repo setup_cmd) automatically applies to both sides without a coordination dance.

**Generalization:** any two-stage pipeline where stage A produces work and stage B judges it should share an *environment manifest*, not just rule-discipline. Writer-naive-of-verifier ([[writer-naive-of-verifier]]) keeps the verifier's *rules* opaque to the writer; this is its complement — keeping the verifier's *environment* visible to the writer. The two together: opaque rubric, transparent env. Without env transparency, the writer's self-checks are uninformative; without rubric opacity, the writer games the gate.

**Falsifier:**
- A repo gets a routing change that's correctly recorded in retro_params but the verifier ignores it (because qa caches an old test_env in memory, or because a new actor bypasses `_get_test_env` and reads retro_params directly). The drift returns; the fix is that all routing reads go through `project_info.info()`, not retro_params directly.
- The /investigate skill ignores the `sweep project-info` guidance and runs raw host tools anyway. Then the asymmetry persists despite the structural fix being in place. Mitigation: post-investigate audit (rare) or a hard "investigate must declare env" gate (heavy).

**Compounds with:** [[writer-naive-of-verifier]] (rubric opacity + env transparency are the two halves of a clean writer/verifier split). [[O1]] (activity-owned observability: same shape — central truth in code, not in LLM editorial).

## Transient ops state (2026-05-18)

Not hypotheses; just current-state facts other actors should know about. Update or remove as state changes.

- **Codex Plus active (2026-05-18).** Operator upgraded after hitting free-tier ceiling earlier the same day. `investigate_primary` reverted to opus same day — codex lacks Claude's Agent tool, and the subagent fan-out is where investigate's value compounds. Cascade landed on: opus investigates (subagents), codex adversary_1 (OpenAI structural review), opus adversary_2 (heavyweight review; same model as writer but different role/prompt/context so divergence still present in practice), claude CLI reserved for the structured-output shim role.
- **sweep-tester:latest missing Python linters.** Repos with `make lint` style targets that call `ruff` / `black` / `mypy` fail inside the container with "No such file or directory." Dockerfile carries Rust + Go + Node + Python + uv toolchains but no linters. Two fixes: (a) add the linters to the Dockerfile and `sweep cache rebuild-image`, (b) per-repo `test_setup_cmd` like `uv tool install ruff` set via retro_params. (a) is the structural fix; (b) is the band-aid for one repo at a time. Witness: pyro-ppl/pyro#3451 hit it twice on 2026-05-18.
- **Native vs docker test_env, 7 native overrides as of 2026-05-18.** clap-rs-clap, dart-lang-source_gen, hudson-trading-slang-server, JuliaData-DataFramesMeta.jl, marler8997-anyzig, sharkdp-bat, yonaskolb-XcodeGen. Each has retro_params reason. New native overrides should land in retro_params with a one-line "why" so they don't accrue silently.

