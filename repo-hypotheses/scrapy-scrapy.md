# TRIAGE_GRAPH — scrapy/scrapy

## MAINTAINER PREFERENCES

- Target branch: `master`
- Tests required with all bug fixes and features
- Prefer end-to-end tests with minimum mocking
- Use Twisted test framework; module names mirror tested modules (e.g. `tests/test_loader.py` for `scrapy.loader`)
- Pre-commit via Ruff; run `tox -e pre-commit`
- PR titles: short but descriptive, include issue references via "Resolves #N"
- One patch per change; keep aesthetic changes in separate commits
- No CLA required
- No anti-AI policy detected
- wRAR and Gallaecio are active maintainers; wRAR is strict on quality ("Very low quality." = instant close)
- CONTRIBUTING.md references https://docs.scrapy.org/en/master/contributing.html

## TRIAGED

### #6574 — Empty URL path with query params causes 400 errors
- Branch: `fix/6574-empty-url-path`
- Status: triaged
- SHA: e03591242e44e180bb3f35f8703368da95826073
- Fix: Normalize empty URL path to `/` in `Request._set_url()` when query or fragment is present
- Tests: 4 new tests in `tests/test_http_request.py`, all 62 tests pass
- Risk: Low. Matches browser behavior and RFC 7230 5.3.1
- Competing PRs: PR #3494 (open, 7 years stale, different approach using canonicalize_url — rejected by maintainer)

### #1163 — FormRequest silently falls back to first form when formname/formid doesn't match
- Branch: `fix/1163-formrequest-formname`
- Status: triaged
- SHA: 941d25615ea25b301f87314a277a8a4f186ac875
- Fix: Raise `ValueError` in `_get_form()` when formname/formid not found, consistent with formxpath behavior
- Tests: Updated 5 existing tests to expect ValueError instead of silent fallback; all 119 form request tests pass
- Risk: Medium. Labeled `backward-incompatible` by maintainer (kmike). Existing code that relies on silent fallback will break.
- Competing PRs: PR #7438 (closed, "Very low quality")

### #1362 — LogCounterHandler counts logs from all crawlers in multi-crawler process
- Branch: `fix/1362-logcounterhandler`
- Status: triaged
- SHA: 02a19d29fda10188f608ae7d5bc421ac51307335
- Fix: Check `record.spider.crawler` in `emit()` before counting; allow records without spider extra
- Tests: 3 new tests in `tests/test_utils_log.py`, all 27 tests pass
- Risk: Low. Scrapy consistently sets `extra={"spider": spider}` on internal logs.
- Competing PRs: None

## INVESTIGATED BUT NOT ATTEMPTED

### #6293 — SitemapSpider ignores sitemap URLs with query params
- Status: KILLED
- Reason: Maintainer (Gallaecio) could not reproduce. Broader fix in progress (PR #5204). 3 competing PRs all closed.

### #6425 — FeedExporter exception with Path objects
- Status: KILLED
- Reason: Fix is docs-only. Competing PR #6611 is open with maintainer approval, needs minor revision.

### #1900 — RetryMiddleware doesn't retry HttpCompressionMiddleware errors
- Status: KILLED
- Reason: Architecture limitation. `process_exception` only catches download-phase errors, not `process_response` errors. Fix requires either middleware manager changes or rethinking error flow. Too risky for first contribution.

### #7260 — scrapy genspider --edit doesn't work
- Status: KILLED
- Reason: Saturated. Open PR #7340 plus 7 closed competing PRs.

### #4330 — Scrapy fails to crawl emoji domains
- Status: KILLED
- Reason: Upstream issue (idna library). Labeled `upstream issue`. Complex, security implications.
