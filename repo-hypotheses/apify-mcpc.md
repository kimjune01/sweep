# Triage Graph: apify/mcpc

## Issue #55: Bridge credential timeout (5s) too short when macOS Keychain requires user password

**Status**: Fixed  
**Branch**: `fix/55-bridge-credential-timeout`  
**Commit**: 6a5cb18

### Root cause

Bridge process waits only 5 seconds for auth credentials via IPC (`src/bridge/index.ts:410`). 

Timeline when Keychain requires password:
1. Bridge spawns, creates socket, starts 5s credential wait
2. Main process detects socket
3. Main process calls `readKeychainOAuthTokenInfo()` → macOS dialog
4. User reads dialog, types password → **5-15 seconds**
5. Bridge timeout fires at 5s → bridge shuts down → socket removed
6. Main process gets credentials, tries to send → **ENOENT**

### Fix applied

Increased timeout from 5000ms to 60000ms in `src/bridge/index.ts:411`.

```typescript
// Before:
setTimeout(() => reject(new Error('Timeout waiting for IPC credentials')), 5000);

// After:
setTimeout(() => reject(new Error('Timeout waiting for IPC credentials')), 60000);
```

Updated comment from "5 seconds should be plenty for local IPC" to "60 seconds to allow for interactive macOS Keychain prompts".

### Alternative approaches considered

**Option A (preferred by maintainer)**: Read credentials before starting bridge  
- Read Keychain in main process before spawning bridge
- Pass credentials immediately after socket ready
- Zero credential wait time
- Requires architectural refactor

**Option C**: Remove timeout entirely  
- Bridge waits indefinitely
- No protection against hung IPC

**Option B (implemented)**: Increase timeout to 60s  
- Simple, low-risk change
- Adequate for interactive password prompts
- Still catches genuine IPC failures

### Evidence

Issue describes actual failure case:
- User clears `node` from Keychain ACL for `mcpc` entries
- Run `mcpc mcp.apify.com connect @session`
- macOS prompts for password
- Wait a few seconds → ENOENT

When "Always Allow" is clicked, `node` added to ACL permanently → `getPassword()` returns instantly → works within 5s.

### Test plan

No automated tests modified (existing tests don't exercise Keychain interaction). Manual validation:
1. Clear Keychain access for `node` to `mcpc` entries
2. Run `mcpc mcp.apify.com connect @session`
3. Wait 10+ seconds before entering macOS password
4. Verify connection succeeds (no ENOENT)

### Classification

- Bug fix: timeout too short for legitimate use case
- Single-line constant change
- No new features, no API changes
- Backwards compatible (longer timeout only helps, never breaks)
