# Mic92/envfs — Triage Graph

Repo: 391 stars, Rust, FUSE filesystem for NixOS
Maintainer: @Mic92 (Jörg Thalheim), active, merges PRs within days
No CONTRIBUTING.md. Default branch: main.

## Open Issues

### #173 — fish shell doesn't work [TRIAGED]
- **Root cause:** `is_fstatat_syscall` only checks `SYS_newfstatat`. Fish shell uses `statx` syscall (via `std::fs::metadata` in Rust) to check if a file exists before executing it. Without `statx` in the whitelist, envfs returns ENOENT.
- **Fix:** Add `libc::SYS_statx` to the syscall check, rename function to `is_stat_syscall`.
- **Branch:** `fix-fish-statx-173`
- **Competing PRs:** None. @kika identified fix 2026-04-14, asked "PR?" but never submitted.
- **Confidence:** High. @fzakaria diagnosed root cause with strace, @kika confirmed statx is the current syscall.

### #180 — podman / ssh [SKIPPED]
- Vague report. Maintainer speculated about ENVFS_RESOLVE_ALWAYS being cleared by podman internals.
- No reproduction steps, no clear fix path.
- **Reason:** Not actionable without reproduction.

### #179 — nixos defaults [SKIPPED]
- Feature request: make envfs default in NixOS installer/profile.
- Maintainer says there's a "rare issue" that needs fixing first.
- **Reason:** Not a code change in envfs. Belongs in nixpkgs.

### #166 — File permissions too open [SKIPPED]
- Programs refuse to run executables via envfs symlinks because they appear world-writable.
- Maintainer discussed: can't change permissions on symlinks that don't exist on stat(). Would require implementing regular files (inodes + read), significant performance impact.
- **Reason:** Architectural change, too complex for first contribution.

## Open PRs

### #219 — Fix fileSystems."/bin".fsType accessed but undefined
- Nix module fix, unrelated to our work.
- Status: open, awaiting review.

## Evidence

- Maintainer merges dependabot bumps promptly (weekly cadence).
- Non-trivial PRs (#214, #215, #216) merged in batches on 2026-03-12.
- Bug fix PRs merge. Feature PRs need discussion.
