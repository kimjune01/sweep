# bit-team/backintime#2438 — Scheduled cron backups silently no-op when `keyringrc.cfg` forces `kwallet.DBusKeyring`

## Issue summary

User on openSUSE Tumbleweed (KDE Plasma 6, Wayland). Three machines, all stopped running scheduled backups ~3 months ago (likely after a system update bumping `python-keyring`). Manual run of the same cron command works. Removing `~/.config/python_keyring/keyringrc.cfg` (which contained `default-keyring=keyring.backends.kwallet.DBusKeyring`) fixed scheduled runs. Local-only profiles also affected.

User's debug log ends at `[CLI::common/tools.py:1540 keyringSupported] Keyring config file directory: /home/user/.config/python_keyring` — the next line of `_check_if_keyring_is_supported` never appears.

## H₀ — Observation

**Claim:** With `default-keyring=keyring.backends.kwallet.DBusKeyring` forced in `~/.config/python_keyring/keyringrc.cfg`, BiT's backup daemon launched by cron does not complete its setup phase; removing the file restores scheduled backups.

**Null:** Forcing the kwallet backend is independent of the cron-vs-terminal startup path; the failure is elsewhere (e.g. cron PATH, DISPLAY).

**Perturbation:** User removed `keyringrc.cfg`. Scheduled backup ran successfully. Reinstating the file (implicit from the bug's prior state) reproduced the failure.

**Trajectory shape:** Divergent. The presence/absence of one config file flips the outcome cleanly; no oscillation, no partial behavior across machines (3-for-3).

**Kill condition for H₀:** A reproduction where keyringrc.cfg is absent and the backup still fails, or where keyringrc.cfg is present and the backup runs under cron. None reported.

**Edge:** Why does forcing `kwallet.DBusKeyring` break the cron-launched daemon when the same backend works from an interactive terminal?

**Reasoning mode:** Induction (user ran the experiment). Confidence ~92%.

---

## H₁ — Fan-out (root-cause candidates)

### H₁ₐ: Module-import-time keyring probe hangs on DBus

**Claim:** `KEYRING_SUPPORTED = _check_if_keyring_is_supported()` at `common/tools.py:1654` runs unconditionally on every import of `tools`. Under cron, no `DBUS_SESSION_BUS_ADDRESS` is set, so `keyring.get_keyring()` at line 1572 — which, with a forced backend, instantiates `kwallet.DBusKeyring` and then is used to compute `__module__` — blocks during subsequent DBus calls in either `backend.get_all_keyring()` (line 1579) or further-down callers.

**Perturbation:** Inspect the surviving log line (`Keyring config file directory:`) — that comes from line 1562. Lines 1576 (`Available keyring backends:`), 1637 (`Not found Metaclasses:`), 1638 (`Available supported backends:`) and either 1642 (`Found appropriate keyring`) or 1645 (`No appropriate keyring found`) should follow. User log shows none of them. Either user truncated, or the process hangs in 1572–1579.

**Trajectory shape:** Divergent (matches the truncation cleanly), but uncertain whether the log is genuinely cut off mid-process or just user-truncated. Needs verification.

**Status:** Likely. The module-load-time global means *every* invocation of `backintime` re-runs this probe — including pure-CLI calls that never need the keyring (local-only profiles, `backintime -h`, the inner `pw-cache` subprocess, the `qt_probing.py` helper). This explains why local-only profiles also break.

### H₁ᵦ: `Password_Cache` daemon hangs in `collectPasswords` → `keyring.get_password`

**Claim:** `password.Password_Cache.collectPasswords()` (`common/password.py:134`) iterates profiles, and for any profile with `passwordSave` + `keyringSupported` calls `tools.password(service, user)` → `keyring.get_password(...)`. With the forced kwallet backend in a cron context, `keyring.get_password()` opens the wallet via `org.kde.kwalletd5/6` over DBus. With no session bus reachable and no user to type the wallet password, the call blocks.

**Perturbation:** Reachable via SSH profiles with `passwordSave=true`. Wouldn't fire for purely-local profiles.

**Status:** Partial — explains SSH profile failure cleanly but does not explain why the user reports local-only profiles also break (unless the user's "local" profile still has `passwordUseCache=true`, which triggers `Mount.__init__` at `common/mount.py:148` to start the `pw-cache` subprocess; the subprocess re-imports `tools` → H₁ₐ).

### H₁ᵧ: `keyring` library version regression (~3 months ago)

**Claim:** A python-keyring update changed the semantics of `default-keyring=` in `keyringrc.cfg` such that forcing `kwallet.DBusKeyring` now eagerly attempts DBus initialization where it previously lazily deferred. Issue surfaces only in environments where DBus is unreachable (cron).

**Perturbation:** `pip show keyring` on the user's three machines, compared against the Tumbleweed package changelog around the regression date.

**Status:** Untested, but aligned with the "all three machines stopped simultaneously after a system update" observation. Distro-coordinated update is the most likely common cause.

### H₁ᵟ: Stale cron environment file (`cronEnvFile`)

**Claim:** `backintime` saves environment at last interactive session and reloads it for cron. If DBUS-related vars were absent when the env was snapshotted (or were stale), the cron run sees a broken DBus environment.

**Perturbation:** Inspect `~/.config/backintime/cron-env` (or equivalent) for `DBUS_SESSION_BUS_ADDRESS`.

**Status:** Possible amplifier, not the root cause. The user's interactive run succeeds *with* `keyringrc.cfg` present, so the interactive env is fine. Cron env is the variable.

---

## Phase 2.5 — Provenance check

- `common/tools.py:1654` (`KEYRING_SUPPORTED = _check_if_keyring_is_supported()`) — module-level call. `git blame` would show this dates to the original keyring support; the unconditional nature is not a recent regression on BiT's side.
- Related: issue [#1321](https://github.com/bit-team/backintime/issues/1321) — comment in tools.py line 1568 references it as the reason for calling `keyring.get_keyring()` here (to force `init_backend()` to fix non-available backends). Fix history is "call get_keyring() to coerce keyring into a usable state."
- Related: issue [#1330](https://github.com/bit-team/backintime/issues/1330) — discusses the keyringrc.cfg + chainer mess. Maintainer linked this issue (#2438) to #1330 in the comments. Backend selection from GUI is on the roadmap but not implemented.
- Related: issue [#1410](https://github.com/bit-team/backintime/issues/1410) — added ChainerBackend to BiT's allowlist. Comment block at tools.py:1599–1608 acknowledges chainer's "unwanted side-effects."
- Related: issue [#2423](https://github.com/bit-team/backintime/issues/2423) (closed) — `org.freedesktop.Notifications` DBus failure under similar headless contexts. Same family of bug.

**Risk assessment:** Touching the keyring probe is in a hot zone — multiple historical bugs cluster here (#1321, #1410, #2423). Any fix must preserve the GUI startup path's ability to detect keyring availability. The minimal-blast-radius fix is wrapping the probe in a timeout and/or making it lazy.

---

## H₂ — Refined diagnosis (current best)

The chain that fits all evidence:

1. **`keyringrc.cfg` forces `kwallet.DBusKeyring` as the sole backend**, bypassing the chainer.
2. **Under cron**, the launched `backintime` process inherits a cron environment with no usable DBus session bus address (no `DBUS_SESSION_BUS_ADDRESS`, and even if set, the bus may be gone or unauthorized for the cron PID).
3. **`tools.py` import** runs `_check_if_keyring_is_supported()` unconditionally. This probe calls `keyring.get_keyring()` (line 1572) and `backend.get_all_keyring()` (line 1579). With a forced DBus-bound kwallet backend, at least one of these triggers a DBus call that blocks (DBus client waits for a reply that never comes) — the `dbus-python` default timeout is 25 seconds *per call*, but kwallet's chained "open wallet" call can wait on user input indefinitely.
4. **Even local-only profiles fail**, because `Mount.__init__` (mount.py:148) starts a `pw-cache` subprocess for any profile with `passwordUseCache=true`. The subprocess re-imports `tools` and re-hits the same hang. Without cache, the main backup daemon waits indefinitely for the pw-cache to be ready.
5. **Three months ago** a `python-keyring` upgrade (or a kwallet backend revision) changed lazy → eager DBus access for the forced-backend path, surfacing what was always-latent.

This is **divergent** evidence — every observed fact is explained by this chain and no observed fact contradicts it.

**Confidence:** ~78%. Abductive — fits the evidence but no direct repro on Tumbleweed yet.

---

## Frontier edges (open experiments)

| # | Experiment | Predicted classification | Cost |
|---|-----------|-------------------------|------|
| F1 | On a Tumbleweed VM, reproduce with `keyringrc.cfg` present, run `backintime --debug backup --background` from cron, attach `py-spy dump` to the hung process. | Divergent — should see DBus call in the stack | 1–2h |
| F2 | Insert `signal.alarm(5)` around `keyring.get_keyring()` and `backend.get_all_keyring()` in `_check_if_keyring_is_supported`. Confirm the probe completes/aborts within 5s under cron. | Divergent | 30min |
| F3 | Inspect cron-env file the user's BiT saved (`tools.envSave(self.config.cronEnvFile())`). Look for `DBUS_SESSION_BUS_ADDRESS`. | If absent → confirms H₂ step 2 | User action |
| F4 | `pip show keyring` on Tumbleweed before and after the regression date (changelog dive) to confirm H₁ᵧ. | Identifies the upstream change | 1h |
| F5 | Make `KEYRING_SUPPORTED` lazy (compute on first read via a module-level descriptor / `__getattr__`). Verify local-only profiles no longer trigger the keyring probe at all. | Divergent improvement for local-only case | 1–2h to implement, needs Tumbleweed to verify |

---

## Proposed fix shape (not yet implemented — needs F1/F2 to confirm)

Two layers, both small:

1. **Make the keyring probe lazy and timeout-bounded.** `KEYRING_SUPPORTED` should be a property/function evaluated on first use, not at module import. Wrap `keyring.get_keyring()` and `backend.get_all_keyring()` in a watchdog (`signal.alarm` or a thread with timeout) so a hung DBus backend can't block the entire backup daemon. On timeout: log a clear error and return `False` (treat as "no keyring available").

2. **Detect non-interactive context.** If `os.getenv('DBUS_SESSION_BUS_ADDRESS')` is unset *and* `DISPLAY`/`WAYLAND_DISPLAY` are unset *and* the active backend's module name contains `kwallet` or `secretservice`, log a warning and skip the probe (return `False`). This prevents the hang entirely in cron-like contexts.

Both changes are localized to `_check_if_keyring_is_supported()` and the `KEYRING_SUPPORTED` constant. The Password_Cache and Password classes that consume `tools.KEYRING_SUPPORTED` already handle `False` gracefully.

---

## Graph state

| Node | Status | Trajectory | Note |
|------|--------|-----------|------|
| H₀ | Confirmed | Divergent | User-verified: removing keyringrc.cfg fixes it |
| H₁ₐ (import-time probe hangs) | Likely | Divergent (pending F1/F2) | Explains local-profile failure |
| H₁ᵦ (collectPasswords hangs) | Partial | Divergent for SSH only | Doesn't explain local-only failure alone |
| H₁ᵧ (keyring version regression) | Likely | Untested | Explains the "3 machines, simultaneous" timing |
| H₁ᵟ (stale cron env) | Possible amplifier | Untested | Not root cause |
| H₂ (combined chain) | Best current diagnosis | Divergent | All evidence fits; no direct repro yet |

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| Removing keyringrc.cfg fixes scheduled cron backup | Induction (user) | 92% |
| `_check_if_keyring_is_supported` runs at every `import tools` | Deduction (read code) | 99% |
| Cron env lacks DBUS_SESSION_BUS_ADDRESS | Abduction | 70% |
| `keyring.get_keyring()` + forced kwallet hangs in cron | Abduction | 65% |
| Three months ago, python-keyring changed lazy→eager DBus init | Abduction | 55% |
| Lazy + timeout-bounded probe will fix it | Abduction | 70% (pending Tumbleweed test) |

## Pruning log

- *No hypothesis killed yet.* H₁ᵦ partially demoted (doesn't alone explain local-only failure) but kept as a contributing factor.

## Next actions (autonomous skill halts here — Tumbleweed VM is the gating dep)

The investigation halts before Phase 5 (prework) because:
- **F1 requires a Tumbleweed VM with KDE Plasma 6 + kwallet** — the maintainer (buhtz) said in the issue thread they need to set one up themselves.
- Without local repro, prework (`extract.py` to confirm the bug exists) cannot be run honestly.
- Shipping a fix without repro means shipping a guess. Per the skill's rule "fail on master, pass with fix" — that test cannot be written yet.

Recommended handoff: the maintainer can verify F1 once their VM is up; this graph names the suspected line numbers (`tools.py:1572`, `tools.py:1579`) for `py-spy` / `strace` attachment. If F1 confirms the DBus hang, the fix-shape (lazy + timeout-bounded probe) is small enough to be a single PR.

## Phase 4.5 — Reframe note

This is not really a backintime bug — it's a *keyring/cron environment compatibility* bug that surfaces *through* backintime because backintime runs an unconditional keyring probe at module import. The transferable pattern: **any module-load-time global that calls into an external system (DBus, network, FUSE, etc.) is a latent ambush waiting for an environment that lacks that system.** Lazy + timeout-bounded is the durable pattern.
