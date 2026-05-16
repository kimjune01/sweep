# vavallee/bindery Triage Graph

**Repo:** vavallee/bindery (243★, Go + React)  
**Description:** Automated book download manager for Usenet/Torrents — Readarr replacement  
**Maintainer:** @vavallee (solo maintainer)  
**Activity:** Active — 10 PRs merged in past week  
**Triage date:** 2026-05-11

## Repo Status

- **Total open issues:** 24
- **Open PRs:** 3 (including #533 agent skills doc, #515 ISBN provider, #485 MSW auth tests)
- **Contribution guidelines:** CONTRIBUTING.md present — Go 1.25+, Node 22+, prefers narrow diffs
- **Standing strategy:** Bug fixes > features. Modular changes > architectural rewrites.

## Denylist

Issues excluded from this triage run:

### User-environment debugging required
- **#531** — NZBGet rejects downloads (id 0) — Prowlarr proxy + NZBGet interaction, needs user env access
- **#560** — Proxy auth mode reports unauthenticated — Authentik header forwarding, needs specific reverse-proxy setup
- **#562** — Hardcover GraphQL field error — needs Hardcover API investigation, external dependency

### Large features / design decisions required
- **#532** — Import from directory of books — full directory scanner + approval UI, not smallest
- **#534** — Indexer/protocol priority — requires design choice between soft/hard cascade
- **#585** — Goodreads CSV import — new upload form + parser + resolver, migration aid scope

### Explicitly deferred by maintainer
- **#537** — Blackhole download mode — "won't do unless demand", placeholder issue
- **#547** — Decompose SettingsPage.tsx (4722 lines) — "too risky", needs multi-PR initiative
- **#548** — DB books.go subquery → JOIN — "careful migration", needs benchmarking
- **#549** — DB history.go SELECT * → explicit columns — "focused PR with regression test"
- **#550** — recommendations.go context.Background → request ctx — "audit all goroutines"
- **#551** — WantedPage optimistic update rollback — "needs UX design"
- **#553** — Harden telemetry-server Dockerfile — distroless migration, "deliberate PR with runbook"
- **#554** — Frontend useCallback/useMemo — "unmeasured", "cargo-cult optimization"

### Documentation only
- **#552** — Document PodSecurityStandards — chart README update, no code

### External patches available
- **#579** — Per-author audiobook root folder — @j-tt has working patch (3ea2bcb)
- **#580** — ABS dual library support — @j-tt has working patch (702b738)

## Candidates (Top 5)

Selected for smallest scope, clear acceptance criteria, and standing-building potential:

### 1. #544 — Library scan UI never auto-refreshes
**Priority:** High  
**Type:** Bug (UX)  
**Scope:** Frontend polling pattern  
**Estimate:** 1-2 hours

**Why this is good:**
- User-visible bug with clear repro
- Fix is mechanical: poll `api.libraryScanStatus()` after trigger, update banner when `ran_at` advances
- Pattern exists elsewhere (queue polling), just needs application
- No backend changes, no schema changes
- Maintainer already spec'd the fix in issue body

**Acceptance criteria:**
- After "Scan Library" click, banner updates from "Scanning..." → "X files, Y reconciled, Z unmatched" without F5
- Polling cancels on navigation
- Works on large libraries (no aggressive timeout)

**Files:**
- `web/src/pages/SettingsPage.tsx` (line 2388 — mount-time fetch, needs polling loop)

---

### 2. #543 — Surface timestamps in Queue
**Priority:** Medium  
**Type:** Enhancement (UX)  
**Scope:** Pipe existing backend data to frontend  
**Estimate:** 2-3 hours

**Why this is good:**
- Data already exists server-side (`AddedAt`, `GrabbedAt`, `CompletedAt`, `ImportedAt`)
- Just add TS interface fields + render logic
- Maintainer spec'd exact approach in issue
- Standalone change, no dependencies

**Acceptance criteria:**
- Queue rows show contextual timestamp ("grabbed 18 min ago" / "completed 5 min ago")
- Hover tooltip shows absolute UTC
- Mobile layout doesn't overflow

**Files:**
- `web/src/api/client.ts` (~line 917 — `Download` interface)
- `web/src/pages/QueuePage.tsx` — render logic

---

### 3. #535 — Library scan: surface unmatched files in UI
**Priority:** Medium  
**Type:** Enhancement  
**Scope:** Persist unmatched scan results, new UI panel  
**Estimate:** 4-6 hours

**Why this is good:**
- User with 732 unmatched files has no visibility (Discord report)
- Maintainer suggests two shapes (table vs JSON blob extension) — we can start with cheaper JSON approach
- Clear data flow: scanner already emits debug logs with paths, just persist them

**Acceptance criteria:**
- After scan, UI shows list of unmatched files with parsed title/author
- Bounded to last N (1000) entries to avoid schema change
- Users can see what the parser guessed for each file

**Files:**
- `internal/importer/scanner.go` (lines 1078-1244 — scan loop, `writeScanResult`)
- `internal/api/library.go` (lines 42-56 — `ScanStatus` API)
- `web/src/pages/SettingsPage.tsx` — UI panel

---

### 4. #427 — Frontend component test coverage
**Priority:** Medium  
**Type:** Enhancement (testing)  
**Scope:** Add component tests using existing Vitest setup  
**Estimate:** 3-5 hours per component

**Why this is good:**
- Infrastructure already in place (Vitest, Testing Library)
- PR #411 added `AuthorDetailPage.test.tsx` as template
- Maintainer explicitly labeled "good first issue" for BookDetailPage, WantedPage, HistoryPage
- Modular — can do one component per PR
- Builds trust via quality contribution

**Acceptance criteria (BookDetailPage example):**
- Grab button state transitions tested
- Search result rendering tested
- Error boundary coverage

**Files:**
- `web/src/pages/BookDetailPage.test.tsx` (new)
- Ref template: `web/src/pages/AuthorDetailPage.test.tsx` (PR #411)

---

### 5. #559 — Add graceful shutdown to main.go
**Priority:** Medium  
**Type:** Bug (data integrity)  
**Scope:** Signal handling for SIGTERM  
**Estimate:** 2-4 hours

**Why this is good:**
- Real data-integrity issue (SQLite WAL not checkpointed, buffered logs lost on SIGTERM)
- Standard Go pattern (signal.NotifyContext)
- Clear test path (k8s pod stop, docker stop)
- Related to #558 (LogHandler.Stop defer)

**Acceptance criteria:**
- On SIGTERM, defers fire (database.Close, sched.Stop, logDBHandler.Stop)
- Graceful shutdown within k8s `terminationGracePeriodSeconds`
- In-flight HTTP requests complete or timeout cleanly

**Files:**
- `cmd/bindery/main.go` — add signal.NotifyContext, wire srv.Shutdown(ctx)

---

## Hypothesis Alignment

- **H0 (cold-start penalty):** Attempt standing-building via #544 or #543 (small, clear wins)
- **H1 (test-first acceptable):** #427 fits this — component tests ARE the contribution
- **H2 (maintainer capacity):** Solo maintainer, merges 10 PRs/week — bandwidth exists, prefers narrow diffs
- **H3 (competing PRs):** No competing PRs for selected issues
- **H4 (AI-friendly repos flood):** No evidence of AI PR spam, clean contribution history
- **H5 (complexity aversion):** Skip #547 (SettingsPage decomp), #548-550 (DB refactors) per maintainer's own "deferred" notes

## Next Steps

1. Implement #544 (library scan polling) — smallest, highest user impact
2. If #544 merges → try #543 (queue timestamps)
3. If standing established → attempt #535 (unmatched files) or #427 (component tests)
4. Monitor #579/#580 — if @j-tt doesn't submit PRs, offer to port patches (with credit)
5. Avoid #531, #560, #562 — user-env debugging not feasible remotely

---

## Session Outcomes (2026-05-11)

### Completed

1. **#543 — Queue timestamps** ✅  
   - Branch: `feat/543-queue-timestamps` (commit 48e7051)
   - Status: Queued for drip
   - Changes: Added `addedAt`, `grabbedAt`, `completedAt`, `importedAt` to Download TS interface + contextual timestamp display with relative time + UTC tooltip
   - Files: `web/src/api/client.ts`, `web/src/pages/QueuePage.tsx`
   - Build: ✅ typecheck passes, lint clean

2. **#535 — Unmatched files UI** ✅  
   - Branch: `feat/535-unmatched-files-ui` (commit ecf5d05)
   - Status: Queued for drip
   - Changes: Backend collects up to 1000 unmatched file entries (path/title/author), extends scan result JSON, frontend renders collapsible table in Settings
   - Files: `internal/importer/scanner.go`, `web/src/api/client.ts`, `web/src/pages/SettingsPage.tsx`
   - Build: ✅ Go build passes, typecheck passes, lint clean

### Discovered

- **#544 — Already fixed!** Polling code already merged to main (commit 5167328, 2026-05-09). Issue was filed in morning, maintainer fixed it same day.

### Skipped

- **#427 — Component tests:** Too complex for remaining token budget (requires understanding component structure, mocking, test patterns)
- **#559 — Graceful shutdown:** Deferred to future session (moderate complexity, backend-only)

---

**Session:** vavallee/bindery triage  
**Branch prefix:** `fix/` for bugs, `feat/` for enhancements, `test/` for #427  
**Quality gates:** Gemini volley + codex crosscheck before push  
**Completion:** 2/5 candidates implemented, 1 already fixed, 2 deferred
