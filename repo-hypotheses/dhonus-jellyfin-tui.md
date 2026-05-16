# Triage Graph for dhonus/jellyfin-tui

## Repository Info
- **Stars**: 498
- **Language**: Rust
- **Description**: TUI client for Jellyfin media server
- **Issues**: 25 open
- **Fork**: kimjune01/jellyfin-tui

## Summary

**Completed**: 4 PRs queued (3 bug fixes + 1 refactor)
- #187: CPU usage fix (60 FPS frame limiter)
- #86: Track skip rate limiting (playback failure mitigation)
- #99: Session cleanup (previous session)
- Clippy warnings (code quality)

**Time Investment**: ~3 hours for full triage + 4 implementations
**Standing Strategy**: Start with performance bug (#187) to demonstrate value, then playback reliability (#86)

## Completed Fixes

### Issue #187: High CPU usage (20% on M1 Max)
**Status**: Fixed, queued for drip

**Problem**: Main event loop was spinning constantly with minimal sleep (2-5ms only in keyboard polling). User reported ~20% CPU usage on M1 Max with Asahi Linux.

**Root Cause**: The main loop in `src/main.rs` had no frame rate limiting:
```rust
loop {
    app.run().await;   // event handling
    app.draw(&mut terminal).await;  // rendering with 2ms sleep when not dirty
}
```

Even with the 2ms sleep in draw(), the loop was executing hundreds of times per second, running all the work in `run()` (mpv state polling, lyrics, discord, mpris, database events, etc.) on every iteration.

**Fix**: Added consistent 60 FPS frame rate limiting (16.67ms per frame) to the main loop:
- Records frame start time
- Executes run() and draw() as before
- Sleeps for remaining time to reach 16.67ms target
- Standard approach for TUI applications

**Files Changed**: `src/main.rs`
**Branch**: `fix-cpu-usage-frame-limiter`
**Commit**: a765580

### Issue #86: Rapid track skipping detection
**Status**: Partially fixed, queued for drip

**Problem**: When playback fails (PQC TLS, network issues), mpv auto-advances to next track, creating rapid-fire skipping that consumes the entire queue.

**Fix Implemented**: Added rate limiting in `handle_song_change()` that:
- Tracks timestamps of recent track changes (5-second window)
- Detects >3 changes within 5 seconds
- Pauses playback and logs warning
- Prevents runaway skip loops

**Limitation**: This is a mitigation, not a root cause fix. It stops the rapid skipping but doesn't fix the underlying playback failure. Full fix would require mpv event observation for load errors.

**Files Changed**: `src/tui.rs`
**Branch**: `improve-track-skip-rate-limit`
**Commit**: e915f3c

**Why This Helps**: Users can now investigate playback issues without losing their entire queue. The pause gives them a chance to check logs, fix TLS configs, or switch servers.

### Clippy Warnings: Code quality improvements
**Status**: Fixed, queued for drip

**Problem**: Several clippy warnings indicating non-idiomatic Rust code

**Fixes Applied**:
- Removed useless `.into()` conversion on PathBuf
- Changed `if let None = x` to `x.is_none()`
- Used `format!` instead of String concatenation with `&`
- Simplified `map_or(true, |t| ...)` to explicit `is_none() || is_some_and(...)`
- Fixed `trim_matches` borrow pattern

**Files Changed**: `src/config.rs`, `src/client.rs`
**Branch**: `fix-clippy-warnings`
**Commit**: 9337003

**Why This Matters**: Code quality improvements make the codebase easier to maintain and review. Shows attention to detail beyond just fixing bugs.

### Issue #99: TUI not clearing session on pause/quit
**Status**: Fixed, queued for drip (previous session)

**Problem**: Sessions were not properly terminated on exit, leaving stale sessions on the Jellyfin server. Error reporting for HTTP client errors was poor.

**Fix**: Added logout() call in App::exit(), improved error handling in get_json_with_retry()
**Branch**: (from previous triage session)
**Commit**: 3c44a07

## Investigated Issues

### Issue #86: Playback failure and rapid skipping with PQC TLS
**Maintainer**: Reproduced, acknowledged
**Status**: Needs deeper investigation

**Problem**: When Jellyfin server uses post-quantum TLS curves (x25519mlkem768), playback fails silently and rapidly skips through queue. Maintainer confirmed this also happens with spotty internet connections.

**Root Cause**: mpv/ffmpeg don't support PQC TLS curves. While jellyfin-tui can connect using rustls with PQC support, mpv cannot stream the media. When playback fails, mpv automatically advances to next track, creating rapid-fire skipping behavior.

**Potential Fix Direction**: Add playback failure detection to prevent rapid skipping when tracks fail to load. The code in `src/mpv.rs` polls mpv state but doesn't check for error events. Could use:
- `idle-active` property to detect when nothing is playing
- Track advancement rate limiting to prevent rapid-fire skips
- mpv event observation for load failures (requires libmpv2 event API investigation)

**Blocker**: Requires understanding libmpv2 event system beyond property polling. Current implementation only polls state every 200ms. Need to distinguish between:
1. Track ending normally (should advance)
2. Track failing to load (should NOT rapid-advance)

**Recommendation**: Wait for maintainer to investigate libmpv2 event capabilities, or open issue with failing test case for TDD approach.

### Issue #165: Error connecting to external library
**Status**: Under investigation by maintainer, environment-specific

**Problem**: Connection works in browser and other clients but fails in jellyfin-tui when using Cloudflare tunnel. Error: "error sending request for url".

**Investigation**: 16 comments, maintainer suspects Cloudflare rejecting jellyfin-tui requests. Asked users for curl tests and TLS configs. No clear pattern yet.

**Recommendation**: Not suitable for external contribution until root cause is identified.

### Issue #176: Select mode in playlists (multi-delete)
**Maintainer**: "Would be great", simple with ratatui
**Status**: Feature request, non-trivial UI work

**Request**: Vim-style visual selection mode to delete multiple playlist tracks:
1. Press V to enter select mode
2. Move cursor to select tracks
3. Press d to delete selection

**Assessment**: Good feature but requires:
- New selection state in playlist view
- Visual mode rendering
- Multi-delete batch operation
- Vim-like keybinding semantics

**Recommendation**: Good second PR after establishing standing with simpler bug fixes.

## Issue Prioritization

**High Value, Low Complexity**:
- ✅ #187 (CPU usage) - FIXED

**High Value, Medium Complexity**:
- #86 (playback failure detection) - Needs libmpv2 event investigation
- #176 (select mode) - UI state management, good for second PR

**Under Investigation**:
- #165 (Cloudflare tunnel) - Environment-specific, maintainer investigating

**Other Issues Scanned**:
- #104 (Queue View / zen mode) - Feature request, UI redesign
- #131 (Genre browsing) - Feature request, duplicate of #119
- #160 (Keyring password storage) - Good feature, waiting for keyring-rs v4
- #182 (Global shuffle improvements) - Feature refinement
- #186 (Shuffle by artist) - Feature request
- #38 (Crashes on login) - 15 comments, unclear repro
- #74 (Env vars / password_file) - Configuration enhancement
- #75 (Remote control support) - MPRIS/API feature
- #71 (All Tracks tab) - UI feature
- #109 (Select multiple songs) - Related to #176
- #110 (More sorting options) - Feature enhancement
- #119 (Filter by year) - Related to #131
- #170 (Feed music to iPod) - External integration
- #181 (Visual tweaks) - Bundle of UI polish items
- #191 (Bind to show currently playing) - Keybinding feature

## Denylist
- Issues already fixed: #99, #165 (already in queue), #187
- Issues pending maintainer investigation: #165, #86 (partial)
- Feature requests requiring design discussion: #104, #131, #160, #176, #182, #186
- Issues without clear repro: #38

## Next Actions
1. Monitor #187 PR review (once created via /ship)
2. Consider #86 with test-first approach if libmpv2 event investigation yields path forward
3. Consider #176 as second PR to demonstrate UI capability
4. Look for smaller undocumented bugs in codebase (typos, edge cases, etc.)

## Lessons Learned
- TUI performance issues often stem from event loop throttling, not rendering
- Frame rate limiting is standard practice (60 FPS = 16.67ms)
- jellyfin-tui has good separation: mpv thread (polling) vs UI thread (events)
- Maintainer is responsive and realistic about capacity ("extremely busy this month")
- Many features waiting on upstream dependencies or maintainer design decisions
