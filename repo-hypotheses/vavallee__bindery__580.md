# vavallee/bindery#580 — ABS dual library support

**Issue:** [#580](https://github.com/vavallee/bindery/issues/580) — labeled `enhancement`, opened by maintainer @vavallee 2026-05-11, filed from @j-tt's BUGS.md.
**Started:** 2026-05-16
**Class:** Feature with external patch available; investigation is *patch-validation + idempotency check*.
**Prior status:** Denylisted in the 2026-05-11 vavallee/bindery triage under "External patches available — #580 ABS dual library support — @j-tt has working patch (702b738)." Re-investigated at user request.

## Halt — superseded by existing PR

**[#670 (open)](https://github.com/vavallee/bindery/pull/670)** by @magrhino, opened 2026-05-16T00:02:43Z, closes #580. Title: "feat(abs): support selecting multiple libraries." Scope: N-library `libraryIds` (not just dual), keeps `abs.library_id` for compat, sequential per-library runs, frontend multi-select, docs, changelog. +1103 / −239 across 18 files. Codecov: 84.4% patch coverage; no maintainer review yet.

PR #670 generalizes the same surviving hypothesis the j-tt patch resolves. Per the investigate halt rule (existing PR addresses surviving hypothesis), this investigation halts and contributes evidence rather than competing.

---

## H₀ — Bug exists in current `main`

**Perturbation:** clone `vavallee/bindery@main`, grep settings keys.

```
grep "SettingABS" internal/api/abs.go
  SettingABSBaseURL   = "abs.base_url"
  SettingABSAPIKey    = "abs.api_key"
  SettingABSLibraryID = "abs.library_id"     ← single
  SettingABSEnabled   = "abs.enabled"
  SettingABSLabel     = "abs.label"
  SettingABSPathRemap = "abs.path_remap"
```

`AudiobooksLibraryID` / `audiobooks_library_id` / `libraryIds`: zero hits on `main`.

**Trajectory:** divergent confirm. The bug is real on `main`; importer enumerates only one library. **Deduction (99%).**

## H₁ — j-tt patch applies cleanly and tests pass

**Perturbation:** fetch `https://github.com/j-tt/bindery/commit/702b738.patch`, `git apply --exclude=BUGS.md` (BUGS.md exists only in j-tt's fork).

```
git apply --check --exclude=BUGS.md  → clean
go build ./...                       → ok
go test ./internal/abs/ ./internal/api/ -count=1
  ok  github.com/vavallee/bindery/internal/abs   2.228s
  ok  github.com/vavallee/bindery/internal/api   5.346s
```

The new test `TestImporter_RunEnumeratesBothLibraries_WhenAudiobooksLibraryIDSet` passes; it would fail on `main` (no `AudiobooksLibraryID` field).

**Trajectory:** convergent. Patch is mergeable, behavior is correct, both libraries enumerated, separate `abs_import_runs` records. **Induction (95%).**

## H₂ — Idempotency check: is anyone already shipping this?

**Perturbation:** `gh pr list --repo vavallee/bindery --search "ABS audiobooks library" --state all`.

```
670  feat(abs): support selecting multiple libraries  magrhino  OPEN  2026-05-16
371  ABS Import Feature Request                       magrhino  MERGED 2026-04-23
```

**#670 body:** "Closes #580 ... letting one Audiobookshelf source import from multiple selected book libraries ... preserves the legacy `abs.library_id` compatibility field while adding ordered `libraryIds` config, sequential per-library import runs, and UI/docs coverage."

**Trajectory:** divergent against duplicating the j-tt patch. A more general fix (N libraries, not 2) is already open and includes the missing frontend wiring that the j-tt patch lacks. **Deduction (99%).**

**Kill condition for "ship j-tt patch as PR":** an open PR by another contributor closing the same issue with broader scope and frontend coverage. Killed.

## H₃ — Where j-tt and magrhino diverge (research value)

| Dimension                | j-tt 702b738 (2 libraries)                 | #670 (N libraries)                                            |
|---|---|---|
| Config shape             | adds `abs.audiobooks_library_id`           | adds ordered `libraryIds` array, mirrors first to `library_id` |
| Run records              | 1 secondary run record per import          | one run per selected library                                  |
| Frontend                 | none — backend + API only                  | replaces dropdown with multi-select                           |
| Docs                     | BUGS.md only                               | `docs/ABS-Import-Wiki.md` + `CHANGELOG.md`                    |
| Diff size                | +251 / −69 (8 files)                       | +1103 / −239 (18 files)                                       |
| Generality               | 2 libraries (books + audiobooks)           | N libraries                                                   |
| Backward compat          | new field is optional, default empty       | `library_id` kept as mirror of first selected                 |

**Insight:** the j-tt fix is the minimal patch for the exact issue-as-written; #670 is what the maintainer asked for once the right abstraction was visible. The issue body asks for "two separate libraries," but the underlying ABS data model is N libraries — magrhino's framing is the better one. **Abduction (75%)** that maintainer will prefer #670; the issue label `enhancement` (not `bug`) and the breadth of magrhino's scope (UI + docs + changelog) suggest they're building for review-readiness, not minimum patch.

---

## Graph state

| Node | Status      | Mode      | Confidence |
|------|-------------|-----------|------------|
| H₀   | Confirmed   | Deduction | 99%        |
| H₁   | Confirmed   | Induction | 95%        |
| H₂   | Confirmed (kill on "ship j-tt patch") | Deduction | 99% |
| H₃   | Open (observation only — not a frontier edge) | Abduction | 75% |

**Frontier:** closed for action. Open only as observation: which framing the maintainer prefers will become visible from review on #670.

## Decision

**Do not ship.** PR #670 supersedes. Three useful downstream actions, in order of value:

1. **No-op locally.** Remove #580 from any drip / triage queue; the issue is being addressed.
2. **Optional comment on #670** noting the j-tt 702b738 patch as prior art with a narrower 2-library framing, if the maintainer asks for alternatives. The j-tt patch's separate-run-record-per-library behavior is one design choice worth surfacing if review on #670 questions the run-record shape.
3. **No comment on #580.** Linking #670 is redundant — `Closes #580` in the PR body already does it.

## Provenance

- `git blame internal/api/abs.go` — `SettingABSLibraryID` predates this issue; the single-library shape is an inherited default, not a deliberate "audiobooks excluded" choice.
- Upstream issue search: only #580 mentions dual-library; no closed PRs on this surface before #670.
- Adjacent contributor activity: @j-tt forked, fixed in BUGS.md style, filed via @vavallee. @magrhino is a returning contributor (PR #371 merged 2026-04-23, the original ABS import feature). #670 is a follow-up to their own work, which is the strongest possible review prior.

## Pruning log

- "Ship j-tt patch as a PR from kimjune01" — killed by H₂ (idempotency, #670 exists and is more general).
- "Add ABS frontend multi-select on top of j-tt backend" — killed by H₂ (would conflict with #670's frontend changes; rebasing would lose to whichever lands first).
- "Comment on #580 linking the patch" — killed (redundant; #670 closes the issue).
