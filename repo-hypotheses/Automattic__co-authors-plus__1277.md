# Automattic/co-authors-plus#1277 — Co-Authors look-up from post.php broken post 4.x upgrade

**Issue:** After upgrading 3.7.0 → 4.0.2, the sidebar's `authors-by-term-ids` request URL contains `ids=%5Bobject%20Object%5D` (`[object Object]` URL-encoded). The reporter traced it to `getEditedPostAttribute('coauthors')` returning full coauthor objects (`{display_name, user_nicename, user_url, user_id}`) instead of an integer array of taxonomy term IDs. They asked: when/why does the post entity's `coauthors` attribute carry objects rather than term IDs?

## H₀ — Plugin registers `coauthors` on the post REST response as objects (deduction)

**Null:** plugin registers it as term-ID array (WP default for `show_in_rest` taxonomy with `rest_base='coauthors'`).

**Perturbation:** grep the entire plugin for `register_rest_field` and any filter that overrides the `coauthors` field on the post response.

**Result:**
- `php/class-coauthors-plus.php:251` — `register_taxonomy('author', ..., ['show_in_rest'=>true,'rest_base'=>'coauthors'])`. WordPress core exposes that as `post.coauthors = [term_id, ...]`.
- Repo-wide grep for `register_rest_field`: only a translator comment in `class-coauthors-controller.php:417`; **no `register_rest_field('post', 'coauthors', ...)` anywhere in the codebase**.
- No `rest_prepare_post` / `rest_prepare_{post_type}` filter mutates the `coauthors` field. `php/class-coauthors-endpoint.php:355` only removes the `wp:action-assign-author` link.
- `sync_coauthors_on_rest_save` (class-coauthors-plus.php:1254) only writes terms server-side from the request; it does not mutate the response payload.

**Trajectory:** divergent against. **Killed.** The plugin ships term IDs in the `coauthors` field of the post REST response, as documented in `docs/upgrading-to-4.0.md:24` and the 7221a90 commit message ("term IDs flow through the core entity store automatically").

**Edge generated:** if the plugin doesn't put objects there, *something else on the reporter's site does*. Candidates: (a) third-party `register_rest_field`/`rest_prepare_post` override, (b) third-party JS calling `dispatch('core/editor').editPost({coauthors: [...objects]})`, (c) stale persisted edit from the pre-4.0 `cap/authors` store sitting in the editor's autosave/local-storage and replaying through the new field name, (d) older cached `build/index.js` shipping objects to `editPost` (the pre-7221a90 sidebar wrote to a custom Redux store, not the post entity — so cache-only is unlikely to be load-bearing here unless the cache predates the rename).

## H₁ — JS hook is unguarded against non-integer entries (deduction)

**Null:** `useCoauthorDetails` validates `termIds` are integers before joining into the request URL.

**Perturbation:** read `src/hooks/use-coauthor-details.js` and `src/utils.js`.

**Result:**
- `use-coauthor-details.js:47` builds the URL as `` `/coauthors/v1/authors-by-term-ids?ids=${ uncachedIds.join( ',' ) }` ``. No type filter on `termIds` or `uncachedIds`. Objects flow straight in and `Array.prototype.join` calls `Object.prototype.toString`, producing `[object Object]`.
- Sibling helper `buildCoauthorTermIds` in `src/utils.js:87` already declares the convention: `const isValidId = ( id ) => Number.isInteger( id );` and filters non-integers before persisting. That convention is not applied to the input side.

**Trajectory:** divergent. **Confirmed.** There is a real defensive gap on the read path: the hook trusts that the entity store hands back integers, but the plugin doesn't enforce that downstream consumers can't shove objects into `editPost({coauthors})`.

## H₂ — The reporter's objects shape matches the `/coauthors/v1/search/` and `/coauthors/v1/authors-by-term-ids` response shape (induction)

**Null:** the objects come from somewhere unrelated to the plugin's own endpoints.

**Perturbation:** compare keys.

**Result:** reporter's objects use `display_name`, `user_nicename`, `user_url`, `user_id` — snake_case PHP keys. The plugin's REST controller (`class-coauthors-controller.php`) and the formatted JS objects (`formatAuthorData` in `src/utils.js`) return camelCase JS-style keys (`displayName`, `userNicename`, `userType`, `termId`). So the reporter's objects are **not** the output of the plugin's REST endpoints — they look like a direct PHP-side serialization (e.g. `get_coauthors()` output, or a custom REST field on their site mapping to coauthor user data).

**Trajectory:** divergent. The objects almost certainly originate from a site-side customization (likely a `register_rest_field` that returns hydrated author data instead of term IDs), not from anything the plugin ships. That customization probably predates 4.0 and was harmless in 3.7 because the sidebar didn't read `getEditedPostAttribute('coauthors')` — it used the custom `cap/authors` store. The 7221a90 rename collided with the customization's field name.

## H₃ — Defensive normalization in `useCoauthorDetails` would prevent the broken URL but not restore the reporter's authors (deduction)

**Null:** filtering inputs to integers fully restores the sidebar.

**Perturbation:** trace what happens if `termIds` is `[{user_id:8703,…}, {user_id:16,…}]` and we apply `Number.isInteger`.

**Result:** `uncachedIds` becomes `[]`, the early-return at line 34 fires with `setAuthors([])`, the spinner clears, and the sidebar shows an empty author list. The reporter still loses their displayed coauthors — but the broken `[object Object]` request goes away, the network panel stops 400-ing, and the failure mode becomes "empty list" instead of "spinner / malformed URL." More importantly, the reporter (or any other site overriding the field) now has the clear feedback that the entity store's `coauthors` payload is wrong-shaped, rather than a confusing URL-encoding artifact.

**Trajectory:** convergent (partial). A defensive guard is correct and small, but it is a **diagnostic fix**, not a root-cause fix. The root cause lives on the reporter's site.

## Frontier

- **E₁ (cheap, decisive on the reporter's side):** ask the reporter to grep their site for `register_rest_field.*post.*coauthors` and for any `editPost({ coauthors:` in custom JS. This is on the maintainer's plate, not ours.
- **E₂ (cheap, ours):** ship the `Number.isInteger` filter in `useCoauthorDetails`. Small, conventional (mirrors `buildCoauthorTermIds`), prevents the broken URL.
- **E₃ (open):** could also `console.warn` once when non-integer entries are dropped, to help site-side debugging. Risk: noisy if a site genuinely persists transient object state during a save round-trip.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Plugin does not register `coauthors` as objects on post response | Deduction (grep, read) | 95% |
| `useCoauthorDetails` URL build is unguarded | Deduction (read) | 99% |
| Reporter's object shape ≠ plugin endpoint output shape | Induction (key comparison) | 90% |
| Root cause is a third-party `register_rest_field` on the reporter's stack | Abduction | 70% |
| Defensive integer filter prevents broken URL but doesn't render authors | Deduction (code trace) | 95% |

## Pruning log

- H₀ killed by repo-wide grep + REST endpoint read. The plugin is not the source of the object shape.

## Recommendation

This is fundamentally a site-side issue, but the JS hook is brittle in a way the plugin's own sister helper (`buildCoauthorTermIds`) explicitly guards against. A two-line `Number.isInteger` filter at `use-coauthor-details.js:29-30` is the minimal change: it converts the failure from "malformed request + spinner" to "empty list with clear signal that the entity store has the wrong shape," and it stays inside the convention already set by `utils.js:87`. The reporter still needs to find the customization on their stack; the patch makes that easier, not harder.

Not auto-shipping — the maintainer-facing value is small (defensive only) and the underlying question ("where is the field coming from?") is better answered by the reporter than guessed at by us.
