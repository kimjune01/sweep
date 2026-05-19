# Hypothesis Graph: antonmedv/fx#413

Target: antonmedv/fx issue #413, "Yank doesn't work with snap install"
Date: 2026-05-18 (second pass, with worktree and source access)
Mode: pipeline investigate. Supersedes the earlier perturbation-blocked pass.

## Issue Recap

Reporter on Ubuntu 25.10 / zsh 5.9, Tilix or gnome-terminal, fx v39.2.0 installed via snap. The yank dialog flashes on the first `y`, the second `y` dismisses it, but xclip / wl-paste / Ctrl-V all come up empty. Uninstalling the snap and reinstalling via the upstream install script fixes yank.

Maintainer (antonmedv, 2026-05-08): "My suspicion: it is _snap_. Try to install by downloading the binary. Problem with snap is - it is a contained environment. So fx can't call vim from it."

Reporter confirmed the non-snap install works and asked for **a warning in the docs / snap installation tab**, explicitly soft-pedalling a code fix.

## H0 — snap strict confinement blocks fx's clipboard subprocess

**Perturbation surface:** the yank handler in `main.go` and the snap packaging in `snap/snapcraft.yaml`.

`main.go:645-660`:

```go
func (m *model) handleYankKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
    switch {
    case key.Matches(msg, yankPath):
        _ = clipboard.WriteAll(m.cursorPath())
    case key.Matches(msg, yankKey):
        _ = clipboard.WriteAll(m.cursorKey())
    case key.Matches(msg, yankValueY, yankValueV):
        _ = clipboard.WriteAll(m.cursorValue())
    case key.Matches(msg, yankKeyValue):
        k := m.cursorKey(); v := m.cursorValue()
        _ = clipboard.WriteAll(k + ": " + v)
    }
    m.yank = false
    return m, nil
}
```

`github.com/antonmedv/clipboard` on Linux shells out to `xsel` / `xclip` / `wl-copy`. `snap/snapcraft.yaml` declares:

```yaml
confinement: strict
apps:
  fx:
    command: bin/fx
    plugs: [ dot-fxrc-js, home, network ]
```

No `desktop`, `wayland`, `x11`, `unity7`, or `desktop-legacy` plugs. Under strict confinement the snap cannot exec arbitrary host binaries on `$PATH` and cannot reach the user's X / Wayland clipboard sockets. The clipboard subprocess returns an error; the handler discards it (`_ =`); the UI flashes the dialog and dismisses.

**Trajectory:** divergent confirming. Code reading and maintainer's prior diagnosis converge on the same cause.

**Reasoning mode:** deduction (read code + snapcraft + snap confinement model). Confidence 95%.

## Fix-shape options considered

| Option | Verdict | Why |
|---|---|---|
| Switch snapcraft `confinement: strict` → `classic` | Not shippable in a PR alone | Classic confinement requires Snap Store manual review and re-approval. Cannot be a code-only change. |
| Add `desktop`, `x11`, `wayland`, `unity7` plugs | Speculative + insufficient | Plugs grant socket/D-Bus access but `antonmedv/clipboard` still relies on host `xclip`/`wl-copy` binaries that aren't on the snap's `$PATH`. Granting plugs without bundling the binaries does not fix the symptom. Untested locally and not asked for. |
| Bundle `xclip` / `wl-clipboard` inside the snap | Out of scope | Real engineering work (stage-packages, plug grants, runtime detection). Maintainer did not ask for it and the reporter is satisfied with documentation. |
| Replace `antonmedv/clipboard` with a native Go clipboard backend that talks X11/Wayland directly | Out of scope | Library swap touches every platform, not snap-specific. Maintainer didn't request it. |
| Add warning to in-repo `README.md` | Wrong venue | README is 23 lines and is a pointer to `fx.wtf`. It has no install section to warn under. |
| Update docs at `fx.wtf` (the canonical documentation) | Correct venue, wrong repo | The docs site lives in a separate repository that this worktree does not include. |
| Surface the dropped clipboard error in the UI | Out of scope but diagnostically useful | Replacing `_ = clipboard.WriteAll(...)` with code that records the error and renders it on the yank result line would have let the reporter self-diagnose. The maintainer did not ask for this, and changing UX behavior on every platform to address a snap-specific limitation is a poor scope match. |

## Provenance

- `git blame snap/snapcraft.yaml`: strict confinement is the original choice for the snap, not a regression.
- `gh pr list` / search: no parallel work on snap or clipboard.
- Operator PR history on this repo: only #414 (stdin/TTY detection, orthogonal).
- Maintainer's thread stance: accepted snap as the cause; no signal they want a code change here.

## Graph State

| Node | Status | Shape | Notes |
|---|---|---|---|
| H0 (snap strict confinement blocks clipboard subprocess) | **confirmed** | divergent | Library shells out; snap blocks; errors silently dropped |
| H1 (switch to classic confinement) | killed | n/a | Requires Snap Store review, not code-only |
| H2 (add desktop/x11/wayland plugs) | killed | speculative | Doesn't bundle the binaries the library needs |
| H3 (bundle clipboard binaries in snap) | killed | out of scope | Engineering scope beyond issue ask |
| H4 (README install warning) | killed | venue-mismatch | README has no install section |
| H5 (fx.wtf docs warning) | open / wrong-repo | predicted convergent | Correct venue lives in a different repo |
| H6 (surface dropped clipboard error in UI) | open / out-of-scope | predicted divergent | Real diagnostic gain; not what the maintainer or reporter asked for |

## Outcome

**Tissue-class.** No PR is justified.

- Root cause is identified and accepted by both reporter and maintainer.
- The only ask on the thread is documentation, and the docs venue (`fx.wtf`) is not in this repo.
- All shippable in-repo code changes either need external (Snap Store) review, expand scope past the reporter's ask, or change cross-platform UX to fix a snap-specific limitation.

The substantive observation worth surfacing back to the maintainer in a tissue comment is the discarded error at `main.go:648-657`. That `_ =` is the reason yank looks like a no-op rather than an error: the clipboard subprocess failure is invisible under any installation route that lacks `xclip`/`wl-copy`, not just snap. Whether the maintainer wants to keep that behavior is their call; the data point is useful.

Halt reason: tissue-class. No PR readiness record written.

## Reasoning Mode Summary

| Claim | Mode | Confidence |
|---|---|---|
| `antonmedv/clipboard` shells out to host binaries on Linux | deduction (library convention + go.mod entry) | 90% |
| snap strict confinement blocks those subprocess calls | deduction (snap model + snapcraft plug list) | 95% |
| Yank handler silently drops the clipboard error | deduction (`main.go:645-660`) | 99% |
| Maintainer wants documentation, not a code fix | induction (read thread) | 90% |
| README is the wrong venue; docs live at fx.wtf | induction (README is 23 lines, points externally) | 95% |

## Pruning Log

- H1 — killed by external constraint (Snap Store classic-confinement review).
- H2 — killed by deduction (plugs alone do not provide clipboard binaries on `$PATH`).
- H3 — killed by scope (not requested, large engineering surface).
- H4 — killed by venue (no install section in README).
- H5 — killed by repo boundary (docs site is a different repository).
- H6 — kept open as a frontier; not part of this issue's ask.
