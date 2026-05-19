# aymericzip/intlayer#381 — Cookie not set on Safari (and Chrome) localhost

**Repo**: aymericzip/intlayer
**Issue**: #381 — "Cookie no set on Safari localhost"
**Reporter**: 6aKa (Feb 2026). Second reporter: oliviercperrier (Chrome, same symptom).
**Maintainer status (aymericzip, Feb-25)**: "had several tries, still without solution. I will pass for that issue for now."

## H₀ — Baseline observation

`routing: { storage: ['cookie', 'header'] }` + `useLocaleStorage().setLocale(...)` produces the `x-intlayer-locale` header but **no cookie**. `localStorage` / `sessionStorage` variants work. So the bug is on the cookie-write path only.

- **Trajectory**: divergent — clean bisection by storage type.
- **Edge**: locate the client-side cookie writer and audit it.

## H₁ — Client writes cookies via `cookieStore.set()` injected by IntlayerProvider

**File**: `packages/@intlayer/core/src/localization/getBrowserLocale.tsx:26-34`

```ts
setCookieStore: (name, value, attributes) =>
  cookieStore.set({
    name, value,
    path: attributes.path,
    domain: attributes.domain,
    expires: attributes.expires,
    sameSite: attributes.sameSite,
  }),
setCookieString: (_name, cookie) => {
  document.cookie = cookie; // fallback
},
```

The caller is `setLocaleInStorageClient` in `packages/@intlayer/core/src/utils/localeStorage.ts:150-174`:

```ts
if (options?.setCookieStore) {
  try {
    options.setCookieStore(name, locale, {...});
  } catch {
    try {
      options.setCookieString?.(name, buildCookieString(name, locale, attributes));
    } catch {}
  }
}
```

- **Reasoning mode**: deduction (read the code).
- **Confidence**: 95%.

## H₂ — `cookieStore.set()` returns a Promise; the sync try/catch cannot observe async rejection

`cookieStore.set()` is async — the [spec](https://wicg.github.io/cookie-store/#CookieStore-set) returns `Promise<undefined>`. Per the WICG/Chrome shipping notes and Safari's 18.4 release, the call resolves/rejects asynchronously.

The wrapper in `setLocaleInStorageClient` is a synchronous `try { ... } catch { fallback }`. The synchronous portion of `cookieStore.set()` succeeds (it just queues the operation and returns a Promise). The Promise is **discarded** (not returned, not awaited, no `.catch` attached). If it rejects, **the `setCookieString` fallback never runs** — and the cookie is silently dropped, matching the reported symptom (no error, no cookie).

**Perturbation (mental)**: trace the control flow for the two failure paths:

| Scenario | sync throw? | catch runs? | fallback runs? | cookie set? |
|----------|-------------|-------------|----------------|-------------|
| Browser w/o cookieStore (old Firefox/Safari pre-18.4) | yes (ReferenceError) | yes | yes | yes (via document.cookie) |
| cookieStore exists, `set()` resolves | no | no | n/a | yes |
| cookieStore exists, `set()` **rejects asynchronously** | **no** | **no** | **no** | **no** ← bug |

- **Reasoning mode**: deduction.
- **Trajectory**: divergent — the bug requires a specific control path (async rejection) that the current code does not handle.
- **Confidence**: 90%.

### Why does Safari reject?

Plausible causes (any of them produce the same symptom):

1. **`domain: undefined`**: per the CookieStore spec, `domain` must be a string or omitted; explicitly passing `undefined` may throw `TypeError` on stricter implementations. Safari's WebKit implementation is known to be stricter on argument validation than Chrome.
2. **`sameSite: undefined`**: same issue. Spec default is `'strict'`; explicit `undefined` is non-canonical.
3. **`expires: undefined`** mixed with absent `maxAge`: edge case in attribute resolution.
4. **Safari ITP path matching**: Safari's cookieStore implementation may reject when path-resolution disagrees with the document's path (the call is made from `IntlayerProvider`, which may run at a non-root path during HMR).

Chrome's symptom (per oliviercperrier) is the same — Chrome's cookieStore is more lenient on `undefined` attributes but Chrome's ITP-equivalent (intent-to-implement) and DevTools network panel both show cookies that briefly appear and disappear when SameSite/Secure attributes mismatch the request context.

### Provenance

- `getBrowserLocale.tsx:26` (`cookieStore.set`): added in commit history when the storage-injection refactor split the cookie writer between `IntlayerProvider` and the storage layer. cookieStore preferred over `document.cookie` because it's the "modern" API.
- `setLocaleInStorageClient` try/catch/fallback: written assuming `setCookieStore` is synchronous-throw-or-succeed. This assumption is wrong for `cookieStore.set` (Promise-returning).
- monolithed (May-17) flagged "cookies set client-side, Safari ITP expires them" — different failure mode (early expiry, not missing-on-write). monolithed's "set cookies at middleware level" is a bigger structural change and not the minimal fix for this specific bug.

## H₃ — Minimal fix: dual-write OR catch async rejection

Two viable shapes:

**Fix A (minimal at injection site)**: Make `setCookieStore` re-throw on async rejection so the outer `setCookieString` fallback runs. But the outer catch is sync — it can't observe the rejection no matter what the inner function does. So Fix A must do the fallback *itself* inside the lambda.

**Fix B (minimal at consumer)**: In `setLocaleInStorageClient`, call BOTH `setCookieStore` (best-effort) AND `setCookieString` (guaranteed). The two writes are idempotent (same name + same value); the second overwrites the first cosmetically. This is the standard belt-and-suspenders pattern used by libraries like js-cookie when bridging the two APIs.

**Fix B is preferred** because:
- The fix lives in `setLocaleInStorageClient`, which is the abstraction that already knows about both APIs.
- No change to the public contract of `setCookieStore` (still typed `=> void`).
- Works for all three failure modes (cookieStore missing, sync throw, async reject).
- Does not require changing tests for `getBrowserLocale.tsx`.

The cost: every cookie write makes two API calls instead of one. Negligible.

The symmetric fix applies to the deprecated `setLocaleInStorage` and the server-side `setLocaleInStorageServer` (though server-side doesn't have the async-Promise problem — `res.cookie` is sync). For minimality, fix only the client path.

- **Reasoning mode**: abduction → deduction (compared against alternatives).
- **Confidence**: 80% the fix resolves the user-visible symptom for at least one of {Safari, Chrome}; 50% it resolves both without browser-specific tweaks.

## Frontier edges (open)

- **Cannot reproduce locally** — the substrate has no Safari, no Chrome with a live IntlayerProvider mounted. Verification requires a maintainer or community user with the affected setup.
- **Which Safari version**: reporter didn't say. Safari 18.4+ has cookieStore; earlier versions don't. If the reporter's Safari is <18.4, the bug is the ReferenceError path — but that's already caught by the sync try/catch and falls back. So either the reporter is on 18.4+ (matching H₂), or there's a *second* bug where the fallback's `document.cookie = cookie` also fails. The buildCookieString helper at `localeStorage.ts:54-69` only emits `Expires=` if `attributes.expires instanceof Date` — but in this codepath, `attributes.expires` is typed `number | undefined`, never a Date. So the fallback creates a **session cookie** (no Expires). That should still be visible in DevTools; not a candidate explanation for "no cookie."
- **The `attributes.expires` type mismatch**: `CookieBuildAttributes.expires: number | undefined` (line 47) but `buildCookieString` checks `instanceof Date`. Dead branch — but separate, not load-bearing here.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| Bug is on cookie-write path only | Induction (reporter bisected) | 99% |
| cookieStore.set returns Promise | Deduction (spec) | 99% |
| Sync try/catch cannot observe async rejection | Deduction | 99% |
| Safari rejects for `undefined` attributes | Abduction | 60% |
| Fix B (dual-write) resolves user symptom | Abduction | 80% |

## Pruning log

- **H_alt (Safari ITP expires after 7d)** — monolithed's hypothesis. Rejected as primary cause: reporter says cookie is never set, not "set then expires." ITP shortens lifetime; it doesn't block writes. May be a *secondary* concern long-term but not what #381 reports.
- **H_alt (Provider not mounted on Safari)** — would also break localStorage variant, but localStorage works. Killed.
- **H_alt (setLocale called before hydration)** — would affect all three storage backends, killed.

## Recommendation

Ship Fix B (dual-write in `setLocaleInStorageClient`) as a small PR. Body should:
- State the bug shape (Promise rejection unobservable via sync catch).
- Note the fix is defensive — covers both async-reject and sync-throw paths.
- Acknowledge inability to verify on Safari locally; ask maintainer/reporter to confirm against #381 repro.
- Link to spec / WICG cookieStore doc for the Promise behavior.

The fix is one ~10-line diff in `localeStorage.ts`. No test added — there's no existing test file for `localeStorage.ts`, and unit-testing browser cookie behavior requires jsdom + a mocked `cookieStore` that simulates async rejection (high-effort scaffolding for one line of behavior). Note this in the PR body. If maintainer requests a test, add one.

## Halt — human gate

Standalone mode (user invoked `/investigate` directly, no triage pipeline detected). Diagnosis written, fix shape grounded, but:

- No browser available in this environment to verify the fix actually resolves Safari/Chrome behavior.
- Maintainer himself is stuck ("I will pass for that issue for now") — this is a known-hard, community-help-needed bug.
- The fix is plausible but unconfirmed; shipping a speculative client-cookie patch to a 5k+ ⭐ repo without a repro is the wrong move.

**Operator decision needed**: approve writing the dual-write patch + opening a PR with the diagnosis, or hand off to a contributor who can repro on actual Safari first.
