# ncbi/amr Triage Graph

## Repo Profile
- Stars: 365
- Language: C++
- License: US Government Public Domain
- CONTRIBUTING: none
- AI policy: none detected
- Open PRs: 0
- Open issues: 9

## Issue Assessment

### #145 - Core dump when running multi-threaded [bug, conda]
- Upstream blast version issue. Maintainer suggested Docker container workaround. Cannot reproduce without specific blast version + conda environment.
- **Action**: Skip. Infrastructure-dependent.

### #139 - Allow download of specific database versions [enhancement]
- Feature request for version-pinned database downloads. Maintainer engaged but no acceptance signal for PRs.
- **Action**: Skip. Enhancement, cold start.

### #138 - AMRProt [bug, can't reproduce]
- Cannot reproduce, stale since 2024-03.
- **Action**: Skip.

### #123 - intermittent ERROR [bug, can't reproduce]
- Intermittent ANSI color code in error output. Cannot reproduce.
- **Action**: Skip.

### #120 - amrfinder_update cannot connect to FTP [bug, can't reproduce]
- Network/FTP connectivity issue. Environment-specific.
- **Action**: Skip.

### #111 - Option to use Diamond instead of Blast [enhancement]
- Major feature request. Complex integration.
- **Action**: Skip.

### #98 - Include nucleotide substitution for point mutations [enhancement]
- Feature request. Maintainer said "possible but difficult." User found workaround.
- **Action**: Skip.

### #89 - amrfinder_update does NOT respect DEFAULT_DB_DIR [enhancement]
- **Status**: ALREADY FIXED. User's last comment: "thanks for the fix."
- **Action**: None.

### #88 - Use the program on Viruses? [question]
- Usage question. Out of scope.
- **Action**: Skip.

## Denylist
(none -- first triage)

## Next Steps
- No actionable bugs. All bugs are "can't reproduce" or environment-specific.
- All enhancements are complex domain-specific features.
- Re-triage if new issues appear.
