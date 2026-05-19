# Hypothesis graph: stacklok/toolhive#5242

vMCP backend-init list-method tolerance: extend recovery from JSON-RPC `-32601` to HTTP-level method-missing signals (404 / 405 / 501) on `resources/list` and `prompts/list`, while keeping `tools/list` strict.

Issue framing already names the fix shape; investigation focuses on *where the HTTP signal actually shows up in the mcp-go error path*, which determines the predicate.

## H₀ — recovery happens inside `initAndQueryCapabilities`

- **Null**: recovery already covers HTTP statuses (issue is a wishlist).
- **Perturbation**: read `pkg/vmcp/session/internal/backend/mcp_session.go`, look at the two `switch` arms guarding `c.ListResources` and `c.ListPrompts`.
- **Trajectory**: divergent — only `errors.Is(listErr, mcp.ErrMethodNotFound)` recovers; everything else falls into the fatal `case listErr != nil` arm. Comment explicitly: "HTTP-level method absence is intentionally fatal."
- **Mode**: deduction. Confidence: 99%.
- **Edge**: H₁ — what shape does the HTTP-layer error take when it reaches that switch?

## H₁ — mcp-go's streamable-HTTP transport returns a string-message error for non-2xx, non-JSON-RPC responses

- **Null**: it returns a typed sentinel we can detect with `errors.Is`.
- **Perturbation**: trace `c.ListResources` → `Client.ListResourcesByPage` → `listByPage` → `Client.sendRequest` → `Transport.SendRequest` → `StreamableHTTP.SendRequest`. Read `client/transport/streamable_http.go` around the non-OK branch.
- **Trajectory**: divergent. Three error shapes for non-2xx responses:
  1. `*OAuthAuthorizationRequiredError` / `*AuthorizationRequiredError` for 401.
  2. `ErrLegacySSEServer` for 4xx on the Initialize request only.
  3. **For our case**: the transport reads the body, tries `json.Unmarshal` into a `JSONRPCResponse`; if that fails, returns `fmt.Errorf("request failed with status %d: %s", resp.StatusCode, body)`. That error is then wrapped in `transport.NewError` by `Client.sendRequest`, surfacing as `*transport.Error{Err: ...}`.
- **Mode**: deduction + induction (read code and ran the test to confirm). Confidence: 95%.
- **Edge**: H₂ — predicate shape: assert on `*transport.Error`, parse the status from the wrapped message. H₃ guards: SSE transport, special-case statuses.

## H₂ — predicate matches `transport.Error` + `"request failed with status N:"` substring

- **Null**: better signal exists (typed error per status).
- **Perturbation**: implement `isHTTPMethodMissing` matching on the wrapped `te.Err.Error()` for `404`, `405`, `501`. Run tests against a `fakeBackend` configured to respond with each status on resources/list / prompts/list.
- **Trajectory**: oscillatory — 405 and 501 cases recovered cleanly on first run; 404 *failed* with `"list resources failed: transport error: failed to send request: session terminated (404). need to re-initialize"`.
- **Mode**: induction. Confidence: 95% on 405/501; failure observed on 404.
- **Edge**: H₂ₐ — 404 takes a different code path in mcp-go. Find it.

## H₂ₐ — mcp-go short-circuits HTTP 404 into `ErrSessionTerminated` before the generic status path

- **Null**: 404 takes the same path as 405/501.
- **Perturbation**: grep for `StatusNotFound` in `streamable_http.go`. Read context.
- **Trajectory**: divergent. Lines 689-694: `if resp.StatusCode == http.StatusNotFound { resp.Body.Close(); c.sessionID.CompareAndSwap(sessionID, ""); return nil, ErrSessionTerminated }`. Runs *before* the JSON-body parse / generic status `fmt.Errorf`. `ErrSessionTerminated` is defined at line 970 as `fmt.Errorf("session terminated (404). need to re-initialize")`.
- **Mode**: deduction. Confidence: 99%.
- **Edge**: predicate must also `errors.Is(err, mcptransport.ErrSessionTerminated)`. Closes the loop on H₂.

## Provenance (Phase 2.5)

- **Origin of the existing recovery**: PR #5232 fixed issue #5231 (Atlassian Rovo). Comment in `mcp_session.go` explicitly notes "HTTP-level method absence is intentionally fatal" — i.e. the deferral is documented, this PR is the planned follow-up. Not a discovery; the issue body cites the review thread `r3211850406`.
- **mcp-go interaction**: `mcp-go@v0.54.0`. The 404 → `ErrSessionTerminated` behavior is a load-bearing detail; if mcp-go ever distinguishes session-termination from generic 404, our predicate will need to narrow. Documented in the predicate's doc comment so the next reader doesn't trip on it.
- **No competing PRs** for this issue (context pack confirms; search returned none).

## H₃ — does SSE need different handling?

- **Null**: SSE transport surfaces 4xx differently and our predicate misses it.
- **Perturbation**: grep `StatusCode` in `client/transport/sse.go`.
- **Trajectory**: convergent. Line 545: `return nil, fmt.Errorf("request failed with status %d: %s", resp.StatusCode, body)`. Same format as streamable-HTTP. SSE doesn't have the 404 short-circuit, but the generic path catches it.
- **Mode**: deduction. Confidence: 90% (no SSE integration test in this PR — left as a known gap).
- **Edge**: closes. Don't need a separate SSE branch in the predicate.

## H₄ — fix must keep `tools/list` strict

- **Null**: predicate accidentally relaxes tools/list too.
- **Perturbation**: leave `tools/list` arm unchanged (it never had `errors.Is(listErr, mcp.ErrMethodNotFound)` recovery in the first place); add `TestInitAndQueryCapabilities_ToolsListHTTPMethodMissingIsFatal` that asserts init aborts for 404 / 405 / 501 on tools/list.
- **Trajectory**: divergent (all three cases abort as expected).
- **Mode**: induction. Confidence: 99%.

## Graph state

| Node | Status    | Trajectory  | Mode      |
|------|-----------|-------------|-----------|
| H₀   | confirmed | divergent   | deduction |
| H₁   | confirmed | divergent   | ded+ind   |
| H₂   | refined   | oscillatory | induction |
| H₂ₐ  | confirmed | divergent   | deduction |
| H₃   | confirmed | convergent  | deduction |
| H₄   | confirmed | divergent   | induction |

## Frontier

- (closed) — predicate covers JSON-RPC -32601, `ErrSessionTerminated`, and `"request failed with status N:"` for 404/405/501. Regression guard for tools/list in place.
- (latent) Integration test against a real SSE backend with HTTP method-missing on resources/list. Not added; SSE deduction at H₃ deemed sufficient since the format string is identical.

## Pruning log

- H₂ as originally formulated (substring match alone) was killed by the 404 test failure. Replaced by H₂ + H₂ₐ together.

## Outcome

Single commit on branch `vmcp-http-method-missing`. Tests pass under both host go and the qa `sweep-tester:latest` container. Readiness record at `~/.sweep/triage-dry-run/5242-pr.md` for `/drip` to consume.
