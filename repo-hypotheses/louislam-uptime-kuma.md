# Triage Graph: louislam/uptime-kuma

## Issue #6586: Push monitor retries not reset after heartbeat

**Status**: Fix implemented and committed  
**Branch**: `fix/push-monitor-retry-reset`  
**Commit**: 700d5dd3  
**Hypothesis**: H4-state (retry counter not reset on state transition)

### Evidence chain

1. **Symptom**: Push monitors with retry logic (e.g., 1 hour heartbeat interval, 25 retries) were not resetting their retry counter after receiving an UP heartbeat. When the monitor subsequently timed out due to no heartbeat, the retry counter continued from the previous value instead of starting fresh from 0.

2. **Database evidence from issue**:
   - Heartbeat ID 27383803: status=1 (UP), retries=0 ✓
   - Heartbeat ID 27383807: status=2 (PENDING), retries=24 ✗ (should be 1)

3. **Root cause**: In `server/model/monitor.js`, the push monitor timeout check (line 746) throws "No heartbeat in the time window" when transitioning from UP to DOWN. The catch block's retry logic (lines 982-990) increments `retries` without checking if this is a fresh UP→DOWN transition that should reset the counter.

4. **Fix**: Added a check in the catch block (before line 983) to reset `retries = 0` when:
   - Monitor type is "push"
   - Previous beat status was UP (accounting for upside-down mode)
   - Current beat is entering error state

### Code paths affected

- `/api/push/:pushToken` endpoint (`server/routers/api-router.js` line 47): handles incoming push heartbeats, calls `determineStatus()` which correctly resets retries on UP ✓
- `Monitor.beat()` (`server/model/monitor.js` line 726): timeout check for push monitors, throws exception on missing heartbeat
- Retry logic catch block (line 982): now includes UP→DOWN transition reset ✓

### Files changed

- `server/model/monitor.js`: 5 insertions in catch block retry logic

### Testing strategy

Manual testing would require:
1. Create push monitor with 1-hour interval, 25 retries
2. Send UP heartbeat via `/api/push/:token?status=up`
3. Wait for timeout (>1 hour + buffer)
4. Verify first timeout heartbeat has retries=1, not retries=25

No existing test coverage for push monitor retry behavior. Adding a test would require mocking time progression or setting a very short interval.

### Maintainer signals

Issue #6586:
- Clear reproduction steps with database evidence
- No competing PRs
- No maintainer comments yet
- Reporter actively uses push monitors (118 monitors total)

The fix is minimal (5 lines), addresses a clear logic bug with database evidence, and follows the existing pattern of checking `previousBeat.status` for state transitions.

---

## Issue #7359 — OAuth2 parameter token_type can be undefined

**Status:** fix committed, PR closed by maintainer  
**Labels:** bug, question  
**Hypothesis:** H3-protocol (RFC non-compliance in token response handling)

### Evidence chain

1. **Symptom:** OAuth2 monitors fail authentication against providers that omit `token_type` from token responses. The Authorization header becomes `"undefined <access_token>"`.
2. **Root cause:** Four separate code paths construct the Authorization header by concatenating `oauthAccessToken.token_type + " " + oauthAccessToken.access_token` without any fallback when `token_type` is undefined.
3. **Fix:** Applied `|| "Bearer"` fallback at all four construction sites:
   - `server/model/monitor.js` line 493 (initial OAuth2 auth)
   - `server/model/monitor.js` line 1212 (401 retry path)
   - `server/monitor-types/globalping.js` line 532
   - `server/monitor-types/websocket-upgrade.js` line 95

### Design decision: inline vs helper

Codex suggested centralizing the fallback into a helper function. Kept inline for this PR because:
- The fix is a single `|| "Bearer"` at each site — 4 characters added per site
- A helper would touch more files and add indirection for a one-liner
- If accepted, a follow-up refactor extracting `buildOAuth2AuthHeader(token)` can consolidate all four sites

### Risk assessment

- **Scope:** Authorization header construction only
- **Regression surface:** OAuth2 monitors; providers that DO return token_type are unaffected (|| short-circuits)
- **RFC compliance:** RFC 6749 section 7.1 specifies Bearer as the default token type
- **Test coverage:** Manual testing required against a provider that omits token_type

### Outcome

PR #7371 closed by maintainer. Finding a different issue for this triage run.
