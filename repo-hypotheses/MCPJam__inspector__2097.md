# MCPJam/inspector#2097 — Hypothesis Graph

Investigation target: **PR #2097** — `fix(evals): pass custom provider configs through eval pipeline` (fixes #1515)

PR author: kimjune01 (substrate, standalone /investigate)
Issue reporter: ziondamore
Branch: `fix/custom-provider-evals`
Base: `main` (5 files, +520 / -377)
CI: snyk ✓ ✓ (only checks available, no test workflow runs)
Maintainer review: **none yet** (coderabbitai bot-review only)

Per-repo triage state for #1515 already in [MCPJam-inspector.md](./MCPJam-inspector.md).

## Causal chain (diagnosis already shipped in PR)

| Node | Hypothesis | Mode | Status |
|------|-----------|------|--------|
| H₀ | Custom-provider eval errors with "Please add your custom API key" even when the custom provider IS configured. | Induction (issue repro) | Confirmed by reporter |
| H₁ | Client-side credential gate has no "custom" slot in `useAiProviderKeys`; treats custom models as missing-key. | Deduction (code trace) | Confirmed |
| H₂ | Server pipeline only receives `customProviders` from org runtime config, not from request body. Local-mode users have no org runtime → providers never reach `createLlmModel`. | Deduction (code trace) | Confirmed |
| F₁ | Threading `customProviders` through `RunEvalsRequestSchema` → `runEvalSuiteWithAiSdk` → `runTestCase` → `resolveEvalModelRuntime` → `createLlmModel`, plus client-side credential recognition, fixes the gate. | Abduction → implementation | Shipped in PR |

## Frontier edges (CodeRabbit-generated abductions, **not yet classified**)

CodeRabbit posted 3 actionable comments (state: COMMENTED, not REQUEST_CHANGES). Per the skill rule "review findings are hypothesis generators," each gets a node.

### H₃ — Client over-sends customProviders payload
- **Claim**: `eval-runner.tsx:708-716` maps over **all** configured `customProviders` (including apiKeys) whenever `usesCustomProviders` is true, instead of filtering to the providers actually referenced by selected models.
- **Verified**: yes, diff confirms unconditional `customProviders.map((cp) => ({ ... apiKey ... }))`.
- **Trajectory**: divergent — finding is real.
- **Risk classification**:
  - Privacy: same-origin server already has access to user's settings store; not a leak per se, but a layering smell. Org-managed deployments where settings live on a different trust boundary than the eval runner *would* leak.
  - Correctness: harmless — server only consults customProviders entries that match the test's `customProviderName`. Unused entries are silently ignored.
- **Kill condition**: confirm no org-managed code path reads the request-body `customProviders` for unauthorized side effects. If clean → downgrade to nit. If contaminated → must filter.
- **Edge**: **defer** unless maintainer asks; the fix is one filter expression but it expands the diff's scope from "make custom providers work" to "and also lock down payload shape."

### H₄ — Single-test endpoints don't accept customProviders
- **Claim**: `server/routes/shared/evals.ts:89-99` defines `RunEvalsRequestSchema` (suite-run) with the new `customProviders` field, but `runTestCase` / `streamTestCase` schemas were not extended. Single-test runs of a custom-provider model still hit the "no key" gate.
- **Verified**: pending — diff search shows only `RunEvalsRequestSchema` at line 538 was extended; runTestCase/streamTestCase need confirmation.
- **Trajectory** (predicted): divergent. If reproduced, it's the same bug the PR claims to fix, just on a different endpoint.
- **Risk classification**: this is the *same* user-facing bug surviving on a sibling code path. Issue #1515 says "Click Run" — repro path is suite-run (matches the fix). Single-test path is a different UI entry not mentioned in the issue.
- **Kill condition**:
  - Pass: re-run extract.py against `runTestCase` endpoint with a custom-provider model — does it fail with the same "Please add your custom API key" error?
  - If yes → must extend the fix.
  - If no (different code path, no credential gate) → CodeRabbit overclaimed.
- **Edge**: **must verify before declaring PR complete.** This is the highest-leverage frontier edge.

### H₅ — Org-replace-not-merge drops request providers
- **Claim**: `evals-runner.ts:1513-1515` — `orgRuntime?.customProviders?.length ? orgRuntime.customProviders : args.requestCustomProviders`. Org-provided list **replaces** request-level list entirely; request-only providers (not in org config) are silently dropped.
- **Verified**: yes, diff confirms ternary replace.
- **Risk classification**: only triggers when **both** orgRuntime and request have customProviders. Issue #1515 is local-mode (orgRuntime undefined) → falls through to request branch → unaffected. Org-mode users who try to BYO custom providers on top of org-supplied ones lose theirs.
- **Trajectory**: divergent — finding is real, scope is narrow.
- **Kill condition**: does any org-managed customer (hosted MCPJam) currently rely on mixing org + request custom providers? Without that signal, this is speculative. Even if real, scope = different issue.
- **Edge**: **defer** — out of scope for #1515. File as separate issue if maintainer asks.

### H₆ (nitpick) — Mixed org/request precedence test
- CodeRabbit asks for a unit test covering H₅'s merge contract.
- Tied to H₅; if H₅ is deferred, H₆ is too.

## Provenance check

- `useAiProviderKeys` hook predates this PR. Adding "custom" as a credential source aligns with how the Settings page already classifies it.
- `customProviders` field on `RunEvalsRequestSchema` is new in this PR — no prior history to conflict with.
- No competing open PR found (`gh pr list --repo MCPJam/inspector --search "custom provider evals"` returns only this one).
- The 200-line stylistic churn (trailing-comma → no-trailing-comma) is incidental from a CI typecheck/lint run; it's noisy but per repo convention. Per "go with the flow," leave as-is.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| F₁ fix wires custom providers through suite-run | Deduction | 95% |
| H₃ over-sends payload | Deduction (diff confirms) | 95%; risk = 30% |
| H₄ single-test path missing | Abduction (pending verify) | 70% |
| H₅ org replace drops request | Deduction (diff confirms) | 95%; in-scope = 15% |

## Frontier classification

| Edge | Action |
|------|--------|
| H₄ — single-test endpoints | **Verify next.** Read `routes/shared/evals.ts` runTestCase/streamTestCase, check if credential gate fires for custom-provider models. |
| H₃, H₅, H₆ | **Defer.** File in MCPJam-inspector.md as known follow-ups; don't expand PR #2097 scope unless maintainer asks. |
| Maintainer review | **Wait.** No human reviewer has touched the PR yet (only bots). |

## Halt rationale

The diagnosis converged before the PR was opened (per MCPJam-inspector.md). The PR is in flight. The new evidence (CodeRabbit) introduces one frontier edge worth verifying (H₄) and two known-but-out-of-scope smells (H₃, H₅).

Per skill rule "If a PR exists: update it… never create duplicate PRs," and per the human-gate rule for Phase 8: any code change to address H₄ requires user go/no-go.

**Next step gated on user**: verify H₄ and if confirmed, decide whether to extend the PR diff or open a separate follow-up. H₃/H₅ left as documented frontier edges.
