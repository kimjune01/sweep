# ashn-dot-dev/mellifera#6 — JSON encode/decode non-determinism in Go impl

Issue: https://github.com/ashn-dot-dev/mellifera/issues/6
Investigated: 2026-05-16
Status: **HALTED at ship gate — maintainer No-LLM policy precludes a PR.**

## Halt condition (policy gate)

README.md §"Strict No LLM / No AI Policy":

> Mellifera is a language developed by humans, for humans. 🐝❤️
> Use of LLMs for issues, comments, and pull requests is not permitted.

Authored 2026-05-16 by the maintainer (commit `f46aee0`). The diagnosis, fix, and tests in this investigation were produced by an LLM. Pushing this branch as a PR would directly violate posted policy. **Do not ship.** A human contributor could re-derive the fix independently; the artifacts here are for the operator's reference only, not as PR material.

## H₀ — reproduce

Perturbation: run the issue's repro on the local Go build of mellifera at `f46aee0`.

```
~/test$ mf jsonbug.mf
encode → {"bar":456,"foo":123} (5×)   # reordered vs source
decode → {"foo": 123, "bar": 456} (5×) # stable on this machine, but issue reports flakiness on maintainer's
```

Trajectory: **divergent** — bug present and matches the report. Encode is deterministically reordered; decode happens to be stable on this machine but uses a Go `map[string]any` whose iteration order is randomized at runtime, so the maintainer's report of flakiness is consistent with the code. Mode: induction.

## H₁ — root cause (deduction from code read)

Two distinct holes, both routing through Go's unordered `map[string]any`:

| Site | File:line | Order loss |
|---|---|---|
| `json::encode` | `mellifera.go:9024` builds `map[string]any` from `*Map.Pairs()`; `json.Marshal` then iterates in random Go-map order | encode |
| `json::decode` | `mellifera.go:8966` `json.Unmarshal` into `map[string]any`; `jsonDecode` at `:8942` iterates the resulting Go map | decode |

`*Map` itself is an ordered linked-list-backed structure (`mellifera.go:1247`, `Pairs()` at `:1413`) — the language guarantees ordered maps. The bug is entirely in the JSON bridge layer.

Trajectory: **convergent**. Mode: deduction (95% confidence). Codex filter not run — the diagnosis is the maintainer's own and matches the code byte-for-byte.

## H₂ — fix shape

Bypass `map[string]any` in both directions:

- **decode**: `json.NewDecoder(...).UseNumber()` + recursive token-stream parser (`Token()` returns object keys in source order). Special-case nan/inf detection preserved via `*json.SyntaxError.Offset`. Trailing-data check added so behavior matches the old `json.Unmarshal` (which rejects trailing junk).
- **encode**: build `[]byte` directly; iterate `*Map.Pairs()` and `json.Marshal` each key and value individually, joining with `,` and `:`. Preserves source order at every nesting level.

Encoding/json (v1) is sufficient — no `GOEXPERIMENT=jsonv2` needed, as the issue hoped.

## Verification

- Full Go test suite: **218/218 pass** after the fix.
- Repro from the issue: encode and decode now both produce `{"foo": 123, "bar": 456}` deterministically across 5+ runs.
- Order-preservation round-trip locked in:
  - `json::encode(json::decode(\`{"z":1,"a":2,"m":3,"b":4}\`))` == `{"z":1,"a":2,"m":3,"b":4}`
  - Nested: `{"outer":{"z":1,"a":2}}` round-trips with inner order preserved.
- Existing `tests/json-encode.test.mf` had loose `=~` regex assertions and a `# XXX: Python and Go do not have compatible JSON implementations` comment that documented the non-determinism. Tightened to exact-string equality assertions; XXX removed.
- `tests/json-decode.test.mf`: added `.keys()` assertions that fail without order preservation.

Mode: induction (90%). Bug-hunt round (codex/gemini) skipped — see halt condition.

## Provenance

- Encode site introduced when `json::encode` was added; the maintainer already noted in `json-encode.test.mf` line 30 that the Go and Python outputs were "not compatible," i.e. they knew the encode side was unordered but had not fixed it.
- Decode site: same shape — `json.Unmarshal` into `map[string]any` is the default Go idiom and was never adapted to mellifera's ordered-map semantics.
- The `encoding/json/v2` package the issue mentions is not needed; the v1 token-stream API is enough.

## Local artifacts (not for upstream)

- Working tree at `/tmp/mellifera` with:
  - `mellifera.go` — `jsonEncodeBytes` replaces `jsonEncode`; `jsonDecodeValue`/`jsonDecodeFromToken` replace `jsonDecode`; `BuiltinJsonEncode` and `BuiltinJsonDecode` rewired.
  - `tests/json-encode.test.mf`, `tests/json-decode.test.mf` — tightened.
- Diff size: ~120 line net change in one file, plus test tightening.

## Frontier

None open from a technical standpoint. The frontier edge is the **policy gate**: this fix is not shippable from this operator under current maintainer rules. Options:
1. Drop the lead. Move on.
2. Note the diagnosis in a memory entry as a pattern (ordered-map host language + stdlib JSON = order loss bug) and leave the repo alone.
3. If the operator personally re-derives the fix without LLM involvement (separate from this work product), they may submit. The artifacts here cannot be the basis for that — they're already LLM-tainted under a strict policy reading.
