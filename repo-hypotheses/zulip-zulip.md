# Triage Graph: zulip/zulip

Generated: 2026-05-09 · Updated: 2026-05-13 (review backflow on #39265)

## Repo Profile

- **Stars:** 25K+
- **Stack:** Python (Django) backend, TypeScript frontend
- **Review culture:** Active maintainers (timabbott, alya). Zulipbot auto-assigns/unassigns. PRs tagged [ai] get extra scrutiny. Help-wanted label gates contributor claims.
- **Merge pattern:** Bug fixes merge if clean and small. Features require significant context.

## Selected: #39202 -- Klipy GIF selector fails with regional language preferences

- **Type:** Bug fix
- **Labels:** bug
- **Competing PRs:** None
- **Assignee:** None
- **Root cause:** `get_base_payload()` in `web/src/klipy_network.ts` passes `user_settings.default_language` (e.g., `en-gb`) directly as the `locale` parameter to Klipy's API. Klipy rejects regional variants with 422.
- **Fix:** Extract base language subtag via `split("-")[0]`. New `get_klipy_locale()` helper.
- **Branch:** `fix-klipy-locale-format`
- **Codex verdict:** Directionally right. Suggested tightening comment (applied), adding fallback (evaluated, dead code per Gemini), adding tests.
- **Gemini verdict:** PASS. "Correctly solves the problem, is safe to ship, and won't break existing functionality."
- **Risk:** Low. Single-line logic change, no behavioral regression for users without regional variants.

## Review Backflow 2026-05-13: Hypothesis Graph (apoorvapendse pushback)

apoorvapendse comment (2026-05-12 19:09): "it only accepts base language codes like en. this is incorrect. See https://docs.klipy.com/migrate-from-tenor/search"

### H0 (PR's original claim): Klipy accepts only base codes like `en`.
- **Perturbation:** Read PR body / first commit message.
- **Evidence:** Reporter in #39202 confirms `en-gb` returns 422 with `{"locale":["The locale format is invalid."]}`. Original PR body says "only accepts base language codes like `en`" and proposed `split("-")[0]`.
- **Classify:** PARTIALLY FALSIFIED at QA (2026-05-13 04:50). Code was rewritten to convert `en-gb` → `en_GB` (Tenor-style underscore) but PR body left stale.

### H1 (apoorvapendse): Klipy accepts regional codes; the strip-to-base claim is wrong.
- **Perturbation:** Fetch `https://docs.klipy.com/migrate-from-tenor/search` and the Fluxer mirror `https://docs.fluxer.app/api-reference/klipy/search-klipy-gifs`.
- **Evidence:** Klipy's `locale` parameter is an enum: `ar, bg, cs, da, de, el, en-GB, en-US, es-ES, es-419, fi, fr, he, hi, hr, hu, id, it, ja, ko, lt, nl, no, pl, pt-BR, ro, ru, sv-SE, th, tr, uk, vi, zh-CN, zh-TW`. Format is **hyphen + uppercase region** (BCP-47), not underscore, and bare `en`/`es`/`pt`/`zh` are NOT in the enum.
- **Classify:** CONFIRMED. Regional codes are accepted (in fact required, for English/Spanish/Portuguese/Chinese/Swedish).

### H2 (current commit `3673eb1`): Klipy expects underscore format `en_GB` like Tenor.
- **Perturbation:** Compare current code output vs Klipy enum. Reporter already tested `en_gb` per issue #39202 ("I did also test the format `en_gb` but klipy did not like that either").
- **Classify:** FALSIFIED. Current PR will still 422 — the Tenor analogy is misleading; Klipy uses BCP-47 hyphen format.

### H3: A correct fix is "uppercase region after hyphen" (`en-gb` → `en-GB`).
- **Zulip emits (via Django `to_language`):** `en`, `en-gb`, `pt`, `pt-pt`, `zh-hans`, `zh-tw`, `es`, plus ~40 base codes.
- **Klipy enum mismatches not fixed by uppercase alone:**
  - `pt-pt` → not in Klipy (only `pt-BR`).
  - `zh-hans` → not in Klipy (closest: `zh-CN`).
  - Bare `en`, `es`, `pt`, `zh`, `sv` → none in Klipy.
  - `eo, fa, gl, gu, kk, ml, mn, my, si, sl, sr, ta, tl, bn, be, bqi, ca, cy, et` → not in Klipy.
- **Classify:** PARTIALLY CORRECT. Naive uppercase fixes `en-gb`/`zh-tw` but leaves silent 422 for many supported Zulip languages.

### H4 (chosen fix): Map Zulip locales to Klipy's enum with `en-US` fallback.
- Pass through if value is already a Klipy code; map known Zulip-only codes (`en` → `en-US`, `es` → `es-ES`, `pt` → `pt-BR`, `pt-pt` → `pt-BR`, `zh-hans` → `zh-CN`, `zh-tw` → `zh-TW`); BCP-47-uppercase any remaining `xx-yy` to `xx-YY`; final fallback `en-US` for codes Klipy doesn't support.
- **Classify:** ADOPTED. Fixes the reporter's `en-gb` case AND closes the silent-422 surface for non-Klipy locales.

### Resolution
apoorvapendse's pushback is correct on substance. Replace current commit with Klipy-enum-aware mapper. Force-push branch, reply citing the docs and acknowledging the correction.

## Evaluated and Rejected

### #39021 -- Copying multiple messages missing newlines
- **Reason:** 2 open competing PRs (#39147 by apoorvapendse, #39076). Crowded.

### #38929 -- Date custom profile fields UI bugs  
- **Reason:** Open competing PR #38888 by Yogesh-Shivaji365, claims PR under review.

### #38436 -- Nested bulleted lists not working with tabs
- **Reason:** Root cause in markdown engine (2-space indentation logic). timabbott acknowledged. Closed PR #38458 tagged [ai]. Higher complexity, needs markdown parser understanding.

### #38342 -- Starred message count not updating on access loss
- **Reason:** Open competing PR #38399 by RahulXDTT.

### #39213 -- API retry-after value in the past
- **Reason:** Feature request disguised as bug. Requires rate-limiter changes, no help-wanted label, no maintainer response.

### #39210 -- Web UI not loading with bare JITSI_SERVER_URL
- **Reason:** Upgrade/config issue. No help-wanted label. Infrastructure-level fix.

### #39202 -- Klipy GIF locale (SELECTED)

### #39196 -- E2E FCM push registration failure
- **Reason:** Complex mobile/push notification infrastructure. No help-wanted label.

### #38972 -- DM via API with restricted email access
- **Reason:** API-level permission bug. No help-wanted label. Needs deep auth understanding.

### #38928 -- DM names bleeding below row
- **Reason:** CSS bug but no help-wanted label. Low maintainer signal.

## Pipeline Status

| Issue | Branch | Status | Gate |
|-------|--------|--------|------|
| #39202 | fix-klipy-locale-format | committed | codex:PASS, gemini:PASS |

## Next Actions

1. Push branch and open PR for #39202
2. Monitor for maintainer response on #38436 (nested bullets) -- if help-wanted added and no competing PR emerges, viable next target
3. Watch #38264 (emoji cut off in left sidebar) -- help wanted, updated recently, CSS-level fix
