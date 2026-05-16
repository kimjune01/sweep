# dotnet/vscode-csharp#8307 — Comment after preprocessor directive scopes everything as `meta.preprocessor`

**Status:** Reframe — already fixed upstream. No PR warranted.

## H₀ — Repro

Issue claims that:
```cs
#if true //
_ = 0;
#endif
```
causes `_ = 0;` to be tokenized as `meta.preprocessor.cs`. JoeRobich (maintainer) confirmed in a comment.

Filed: 2025-05-20. Labels: Bug, help-wanted. Milestone: Backlog.

## H₁ — Grammar lives in `dotnet/csharp-tmLanguage`, not in vscode-csharp

**Perturbation:** grep `package.json` of `dotnet/vscode-csharp` for C# grammar registration.
**Result:** vscode-csharp registers only `aspnetcorerazor` and `xaml` grammars. No `source.cs`. VS Code bundles the C# grammar built-in, sourced from `dotnet/csharp-tmLanguage`.
**Trajectory:** divergent — venue for fix is `dotnet/csharp-tmLanguage`, not vscode-csharp.
**Mode:** deduction (read manifest). Confidence: 99%.

## H₂ — Root cause in grammar: `#comment` consumes EOL, blocks preprocessor `end` pattern

**Perturbation:** read `src/csharp.tmLanguage.yml`. The `preprocessor` block uses `end: (?<=$)`. Inner patterns include `#preprocessor-comment` (or, in old version, the generic `#comment`). Old `#comment` line-comment match was `(//).*$` — consumed the trailing newline, so the outer `(?<=$)` never matched, causing the preprocessor scope to bleed into subsequent lines.
**Trajectory:** convergent.
**Mode:** deduction. Confidence: 95%.

## H₃ — Already fixed upstream (PR #348, merged 2025-12-19)

**Perturbation:** `gh pr list --repo dotnet/csharp-tmLanguage --search "preprocessor"`.
**Result:**
- Issue dotnet/csharp-tmLanguage#335 — "Line comments right after preprocessor directives break highlighting" (CLOSED).
- PR dotnet/csharp-tmLanguage#348 — "Fix preprocessor directive highlighting when followed by line comments" — MERGED 2025-12-19.
- Fix: introduced a dedicated `preprocessor-comment` rule that does **not** consume the end-of-line marker, swapped the generic `#comment` includes for `#preprocessor-comment` inside preprocessor scopes. Confirmed present in current `src/csharp.tmLanguage.yml` at line 3499 / 3513.
**Trajectory:** divergent — upstream fix is real and shipped.
**Mode:** induction (queried repo state). Confidence: 95%.

## H₄ — Fix is propagated to VS Code's bundled grammar

**Perturbation:** `curl https://raw.githubusercontent.com/microsoft/vscode/main/extensions/csharp/syntaxes/csharp.tmLanguage.json | grep -c preprocessor-comment` → 3 occurrences.
**Trajectory:** divergent — fix is in VS Code main as of today (2026-05-16, ~5 months post-merge).
**Mode:** induction. Confidence: 95%.

## Provenance

- Bug commit: pre-existing pattern (`(//).*$` line-comment), in place since the grammar's introduction. Not a recent regression.
- Upstream fix author: copilot coding agent + JoeRobich review. JoeRobich is also the maintainer who triaged vscode-csharp#8307.
- Adjacent: the same JoeRobich confirmed the bug on vscode-csharp#8307 in May 2025 and the upstream fix landed Dec 2025. The vscode-csharp issue was simply never closed after the upstream fix propagated.

## Reframe (Phase 4.5)

Original framing — "produce a fix PR for vscode-csharp#8307" — is **retired**. The fix:

1. Could not land in vscode-csharp (wrong repo).
2. Already landed in dotnet/csharp-tmLanguage#348 (the correct repo).
3. Is already synced into microsoft/vscode's bundled grammar.

There is no productive PR to write. The correct downstream action is to comment on the issue noting the upstream fix and asking the reporter to verify against a current VS Code build; the maintainer can then close.

## Graph state

| Node | Status | Shape | Mode |
|------|--------|-------|------|
| H₀ repro | confirmed (by maintainer) | — | induction |
| H₁ grammar venue | confirmed | divergent | deduction |
| H₂ root cause | confirmed | convergent | deduction |
| H₃ upstream fix exists | confirmed | divergent | induction |
| H₄ fix in VS Code main | confirmed | divergent | induction |

## Frontier

- Verify the reporter's VS Code + extension version (their build may predate the grammar sync). No code action required from us — this is a maintainer triage step.

## Decision

**No PR.** Drop or surface as a "looks already fixed upstream — please verify" comment. Flag for `/drip` as informational only, not a PR candidate.
