# vavallee/bindery#665 — tier-1 t=book falls through on canned feeds

**Status:** Diagnosed (issue author supplied root cause + fix shape). Building prework.
**Date:** 2026-05-16

## H₀ — observation

Some Torznab indexers (Jackett→AudioBookBay observed) advertise `book-search=yes` but ignore `title`/`author` params on `t=book`, returning a fixed 18-item category feed regardless of query.

Bindery treats any tier-1 response with `len(items)>0 && Total<1000` as a match (`client.go:141`), so the canned feed wins and tiers 2/3/4 never run. Every specific-book search returns the same 18 audiobooks.

**Reasoning mode:** deduction. Confirmed by reading `BookSearch` at `internal/indexer/newznab/client.go:125-170`. **Confidence:** 98%.

## H₁ — fix shape (from issue author)

After tier-1 parsing, check whether any result title contains *all* significant words from the query title (length ≥ 4, common stopwords excluded). If none match, treat the feed as canned and fall through to tiers 2/3/4.

**Perturbation:** add a `titleHasRelevantResult(query, results)` guard between `len(items)>0` and the early return.

**Predicted trajectory:** divergent improvement — canned feeds always fail the guard (their titles don't contain the queried book's name), and genuine tier-1 hits always pass it (the indexer returned them because the title matched).

**Reasoning mode:** abduction. **Confidence:** 80% pre-implementation.

## Provenance check

- `client.go:141` introduced in early indexer work; the `Total<1000` guard appears to be defending against unfiltered "browse all" responses but does not catch canned per-category feeds. The threshold is well below 18, so canned feeds slip through.
- No upstream Jackett fix — AudioBookBay's Torznab `t=book` endpoint is documented as wired to a category browse, not a parameterised search. The fix has to live in the client.
- Issue author offered to PR but the maintainer typically accepts well-scoped community fixes (#622, #592 merged from external contributors).

## Frontier edges (after Phase 1)

- **E₁:** is "significant words ≥4 chars" the right cutoff? Edge case: `1Q84` (no ≥4 ascii word), `It` (Stephen King), `Us`. Plan: when no significant words remain, *accept* tier-1 (can't filter, default to existing behavior). This regresses canned-feed detection for short titles but preserves correctness for legitimate ones.
- **E₂:** match against `r.Title` (release name) or `r.BookTitle` (newznab attr)? Release names often have "by Author Name.epub" appended — should still contain the title. BookTitle attr may be empty. Plan: concatenate both, lowercase, substring match.
- **E₃:** stopword list scope. "with", "from", "this", "that", "your", "into" are ≥4 chars and would dilute the match. Need a small allowlist of stopwords to skip. Plan: hardcode ~15 common English book-title connectives.

## Graph state

| H | Status | Trajectory | Mode | Conf |
|---|--------|------------|------|------|
| H₀ canned feed bypasses guard | Confirmed | divergent | deduction | 98% |
| H₁ relevance check fixes it | Pending bench | predicted divergent | abduction | 80% |

## Implementation

Branch `fix/665-tier1-canned-feed-fallthrough` in /tmp/bindery-665.

- `internal/indexer/newznab/client.go`: added `significantTitleWords` + `titleHasRelevantResult` helpers; wrapped tier-1 acceptance with the guard. Unicode-aware (uses `unicode.IsLetter`/`IsDigit` and `utf8.RuneCountInString` so accented titles like "Café" survive edge-trimming and the 4-char rune cutoff).
- `internal/indexer/newznab/client_test.go`: 4 new tests
  - `TestBookSearch_FallsThroughCannedTier1Feed` — canned 18-item Hobbit/1984/Dune feed must trigger fall-through when user queries "Life Ascending" by Nick Lane. Verified to FAIL on master and PASS with fix.
  - `TestBookSearch_Tier1AcceptedWhenTitleMatches` — legitimate tier-1 hit must short-circuit (no extra calls).
  - `TestBookSearch_Tier1AcceptedWhenQueryHasNoSignificantWords` — preserves prior behavior for short titles like "It".
  - `TestSignificantTitleWords` + `TestTitleHasRelevantResult` — helper coverage including unicode case.

## Phase 7 review

Codex unavailable (quota). Gemini 3.1 Pro raised:
- ✅ Unicode trim destruction (e.g. `café` → `caf` under ASCII-only TrimFunc) — **fixed** with `unicode.IsLetter`/`unicode.IsDigit` + `utf8.RuneCountInString`.
- ⚠️ Short-title bypass (titles with no ≥4-char content words accept tier-1) — **documented tradeoff**; matches issue author's proposal. Could fall back to author-surname check but adds complexity for the rare case where AudioBookBay's popular-audiobook feed happens to share an author with the query.
- ⚠️ Diacritic normalization mismatch (`Pokémon` query vs `Pokemon` release) — pre-existing across the codebase; the issue is bigger than this PR's scope.
- ⚠️ 4-char cutoff drops "War", "Art", "God" — defensible: 3-char substring matching produces too many false positives ("Art" in "Article", "Smart", "Heart"). Keeping.

## Graph state (final)

| H | Status | Trajectory | Mode | Conf |
|---|--------|------------|------|------|
| H₀ canned feed bypasses tier-1 guard | Confirmed | divergent | deduction | 98% |
| H₁ title-relevance guard fixes it | Confirmed | divergent | induction (test) | 95% |
| H₂ ASCII-only trim breaks accented titles | Confirmed → fixed | divergent | abduction→deduction | 95% |
| H₃ author-surname fallback for short titles | Open (deferred) | predicted convergent | abduction | 60% |

## Phase 8 (ship) — awaiting human gate

Diff: ~70 lines impl + 200 lines tests, single package. Ready to PR to vavallee/bindery from kimjune01's fork. PR title: `fix(newznab): fall through tier-1 t=book when indexer returns canned category feed (#665)`.
