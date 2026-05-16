# Triage Graph: pallets/quart

**Repository:** pallets/quart  
**Maintainer:** davidism (same as click, jinja)  
**Stars:** 3.6K  
**External merge rate:** 83% (highest in pallets org)  
**Triage date:** 2026-05-09  

---

## Priority Issue: #451

**Issue:** Incorrect typing using AnyStr  
**Reporter:** Brandieee (David)  
**Created:** 2025-11-21  
**Status:** IMPLEMENTED  

### Problem
`AnyStr` is deprecated in Python 3.13 and was being used incorrectly throughout the codebase. According to Python typing docs, `AnyStr` should only be used as a TypeVar constraint for generic functions, not for parameters accepting either `str` or `bytes`.

### Competing PR Analysis
- **PR #452:** Same author (Brandieee), opened 2025-11-21, **6 months stale**
- **No reviews, no comments**
- Changes: 8 files, +16/-23 (correct scope)
- Classic stale PR pattern

### Solution
Replaced all `AnyStr` usage with explicit `str | bytes` union type across:
- `src/quart/app.py` — `test_request_context` data parameter
- `src/quart/asgi.py` — `ASGIWebsocketConnection.send_data`
- `src/quart/signals.py` — Signal handler type comments
- `src/quart/typing.py` — Protocol method signatures
- `src/quart/testing/client.py` — Test client methods
- `src/quart/testing/connections.py` — Test websocket connection
- `src/quart/testing/utils.py` — `make_test_body_with_headers`
- `src/quart/wrappers/websocket.py` — Websocket receive/send

**Branch:** fix-anystr-typing  
**Commit:** a4c290a  
**Hypothesis:** H2 (stale PR investigation)  

---

## Other Issues Scanned

### #463: Easier API to limit upload size per route
- No competing PR
- Feature request, no comment traffic
- **Skipped:** Feature PRs don't merge at cold repos

### #461: Test break from Werkzeug 3.1.6 → 3.1.7
- `test_propagation` fails with SecurityError
- **Workaround exists:** Change `"server": None` to `("localhost", 80)` in test fixtures
- Comment suggests may self-resolve with Werkzeug 3.1.8
- **Skipped:** Upstream dependency issue, likely transient

### #451: AnyStr typing (SELECTED)
- See above

### #441: Development reloader terminal control issue (Windows)
- 1 comment, platform-specific edge case
- **Skipped:** Low impact, narrow scope

### #439: App appends `:5000` to socket file name
- **Competing PR #440:** Stale (July 2025, 10 months old)
- Socket file edge case
- **Skipped:** Niche issue, old stale PR

### #438: Middleware type errors with asgi_app
- `app.asgi_app = middleware(app.asgi_app)` produces mypy error
- **No competing PR**
- Core issue: `asgi_app` is a method, can't be assigned to
- **Skipped:** Requires architectural investigation, documentation may be wrong

### #426: Hypercorn environment variables not loading
- No competing PR, no comments
- Hypercorn-specific, not Quart
- **Skipped:** External dependency scope

### #425: Allow max_content_length per-request override
- No competing PR
- Feature request
- **Skipped:** Feature PRs at cold repos

### #423: Allow template_folder to be PathLike[str]
- **Competing PR #424:** Stale (March 2025, 1.5 months old)
- Flask compatibility feature
- +1/-1 changes, trivial
- **Skipped:** Existing PR, trivial change suggests low priority

### #419: Websockets RuntimeError: Not within request context
- No competing PR, no comments
- Error report without reproduction
- **Skipped:** Needs more information

### #408: App not closing correctly - Address in use
- No competing PR, no comments
- Resource cleanup issue
- **Skipped:** No clear reproduction

### #406: Hot reload broken with +x permissions
- **Competing PR #407:** Stale (Feb 2025, 3 months old)
- Linux-specific edge case
- Author proposed fix in issue comments
- **Skipped:** Existing PR, narrow impact

### #404: Blueprint type mismatch with Flask
- **Competing PR #405:** Stale (Feb 2025, 3 months old)
- mypy type error with `app.blueprints` returning Flask Blueprint type
- Author offered two solution approaches
- **Skipped:** Existing PR, complex typing issue

### #387: Add API to name background tasks
- No competing PR
- Feature request
- **Skipped:** Feature at cold repo

### #383: Exception propagation config not working
- **Competing PR #385:** Stale (Nov 2024, **18 months old**)
- Core config setting broken
- **Candidate for future investigation:** Very old stale PR, maintainer-acknowledged bug

---

## Maintainer Activity Pattern

Recent merges (last 10):
- PR #445: Merged Sep 2025, 0 reviews
- PR #444: Merged Aug 2025, 0 reviews
- PR #436: Merged Jun 2025, 0 reviews
- PR #433: Merged Jun 2025, 0 reviews
- PR #432: Merged Jul 2025, 0 reviews
- PR #398: Merged Dec 2024, 0 reviews
- PR #395: Merged Dec 2024, **1 review**
- PR #391: Merged Nov 2024, 0 reviews
- PR #386: Merged Nov 2024, **1 review**
- PR #381: Merged Nov 2024, 0 reviews

**Pattern:** davidism merges without review (self-merge or auto-merge). External PRs go stale even when correct. 83% external merge rate suggests he does eventually merge external work, but on unpredictable timelines.

**Strategy:** Submit clean, well-documented PRs. Don't expect review. Signal "this is ready" clearly. PR #452 likely stalled because it had no description beyond commit message.

---

## Hypothesis Coverage

- **H0 (documentation gap):** Not tested this cycle
- **H1 (maintainer-acknowledged bug):** #383, #461 candidates
- **H2 (stale PR investigation):** #451 ✓ (selected)
- **H3 (Flask parity):** #423 candidate
- **H4 (type safety):** #404, #438 candidates
- **H5 (test infrastructure):** #461 candidate
- **H6 (edge case handling):** #406, #439 candidates

---

## Next Steps

1. Push `fix-anystr-typing` to fork
2. Open PR with clear description linking to issue #451 and noting PR #452 staleness
3. Monitor merge timeline to calibrate davidism's response pattern
4. If merged: investigate #383 (18-month stale PR on config bug)
5. If stalled: pivot to #438 (asgi_app typing, no competing PR)
