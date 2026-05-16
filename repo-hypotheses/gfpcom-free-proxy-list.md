# Triage Graph: gfpcom/free-proxy-list

**Repo:** gfpcom/free-proxy-list (312 stars, Go proxy aggregation tool)
**Date:** 2026-05-11
**Open Issues:** 7
**Open PRs:** 1 (Dependabot)

## Issue Scoring

### ✅ Actionable

1. **#14** - "feat(parser): add clash config parser" (Score: 95/100)
   - **Status:** Implemented (branch: fix/clash-config-parser-14)
   - **Labels:** help wanted, good first issue, hacktoberfest
   - **Why:** Clear spec, documented format, no competition, fits existing architecture
   - **Implementation:** Added `FromClash` transformer that parses YAML and extracts proxy URLs
   - **Tests:** Full test coverage for http, socks, ss proxies
   - **Commits:** 2 (test first, then impl)

2. **#21** - "fix(sources): Add New Proxy Sources" (Score: 85/100)
   - **Status:** Implemented (branch: fix/add-proxy-sources-21)
   - **Labels:** help wanted, good first issue, hacktoberfest
   - **Why:** Trivial contribution, clear pattern, helps project
   - **Note:** JiwaniZakir commented "Working on it" on 2026-03-19, but no PR yet
   - **Implementation:** Added 3 new repos (ShiftyTR, clarketm, VPSLab) to http/https/socks4/socks5
   - **Commits:** 1

### ⏸️ Complex / Competing Interest

3. **#16** - "feat(transformer): support to expand lists from a remote url" (Score: 45/100)
   - **Labels:** help wanted, good first issue, hacktoberfest
   - **Why low score:** Requires pipe architecture (`read_lines | download | parse_clash`), complex
   - **Competition:** JiwaniZakir actively working (2026-03-17 comment)
   - **Decision:** SKIP - let active contributor finish

4. **#23** - "feat(transformer): add a new transformer to extract url from README.md" (Score: 40/100)
   - **Labels:** help wanted, good first issue, hacktoberfest
   - **Why low score:** Similar complexity to #16, needs pipe transformer
   - **Decision:** DEFER - implement #14 first, revisit if time

### ❌ Denied

5. **#42** - "the list of trojans is a little broken" (Score: 0/100)
   - **Labels:** wontfix
   - **Maintainer response:** "skip them on reading"
   - **Decision:** DENIED - explicitly wontfix

6. **#22** - "fix(sources): decode php code, and get remote proxy list" (Score: 15/100)
   - **Labels:** help wanted, good first issue, hacktoberfest
   - **Why low score:** Vague requirements, no example URL
   - **Decision:** SKIP - insufficient detail

## Hypothesis Alignment

- **H0 (Bug fixes > features):** Both implemented are additions, not fixes. Testing.
- **H2 (Solo maintainer responsiveness):** gfpcom very active in comments, gives examples
- **H3 (Documentation = green flag):** Excellent CONTRIBUTING.md with examples
- **H5 (Good first issue label accuracy):** #14 was accurate, #16/#23 are mislabeled (too complex)

## Next Steps

Both branches ready for drip queue. Waiting for quality gates before push.
