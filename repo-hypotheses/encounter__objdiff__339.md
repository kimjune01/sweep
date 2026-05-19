# encounter/objdiff#339 — objdiff.json parsing fails on Windows with absolute paths

## H₀ — Report: target_path `D:/Games/.../foo` becomes `D:Games\...\foo`

User reports: configuring an absolute Windows path `"target_path": "D:/Games/BlackAndWhite/openblack/..."` produces an error `Target path 'D:Games\BlackAndWhite\openblack\...`. The slash between drive letter and root path is missing — a drive-relative result, not absolute. Build dispatch fails because the (broken) path doesn't `strip_prefix(project_dir)`.

**Trajectory: divergent.** The bug is mechanical and reproducible from the report.

## H₁ — Slash-to-backslash conversion is component-wise re-encoding

JSON deserializer parses `target_path` as `typed_path::Utf8UnixPathBuf` ([objdiff-core/src/config/mod.rs:104](https://github.com/encounter/objdiff/blob/main/objdiff-core/src/config/mod.rs#L104)). Conversion to `Utf8PlatformPathBuf` happens at five join callsites (gui/app.rs, gui/config.rs, cli/cmd/diff.rs, cli/cmd/report.rs, core/jobs/create_scratch.rs) via `path.with_platform_encoding()`.

`with_platform_encoding` re-encodes by walking components. The Unix parser has no concept of a Windows drive prefix, so `D:/Games/foo` becomes three `Normal` components `["D:", "Games", "foo"]`. The Windows encoder pushes `D:` as a drive prefix without RootDir, then appends the rest with `\` separators → `D:Games\foo`. Drive-relative, not absolute.

**Perturbation (typed-path 0.12, host-agnostic via `Utf8WindowsPathBuf`):**

```
direct (Utf8WindowsPathBuf::from(str)): "D:/Games/BlackAndWhite/foo.o"  abs=true
with_encoding (component-wise reencode): "D:Games\BlackAndWhite\foo.o"  abs=false
```

**Trajectory: divergent confirmed.** The kill condition for the old conversion is "produces a drive-relative path for any drive-rooted input."

### Provenance

The pattern `path.with_platform_encoding()` is consistent across the codebase; this is an inherited default for the unix→platform bridge, not a deliberate design choice for the drive-letter case. The submitter's note in the issue (`Objdiff automatically converts the forward slashes to backslashes ... but misses the one on the root drive`) names the failure mode precisely.

`Utf8PlatformPathBuf::from(&str)` is already used in `objdiff-core/src/config/path.rs` for the `platform_path` argp helper — so passing the raw string to the platform parser is an established idiom in the same file.

## H₂ — Fix shape: parse the raw string with the platform parser, don't re-encode by components

`Utf8PlatformPathBuf::from(unix_path.as_str())` on Windows is `Utf8WindowsPathBuf::from(str)`, whose parser recognises `D:/` as a drive root and accepts `/` as a separator. On Unix it's `Utf8UnixPathBuf::from(str)` — identical to the previous behavior.

Helper: `objdiff_core::config::path::from_unix_path(&Utf8UnixPath) -> Utf8PlatformPathBuf`. Replaces every `path.with_platform_encoding()` callsite where the source is `Utf8UnixPath` (the JSON-config side). Untouched: `path.with_unix_encoding()` callsites (different direction; relative-only, no drive concern).

### Regression check

- Two unit tests in `config::path::tests` lock in: (a) the platform parser preserves drive root, (b) component re-encoding loses it. Both use `Utf8WindowsPathBuf` directly so they run cross-platform.
- One `#[cfg(windows)]` test exercises `from_unix_path` itself on Windows.
- `cargo check -p objdiff-gui` and `cargo build -p objdiff-core -p objdiff-cli` clean.

For relative paths (`objects/foo.o` — the common case), both old and new paths yield a usable result: old normalized separators to `\`, new keeps `/`. Windows file APIs and `typed-path` strip_prefix accept both, so no functional regression. Tests confirm.

## Graph state

| Node | Status   | Trajectory | Reasoning |
|------|----------|------------|-----------|
| H₀   | observed | divergent  | report    |
| H₁   | confirmed | divergent | induction (reproduced via standalone typed-path script) |
| H₂   | confirmed | divergent | induction (tests pass, build clean) |

## Frontier

None remaining for this issue. Drive-letter paths that *don't* include the root slash (`D:foo` — actual drive-relative) are still parsed as drive-relative under the new code, matching Windows semantics. The bug is closed by the fix.

## Reasoning modes

- H₀: induction from user report.
- H₁: deduction (read code, traced encoding) + induction (perturbation reproduced both behaviors).
- H₂: deduction (typed-path API guarantees) + induction (tests pass).
