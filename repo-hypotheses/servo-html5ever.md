# servo/html5ever Triage

Date: 2026-05-10
Status: GATE_FAIL - No actionable issues found
Org: servo (warm - #44816 merged)

## Scan Results

Scanned 50 open issues. No issues met actionability criteria.

## Issue Classification

### Already Fixed (not closed)
- **#351** - Panic on `assertion failed: c.is_some()` - Tested with current codebase, panic no longer occurs. Likely fixed in refactor.
- **#219** - Warning spam for `stop_parsing` and `</script>` - Grep confirms warnings removed from codebase.

### Feature Requests (not bugs)
- **#583** - Request to disable automatic `<html><body>` wrapper - This is spec-compliant behavior, not a bug.
- **#703** - Faster tokenizer for `DOMParser`/`innerHTML` - Performance optimization, labeled "experiment".
- **#617** - Encoding/prefetching improvements - Architecture proposal.

### Complex Architectural Issues
- **#289** - O(n) time guarantee for pathological input - Has stale PR #297 from 2017. Would require significant data structure changes (vectors → linked lists/hash sets).
- **#512** - Malformed HTML parsed differently from browsers - Related to adoption agency algorithm, complex edge case.
- **#588** - Invalid HTML produces duplicated elements - Maintainer comment indicates partially expected behavior per spec.
- **#694** - MathML/foreign content handling modifies original DOM - Complex foreign content integration issue.

### Documentation
- **#451** - Add descriptions to examples
- **#452** - Update xml5ever README

### Questions (not issues)
- **#433** - How to replace NodeRef with child - API usage question.
- **#477** - Cargo dependency resolution with `*` versions - Cargo behavior, not code bug.

## Gate Decision

**KILLED** - No actionable issues.

Servo/html5ever is well-maintained with recent activity (14 PRs merged in past 6 months). Open issues are either:
1. Already resolved but not administratively closed
2. Feature requests requiring maintainer design decisions
3. Deep architectural changes requiring extended engagement

No mechanical bug fixes available that match pipeline criteria (clear repro + acceptance test + minimal scope).

## Hypothesis Updates

- **H0** (Random selection): N/A - targeted repo based on warm org status
- **H2** (Well-maintained gatekeeping): SUPPORT - Clean codebase, recent merges, but high bar for changes
- **H4** (Issue age signals stale repo): REJECT - Old issues don't indicate neglect here; maintainers focus on real work over admin

## Recommendation

Skip html5ever for this sweep cycle. Target other servo/* repos or expand to different orgs.
