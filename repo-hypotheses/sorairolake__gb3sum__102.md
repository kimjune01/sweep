# sorairolake/gb3sum#102 — Poor memory management

**Issue:** Hashing a multi-GB file causes gb3sum to consume all available RAM until the system thrashes / swaps. Reporter cites DirHash (C), GoHash (Go), Paq (Rust) as counter-examples that stream and stay flat.

**Authoritative comment (zeebo, author of `github.com/zeebo/blake3`):** "My blake3 library uses O(1) space to hash things and isn't the root cause. The root cause is here: app.go#L42 where it reads the full file into memory."

---

## H₀ — `readFile` slurps entire input via `io.ReadAll`

**Mode:** Deduction (read the code).
**Perturbation:** Read `app.go`.
**Observation:** `readFile` at `app.go:21–44` calls `io.ReadAll(reader)`, returning the entire file as a single `[]byte`. It is invoked from three sites:
- L83 — reading a checksum file (typically small, acceptable).
- L116 — reading the file being **verified** (could be GB).
- L227 — reading the file being **hashed** (could be GB).
In both L116 and L227 the resulting `[]byte` is passed to `hasher.Write(input)`. Peak RAM ≈ file size.
**Trajectory:** Divergent — code path matches reporter's symptom exactly; zeebo confirms it independently.
**Status:** CONFIRMED.

## H₁ — Streaming via `io.Copy(hasher, file)` is sufficient

**Mode:** Deduction.
**Perturbation:** `*blake3.Hasher` (zeebo's lib) implements `io.Writer` — `Write([]byte) (int, error)`. `io.Copy` will pull a 32 KiB buffer at a time from the file and feed it to the hasher. Peak RAM ≈ 32 KiB regardless of file size.
**Trajectory:** Divergent — matches reporter's reference implementations (DirHash/GoHash/Paq all stream).
**Status:** CONFIRMED.

## H₂ — Checksum-file slurp at L83 is fine to keep

**Mode:** Deduction.
**Observation:** Checksum files are human-authored, line-oriented, KB-scale. The subsequent code wraps the bytes in `bytes.NewReader` + `bufio.Scanner` to iterate lines, so a `[]byte` form is convenient. No memory pressure expected.
**Status:** CONFIRMED — leave L83 unchanged. Only L116 and L227 need streaming.

## Provenance check

- `git blame` (origin/develop, commit `02d91d5`): `io.ReadAll` path predates the issue; introduced when the tool was first written in 2024 by the maintainer (Shun Sakai). Not a deliberate design choice — just the standard "read whole file" idiom carried into the hashing loop.
- Sister tools by same maintainer (`gb2sum` etc.) likely have the same bug — out of scope for this PR; could be a follow-up.
- No competing PR addresses this issue (`gh pr list` survey: PRs #88–#108 are all dependabot / lint chores).
- CONTRIBUTING.adoc: git-flow, branch from `develop`, add a test if possible, update CHANGELOG. No LLM-authored policy.

## Diagnosis

Replace `readFile` + `hasher.Write` for the two hashing call sites (verify-mode L116, hash-mode L227) with an open + `io.Copy(hasher, reader)` helper. Keep `readFile` for the small checksum-file read at L83.

## Fix shape

```go
func hashFile(filename string, hasher *blake3.Hasher) (err error) {
    var reader io.Reader
    switch filename {
    case "-":
        reader = os.Stdin
    default:
        file, err := os.Open(filename)
        if err != nil { return err }
        defer func() {
            if e := file.Close(); e != nil { err = e }
        }()
        reader = file
    }
    _, err = io.Copy(hasher, reader)
    return err
}
```

L116–132 collapse to: `hasher.Reset()` (or re-`New()`) + `hashFile(checksum.unescapedFilename, hasher)`.
L227–232 collapse to: `hashFile(filename, hasher)`.

## Test plan

1. **Existing tests pass** (`go test ./...`) — correctness regression check.
2. **New regression test:** hash a temp file written from `bytes.Repeat` (e.g. 16 MiB), verify the digest matches the equivalent `hasher.Write(buf)` digest. Asserts streaming path produces identical output to the slurp path.
3. **Peak-memory assertion** (optional, fragile across platforms — skip; the streaming path is structurally O(1) by construction).
4. CHANGELOG entry.

## Implementation + measurement (2026-05-16)

Applied the fix on branch `fix/stream-large-files`. Added `hashFile(filename, io.Writer) error` that streams via `io.Copy`, swapped both hashing call sites, kept `readFile` for the checksum-file slurp at L83.

**Cross-check on 512 MiB random file:**
- master (`io.ReadAll`): peak RSS 1290911744 B (~1.29 GB)
- fix (`io.Copy`): peak RSS 5128192 B (~5.1 MB)
- ~250x reduction; digests identical
  (`389cd737d075b9c36d7536bf6449f6049c58a6659f67c041148f675acec5b6c9`)

**Regression test added** (`TestHashFileMatchesWrite`): hashes an 11 MiB temp file via `hashFile` and compares to `hasher.Write(payload)` on the same bytes. Passes on the fix branch.

`go test ./...` and `go vet ./...` pass.

## Frontier edges

- (out of scope) sister CLI tools by same maintainer likely share the bug — surface as follow-up.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| `io.ReadAll` causes O(N) RAM | Deduction | 99% |
| `io.Copy(hasher, reader)` fixes it | Deduction | 99% |
| L83 doesn't need changing | Deduction | 95% |
