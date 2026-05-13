# CopterExpress/clover Triage Graph

**Repo**: CopterExpress/clover (496 stars, C++ - ROS drone platform)  
**Date**: 2026-05-11  
**Status**: COLD_REPO - No actionable issues

## Summary

Investigated all 3 open issues. None are suitable for building standing:

### Issue Analysis

#### #514 - "Contours for cv2 dont working"
- **Status**: NOT_ACTIONABLE
- **Reason**: User posted code snippet without clear problem statement. Maintainer (okalachev) asked "What do you mean by not working?" No response. This is user code, not a framework issue.
- **Evidence**: Issue body shows application code using cv2.findContours but no error message or expected vs actual behavior.

#### #505 - "odometry data corrupted"
- **Status**: NOT_ACTIONABLE  
- **Reason**: Valid complaint (drone rotates when stationary, affects gmapping), but only comment is spam (unrelated Python code from zybinskijsasa67-rgb). No logs, no diagnostic info, no steps to reproduce. Could be hardware (IMU drift, magnetometer interference), configuration (incorrect transform), or environmental. Not diagnosable remotely without engagement.
- **Evidence**: Issue body mentions base_link rotation from odometry topic, but provides no telemetry data or system configuration.

#### #511 - "Problems with Raspberry Ai Camera and clover 0.26v"  
- **Status**: HARDWARE_COMPATIBILITY
- **Reason**: Maintainer (okalachev) already engaged. Hardware-specific (Raspberry AI Camera + imx500 driver). User posted extensive diagnostic output. This is an ongoing conversation, not a standing-building opportunity.
- **Evidence**: 3 comments with logs and troubleshooting steps. Active maintainer support.

## Repo Characteristics

**Recent Activity**:
- Last merged PR: #515 (2026-04-14) - docs improvements by fly-pigTH
- PR merge pattern: Docs fixes welcome (see #515, #509, #503, #502)
- Very low PR velocity: ~4 docs PRs/year recently
- No code PRs merged since 2023

**Issue Patterns**:
- Low volume: 3 open issues total
- User support requests dominate (hardware setup, usage questions)
- No clear feature requests or acknowledged bugs

**Recommendation**: 
SKIP this repo for now. Wait for better issues or look for documentation improvements:
- Line 37 in docs/en/safety.md has `<!-- FIXME: add translated soldering iron picture -->`
- Could audit docs for broken links, missing images, or clarity improvements
- But docs PRs have minimal impact on standing (no code review, no maintainer engagement on substance)

## Hypothesis Updates

- **H0 (Ignored)**: N/A - no PR attempted
- **H1 (Standing-first)**: Confirmed - no issues suitable for standing-building
- **H4 (Docs-first)**: Possible path via documentation improvements, but low impact
- **H5 (Stale maintainer)**: Active maintainer (okalachev) responds to issues, but repo is low-velocity

## Next Steps

1. DEFER: Don't create any PRs for this repo now
2. MONITOR: Check back in 3 months for new issues
3. ALTERNATIVE: If pursuing this ecosystem, focus on related repos (PX4, mavros) with higher activity
