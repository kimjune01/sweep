# toml-lang/toml-test Triage Graph

## Repo Profile
- Stars: 258
- Language: Go
- License: MIT
- CONTRIBUTING: none
- AI policy: none detected
- Open PRs: 1 (#166 - CRLF tests, by maintainer arp242)
- Open issues: 2

## Issue Assessment

### #136 - Millisecond decoder tests pass with second precision output
- **Root cause**: Bug in `cmpAsDatetimes()` at json.go line 210: `time.Parse(layout, datetimeRepl.Replace(want))` parsed `want` twice instead of parsing `have`. Comparison always passed because it compared want against itself.
- **Status**: ALREADY FIXED in commit f53d154 (2025-04-23), released in v2.0.0+. Issue is stale-open.
- **Action**: None needed. Could comment on issue noting it's fixed.

### #183 - valid/datetime/no-seconds fails when decoder omits optional seconds
- **Status**: By design. Maintainer (arp242) responded: "just encode it as 13:37:00 in your JSON." Not a bug.
- **Action**: None.

## Denylist
(none -- first triage)

## Next Steps
- No actionable issues. Repo is well-maintained by arp242.
- Re-triage if new issues appear.
