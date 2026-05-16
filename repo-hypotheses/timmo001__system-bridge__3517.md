# timmo001/system-bridge#3517 — Crash when building from source on macOS

**Issue:** Panic in `data.(*DataStore).saveModuleData` while persisting module data — `reflect: call of reflect.Value.Int on string Value`. Reporter on macOS 15.6.1 (M4), Go 1.24.6. The "Getting displays data" log line precedes the panic.

## H₀ — Plain serialization of `[]types.Display` via viper.WriteConfig is broken on macOS

- **Null:** Serialization is fine; another data shape is responsible.
- **Perturbation:** Mirror `saveModuleData` exactly — viper.New + SetConfigName/Type + AddConfigPath + Set("module"/"data"/"updated") + WriteConfig. Run twice (first → SafeWriteConfig, second → WriteConfig over existing file).
- **Result:** Wrote OK both times. JSON is well-formed. No panic.
- **Shape:** Convergent (against H₀). The bare serialization path of a `[]Display` with the same fields does not panic.
- **Kill condition:** H₀ killed. The bug is not "viper+json can't write []Display."
- **Edge:** Data must differ from the trivial case at runtime — either real macOS data has a value that trips the encoder, or the slice contains something other than `types.Display`.

## H₁ — Real macOS CoreGraphics displays produce a value that trips json encoder

- **Null:** macOS CGO path yields plain ints; encoding works.
- **Perturbation:** Re-ran the displays_darwin.go body verbatim on this M-series Mac (2 active displays). Built with the same viper/json path, looped 5 iterations.
- **Result:** 5 successful iterations. Display IDs ("3", "1"), Resolutions (3008×1692, 1728×1117), pointers set. No panic.
- **Shape:** Convergent (against H₁) on this hardware/build.
- **Kill condition:** Not the CGO data shape under nominal conditions. Still possible under a specific multi-display/hotplug/sleep timing that we did not hit.
- **Edge:** State or context other than the immediate Display values — concurrent modification, stale loaded data, or a different module's data wearing the "displays" log line.

## H₂ — Another module's saveModuleData panicked; "Getting displays data" is interleaved log noise

- **Why this matters:** 3 worker goroutines pull from the queue (`update.go:60-69`). All modules get queued every tick (`update.go:172-178`). Logs from concurrent workers interleave.
- **Test against trace:** `data/data.go:227` is in `saveModuleData`; the trace bottoms at `structEncoder({{... 0xb ...}}, ...)` — 0xb = 11 fields. Among slice-of-struct module data types, only `types.Display` has exactly 11 fields (per `awk` field count over `types/`). `CPUData` and `MemoryVirtual` also have 11 fields but are encoded as a single struct, not as a slice element (`map → interface → slice → array → struct`).
- **Shape:** Divergent against H₂. The 11-field struct in a slice is almost certainly `Display`.
- **Edge:** Back to the Display path, but at non-nominal state.

## H₃ — Stale data from `loadModuleData` survives into `saveModuleData`

- **Why plausible:** `GetModule` (data.go:73-99) lazily calls `loadModuleData` when `module.Data == nil`. `loadModuleData` uses `viper.Unmarshal(m)` against an existing on-disk `displays.json`. The decoded `Data any` becomes `[]any` of `map[string]any` with JSON numbers as `float64` (mapstructure default). It is then written back into the registry.
- **However:** Both write paths (`SetModuleData`, `TriggerModuleUpdate`) replace `module.Data = data` before `saveModuleData`. So loaded shape is overwritten by fresh `Update()` output before save.
- **Open hole:** Is there ANY path where the loaded data reaches `saveModuleData` without `Update()` first? Grep finds none in current code. But the registry's previous-loaded data sits there until the first worker tick replaces it — if a different writer (e.g., a hand-rolled refresh, a future bus subscriber that calls Set on the underlying slice) mutated the in-place loaded slice, it would still be overwritten on save.
- **Shape:** Convergent against H₃ in current code. Worth re-checking after any refactor.

## H₄ — `bus.Publish` of `safeModule` races with concurrent JSON encoding of the same `module.Data`

- **Setup:** `SetModuleData` constructs a `safeModule` sharing `module.Data` (the same interface header) and publishes on `bus`. Subscribers can encode `safeModule.Data` concurrently with `saveModuleData`'s encode.
- **But:** Both readers see the same `[]Display` backing array. `encoding/json` is safe for concurrent reads. `module.Data = data` does not mutate old values; it replaces the interface. No torn struct fields.
- **Shape:** Convergent against H₄. Race exists in `GetAllModuleData` (no lock) but not in the encode path.

## H₅ — Go 1.24.6 encoding/json bug with interfaceEncoder → structEncoder cache

- **Why considered:** The panic ("intEncoder selected, String value") is structurally impossible from analysis alone — `Value.Field(i)` carries the field's declared type. Either the type cache is corrupt or the value passed to structEncoder is not the declared type.
- **Status:** No known Go 1.24.x issue matching this fingerprint in a brief search. Plausible but unverified.
- **Shape:** Open (cannot test on the user's machine).

## Provenance check

- `types/displays.go` last touched in commit `dea48568` ("Rebuild in Go #3391"). Schema has been stable.
- `data/data.go` last touched in `d32f8cd` (lock file maintenance — unrelated). The save/load code path is the original Go rewrite.
- No upstream viper issues found for this exact panic. viper's `Codec.Encode` is just `json.MarshalIndent` on a `map[string]any` — no transformation layer that could cast int↔string.
- No competing PR addressing this issue (`gh pr list` empty for related searches).

## Diagnosis (partial)

The crash is real, the call stack unambiguous, but the data shape required to produce `intEncoder on string Value` from a `[]types.Display` is not reachable via the analyzed code paths nor reproducible on a stock M-series Mac. The most actionable hypotheses are:

1. **Per-system state** — the reporter's persisted `displays.json` (or another module's persisted file) is in a state that, when re-loaded via `loadModuleData` and re-saved without first being refreshed by `Update`, hits the encoder bug. We can't yet identify the route.
2. **Defensive fix is independent of root cause.** A worker goroutine panic terminates the whole process. `saveModuleData` should `recover()` and log the offending module/data shape so the next occurrence yields a diagnostic instead of a crash.

## Recommended next perturbations (frontier)

- **E1 — Ask the reporter for `displays.json` contents.** A single file dump from `~/Library/Application Support/system-bridge/data/displays.json` (and a `ls -la` of the data directory) would convert this from speculative to reproducible. **Predicted shape:** divergent (the file will either parse to a normal Display shape, killing H₃, or contain something unexpected, confirming it).
- **E2 — Add `recover()` to `saveModuleData` and log `fmt.Sprintf("%#v", m.Data)` on panic.** Ships a defensive fix that also produces diagnostics for future occurrences. **Predicted shape:** divergent on the next crash (the recovered log names the field/value).
- **E3 — Replace `viper.WriteConfig` with direct `json.MarshalIndent` + `os.WriteFile`.** Cuts the dependency on viper's allSettings + flattening for what is just a leaf-key write of three fields. Doesn't fix the underlying issue but reduces surface area and matches the codec's actual behavior. **Predicted shape:** convergent (no behavior change in normal cases, simpler code).
- **E4 — Run system-bridge with `-race` for a few hours on the reporter's machine.** If H₄ or some other race is real, the race detector will name the offending offset. **Predicted shape:** divergent if a race is the cause; convergent (no race output) otherwise.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| Panic site is `saveModuleData` via `viper.WriteConfig` → `json.MarshalIndent` | Deduction (stack trace) | 99% |
| 11-field struct in slice ⇒ `types.Display` | Deduction (field count over types/) | 95% |
| Bare `[]Display` viper round-trip does not panic | Induction (synthetic repro) | 95% |
| Real M-series Mac CGO path does not panic | Induction (live repro, 2 displays) | 90% |
| Cause is per-system state or Go-runtime edge | Abduction (residual) | 50% |
| `recover()` in `saveModuleData` would prevent process crash | Deduction (Go semantics) | 99% |

## Pruning log

- H₀ (bare serialization broken) — killed by synthetic repro.
- H₁ (CGO data inherently bad) — killed by live repro on M-series Mac.
- H₂ (wrong module attributed) — killed by 11-field match to Display.
- H₃ (stale-load + no-refresh save) — killed in current code; flagged for re-check on refactor.
- H₄ (concurrent encode race) — killed by `[]Display` immutability semantics.
- H₅ (Go encoding/json bug) — open; cannot test without reporter access.

## Status

**Frontier open.** No PR shippable without either a reproducer (E1/E4) or the defensive fix (E2/E3) — both viable. The defensive fix is the cheapest decisive perturbation that produces value for users on the next occurrence; ship it standalone rather than block on reproducing the original bug.
