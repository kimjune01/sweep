# Hypothesis Graph: vavallee/bindery#675

**Issue:** Prowlarr integration adds all indexers (including unrelated and disabled ones).
**Expected (per reporter):** "Similar behavior to readarr: Never add disabled indexers; Only add indexers with ebook/audiobook support setup in Prowlarr."

## H₀ — Baseline observation

- **Reported behavior:** `prowlarr sync complete ... added=11 updated=0 removed=0` adds every indexer Prowlarr knows about, regardless of `enable` flag or whether it carries any book category.
- **Perturbation:** read `internal/prowlarr/{client,syncer}.go`.
- **Findings:**
  - `client.go:40-48` defines `remoteIndexer` with **no `enable` field**. The Prowlarr `/api/v1/indexer` payload includes `enable: bool`, but bindery silently drops it.
  - `syncer.go:75-78`:
    ```go
    cats := filterCategoriesForMedia(ri.Categories)
    if len(cats) == 0 {
        cats = []int{7020}
    }
    ```
    When an indexer's Prowlarr categories contain *no* book/audiobook category, the syncer **invents `[7020]`** and adds it anyway. That's how unrelated (movies/TV/music-only) indexers materialize as ebook indexers in bindery.
- **Trajectory shape:** divergent — the code path matches the report exactly.
- **Edge:** propose fix that (a) reads `enable` and skips disabled, (b) skips indexers that carry no media-relevant category instead of fabricating `7020`.

## H₁ — Disabled indexers leak in because `enable` is never deserialized

- **Null:** `remoteIndexer` deserializes `enable`.
- **Perturbation:** grep `internal/prowlarr` for `enable|Enable` → 0 matches.
- **Trajectory:** divergent. Confirmed.
- **Edge:** add `Enable bool` to `remoteIndexer` and `IndexerInfo`; have syncer `continue` on `!Enable`.

## H₂ — Unrelated indexers leak in because `[7020]` is a fallback, not a gate

- **Null:** unrelated (e.g. movies-only `[2000]`, music-only `[3010]` — audiobook is 3030) indexers either fail filtering or are stored with their own categories.
- **Perturbation:** trace `filterCategoriesForMedia([2000, 5030])` → returns `[2000, 5030]` (non-empty), so the fallback doesn't fire but the indexer still gets added with non-book cats. Trace `filterCategoriesForMedia([])` → `[]`, fallback fires, indexer added as `[7020]`.
- **Trajectory:** divergent — both branches lead to "unrelated indexer added". The current "only ebook/audiobook" intent is not enforced.
- **Edge:** replace the `[7020]` fallback with a `continue`. The eligibility predicate is: at least one category in `7000-7999` (books/ebooks) or `3030` (audiobooks). Use it on `ri.Categories` *before* `filterCategoriesForMedia` so we don't depend on the filter's parent-widening side-effect.

## H₃ — Reconciliation: skipping doesn't strand previously-synced rows

- **Null:** if a Prowlarr indexer is disabled or unrelated, the existing bindery row stays orphaned.
- **Perturbation:** read `syncer.go:127-138`. Anything not in `seen` is deleted. If we skip without adding to `seen`, the previously-added unrelated row is removed on the next sync.
- **Trajectory:** convergent — skipping is the *right* shape; it cleans up the user's mess from previous bad syncs.

## Provenance

- `git log -p internal/prowlarr/syncer.go | head -200` (local): `filterCategoriesForMedia` and the `[7020]` fallback were added by a prior PR ("widen parent-only category"). The widen-fallback was correct for the case "Prowlarr returned `[7000]` only" but became a leak when extended to "Prowlarr returned no book cats at all".
- No prior issue or PR mentions the disabled-indexer / cross-category leak (search: `gh issue list --repo vavallee/bindery --state all --search "prowlarr disabled enable"` → none).
- Reporter explicitly cites readarr as the reference behavior. Readarr's Prowlarr sync filters by `enable: true` and by category capability — same fix shape.

## Fix shape

1. `client.go`:
   - `remoteIndexer.Enable bool` from `enable`.
   - `IndexerInfo.Enable bool`, propagated.
2. `syncer.go`:
   - At top of loop: `if !ri.Enable { continue }`.
   - Replace `if len(cats) == 0 { cats = []int{7020} }` with `if !hasMediaCategory(ri.Categories) { continue }`.
   - Helper `hasMediaCategory`: any cat in `[7000, 8000)` or `== 3030`.
3. Tests: disabled indexer not synced; indexer with only `[2000]` not synced; indexer with `[2000, 7020]` synced; existing row for a now-disabled indexer is removed on next sync.

## Reasoning mode

| Claim | Mode | Confidence |
|-------|------|------------|
| `Enable` never read | Deduction (grep + source) | 99% |
| `[7020]` fallback admits unrelated indexers | Deduction (source) | 99% |
| Readarr filters identically | Abduction (reporter's claim + common knowledge) | 80% |
| Skipping unrelated indexers cleans previous bad rows | Deduction (delete loop) | 95% |

## Frontier

- None for the diagnosis. Open frontier: does Prowlarr return capability via a separate field (e.g. `capabilities.categories`) versus the `categories` array bindery already reads? Spot-check by greping Prowlarr OpenAPI later if reviewer pushes back; for now, the `categories` field at the indexer level *is* the capability set Prowlarr exposes via `/api/v1/indexer`.
