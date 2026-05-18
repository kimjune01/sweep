# Hypothesis Graph: mike-engel/jwt-cli#459

**System under investigation:** PR #459 "feat: support unsecured JWTs (alg: none, RFC 7519 s6.1)" — fixes upstream issue #253.
**State:** PR open, mergeable, no reviews, no comments. CI = `action_required` (fork PRs need maintainer approval). Branch: `fix/unsecured-jwt-253`.
**Question:** What review risks does the shipped diff carry? Where will the maintainer push back?

## H₀ — baseline

- **Observation:** PR exists, tests added (encode unsecured, decode RFC 7519 example, roundtrip), JSON output schema preserved for non-unsecured tokens.
- **Perturbation:** Read the diff + cross-reference with upstream issue #253 thread.
- **Trajectory:** Convergent. The mechanical change matches the RFC: empty signature on encode, signature-skip on decode, `--secret` made optional when alg is none.
- **Edge:** Where does the diff *exceed* or *diverge from* the maintainer's stated preferences in #253?

## H₁ — Missing `--unsecured` opt-in flag (likely review nit)

- **Hypothesis:** The maintainer or filer will request an explicit opt-in (`--unsecured`) on both encode and decode, because the issue text says so.
- **Provenance:** Issue #253 (felschr, 2023-04-06): *"Instead of `jwt encode --alg=none` the CLI could also expose this functionality via `jwt encode --unsecured` to make the security implications more obvious. Additionally, `jwt decode` could also require an `--unsecured` argument and throw a validation error if not provided when decoding an unsecured JWT."* Reasoning mode: **deduction** (read the source). Confidence: ~90%.
- **Null:** Maintainer accepts `--alg none` as sufficient signal.
- **Perturbation (not run):** Wait for maintainer feedback; if requested, add `--unsecured` as a required gate on decode.
- **Trajectory shape:** Pending — open frontier edge.
- **Kill condition:** Maintainer merges without comment, or explicitly approves the `-A none` form.
- **Edge:** If raised, add `--unsecured` to both `EncodeArgs` and `DecodeArgs`. Encode: require it when `--alg=none`. Decode: require it when input JWT has `alg: "none"`; otherwise return a validation error. This is the maintainer's exact suggested shape; do not negotiate.

## H₂ — Silent `unwrap_or(HS256)` fallback in `decode_token`

- **Hypothesis:** When user passes `--alg none` but the JWT is *not* unsecured (header has a real alg), `translate_algorithm(alg).unwrap_or(Algorithm::HS256)` silently substitutes HS256 with no error. This masks user error.
- **Location:** `src/translators/decode.rs`, line where `algorithm` is computed after the `is_unsecured_jwt(&jwt)` early-return.
- **Provenance:** Reasoning mode: **deduction** (traced the consequences). Confidence: ~95%.
- **Null:** This branch is unreachable because `is_unsecured_jwt` returns false here, so the original behavior is preserved.
- **Trajectory:** Divergent against the null. The branch IS reachable when `--alg=none` is passed alongside a non-unsecured JWT. But pre-existing `decode_token` already silently picks HS256 when the header alg is unparseable, so this matches established convention. Not a regression, but worth flagging.
- **Kill condition:** None — the behavior matches existing code shape.
- **Edge:** Leave as-is. If raised in review, propose tightening the fallback in a follow-up.

## H₃ — `TokenOutput.header` type change (false alarm)

- **Hypothesis:** Changing `TokenOutput.header` from `jsonwebtoken::Header` to `serde_json::Value` breaks the `--output json` schema for existing consumers.
- **Perturbation:** Compare serialized output. `Header` derives `Serialize` and emits `{"alg": "...", "kid": "...", ...}`. `serde_json::to_value(&data.header)` produces the same map. The CLI JSON output is byte-identical.
- **Trajectory:** Divergent against the hypothesis. **Killed.**
- **Provenance:** Reasoning mode: **deduction** (read jsonwebtoken::Header derive macros + diff). Confidence: 95%.
- **Edge:** None. Internal test assertions changed from `header.alg == Algorithm::HS256` to `header["alg"] == "HS256"` — Rust-side test ergonomics only, no behavioral change.

## H₄ — RFC 7519 compliance

- **Hypothesis:** Encoded output and decode validation match RFC 7519 Section 6.1.
- **Perturbation:** `encode_unsecured_token` produces `header_b64.claims_b64.` (trailing dot, empty signature). `decode_unsecured_token` rejects non-empty signature parts. RFC example token (`eyJhbGciOiJub25lIn0.eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFtcGxlLmNvbS9pc19yb290Ijp0cnVlfQ.`) is tested.
- **Trajectory:** Convergent. **Confirmed.**
- **Provenance:** Reasoning mode: **induction** (test runs against RFC example). Confidence: 95%.

## H₅ — `Header::new(Algorithm::HS256)` placeholder smell

- **Hypothesis:** `decode_unsecured_token` constructs a `Header` with a fake `Algorithm::HS256` placeholder because `jsonwebtoken::Header` has no `none` variant. A reviewer may flag this as misleading.
- **Trajectory:** Convergent. The placeholder is never displayed — `raw_header` overrides it everywhere it reaches output. But it does propagate into `TokenData<Payload>.header` returned from `decode_token`, which any downstream consumer of `validated_token.header.alg` would mis-read as HS256.
- **Kill condition:** Search `print_decoded_token` and confirm `token.header.alg` is never read for unsecured branch. Confirmed in diff — output paths funnel through `raw_header`.
- **Edge:** Acceptable as-is. Document with a comment if maintainer asks. Reasoning mode: **deduction**. Confidence: 90%.

## Graph state

| Node | Status | Shape | Reasoning mode |
|------|--------|-------|----------------|
| H₀ | confirmed | convergent | deduction |
| H₁ — `--unsecured` opt-in missing | **open frontier** | pending | deduction |
| H₂ — silent HS256 fallback | confirmed (matches existing convention) | convergent | deduction |
| H₃ — JSON schema breakage | **killed** | divergent against | deduction |
| H₄ — RFC compliance | confirmed | convergent | induction |
| H₅ — `Header::new(HS256)` placeholder | confirmed (cosmetic) | convergent | deduction |

## Frontier edges

- **H₁ (highest leverage):** Maintainer requests `--unsecured` opt-in. Predicted classification: divergent (clear ask). Pre-drafted fix shape: add `--unsecured` boolean to both `EncodeArgs` and `DecodeArgs`; gate alg=none on its presence. **Don't act preemptively** — the maintainer's 2023 comment was "happy to review PR" without re-asserting the flag preference; the asymmetric risk is over-engineering before signal arrives. Wait for review.

## Pruning log

- **H₃** killed: header JSON output is byte-identical; the type change is Rust-internal.
- **H₂** retained but downgraded: matches existing fallback shape in the same function.

## Halt rationale

PR is shipped (Phase 8 done before this investigation). No new perturbation is reachable until the maintainer responds or CI is approved. The graph documents the load-bearing review risk (H₁) so /drip / amend can act quickly if maintainer raises it. No code change recommended.
