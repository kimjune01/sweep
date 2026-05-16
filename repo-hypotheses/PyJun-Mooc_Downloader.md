# Triage Graph: PyJun/Mooc_Downloader

**Repo:** PyJun/Mooc_Downloader (500★, Python, MOOC video downloader)  
**Triage Date:** 2026-05-11  
**Result:** UNSUITABLE — Contribution-hostile (frozen open-source codebase, active closed-source development)

## Evidence

### Codebase Status
- Last code commit: 2020-05-18 (merged PR #32)
- Since 2023: Only README updates, zero code changes
- PR acceptance rate: 1 merged PR total (2020-05-18)

### Maintainer Disclosure
README explicitly states:
> "项目代码已好久未更新，Releases下有我打包好的exe文件，可直接下载使用~【该项目为早期开源的代码，最新版本代码未开源】"

Translation: "The project code hasn't been updated in a long time. Download the exe from Releases. **This is early open-source code; the latest version is not open-source**."

### Issue Analysis
12 open issues scanned:
- **#181**: iCourse broken (needs closed-source fix)
- **#170**: Mac support (packaging work on closed-source version)
- **#148**: Yuketang support (feature request for paid version)
- **#146**: Geek Time support (feature request for paid version)
- **#124**: Contact info (meta)
- **#105**: More sites (feature request)
- **#100**: Additional materials (feature for closed version)
- **#99**: Download quizzes (feature request)
- **#68**: More sites (feature request)
- **#67**: Logout feature (feature request, closed version only)
- **#31**: Custom chapter selection (feature request, maintainer said "will add to GUI later" in closed version)
- **#16**: More sites (feature request)

**All issues are feature requests for the closed-source paid version.** Zero actionable bugs in open-source code.

## Hypothesis Classification

**H2 (Maintainer Bandwidth) — FALSIFIED**  
Not a bandwidth problem. Maintainer is actively maintaining a paid closed-source fork and explicitly refuses to update the open-source codebase. This is a business model, not contributor neglect.

**H5 (Competence Signaling) — INAPPLICABLE**  
No path to demonstrate competence when maintainer won't merge code.

## Verdict

**Status:** REJECTED — no actionable work  
**Reason:** Frozen open-source codebase with active closed-source development. Contributing to the open repo doesn't help users (they use the closed exe) and won't be accepted by the maintainer (zero code PRs since 2020).

This repo violates pipeline actionability requirements:
1. Maintainer-acknowledged problems → None (all issues reference closed version)
2. Mechanical acceptance criteria → None (no code changes accepted)
3. User impact → None (users don't use this code)

## Recommendation

Remove from roster. Flag similar dual-license "early open-source code + active closed-source development" repos in future intake.
