# Hypothesis Graph: rustledger/rustfava#136

**Issue**: "Failed to open file: Error: Server failed to start" on macOS v1.30.12
**Reporter**: vsenn
**Created**: 2026-05-07
**Investigator**: kimjune01 (claude opus-4.7)
**Date**: 2026-05-18

## H₀ — "Default port conflict" (reporter's initial guess)

- **Hypothesis**: Port 5000 already in use; need custom-port config.
- **Perturbation**: Reporter ran `rustfava -p 5009 main.bean`.
- **Result**: Still fails. Different error surfaces (the *real* one):
  ```
  rustfava/rustledger/engine.py:164 in _rpc_call
    raise RustledgerError(f"Empty response: {error_msg}")
  RustledgerError: Empty response: rustledger-ffi-wasi - Rustledger FFI via WASI (JSON API for embedding)
  ```
- **Trajectory**: **Divergent against.** Killed. The port hypothesis was a wrapper symptom from the desktop frontend's 6-second `waitForServer` timeout (`desktop/src/main.ts:336`). The desktop alert masked the upstream `_rpc_call` failure. Reporter's CLI repro surfaced the underlying error.
- **Edge generated**: The wasm subprocess returned no stdout; stderr was the binary's own banner text.

## H₁ — Wasmtime stdio inheritance regressed in a newer wasmtime version

- **Hypothesis**: User's `wasmtime` is too new and no longer forwards host stdin to the WASM module by default; the wasm received no input and printed its help banner.
- **Perturbation** (local, my Mac): Installed wasmtime 44.0.1 (current latest). Ran:
  ```
  echo '{"jsonrpc":"2.0","method":"util.version","id":1}' \
    | wasmtime run /tmp/rustledger-ffi-v0.11.0.wasm
  ```
- **Result**: `{"jsonrpc":"2.0","result":{"apiVersion":"1.0","version":"0.11.0"},"id":1}` — exit 0. With empty stdin (`</dev/null`), v0.11.0 returns a JSON-RPC error (`"Empty request body"`), NOT a banner.
- **Trajectory**: **Divergent against.** Killed. Current wasmtime + v0.11.0 wasm produces the documented JSON-RPC behavior. The banner text the user saw does NOT appear from v0.11.0 under any invocation I could find (no-stdin, --help, junk args — all return JSON).

## H₂ — Stale wasm cached on disk (PRIMARY DIAGNOSIS)

- **Hypothesis**: The on-disk wasm file is an OLDER rustledger version (v0.8.x or earlier) with a subcommand-style CLI; the new engine.py pipes JSON-RPC but the old wasm wants `argv[1]=<subcommand>`, so clap prints its help banner to stderr and exits with empty stdout.
- **Perturbation** (local): Downloaded `rustledger-ffi-wasi-v0.8.5.wasm`, ran it through the exact same engine.py code path:
  ```
  echo '{"jsonrpc":"2.0","method":"util.version","id":1}' \
    | wasmtime run /tmp/rustledger-ffi-v0.8.5.wasm
  ```
- **Result** (stderr, exit 0, empty stdout):
  ```
  rustledger-ffi-wasi - Rustledger FFI via WASI (JSON API for embedding)

  Usage: rustledger-ffi-wasi <command> [args...]
  ```
  **Byte-for-byte match** with the user's reported error stderr. Confirmed on v0.7.0, v0.8.0, v0.8.5 — all subcommand-style. v0.9.0+ flipped to stdin-only JSON-RPC.
- **Trajectory**: **Divergent for.** Confirmed.
- **Causal chain**: user installed an older rustfava → `_download_wasm` cached `rustledger-wasi.wasm` (v0.7/0.8.x) at `lib/python3.13/site-packages/rustfava/rustledger/rustledger-wasi.wasm`. `uv tool upgrade rustfava` bumped Python code (which now hard-codes `RUSTLEDGER_VERSION = "v0.11.0"`) but the cached `.wasm` was preserved (or the new engine.py's `if not wasm_path.exists()` guard saw the file and skipped re-download).

## Provenance check (mandatory on confirmed H)

- **Cache code**: `src/rustfava/rustledger/engine.py:64-68` — wasm path is version-agnostic (`rustledger-wasi.wasm`); `_download_wasm` only fires when the file is missing.
- **Version bumps**: `.github/workflows/update-rustledger.yml` automates `RUSTLEDGER_VERSION` sed-replace in engine.py — the URL changes per release but the on-disk filename never does. So every rustledger upgrade leaves stale caches behind for every existing user.
- **Wheel contents**: PyPI wheel does NOT bundle the wasm (publish.yml runs `uv build`; MANIFEST.in does not graft the rustledger dir's wasm; checkout has no `.wasm` in `src/rustfava/rustledger/`). All PyPI users hit `_download_wasm` on first run.
- **Desktop bundle**: `.github/workflows/desktop-release.yml:74-75` downloads the wasm at build time into the same `rustledger-wasi.wasm` filename. So .dmg users get a wasm version frozen at build time — but the desktop bundle reinstall path also doesn't refresh the file if a user-writable cache exists.
- **Related**: #120 (same "Server failed to start" symptom on Tahoe 26.4, .dmg). Maintainer @robcohen asked about quarantine and binary path — quarantine fix did not resolve it. Same root cause is plausible: the .dmg shipped one wasm, user's cached/preserved file is older. Worth flagging in the comment.

## H₃ (frontier — not investigated) — Quarantine/Gatekeeper on the cached wasm

- **Hypothesis**: macOS may apply `com.apple.quarantine` to runtime-downloaded `.wasm` files; wasmtime might fail to mmap quarantined files silently.
- **Predicted classification**: Likely **divergent against** — wasmtime mmaps the wasm, quarantine usually fails the read with an OSError (which engine.py's `except OSError` catches and re-raises as `Failed to run wasmtime`, not `Empty response`). The stderr text we see is unambiguously the v0.8.x banner.
- **Status**: Left open as a frontier edge in case the .dmg path (#120) has a different mechanism.

## Causal chain (confirmed)

`older rustfava installed → _download_wasm cached v0.8.x wasm at version-agnostic path → user upgraded rustfava → engine.py now expects v0.11.0 JSON-RPC interface → invokes stale v0.8.x wasm → wasm sees no subcommand argv → clap prints "Usage: rustledger-ffi-wasi <command>..." to stderr, exits 0 with empty stdout → engine.py raises RustledgerError("Empty response: ...") → desktop frontend's 6-second waitForServer times out → user sees "Failed to open file: Server failed to start"`

## Proposed fix shape

1. **Version-pin the cache filename**: change `Path(__file__).parent / "rustledger-wasi.wasm"` → `Path(__file__).parent / f"rustledger-wasi-{RUSTLEDGER_VERSION}.wasm"`. Every version bump triggers a one-time re-download; old files become garbage-collectable.
2. **Coordinate with desktop bundle**: update `.github/workflows/desktop-release.yml` to write the wasm to the version-pinned filename so the bundled .dmg path matches.
3. **Optional sweep of stale caches**: on engine init, glob `rustledger-wasi-*.wasm` siblings of the active file and unlink any that don't match the current version. Cheap, reduces disk creep.

This is a **library-author fix**, not a user-workaround. The user-side workaround is "delete the cached `.wasm` and let it re-download", but that doesn't scale.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Empty-stdout + banner-on-stderr exactly matches v0.8.x wasm | Induction (ran the exact perturbation) | 98% |
| v0.11.0 wasm cannot produce that banner | Induction (tried no-stdin, --help, junk args) | 95% |
| Cache filename is version-agnostic and gated on existence only | Deduction (read engine.py:64-68) | 99% |
| User has a stale wasm from a prior rustfava install | Abduction from the above | 90% |
| Version-pinned filename fixes the root cause | Deduction (changes the gate variable) | 95% |
| Desktop .dmg case (#120) has the same root cause | Abduction (same stderr would, but #120 didn't post the engine stack trace) | 65% |

## Graph state

| Node | Status | Trajectory |
|---|---|---|
| H₀ port conflict | killed | divergent against |
| H₁ wasmtime regression | killed | divergent against |
| H₂ stale wasm cache | **confirmed** | divergent for (byte-match) |
| H₃ quarantine on cached wasm | open (low priority) | predicted divergent against |

## Pruning log

- H₀ killed by reporter's `-p 5009` followup (their experiment, not mine).
- H₁ killed by my local perturbation with wasmtime 44.0.1 + v0.11.0 wasm.

## Routing

- Bug exists across ALL platforms whenever a user upgrades rustfava across a `RUSTLEDGER_VERSION` boundary. macOS reporters see it because the desktop frontend's generic "Server failed to start" alert is the most visible failure mode; CLI users hit the same `Empty response` trace.
- Fix is small (one f-string + workflow update), but it touches a release artifact path, so it deserves maintainer review before shipping. Filing as a **tissue** comment on #136 + #120 with the diagnosis and the proposed fix shape is the right next step. Do NOT auto-open a PR — the maintainer should choose the cache strategy (filename pin vs. sentinel file vs. content hash) and decide whether to coordinate the desktop-bundle rename.
