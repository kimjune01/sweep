# chojs23/concord#93 — Custom emojis missing from composer autocomplete

**Issue:** Typing `:pepe_ok` in a guild text channel does not surface custom emoji suggestions; only unicode shortcodes appear. Concord 2.0.0, Linux/Kitty. Author: OverStyleFR.

## H₀ — Filter / picker logic excludes custom emojis

**Null:** Custom emojis are filtered out in `build_emoji_candidates`.

**Perturbation (read-only):** Trace `composer_state.refresh_active_mention_query` → `emoji_candidates_for_query` → `build_emoji_candidates`.

- `src/tui/state/composer_state.rs:654` calls `self.discord.custom_emojis_for_guild(guild_id)` and forwards to `build_emoji_candidates`.
- `src/tui/state/composer.rs:98-156` filters by `name.to_ascii_lowercase().starts_with(needle)`, ranks customs above unicode, includes unavailable customs (so they appear greyed, not hidden).
- Existing test `emoji_picker_keeps_more_than_visible_candidates_selectable` (tests/mod.rs:4439) shows the picker correctly surfaces custom emojis added via `GuildEmojisUpdate`.

**Trajectory:** Convergent against — the candidate-building code is sound. **H₀ killed.**

**Edge:** If the picker logic is fine, the symptom implies `custom_emojis_for_guild(guild_id)` returns an empty slice for the user's guild.

## H₁ — `selected_channel_guild_id` returns None for guild text channels

**Null:** Composer can't resolve the active channel's guild.

**Perturbation:** Read `src/tui/state/channels.rs:647` and `selected_channel_state` at line 994.

- `selected_channel_state()` returns `self.discord.channel(active_channel_id)`, `.guild_id` is set on `ChannelInfo` for guild channels in `parse_channel_info(_, Some(guild_id))` (called from both `parse_guild_create` and `parse_supplemental_guild_events`).

**Trajectory:** Convergent against — guild_id is consistently propagated. **H₁ killed.**

**Edge:** Cache is empty because the gateway parser never populated it.

## H₂ — `parse_supplemental_guild_events` drops the `emojis` field

**Null:** Discord's READY_SUPPLEMENTAL carries per-guild emojis but the parser ignores them.

**Perturbation:** Read `src/discord/gateway/parser/ready.rs:212-263` (`parse_supplemental_guild_events`).

It iterates each supplemental guild and forwards: `roles`, `channels`, `threads`, `members`, `member`, `presences`, `voice_states`. **No handling of `emojis`.** Compare with `parse_guild_create` (parser/guilds.rs:73-77) which DOES read `emojis`.

**Trajectory shape:** Suggestive but unverified — I don't have a captured Discord gateway payload to confirm READY_SUPPLEMENTAL ever carries an emojis array on its per-guild entries. Public Discord client telemetry suggests SUPPLEMENTAL is primarily presence/member top-ups; emojis usually ride in the streamed GUILD_CREATE for lazy guilds.

**Confidence:** Abductive ~55%. The asymmetry between `parse_guild_create` and `parse_supplemental_guild_events` is suspicious but not proof.

**Edge:** Need a real READY_SUPPLEMENTAL capture to confirm presence of emoji fields. Without it, this is an untested guess.

## H₃ — Guild emojis are nested under `properties` in lazy mode

**Null:** With `LAZY_USER_NOTIFICATIONS` capability, Discord nests fields under `properties`. `parse_guild_create` uses `guild_field()` helper for `name` and `owner_id` only. If `emojis` is also nested for some payloads, `data.get("emojis")` returns None.

**Perturbation:** Read `parse_guild_create` at parser/guilds.rs:18-91 and `guild_field` helper at 311-316.

`emojis` is fetched via `data.get("emojis")` directly (line 73) — no `properties` fallback.

**Confidence:** Abductive ~30%. The existing comment in the file (line 22) explicitly enumerates "name / icon / owner_id" as the lazy-mode-nested fields, not emojis. Public reverse-engineering notes I'm aware of also list emojis at root. Plausible but the inline doc weakens it.

## H₄ — Filter is `starts_with`, Discord client uses substring

**Null:** Concord requires emoji name to start with the query; Discord matches substring.

**Perturbation:** Read composer.rs:110.

`starts_with(&needle)` — strict prefix. The user's example (`:pepe_ok` matching an emoji literally named `pepe_ok`) would still match a prefix filter, so this would not explain the reported symptom in their concrete example. **H₄ killed for this reproducer**, though it's a real UX gap separately.

## Graph state

| H | Status | Shape | Provenance |
|---|--------|-------|------------|
| H₀ picker filter excludes customs | killed | convergent against | deduction from composer.rs:98 |
| H₁ guild_id resolution broken | killed | convergent against | deduction from channels.rs:994 |
| H₂ SUPPLEMENTAL drops emojis | open | unverified abduction | parser/ready.rs:212 (missing field handler) |
| H₃ properties-nested emojis in lazy mode | open, weak | abduction | parser/guilds.rs:73 vs guild_field |
| H₄ prefix vs substring | killed for reported example | divergent against | reproducer literally starts with the emoji name |

## Frontier edges

- Capture a real Discord user-account READY + READY_SUPPLEMENTAL payload from a session with custom emojis. If supplemental guild entries contain an `emojis` array, H₂ is confirmed and the fix is one parser hunk.
- Capture a GUILD_CREATE for a lazy-mode large guild; check whether `emojis` lives at root or in `properties`. Confirms or kills H₃.
- Without a payload capture, the next decisive step would be to add debug-level logging in `parse_user_account_event` that dumps top-level keys of every guild seen, and ask the reporter to run a debug build briefly. That requires maintainer coordination.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|------------|
| Filter logic in `build_emoji_candidates` is correct | Deduction | 95% |
| `selected_channel_guild_id` works for guild channels | Deduction | 95% |
| `parse_supplemental_guild_events` does not parse `emojis` | Deduction | 99% |
| SUPPLEMENTAL contains `emojis` for at least some accounts | Abduction | 55% |
| Lazy mode nests `emojis` in `properties` | Abduction | 30% |

## Pruning log

- Killed H₀ (picker filter) after reading composer.rs:98-156 and tests/mod.rs:4439.
- Killed H₁ (guild_id) after reading channels.rs:647-997.
- Killed H₄ (prefix vs substring) — fails to explain the literal reproducer.

## Verdict

No PR shipped. The investigation identified the asymmetry between `parse_guild_create` (handles `emojis`) and `parse_supplemental_guild_events` (does not), which is the most plausible root cause but **unverified without a real gateway capture**. Shipping a "also parse emojis in supplemental" patch speculatively would be a guess; if the real payload doesn't carry emojis there, the patch is dead code and the maintainer reads it as noise.

Recommended next action: tissue-style comment summarizing the trace so the maintainer (or a contributor with Discord network-capture tooling) can confirm which gateway payload carries the user's emojis. The fix is likely 5 lines once the source is identified.
