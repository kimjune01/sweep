# sorairolake/qrtool Triage Graph

## Repo Profile
- Stars: 278
- Language: Rust
- License: Apache-2.0 OR MIT (dual)
- CONTRIBUTING: CONTRIBUTING.adoc (git-flow branching, conventional commits, branch from develop)
- AI policy: none detected
- Open PRs: 0
- Open issues: 1

## Issue Assessment

### #695 - Nothing returned when decoding a QR code [bug, help wanted]
- **Root cause**: Two-layer problem. (1) Upstream rqrr crate fails to detect certain QR codes (photo-of-screen, Edge-generated). (2) qrtool itself returns exit code 0 with empty output when no QR code is detected.
- **Our fix**: Layer 2 only. Added `anyhow::ensure!(!contents.is_empty(), "no QR code found in the image")` after decode attempt. TDD: failing test with plain PNG, then fix.
- **Maintainer signal**: "I think this issue should be fixed" and "If someone fixes this in this crate, I'll accept it" (2025-02-13). Strong acceptance signal.
- **Branch**: `fix/decode-exit-code-on-empty` from `develop`
- **Status**: triaged, pushed to fork
- **Risk**: Low. One-line change in app.rs, test added. Layer 1 (rqrr detection) remains open.

## Denylist
(none -- first triage)

## Next Steps
- Run /qa then /drip on the fix
- Layer 1 fix would require changes to rqrr crate (upstream dependency)
