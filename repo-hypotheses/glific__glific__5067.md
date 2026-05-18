# Hypothesis Graph — glific/glific#5067

**Issue:** [#4848](https://github.com/glific/glific/issues/4848) — `create_and_send_message` accepts requests with omitted `type` + `nil` body, persisting null-body messages that crash the frontend (TypeError, logs users out).

**PR:** [#5067](https://github.com/glific/glific/pull/5067) — author: `kimjune01`; state: OPEN, mergeable, REVIEW_REQUIRED; CI green (CodeRabbit + GitGuardian); branch `fix/4848-require-type-in-message-input`.

**Reporter / author check:** issue by `shijithkjayan` (different account), PR by `kimjune01`. No self-PR halt.

## Causal chain

H₀ (observation, confirmed) → H₁ (Option 1 preferred, killed by H₂) → H₂ (Option 1 breaks update_message, confirmed) → H₃ (function-level guard, confirmed and shipped) → H₄ (assertion specificity, frontier).

## Graph state

| Node | Hypothesis | Status | Trajectory | Provenance |
|------|-----------|--------|-----------|------------|
| H₀ | Null-body message persists when `type` omitted; test fails on master | **Confirmed** | Divergent | commit `98902b6fc` ("test: reproduce #4848 — nil body accepted when type is omitted (fails on master)") |
| H₁ | Maintainer prefers Option 1: `non_null(:message_type_enum)` on `:message_input` | **Confirmed** | Divergent | Issue #4848 body: "Option 1 (make type required) is preferred" |
| H₂ | `non_null` on `:message_input` breaks `update_message` mutation (input shared) | **Confirmed (kill of H₁)** | Divergent against H₁ | `lib/glific_web/schema/message_types.ex:277` and `:314` both `arg(:input, :message_input)`; revert commit `c0920f5ac` ("revert non_null on message_input type to avoid breaking update_message mutation") |
| H₃ | Function-level guard in `create_and_send_message/1` catches the omitted-type case without touching schema | **Confirmed and shipped** | Divergent | commit `c0920f5ac`; test in `test/glific/messages_test.exs:759-780` passes |
| H₄ | CodeRabbit nitpick: assert specific error string `"Could not send message with empty body"` instead of `{:error, _}` | **Frontier (open)** | Predicted convergent — trivial improvement | CodeRabbit review on commit `c0920f5ac` (line 759-780) |
| H₅ | Hybrid: introduce `:create_message_input` (non_null type) separate from `:message_input` for update | **Frontier (open)** | Predicted oscillatory — addresses H₁ but expands scope; risks breaking other callers (`create_and_send_message_to_group` etc.) | `message_types.ex:271,283` show 3+ mutations share `:message_input` |
| H₆ | Inline comments in the new guard clause violate "no WHAT comments" heuristic | **Frontier (low-priority)** | Predicted convergent if pruned | `lib/glific/messages.ex:263-264` two comment lines explain mechanics already conveyed by the pattern match |

## Reasoning modes

| Claim | Mode | Confidence |
|-------|------|-----------|
| Test fails on master, passes with fix (H₀, H₃) | Induction (git history shows ordered commits; CI green on latest) | 95% |
| Option 1 breaks update_message (H₂) | Deduction (read schema, both mutations arg same input) + induction (commit message documents the breakage) | 95% |
| Maintainer prefers Option 1 (H₁) | Deduction (issue body explicit) | 99% |
| Hybrid input objects would work (H₅) | Abduction (no test run, would need separate prework) | 65% |

## Frontier edges (cheapest decisive perturbation first)

1. **H₄ — assert specific error string.** Cheapest. Tightens test, addresses CodeRabbit's one open comment, matches existing convention in `messages.ex:260` (sibling clause returns same string). Expected trajectory: divergent improvement.
2. **H₆ — drop the two explanatory comments.** Trivial. Pattern is self-documenting; the commit message carries the "why."
3. **H₅ — hybrid input objects.** Highest scope, lowest leverage given Option 2 already addresses AC. Defer unless maintainer pushes back.

## Provenance

- The non_null attempt and its revert are both already in PR history — maintainer can see the discovery trail in the commit log, which preempts the "why didn't you do Option 1?" review comment.
- `:message_input` is used by `create_message`, `create_and_send_message`, `create_and_send_message_to_group`, and `update_message`. Schema-level non_null would have broken at least the last one.

## Pruning log

- **H₁ killed by H₂**: schema-level fix attempted (commit `07b47f1a4`), reverted same-session after the `update_message` regression was traced. The kill condition generated H₃ (function-level guard) which shipped.

## Recommendation

Apply H₄ (one-line test tightening). H₅ and H₆ are deferrable. The PR's runtime-guard approach is the minimum-scope path consistent with the "go with the flow" rule — Option 1 was tried, hit a real regression, and the function-level guard is the natural Elixir-idiomatic fallback (matches the existing `%{body, type: :text}` clause directly above it at `messages.ex:260`).
