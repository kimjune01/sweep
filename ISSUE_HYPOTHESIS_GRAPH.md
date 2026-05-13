# Issue Hypothesis Graph (2026-05-13, retro 2)

The pipeline files issues, not just PRs. Issues are a different artifact with different reception dynamics: pure prose, no code to dilute the signal, no test to verify. This graph tracks what we're learning about issue reception, separate from the [PR hypothesis graph](HYPOTHESIS_GRAPH.md).

**Strategy shift (2026-05-13):** Issue reception (not PR merge rate) is now the lead optimization target. The campaign operates on patience — wait for a maintainer to voice the AI-slop pain, then offer; never project the problem onto silent repos. See [[feedback-slop-filter-patience]].

**Current state since campaign epoch (2026-05-12, slop-filter launch):** 58 issues, **16 positive / 7 negative / 10 bot-closed / 25 inconclusive** — 69% positive reception rate (positive ÷ (positive + negative); bot-closed and inconclusive excluded). Numerator and denominator from `scoreboard --since 2026-05-12 --json`.

The earlier 51% number was wrong: 10 of the "rejections" turned out to be bot-closures (DrahtBot on bitcoin, github-actions[bot] on ant-design, silent automation on cypress/wayvnc/etc.). After enriching the cache with `closed_by` and reclassifying, the maintainer-decided rate is 69% — that's the honest signal from humans who actually looked at our offer.

Issue types we file:
- **bug-report** — from /investigate findings; usually paired with a PR (test-first protocol per [[feedback-test-first]])
- **slop-filter offer** — "Protect your repo from AI slop PRs" template, distributed via /distribute-slop-filter
- **competing-PR ack** — rare, when investigation finds someone else's fix in flight

The hypotheses below predict reception per type.

---

## HI0: Issue reception correlates with the artifact type

**Prediction:** Reception rates split sharply by issue type. Bug reports paired with a failing test merge as fast as the corresponding PR. Slop-filter offers split bimodally — repos that perceive AI PRs as a problem accept; repos that don't, label spam or silent-ignore.

**Status: PARTIALLY CONFIRMED.** Pre-campaign issues (all bug-report companions) ran ~89% positive. Campaign issues (mostly slop-filter offers) run 69% maintainer-decided, 28% positive against the full denominator including silent-treatment-as-negative. The split exists; the magnitude depends on whether you exclude bot-closures from the denominator (you should — they're not maintainer signal).

**Evidence for:** Pre-campaign 89% vs campaign 69% (-20 points). Bot-closure cluster (10/58) concentrated entirely on slop-filter offers. tinygrad: 5/5 positive on bug-reports. yt-dlp/nuxt: spam-label on slop-filter offers, never on bug-reports.

**Evidence against:** Some slop-filter offers landed positive (vue, tailwindcss, hugo, keras, OWASP, microsoft/vscode-copilot-chat) — the pitch isn't universally rejected. The bimodal hypothesis predicts this; the spread is across maintainer-receptiveness, not artifact type alone.

**Refined prediction:** Within slop-filter offers, reception is gated by maintainer-voiced pain (HI6). Bug-reports continue to convert near 100% because they answer a specific bug, not a general anxiety.

---

## HI1: Issues are detected as AI-generated faster than PRs

**Prediction:** Time-to-close on AI-detected issues is shorter than on AI-detected PRs. Issues are pure prose; reviewers don't have to read a diff to form a judgment. PRs at least require the reviewer to look at code, which pushes the AI-detection moment past the first impression.

**Status: STRENGTHENED.** Bot-closure data confirms automation is the primary detector, and automation runs in seconds. yt-dlp 2h 4m (`spam` label by bot), bitcoin/bitcoin DrahtBot (immediate close after running its LLM spam classifier), ant-design github-actions[bot] (workflow-driven). Compare to PR detection times of 7h–2d.

**Evidence for:** 5 of 10 bot-closures fired within minutes-to-hours. DrahtBot's comment is literally "LLM spam detection (✨ experimental): SPAM" — the bot reads the issue body, classifies, closes. Faster than any human reviewer.

**Evidence against:** None observed. The faster-bot-than-human story is consistent across the data.

**Action:** Slop-filter offers should target only repos *without* automated bot defenses (the bot-closed bucket is already filtered out by `offer-slop-filter` as of 2026-05-13). Bot-closure isn't reception data; it's "your offer reached a wall, not a person."

---

## HI2: Org-level reception transfers across repos for issues, faster than for PRs

**Prediction:** A maintainer who labels one issue from us as spam will label subsequent issues to sibling repos as spam, faster than they reject sibling-repo PRs. Reason: issue review is shallower, so the org-as-account perception updates faster.

**Status: STRENGTHENED.** Both astral-sh issues (uv, ruff) closed negatively; the org's anti-AI posture transferred. fluxcd, Homebrew, freeCodeCamp, sindresorhus, sourcebot — all evicted via single-issue rejection. No false positives observed yet.

**Evidence for:** astral-sh (2/2 negative), and the bot-closure cohort across orgs follows the same pattern: once one repo's automation flags us, the org's other repos likely have the same automation.

**Evidence against:** Only astral-sh has multiple issues from us in the same org. Single-data-point limitation.

**Action:** [[feedback-org-level-pacing]] applies to issues. After the campaign's first evicting close from any repo in an org, evict the entire org for slop-filter purposes (bug-report track may stay open if the rejection was about the offer specifically).

---

## HI3: The slop-filter framing is read as projection by repos not yet experiencing pain

**Prediction (revised 2026-05-13):** The "Protect your repo from AI slop PRs" template fails not because the framing is bad but because the *timing* is wrong. Repos that aren't yet feeling the pain perceive the offer as projecting an external problem onto them — confused-spam reaction. Repos that ARE feeling pain receive the same template positively.

**Status: CONFIRMED via strategy correction.** The campaign was paused on cold pitches and pivoted to wait-for-voiced-pain (HI6). The 7 maintainer-decided rejections cluster on repos with no recent maintainer mention of AI-slop pressure (yt-dlp's spam-label was bot, but freeCodeCamp/sindresorhus/Homebrew/cypress/puppeteer/SteeltoeOSS/wayvnc all closed without any maintainer engagement on the topic). The 16 positives include repos where maintainers have spoken about AI in their own issue trackers (microsoft/vscode-copilot-chat is literally a Copilot tool; obra/superpowers is an AI agent stack).

**Evidence for:** Pre-campaign 89% (issues responded to specific bugs the maintainer had already filed) vs campaign 69% (issues offered an unsolicited solution). The delta is the projection cost.

**Evidence against:** Some confused-but-positive responses — vuejs/vue, tailwindcss accepted without prior visible AI-slop complaint. May be receptive maintainers regardless of voiced pain. Sample-size-bound for now.

**Action: TAKEN.** `offer-slop-filter` now requires a maintainer (OWNER/MEMBER/COLLABORATOR) mention of AI-slop pressure in the last 60 days. Cold pitches are blocked at the gate. Query terms are v1; refine as misses surface (curl/curl is a known miss — Stenberg writes about it in non-canonical phrasings).

---

## HI4: Inconclusive issues degrade negative if left alone — withdraw at 2d to preserve trust

**Prediction (revised 2026-05-13):** Open issues with zero engagement degrade toward negative reception over time (the original HI4). The correction: rather than wait and absorb the negative classification, withdraw our own offer at 2 days of silence. This converts a future negative into a clean withdrawal that preserves the maintainer relationship.

**Status: PROCEDURAL — built, not yet tested.** `offer-slop-filter --withdraw-stale` runs as phase 1 of every /distribute-slop-filter tick, closes our open issues silent for 2+ days with zero comments AND zero reactions (👀, 👍 protect from withdrawal). Posts a polite withdrawal comment so the maintainer sees we noticed and respected their silence.

**Evidence for (a priori):** [[feedback-slop-filter-patience]] frames silence as a real signal. Acting on it preserves the option to offer again later when the pain surfaces — a future positive convertibility we'd burn by leaving the issue open as ambient pressure.

**Test:** Compare maintainer reception of *follow-up* offers (after a withdrawal) vs first-time offers in the post-pain regime. If withdrawal preserves trust, the second offer's reception rate should match or exceed first-offer reception rates.

---

## HI5: Issue volume per repo has a sharp cliff at 3, not a gradient

**Prediction:** A repo can absorb 1 issue from us without flagging the account; absorbs 2 with skepticism; flags as spam at 3+. Cliff between 2 and 3.

**Status: UNTESTABLE under current strategy.** The pain-gated + 1-per-repo throttle means we will rarely if ever reach 3 issues to a single repo. Pre-registered for the historical record; deprioritized as a test target.

---

## HI6 (NEW 2026-05-13): Maintainer-voiced pain precedes positive reception

**Prediction:** Slop-filter offers sent within 60 days of an OWNER/MEMBER/COLLABORATOR mention of AI-PR pain in the same repo will convert at substantially higher reception rate than cold offers. The pain-mention is the readiness signal — the maintainer has decided the problem is real and worth solving, so an external offer arrives as a response rather than as a projection.

**Status: PRE-REGISTERED.** All 58 campaign issues to date were sent without the pain gate (the gate was added 2026-05-13 after this graph's first revision). Going forward, every offer carries a pain-mention citation (or doesn't ship).

**Evidence for (a priori):** The 16 positive responses correlate weakly with public maintainer AI-discourse (microsoft/vscode-copilot-chat, obra/superpowers). The 7 maintainer-rejections correlate with silence on the topic in the target repo's recent activity. Causation isn't established but the correlation is consistent with the prediction.

**Test:** Compare reception rate of post-pain-gate offers (cohort starting 2026-05-13) against cold-pitch offers (cohort 2026-05-12 to 2026-05-13). Predict: post-pain rate ≥ 80%, cold rate as observed (69% maintainer-decided, 28% raw).

**Falsification:** If pain-gated offers don't outperform cold offers materially, the readiness-signal hypothesis is wrong and the failure mode is something else (account standing? template wording? something orthogonal).

---

## HI7 (NEW 2026-05-13): Patience compounds; reach decays

**Prediction:** Sending fewer, better-timed offers will produce more total positive receptions over a 6-month horizon than sending many cold offers. Reason: a cold rejection burns the repo's optionality permanently (the org-level transfer per HI2 means even sibling repos become harder to approach), while patience preserves it.

**Status: PRE-REGISTERED — strategic conviction, not yet measured.** Built into the campaign as the reason for the pain gate and the 2-day withdrawal.

**Test:** At 30, 60, 90 days post-strategy-shift: count total positive receptions under the patience strategy vs an extrapolated cold-pitch counterfactual. The counterfactual is 28% × volume; the actual will be (post-pain-rate) × (smaller volume). If the actual exceeds the counterfactual on absolute count, patience compounds. If not, reach was right and we burned future demand for nothing.

---

## Cross-graph link

The PR hypothesis graph's H0 ("quality-gated AI contributions are indistinguishable from human ones") and HI0 here are sibling tests with different artifact pressure. PRs have code as a buffer; issues don't. The bimodal split confirmed in HI0 is evidence *against* H0's universality in the issue regime — issues fail at higher rates because the prose IS the artifact, leaving no surface for code-quality to mask the AI signal.

**Strategic shift (2026-05-13):** the pipeline now optimizes for issue positive reception rate, not PR merge rate. PRs continue to ship as a baseline; issues are the new lead artifact. The implication for /retro is to weight HI0–HI7 outcomes more heavily than H0–H6 in the next consolidation pass.
