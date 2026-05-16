# Triage Graph: Aider-AI/aider (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 3702 | --no-verify-ssl fails for gemini/openrouter | OPEN | 8.45 | Small (2 lines) | paul-gauthier labeled "priority" | INVESTIGATED |

## T3702: --no-verify-ssl fails for gemini/openrouter backends

### Root Cause

`aider/main.py:522` sets `os.environ["SSL_VERIFY"] = ""` (empty string). Providers using litellm's shared `client_session` work because aider also sets `httpx.Client(verify=False)`. But gemini, openrouter, and anthropic create per-request httpx clients via litellm's `get_ssl_verify()`, which reads `SSL_VERIFY` from env. Empty string falls through `str_to_bool("")` as `None`, so `""` is passed to `httpx.Client(verify="")` — httpx interprets that as a CA-bundle path, triggering `CERTIFICATE_VERIFY_FAILED`.

### Fix (2 lines production, +2/-1 test)

1. `aider/main.py:522`: Change `os.environ["SSL_VERIFY"] = ""` → `os.environ["SSL_VERIFY"] = "False"`
2. `aider/main.py` after 523: Add `litellm._lazy_module.ssl_verify = False` (belt-and-suspenders)
3. `tests/basic/test_ssl_verification.py:68`: Update assertion to match `"False"` + add `ssl_verify` check

### PR Viability: HIGH

- paul-gauthier labeled "priority" — he wants this fixed
- 2-line production change, net-zero complexity
- Existing test file covers this exact path
- **Risk:** diverdale posted diagnosis Apr 30 with a thumbs-down reaction. Check for competing PRs before submitting.

---

*Dry run — no remote side effects.*
