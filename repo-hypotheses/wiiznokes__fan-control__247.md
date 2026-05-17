# wiiznokes/fan-control#247 — Hypothesis Graph

PR: <https://github.com/wiiznokes/fan-control/pull/247> (mine, fixes #197)
Branch: `confirm-on-close`, head `3b5e1f8`
CI run: 25873995856 — Build (ubuntu+windows), Rust tests (ubuntu), Clippy (ubuntu+windows) FAILED. Fmt jobs SUCCESS.

## H₀ — observation

CI failed compilation. Two distinct compiler errors in `ui/src/lib.rs`:

1. **E0599 (Windows only):** `no variant or associated item named 'Exit' found for enum 'message::AppMsg'`
2. **E0308 (all platforms):** `match arms have incompatible types — expected 'Task<AppMsg>', found 'Task<Action<_>>'`

**Trajectory:** divergent — compiler is deterministic, no ambiguity. Both errors point at the same call site I added: `Task::done(AppMsg::Exit)` at `ui/src/lib.rs:638`.

**Reasoning mode:** deduction (read the code + compiler output). Confidence 99%.

## H₁ — root cause

`AppMsg::Exit` is gated `#[cfg(target_os = "linux")]` in `ui/src/message.rs:35-36`; on non-Linux the close path uses `AppMsg::HideWindow` (minimize to tray). The new dialog-update arm at lib.rs:634-640 calls `AppMsg::Exit` unconditionally, breaking Windows compile.

Independent of that, the surrounding `DialogMsg` match feeds into `.map(cosmic::action::app)` at lib.rs:642. Sibling arms (Udev/CreateConfig/RenameConfig) all return `Task<their-DialogMsg-variant>`, which the map lifts into `Task<Action<AppMsg>>`. My new arm returns `Task<AppMsg>` directly — mismatched types even before the cfg issue.

**Provenance:** introduced by commit ac4c1a7 ("fix: use Task::done(AppMsg::Exit) instead of direct exit action"). The earlier attempt presumably used `cosmic::iced_runtime::task::effect(...)` directly; the "fix" regressed the type signature and the cross-platform gate.

## Fix shape

Hoist `DialogMsg::ConfirmClose` out of the mapped match — handle it before `.map(cosmic::action::app)` so it can return a `Task<AppMsg>` directly, and pick the right close variant per platform.

```rust
AppMsg::Dialog(dialog_msg) => {
    // ConfirmClose escapes the dialog-update pattern: it dispatches an AppMsg,
    // not a DialogMsg, so handle it before the action::app mapping.
    if let DialogMsg::ConfirmClose(confirm_close_msg) = dialog_msg {
        self.dialog = None;
        return match confirm_close_msg {
            ConfirmCloseDialogMsg::Cancel => Task::none(),
            #[cfg(target_os = "linux")]
            ConfirmCloseDialogMsg::Close => Task::done(AppMsg::Exit),
            #[cfg(not(target_os = "linux"))]
            ConfirmCloseDialogMsg::Close => Task::done(AppMsg::HideWindow),
        };
    }
    return match dialog_msg {
        DialogMsg::Udev(message) => udev_dialog::update(self, message),
        DialogMsg::CreateConfig(m) => CreateConfigDialog::update(self, m),
        DialogMsg::RenameConfig(m) => RenameConfigDialog::update(self, m),
        DialogMsg::ConfirmClose(_) => unreachable!(),
    }
    .map(cosmic::action::app);
}
```

## Verification plan

- `just test` on Linux (current host) — must pass.
- `cargo check --target x86_64-pc-windows-gnu` if cross-tool is available; otherwise rely on CI.
- Push and watch CI for both ubuntu and windows.

## Graph state

| Node | Status | Mode | Confidence |
|------|--------|------|------------|
| H₀ — CI compile failure | confirmed | deduction | 99% |
| H₁ — Exit gated + map mismatch | confirmed | deduction | 95% |
| Fix — hoist ConfirmClose pre-map | proposed | abduction | 80% — verify via CI |
