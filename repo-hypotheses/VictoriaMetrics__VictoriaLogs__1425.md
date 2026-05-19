# VictoriaMetrics/VictoriaLogs#1425 — misleading regex parse error

## Issue
Query `field:~"(?i)\$"` returns:

```
cannot parse `query` arg: cannot read regexp for field "field": compound token cannot start with "\""; put it into quotes if needed; context: [field:~"]; query=field:~"(?i)\$"
```

hagen1778 suspects `\` flips the parser into "raw" mode and `"` gets reported as a denied compound token.

## H₀ — abductive cause (lexer fallback discards the real error)

**Hypothesis.** The lexer at `lib/logstorage/parser.go` switches on the leading `"` and calls `strconv.QuotedPrefix(s)`. For `"(?i)\$"`, `\$` is not a valid Go escape, so `QuotedPrefix` returns `invalid syntax`. The lexer silently falls back to emitting `"` as a single-char unquoted token via `nextCharToken(s, 1)`. Downstream, `nextCompoundTokenExt` sees `"` as a non-word non-glue token starting a compound, and emits the misleading "compound token cannot start with `\"`" message.

**Perturbation.** Run `strconv.QuotedPrefix` on adjacent inputs:

```
"(?i)\$"     -> err: invalid syntax     (lexer falls back here)
"(?i)\\$"    -> OK
"(?i)$"      -> OK
"foo\bar"    -> OK                       (\b is a valid Go escape)
```

**Trajectory.** Divergent in favor. `QuotedPrefix` is exactly the gate that rejects the user's input, and the fallback at parser.go:305-319 is exactly where the meaningful error vanishes. Reproduced verbatim against the worktree.

**Provenance.** The `case '"', '`':` branch at parser.go:305 and `case '\'':` at parser.go:320 both swallow `strconv` errors. The compound-token error site at parser.go:131 then fires on the bare quote char. No related open PRs (`logsql improve` search).

## Fix shape

Preserve the real quote-parse error in the lexer and surface it through the downstream compound-token error path.

1. Add `quoteErr error` field to `lexer`.
2. In `nextToken`, clear it on each invocation.
3. In the `"`/`` ` ``, `'` branches, set `lex.quoteErr = fmt.Errorf("cannot parse quoted string starting with %s: %w", quotedStringPreview(s), err)` before falling back to `nextCharToken`.
4. In `nextCompoundTokenExt`, return `lex.quoteErr` instead of the generic "compound token cannot start with..." message when it is set.

Minimal change (~25 LOC). General — same message improvement applies to any parser path that would have accepted a quoted token.

### After the fix
```
cannot parse `query` arg: cannot read regexp for field "field": cannot parse quoted string starting with "\"(?i)\\$\"": invalid syntax; context: [field:~"]; query=field:~"(?i)\$"
```

The error now names the parse mode (quoted string), the offending input, and the underlying reason.

## Phase 5.5 — regression check

- `go test ./lib/logstorage/ -count=1` — pass (7.1s).
- `go build ./...` — clean.
- `go vet ./lib/logstorage/` — clean.
- New regression test `TestParseFilterRegexp_MalformedQuotedString` covers `"`-quoted and `'`-quoted malformed escapes; asserts the error names "cannot parse quoted string" and does not contain the misleading "compound token cannot start with" wording. Backtick quoting is Go's raw-string mode (accepts arbitrary backslashes); not affected and intentionally excluded.

## Graph state

| Node | Status | Shape | Edge |
|------|--------|-------|------|
| H₀: lexer fallback drops `strconv` error → misleading compound-token error | confirmed | divergent | implement fix in lexer + surface in compound-token path |

Frontier closed.

## Reasoning mode

| Claim | Mode | Confidence |
|-------|------|------------|
| `strconv.QuotedPrefix("\"(?i)\\$\"")` returns `invalid syntax` | induction | 99% |
| Lexer falls back to single-char token on quoting failure | deduction (parser.go:305-319) | 99% |
| `nextCompoundTokenExt` then emits the misleading message | deduction (parser.go:130-132) | 99% |
| Preserving the quote error is the minimal user-visible fix | abduction | 90% |
