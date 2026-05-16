# vavallee/bindery#579 — Per-author audiobook root folder

**Issue:** [#579](https://github.com/vavallee/bindery/issues/579) — labeled `enhancement`, opened by maintainer @vavallee 2026-05-11, filed from @j-tt's BUGS.md.
**Started:** 2026-05-16
**Class:** Feature with external patch available; investigation is *patch-validation + idempotency check*.
**Prior status:** Denylisted in 2026-05-11 vavallee/bindery triage under "External patches available — @j-tt has working patch (3ea2bcb)." Re-investigated at user request.

---

## H₀ — Bug exists in current `main`

**Perturbation:** clone `vavallee/bindery@main`, read scanner.go around lines 750-770.

```go
// internal/importer/scanner.go:755-762 (current main)
// audiobookRoot always starts from BINDERY_AUDIOBOOK_DIR (set at
// startup). effectiveLibraryDir is format-agnostic — it resolves the
// per-author ebook root folder — so applying it here would send
// audiobooks into the ebook root whenever the author has any custom
// root folder assigned, silently ignoring BINDERY_AUDIOBOOK_DIR
// (#421). Until a per-author audiobook root folder field exists we
// leave audiobookRoot as-is.
audiobookRoot := s.audiobookDir
```

The comment is a self-confessed gap. `effectiveAudiobookDir` does not exist; `models.Author` has `RootFolderID` only (no `AudiobookRootFolderID`); no migration adds an audiobook root column.

**Trajectory:** divergent confirm. The capability is missing by design pending this exact change. **Deduction (99%).**

## H₁ — j-tt patch applies cleanly and tests pass

**Perturbation:** fetch `https://github.com/j-tt/bindery/commit/3ea2bcb.patch`; `git apply --check --exclude=BUGS.md`.

```
git apply --check --exclude=BUGS.md  → clean (exit 0)
go build ./...                       → ok
go test ./internal/importer/ ./internal/api/ ./internal/db/ -count=1
  ok  github.com/vavallee/bindery/internal/importer  1.058s
  ok  github.com/vavallee/bindery/internal/api       5.092s
  ok  github.com/vavallee/bindery/internal/db        1.628s
```

The new test `scanner_rootfolder_test.go` (+91 lines) covers `effectiveAudiobookDir` fall-back to `BINDERY_AUDIOBOOK_DIR` and resolution when `AudiobookRootFolderID` is set. The test would fail on `main` (no field, no method).

**Trajectory:** convergent. Patch is mergeable, tests pass, behavior matches the issue spec. **Induction (95%).**

## H₂ — Migration number collision

**Perturbation:** `ls internal/db/migrations/`.

```
037_download_import_retry_count.sql
038_default_import_mode_hardlink.sql   ← main already uses 038
039_orphan_author_reassign.sql
```

j-tt's patch adds `038_author_audiobook_root_folder.sql`. Direct apply produces two `038_*` files — a duplicate migration number. The issue body flagged this caveat: "Fork uses migration 038. Needs renumbering once main's next free migration number is known."

Renumbered locally to `040_author_audiobook_root_folder.sql`. Build + tests still pass.

**Trajectory:** divergent. Patch needs a one-file rename before shipping. **Deduction (99%).** Mechanical, not load-bearing.

## H₃ — Idempotency: is anyone already shipping this?

**Perturbation:** `gh pr list --repo vavallee/bindery --search "<keywords>" --state all` across multiple phrasings (`"579 in:title,body"`, `"audiobook_root_folder_id"`, `"per-author audiobook"`, `"j-tt OR audiobookRootFolderId"`).

Zero open or closed PRs reference #579, the new column, or the new field. No competing draft from @j-tt either — the fork commit exists but no upstream PR was opened. #439 (merged 2026-05-03 by @vavallee) added the *ebook* per-author root + exposes audiobookDir read-only in UI; that PR is the precursor that made this surface coherent but explicitly left the audiobook side for later (the comment at scanner.go:755-762 was added by that PR).

**Trajectory:** divergent. No duplication risk. Slot is open. **Deduction (99%).**

## H₄ — Frontend gap

**Perturbation:** `git diff --stat` of the patched tree.

```
internal/api/authors.go                      | 42 +++---
internal/db/authors.go                       | 23 +-
internal/importer/scanner.go                 | 27 +-
internal/importer/scanner_rootfolder_test.go | 91 +++++
internal/models/author.go                    |  1 +
```

Backend-only. API accepts `audiobookRootFolderId` but no UI field sets it. PR #439 already exposes audiobookDir as a read-only UI surface — there is established precedent for "backend-only with UI follow-up."

**Trajectory:** convergent (partial). The issue-as-written asks for the capability; the API surface satisfies the request via REST. UI wiring is a defensible follow-up, not a blocker, given:
- Issue is `enhancement` (not `bug`), so scope is "make it possible," not "make it discoverable."
- Maintainer's standing strategy (per CONTRIBUTING.md, prior triage): narrow diffs > broad ones.
- @j-tt is the original reporter and chose backend-only — the user with the pain point validated this shape.

**Abduction (70%)** that backend-only ships cleanly; **abduction (40%)** that maintainer requests UI in review. Either outcome is fine — UI add is a small follow-up if asked.

---

## Graph state

| Node | Status      | Mode      | Confidence |
|------|-------------|-----------|------------|
| H₀   | Confirmed   | Deduction | 99%        |
| H₁   | Confirmed   | Induction | 95%        |
| H₂   | Confirmed (fix: renumber 038→040) | Deduction | 99% |
| H₃   | Confirmed (slot open) | Deduction | 99% |
| H₄   | Open observation (backend-only is defensible; UI may be requested in review) | Abduction | 70% |

**Frontier:** closed for action. Only H₄ remains as a review-time observation, not a perturbation worth running pre-ship.

## Provenance

- `git blame internal/importer/scanner.go:755-762` — comment introduced by #439 (merged 2026-05-03), which intentionally split ebook routing from audiobook routing and left this gap with a forward reference to a future "per-author audiobook root folder field."
- Upstream issue search: only #579 names this gap; the related #421 (resolved by #439) explicitly avoids touching audiobook routing.
- Adjacent contributor activity: @j-tt is a returning reporter (also filed #580, which is being shipped by @magrhino in PR #670). On #579, j-tt provided the patch but did not open a PR — the maintainer filed #579 specifically to invite a PR from the patch.
- Sibling investigation: [vavallee__bindery__580.md](./vavallee__bindery__580.md) — same class (j-tt external patch), but killed at H₂ by a competing broader PR. #579 has no such competition.

## Decision

**Ship.** Phase 8 (human gate). The j-tt patch with a one-file migration renumber (038→040) is a clean, tested PR.

### Readiness record

- **Branch:** `feat/579-per-author-audiobook-root` (off `main` at HEAD ~94a5103-equiv).
- **Diff:** +147 / −37 across 5 Go files + 1 new migration (`040_author_audiobook_root_folder.sql`).
- **Tests:** `go test ./internal/importer/ ./internal/api/ ./internal/db/ -count=1` → all pass. New test `TestEffectiveAudiobookDir_*` fails on `main`, passes with patch.
- **Build:** `go build ./...` clean.
- **PR title:** `feat(importer): add per-author audiobook root folder (#579)`
- **PR body (draft):**
  > Closes #579. Adds `audiobook_root_folder_id` to `authors` and `AudiobookRootFolderID *int64` to `models.Author`. New `Scanner.effectiveAudiobookDir()` resolves the per-author folder when set, falling back to `BINDERY_AUDIOBOOK_DIR`. `effectiveLibraryDir()` (ebook path) is unchanged, preserving #421's separation. Create/Update API accept `audiobookRootFolderId`.
  >
  > Migration renumbered from j-tt's fork (038 → 040) to slot after `039_orphan_author_reassign.sql`.
  >
  > Tests: `internal/importer/scanner_rootfolder_test.go` covers fall-back and override.
  >
  > Credit: patch by @j-tt ([3ea2bcb](https://github.com/j-tt/bindery/commit/3ea2bcb)); I renumbered the migration and verified against current `main`. Frontend wiring to *set* the field is intentionally deferred — #439's audiobookDir surface is the natural UI follow-up.

## Pruning log

- "Open competing PR with broader N-folder shape" — killed: scope inflation, maintainer asked for exactly this. (Contrast with #580 / #670 where N-library was the right generalization because ABS itself supports N libraries; per-author folders are already 1:1 with authors.)
- "Add frontend in same PR" — deferred (H₄). Backend-only matches j-tt's chosen shape and maintainer's narrow-diff preference; UI is a follow-up if review asks.
- "Wait for j-tt to open the PR" — killed by H₃: j-tt filed via maintainer's BUGS.md ingestion rather than directly, and the maintainer explicitly filed #579 to invite a contributor PR.
