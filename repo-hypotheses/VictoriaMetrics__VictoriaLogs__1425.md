# VictoriaMetrics/VictoriaLogs#1425 — logsql: improve regex parsing error message

**Issue:** `field:~"(?i)\$"` produces `compound token cannot start with "\""; put it into quotes if needed`, which is misleading — the string IS in quotes.

## H₀ — Baseline observation

**Hypothesis:** The lexer fails to parse the quoted string `"(?i)\$"` because `\$` is not a valid Go escape sequence, falls back to treating `"` as a single-char token, then `nextCompoundToken` rejects it with a misleading message.

**Perturbation:** Run `strconv.QuotedPrefix("\"(?i)\\$\"")` directly.

**Result:** `err=invalid syntax`. Confirmed.

**Trajectory:** Divergent — strconv rejects the input because `\$` is not in Go's escape table (`\\`, `\"`, `\n`, etc.). The lexer at `parser.go:304-319` falls through silently to `nextCharToken(s, 1)`, producing a bare `"` token. `nextCompoundTokenExt` at line 130 then issues the unhelpful error.

**Reasoning mode:** Deduction (read + reproduce). Confidence 98%.

## Causal chain

1. User writes `field:~"(?i)\$"`.
2. parser reaches `parseFilterTilda` which calls `lex.nextCompoundToken()`.
3. Inside `nextToken`, `r == '"'` branch calls `strconv.QuotedPrefix(s)`.
4. Go's strconv treats `\$` as an invalid escape (Go strings require `\\$` for backslash+dollar). Returns `invalid syntax`.
5. The error is discarded; lexer falls to `lex.nextCharToken(s, 1)`, returning a token of just `"`.
6. `nextCompoundTokenExt` calls `isAllowedCompoundToken` which returns false for `"` (not isWord, not in glueCompoundTokens).
7. Error: `compound token cannot start with "\""`.

The misleading message: it tells the user to put the token in quotes — but the token IS the leading quote of an already-quoted string. The real diagnosis (invalid Go escape) is lost.

## Fix shape (Phase 5)

Surface the strconv error instead of swallowing it. In `nextToken` (`parser.go:304-319`), when QuotedPrefix or Unquote fails on `"`/`` ` ``, store the error on the lexer. Upstream `nextCompoundTokenExt` consults this and emits a meaningful diagnostic.

**Diff sketch (lexer.go):**
- Add `tokenErr error` field on `lexer`.
- In `nextToken`, set `lex.tokenErr` with strconv message when quoted parse fails. Also try to find the closing quote (best-effort) to include the offending substring.
- In `nextCompoundTokenExt` (and any other consumer that issues a "compound token cannot start with" / "cannot read X" error), check `lex.tokenErr` first and surface it.

Expected new error:
```
cannot parse `query` arg: cannot read regexp for field "field": cannot parse quoted string starting at `"(?i)\$"`: invalid syntax: \$ is not a valid escape sequence (use \\ for a literal backslash); context: [field:~"]; query=field:~"(?i)\$"
```

**Test (TestParseQuery_Failure):**
- `f(\`field:~"(?i)\\$"\`)` — already errors today; fix doesn't change pass/fail.
- Add a dedicated `TestParseQuery_BadQuotedString` checking the error text contains "quoted string" / "invalid syntax", so the message improvement is locked in.

**Regression risk:** Changes only error message paths; no semantic changes. All existing tests are pass/error existence checks (per TestParseQuery_Failure pattern). Low risk.

## Provenance

- `parser.go:304-319` — quoted-string branch. Last touched ~by VM team for compound-token unification.
- `parser.go:130` — the misleading error message.
- No prior PRs found addressing this specific phrasing.

## Frontier edges

- Open: are there other call sites that swallow `strconv.QuotedPrefix` error and produce misleading messages (e.g., single-quote path at 320-335, regex/pipe arg parsing)? Likely yes — the same fix-shape applies.
- Open: backtick token `` ` `` has the same hazard. Cover both in the fix.

## Status

- H₀: confirmed (divergent).
- Fix shape: grounded.
- Implemented in `lib/logstorage/parser.go` (+34 lines): added `tokenErr` on lexer, captures strconv error when `"` / `` ` `` / `'` quoted-string parse fails, surfaces it in `nextCompoundTokenExt` ahead of the generic compound-token error. Added `quotedStringPreview` helper that finds the apparent closing quote so the diagnostic includes the offending substring.
- Tests: extended `TestParseQuery_Failure` with the issue's exact case (and two siblings); added `TestParseQuery_BadQuotedStringMessage` to lock in the "quoted string" wording.
- Verified: full `go test ./lib/logstorage/` passes in 7.6s.

**Before:**
```
cannot read regexp for field "field": compound token cannot start with "\""; put it into quotes if needed; context: [field:~"]
```

**After:**
```
cannot read regexp for field "field": cannot parse quoted string "\"(?i)\\$\"": invalid syntax; context: [field:~"]
```

