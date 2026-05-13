# Triage Graph: aajanki/yle-dl

**Repo**: aajanki/yle-dl  
**Stars**: 360  
**Language**: Python  
**Description**: Download videos from Yle servers (Finnish public TV)  
**Date**: 2026-05-11

## Hypothesis

**H0**: Bug fix PRs for parser/extraction issues merge. Feature PRs require maintainer approval.

**Evidence**:
- Last merge: #400 SOCKS proxy (2026-05-10, 1 day ago) - feature
- Recent merges: #398 subtitle delay, #397 timeouts, #382 subtitle fix
- Maintainer actively merges both features and fixes
- No CONTRIBUTING.md, no strict guidelines

**Standing path**: Fix a small parser bug → responsive iteration → earn trust → propose features.

## Issues Investigated

### #401: Downloading short videos (https://yle.fi/v/video/91-20224464)
**Status**: ❌ Not actionable  
**Created**: 2026-05-10 (1 day ago)  
**Comments**: 0  

**Investigation**:
- URL pattern `https://yle.fi/v/video/91-20224464` matches fallback case in `extractor_factory`
- Program ID extraction: `91-20224464` → needs mapping to `1-*` format  
- Actual embed URL shows `1-78021451`, but API returns `"not_allowed"`
- **Root cause**: Content is geo-blocked or restricted, not a code issue
- Similar ID seen: `1-20224464` (URL ID `91-` → `1-` prefix swap)

**Devil's advocate**: Even if we fix ID extraction, content returns `not_allowed`. This is a content restriction, not a parser bug. No code fix will enable downloads.

**Verdict**: Skip. Content restriction issue, not fixable by code.

### #385: Subtitles cut off after certain timestamp
**Status**: ❓ Needs deeper investigation  
**Created**: 2025-06-26  
**Comments**: 1 (maintainer)  

**Maintainer comment**: "It's probably a configuration error on Areena or a bug in ffmpeg. Either way fixing this would be a task for somebody who understands more about ffmpeg than I do."

**Devil's advocate**: Maintainer explicitly stated this needs ffmpeg expertise beyond their own. Upstream issue.

**Verdict**: Skip. Upstream ffmpeg or Areena API issue.

### #362: Piping to MPV in Windows seemingly broken
**Status**: ❓ Platform-specific  
**Created**: 2024-06-16  
**Comments**: 1 (maintainer)  

**Investigation**: Windows-specific piping issue with MPV. Maintainer suggested cache workaround. Needs Windows environment to reproduce and test.

**Verdict**: Skip. Requires Windows env, no Mac/Linux repro.

## Repository Health

**Merge velocity**: 10 merged PRs in ~16 months (0.6 PR/month)  
**Last activity**: 1 day ago (PR #400 merged)  
**Maintainer engagement**: High (responds to issues, merges regularly)  
**Open PRs**: 1 (#399 subtitles-only, 7 months old, no review)  
**Open issues**: 17

**Quality signals**:
- CircleCI build status badge
- Tests exist (unit + integration)
- PyPI published
- Clear README
- Active maintenance

## Denylist

- #401 (content restriction, not code)
- #385 (upstream ffmpeg/Areena issue)
- #362 (Windows-only, needs env)

## Recommendation

**Action**: Archive this triage session. No actionable standing-building issues found.

**Rationale**:
1. Most open issues are service-specific (Yle API changes, geo-blocking, content restrictions)
2. Issues requiring domain expertise (ffmpeg internals, Windows piping)
3. Feature requests (#388 flatpak, #361 NFO metadata, #340 subtitles-only) compete with existing PR #399
4. Cold start problem: No easy bug fixes to build standing

**Next steps**: Monitor for parser bugs, regex issues, or Python 3.x compatibility as they arise. This repo's issue backlog is dominated by external dependencies (Yle API, ffmpeg, geo-blocking) rather than code bugs.

## Hypothesis Update

**H0 holds**: Maintainer accepts features (#400, #398) and fixes (#397, #382). But current issue backlog has no actionable standing-building opportunities. The repo is well-maintained but issue quality is low (service issues, not code bugs).

**Pipeline learning**: Some repos have healthy maintenance but poor issue quality. Skip early rather than force investigation.
