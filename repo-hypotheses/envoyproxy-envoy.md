# envoyproxy/envoy PR #44981 — Hypothesis Graph (code dispute)

**PR**: https://github.com/envoyproxy/envoy/pull/44981
**Issue**: https://github.com/envoyproxy/envoy/issues/44111 (filed by @bbassingthwaite, assigned @cpakulski, label `bug`)
**Reviewer pushback**: @kyessenov 2026-05-13 — "Please fix DCO. I don't think system time is safe to use as a deadline, it's discontinuous."
**Posture**: code dispute. Verify before capitulating or pushing back. Replaces prior triage notes; PR is now in review-dispute state.

---

## H0 — systemTime is the correct fix for the cross-instance bug

**Verdict: CONFIRMED.**

Evidence:
1. **Original bug is real and user-visible.** Issue #44111 from @bbassingthwaite describes multiple Envoy instances behind an NLB; cookies issued by instance A are validated by instance B; B's `monotonicTime()` baseline is unrelated to A's, so cookies appear pre-expired and the upstream host is reselected — breaking session affinity. Reporter himself proposes `systemTime()` as the fix.
2. **Maintainer @cpakulski concurred** on the issue thread: "Your analysis makes sense. I do not remember exact reasoning behind usage of monotonic time, but am thinking that the design process did not take 1+ Envoys into account."
3. **Code under monotonicTime is structurally broken across processes by definition.** `std::chrono::steady_clock` (which `time_source_.monotonicTime()` wraps) has an implementation-defined epoch per the C++ standard — comparing values across processes is meaningless.
4. The PR makes both sides — `onUpdate` cookie write in `source/extensions/http/stateful_session/cookie/cookie.cc:22` and `onRequest` validation in `source/extensions/http/stateful_session/cookie/cookie.h:78` — use `systemTime()`, so the TTL math is symmetric on a single instance and meaningful across instances.

## H1 — systemTime is unsafe as a deadline because it's discontinuous (kyessenov's claim)

**Verdict: TRUE IN GENERAL, INAPPLICABLE TO THIS DEADLINE.**

The general statement is correct: `systemTime()` (= `std::chrono::system_clock`) can jump (NTP step, manual set, virtualization pause/resume). For *process-local* deadlines this is exactly the right reason to prefer `monotonicTime()`.

But the structural requirement here forces wall clock:

1. **The deadline crosses processes.** The cookie travels envoy-A → client → envoy-B. The only deadline both processes can agree on is one expressed in a shared epoch — wall clock. `monotonicTime()` is *defined* to be incomparable across processes; its epoch is unspecified and typically tied to boot time.

2. **Envoy's own precedents use `systemTime()` for exactly this shape:**
   - `source/extensions/filters/http/jwt_authn/authenticator.cc:257` — JWT `exp` validation: `absl::FromChrono(timeSource().systemTime())`. JWT crosses processes with a wire-format `exp`, identical structure to this cookie.
   - `source/extensions/filters/http/oauth2/filter.cc:605, 1145, 1174, 1205` — OAuth2 cookie `expires` is built from `time_source_.systemTime()`.
   - `source/extensions/filters/http/cache/upstream_request.cc:73, 219` and `cache_v2/cache_sessions_impl.cc:720, 863, 888` — HTTP cache freshness uses `systemTime()`.
   - `source/extensions/filters/network/redis_proxy/proxy_filter.cc:166`, `command_splitter_impl.cc:653, 1126` — Redis epoch comparisons use `systemTime()`.

3. **Every `monotonicTime()` precedent for an "expiry" or "deadline" in the tree is process-local:**
   - `source/extensions/filters/http/jwt_authn/jwks_cache.cc:159, 165` — cached JWKS validity within one process.
   - `source/common/grpc/buffered_message_ttl_manager.h:33` — in-process gRPC ack timeout.
   - `source/common/config/ttl.cc:66` — xDS resource TTL inside one envoy.
   - `source/common/http/http_server_properties_cache_impl.cc:107-112` — in-process HTTP/3 Alt-Svc cache.
   - `source/extensions/tracers/datadog/agent_http_client.cc:57` — in-process request deadline.

   Pattern is unambiguous: **process-local → monotonic; cross-process / wire-serialized → system.** The cookie is the latter.

4. **Clock-skew tolerance is operator-managed, not envoy's job.** Same convention as JWT and X.509: wall-clock expiries assume NTP-synced hosts. Standard NTP corrections are sub-second; cookie TTLs are minutes to hours. The "1-hour backward jump" failure mode would simultaneously break JWT, OAuth2, HTTP cache, certificate validation, and access-log timestamps — it's a fleet-wide event, not a stateful_session-specific risk.

5. **The objection, if accepted, would invalidate JWT/OAuth2/cache.** If `systemTime()` is unsafe for a cross-process deadline, then envoy's JWT `exp` check is also unsafe, and so is OAuth2 cookie expiry. The project has resolved this trade-off the same way the rest of the industry has.

kyessenov's review reads as a generic "system time is discontinuous" warning applied without checking whether the deadline is single-process or multi-process. It's the right warning for `jwks_cache`; it's the wrong critique for a wire-serialized cookie.

## H2 — third path (hybrid clock, monotonic-anchored-to-wall, server-side store)

**Verdict: NOT JUSTIFIED in scope of this bug.**

Considered:
- **Hybrid (monotonic interior + wall on serialization)**: pointless. At deserialization on a different host you must re-anchor to wall clock anyway, so the on-wire deadline is wall-clock either way.
- **Server-side session table keyed by opaque cookie id**: legitimate alternative *architecture*, not a clock fix. Out of scope for this bug; orthogonal feature.
- **HMAC-signed cookie with skew tolerance window**: cookie isn't signed today; adding signing is a separate proposal. The configured `ttl` is already the operator's tolerance window.

There is no clock primitive that gives both cross-process portability AND immunity to wall-clock discontinuity — the trade-off is intrinsic.

## H3 — original bug has a different root cause; fix is elsewhere

**Verdict: FALSIFIED.**

The bug is mechanically deterministic: `monotonicTime()` epoch is per-process, the cookie's `expires` field is an integer compared against `monotonicTime().time_since_epoch()` on a *different* process. Definitional mismatch, not symptom of something else. Reporter, maintainer, and the code path agree on the mechanism.

---

## Recommendation

**Push back, with evidence.** Acknowledge kyessenov's general principle (correct in the abstract), demonstrate that this specific deadline must be wall-clock because it crosses processes, cite the JWT and OAuth2 precedents in envoy's own tree.

DCO is a mechanical fix unrelated to the substantive question — handle after the design point is settled, to avoid muddying the thread.

## Provenance

- Repo: ~/Documents/envoy, branch `sweep-triage-1778364683`, base `upstream/main`
- PR diff: 2 files changed, 2 insertions/2 deletions in source; tests updated to `setSystemTime` to match.
- Files inspected: see citations above.
- Issue thread: envoyproxy/envoy#44111 (@bbassingthwaite report, @cpakulski concur).
- PR thread: envoyproxy/envoy#44981 (@kyessenov review 2026-05-13T17:45Z).
