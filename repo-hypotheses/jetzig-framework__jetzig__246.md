# jetzig-framework/jetzig#246 — Cookie parsing broken (Zig 0.14.1)

**Verdict:** No fix to ship. Maintainer-resolved version-mismatch issue.

## H₀ — Cookies.parse on `main` mishandles `name-with-dash=value`

- **Null:** `Cookies.parse` correctly parses `ownfusion-token=abc123` and stores under that key.
- **Perturbation:** Read `src/jetzig/http/Cookies.zig` on `main` (HEAD `0987e0b`), trace the loop for the reporter's input shape; review existing test cases.
- **Trajectory:** Divergent for null. Parse loop accumulates key chars until `=`, value chars until `;` or end-of-string, then `put`s under the unmodified key. `-` is not specially handled in the key path. The `parseFlag` short-circuit only fires for reserved attribute names (domain, path, samesite, secure, httponly, partitioned, expires, max-age); `ownfusion-token` does not match. Existing tests `basic cookie string`, `cookie string with irregular spaces`, `domain=example.com` all cover the same shape.
- **Kill condition:** No bug present on current `main`. H₀ killed.
- **Mode:** deduction (read the code).
- **Confidence:** ~95%.

## H₁ — Reporter is on an unsupported jetzig × zig combination

- **Null:** `main` builds and runs cookie parsing on Zig 0.14.1.
- **Perturbation:** Inspect imports on `main`: `Cookies.zig` line 6 uses `std.Io.Writer`, line 3/177/181 use `std.ArrayList` / `.empty` / `.append(allocator, ...)` API (Writergate-era / 0.15-style). `std.Io.Writer` was introduced in the Writergate cycle (Zig 0.15-dev). Zig 0.14.1 ships `std.io.Writer` (lowercase `io`) and the old ArrayList API.
- **Trajectory:** Divergent for H₁. `main` cannot compile on Zig 0.14.1. The reporter must be running a snapshot from the `zig-0.14` branch or an older tag.
- **Maintainer corroboration:** Cohors1316 in-thread: "You'll have to use the zig-0.14 branch for that version of zig. Writergate forced a lot of major changes that are not backwards compatible."
- **Reporter accepted:** "If this supports 0.15 now, I'll see about updating instead, thanks!"
- **Kill condition:** None — H₁ confirmed.
- **Mode:** deduction + induction (maintainer testimony, accepted by reporter).
- **Confidence:** ~95%.

## Graph state

| Node | Status | Shape |
|------|--------|-------|
| H₀ (bug on main) | killed | divergent for null |
| H₁ (version mismatch, maintainer-resolved) | confirmed | divergent for H₁ |

## Frontier edges

None. The issue is resolved by the maintainer's recommendation (use `zig-0.14` branch or update Zig to 0.15). Reporter accepted.

## Reframe

This is a support thread, not a defect. The `main`-branch cookie parser is fine. The right action is to halt; there is nothing to PR upstream that the maintainer hasn't already addressed in-thread.

## Pruning log

- H₀ killed by code read at `0987e0b`: parse loop handles `name-with-dash=value` with and without trailing `;`; existing tests cover the same shape with `foo=bar`.
- No prework, benchmark, or bug hunt initiated — diagnosis halted at Phase 4 (Report) because no fix is warranted.
