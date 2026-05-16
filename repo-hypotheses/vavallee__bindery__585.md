# vavallee/bindery#585 — Goodreads CSV one-shot import

**Issue:** [#585](https://github.com/vavallee/bindery/issues/585) — feature request, labeled `enhancement`, opened by maintainer @vavallee.
**Started:** 2026-05-16
**Class:** Feature implementation, not bug diagnosis. Investigation here is *scope verification* — does the maintainer's "small bindery-side scope" claim hold against the actual codebase?
**Prior status:** Denylisted in 2026-05-11 triage as "Large features / design decisions required." Re-opening at user request.

## H₀ — Maintainer's scope claim

> "the bindery-side scope is small: a file-upload form, a CSV parser, and reuse of existing `ResolveBookByISBN` + add-book machinery. No new metadata provider, no new sync loop, no new auth dance."

**Perturbation:** read the codebase to map each claimed building block to actual code, count missing pieces.

**Trajectory:** convergent with refinement. Most building blocks exist; one significant piece (frontend UI) is entirely absent. Reasoning mode: **deduction** (95%).

### Building blocks found (provenance)

| Claim | Location | Status |
|---|---|---|
| `ResolveBookByISBN` exists | `internal/metadata/aggregator.go:256` | ✅ Confirmed |
| Multipart upload + temp spool + Content-Type allowlist | `internal/api/migrate.go:18-50` (`allowedUploadCT`, `uploadTempDir`, `acceptUpload`) | ✅ Confirmed — directly reusable |
| Migrate handler scaffolding | `internal/api/migrate.go:52-88` (`MigrateHandler`, `NewMigrateHandler`) | ✅ Confirmed — Goodreads is a sibling endpoint |
| Existing CSV importer | `internal/migrate/csv.go` (204 LOC, `ImportCSVAuthors`) | ⚠️ Author-list shape, not book-row shape — pattern reusable, code not |
| Async-with-status pattern | `internal/migrate/readarr_importer.go:1-136`, `ImportReadarrStatus` endpoint | ✅ Available if Goodreads imports run long (likely — N books × ISBN resolution) |
| Routes wired | `cmd/bindery/main.go:824-827` (`/migrate/csv`, `/migrate/readarr`, `/migrate/readarr/status`) | ✅ Pattern is clear — add `/migrate/goodreads` |
| Add-book flow | `internal/api/authors.go:1158` (`AuthorHandler.AddBook`) — find-or-create author, then create book | ✅ The flow exists but is HTTP-shaped; needs a non-HTTP helper or internal call |
| Frontend Settings → Import UI | grep `migrate` in `web/src/`: zero hits | ❌ **No frontend wiring exists for the *existing* CSV/Readarr migrate endpoints either** |

## H₁ — Frontend cost is hidden in the issue body

**Hypothesis:** the issue undercounts frontend work because the existing migrate endpoints have no UI either. Adding Goodreads import means either (a) building the first migrate UI from scratch, which serves all three importers, or (b) building a Goodreads-only UI that prefigures the others.

**Perturbation:** `grep -r migrate web/src/` — single unrelated hit (`AliasesMigrated` in `client.ts:523`).

**Trajectory:** divergent. Frontend work is real and non-trivial: file upload, dry-run preview, results page, failed-row download. The issue mentions all of these. They don't exist anywhere in the codebase. Reasoning mode: **deduction** (95%).

**Kill condition:** if a draft Settings → Import page exists in an open PR, this collapses. Checked open PRs (`gh pr list --search "import"`) — none. Triage doc lists 3 open PRs, none on this surface.

**Edge:** the scope estimate in the issue body is backend-only. Realistic estimate splits roughly 50/50 backend/frontend.

## H₂ — Book-add path needs adaptation

**Hypothesis:** the issue's "reuse add-book machinery" handwaves over a real gap. `AuthorHandler.AddBook` is HTTP-shaped (decodes JSON request, writes JSON response). A bulk importer needs a non-HTTP helper, or it has to fake-loop through `httptest`-like calls.

**Perturbation:** read `authors.go:1158-1250` to identify the reusable core vs HTTP boilerplate.

**Trajectory:** convergent — the core flow (find-or-create author → fetch metadata → create book) is ~50 lines and can be extracted to a `migrate.AddBookByForeignID(ctx, ...)` helper that both `AuthorHandler.AddBook` and the new Goodreads importer call. Reasoning mode: **abduction** (70%) — I have not read the full handler body, just the prelude.

**Edge:** before implementation, this refactor either (a) ships as a prep PR, or (b) lands in the same PR but inflates the diff. Either way it adds non-trivial scope the issue doesn't budget for.

## H₃ — Resolution fallback complexity

**Hypothesis:** the issue says "on ISBN miss, fall back to a title+author search via the primary provider." Goodreads exports routinely contain books with no ISBN (e-only editions, pre-ISBN works). Title+author search is fuzzier than ISBN lookup — match quality varies by provider, and incorrect matches are silently destructive (wrong book gets added).

**Perturbation:** check what title+author search the aggregator currently exposes, and whether it's already wired for the "user picks the right one" UI flow.

**Trajectory:** unrun. Open frontier edge. Predicted classification: **oscillatory** — title search works fine for popular books and badly for obscure ones, which is exactly the long-tail population a Goodreads export contains.

**Kill condition for the simple version:** if dry-run preview surfaces ambiguous matches for user resolution, the "silent destructive match" risk is contained. The issue does mention a dry-run, so this is probably fine — but it shifts work into the frontend.

## H₄ — "Exclusive Shelf" semantics

The issue's step 6 says: `read` → mark as imported/owned without grabbing; `to-read` → add to monitored; `currently-reading` → user choice.

The "imported/owned without grabbing" state doesn't obviously map to bindery's existing book-monitored flag (bindery is a *download* manager — the natural states are *want* and *have*, where *have* is satisfied by an import scanner finding the file on disk). Marking a `read` Goodreads book as "have" without an actual file present creates a phantom-owned record.

**Trajectory:** unrun. Open frontier edge. This is a maintainer design call, not a code change to validate.

## Graph state

| Node | Status | Trajectory | Reasoning |
|---|---|---|---|
| H₀ scope claim | partial | convergent | backend ≈ small, frontend missing |
| H₁ frontend cost hidden | confirmed | divergent | deduction (95%) |
| H₂ book-add reuse | confirmed-with-refactor | convergent | abduction (70%) — needs full read |
| H₃ resolution fallback | open | predicted oscillatory | — |
| H₄ exclusive shelf semantics | open | requires maintainer input | — |

## Frontier edges

1. **Read full `AuthorHandler.AddBook` body** to confirm the reusable core is extractable (kills/confirms H₂).
2. **Maintainer dialogue** on H₄ — what does "owned without grabbing" mean in bindery's data model? This is a design question that can't be answered from code alone.
3. **Frontend pattern** — is there a planned migrate UI in any spec/doc? (Check `docs/` and `AGENTS.md`.)

## Recommendation — do not ship a PR

**Why halt at diagnosis** (this is the Phase 4.5 reframe path):

1. **This is a feature, not a bug.** The investigate skill's strength is perturbing engineered systems to find what's broken. A greenfield feature has no kill conditions to follow — the "edges" are design decisions, not measurements.
2. **Maintainer hasn't blessed implementation.** The issue is the maintainer's own proposal but is labeled `enhancement`, not `help wanted`. Shipping a 500+ LOC PR (backend importer + frontend page + tests) unsolicited is exactly the [non-renewable-attention](https://june.kim/blind-blind-merge) failure mode.
3. **Open design questions (H₄) need maintainer input** before any code is written. The "exclusive shelf" → bindery-state mapping is not derivable from the codebase.
4. **Prior triage decision was correct** — this *is* a large feature, and the new evidence (frontend UI is entirely missing for the whole migrate subsystem, not just Goodreads) confirms that.

**Actionable output:** if the operator wants to engage on this issue, the smallest defensible move is a comment on #585 asking the maintainer:
- Is the bundled scope (backend importer + first-ever migrate UI) the right unit, or should the UI ship separately covering existing Readarr+CSV importers first?
- For H₄, what's the intended semantics of importing a `read` book? Phantom-owned, monitored-then-archived, or skip?

That's a reviewer-attention-cheap probe. Shipping code now is the wrong move.

## Pruning log

- **Direct "implement and PR" path** — killed by the absence of a frontend migrate UI for *any* importer. Building one for Goodreads alone prefigures architectural decisions for the others; that should be a maintainer call, not a contributor fait accompli.
- **"Backend-only PR (just the importer + endpoint)"** — viable but low-value. Without a UI, no user can reach it. Maintainer would have to either build the UI themselves or hold the PR open indefinitely.
