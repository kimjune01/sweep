# Hypothesis graph: mikey0000/Mammotion-HA#681

**Issue**: "Move forward/left/right/back commands don't work" — pressing yields *"Error running action: Unknown error"*. Reporter on 0.5.31; second user (Popoff-fr) reports "same problem with all versions."

---

## H₀ — The "Unknown error" message comes from an uncaught exception in `async_move_*` → `async_send_command`

- **Null**: HA renders a translated, integration-owned error string.
- **Perturbation**: read `strings.json`/`translations/en.json` for `command_failed` / `api_limit_exceeded`; trace `async_send_command` exception flow in the user's version (v0.5.31) vs main (post-0.5.44).
- **Result**:
  - `strings.json` *does* define `exceptions.command_failed` ("Failed to send command to the mower.") and `api_limit_exceeded`. So if the integration raised `HomeAssistantError(translation_key=…)`, HA would show that text — **not** "Unknown error".
  - "Error running action: Unknown error" is HA's catch-all for **non-`HomeAssistantError` exceptions** bubbling out of `async_press`.
  - In **v0.5.31** `async_send_command` (lines 364-404) catches `(DeviceOfflineException, NoTransportAvailableError)`, marks the device offline, then **retries with `prefer_ble=True`**. The retry's `try/except` only catches `COMMAND_EXCEPTIONS`. If the retry raises `NoTransportAvailableError` (BLE unusable too — exactly Popoff-fr's situation: `ble_usable=False`), and `NoTransportAvailableError` is **not** in `COMMAND_EXCEPTIONS`, it escapes uncaught → "Unknown error".
  - Commit **22ef353** ("raise errors consistently", in 0.5.44, 2026-05-12) deletes that fallback block and adds an explicit `except NoTransportAvailableError as exc: raise HomeAssistantError("command_failed")`. After 0.5.44 the same code path produces "Failed to send command to the mower." (translated), not "Unknown error".
- **Trajectory**: divergent toward H₀ (confirmed for the *message*, not the underlying cause).
- **Mode**: deduction.
- **Edge → H₁**: why is no transport available when other commands (undock, return_to_dock) succeed via cloud?

### Provenance (H₀)
- Origin of the buggy retry: predates v0.5.31. Removed in 22ef353 on 2026-05-12 — already shipped in 0.5.44 / 0.5.45 by the time reporter filed (reporter on 0.5.31 from autumn 2025).
- Popoff-fr's claim "same problem with all versions" likely conflates the *symptom* (button doesn't move the mower) with the *error message*. Post-0.5.44 the message would change but the underlying not-moving behavior persists (see H₁).

---

## H₁ — Move commands need BLE; cloud accepts them but the Yuka firmware drops them

- **Null**: the cloud path delivers move commands identically to other nav commands; the mower acts on them.
- **Perturbation**: read Popoff-fr's attached HA log; compare protobuf send + ack patterns for `release_from_dock` (works) vs the move pathway.
- **Result**:
  - Popoff-fr's log captures **undock** and **return_to_dock**: both fall back to `cloud_aliyun` (`BLE preferred but not usable — falling back to TransportType.CLOUD_ALIYUN`), the gateway returns `200 OK`, the mower responds with a `MSG_CMD_TYPE_NAV` `todevTaskctrlAck` (action=6, action=5), and state transitions follow. Nav commands *do* work via cloud.
  - The log does **not** contain a move_forward attempt — Popoff-fr only exercised undock/dock. So we don't have direct evidence of move-via-cloud being dropped. But:
    - In pymammotion, move commands are built via `mammotion/commands/mammotion_command.py::move_forward/back/left/right` → `send_movement` (subtype 2 — a different message family than nav `todevTaskctrl`). The Mammotion app itself sends these only on BLE.
    - The `_async_ensure_ble_client` short-circuit + `_nudge_available` gating added 0.5.44 explicitly disables movement buttons when BLE is not usable, suggesting the maintainer knows cloud-side movement is unreliable.
  - Yuka-side: BLE proxy is 3m away, RSSI -26 (excellent), yet integration reports `ble_usable=False`. Root cause of *that* lives in `pymammotion` BLETransport's usability check — outside the scope reachable without a device.
- **Trajectory**: divergent toward H₁ (consistent — directly verifiable by reproducing a move attempt, which we can't from here).
- **Mode**: abduction + deduction (from code layout and the maintainer's own 0.5.44 gating decision).

---

## H₂ — JogibaerNr1's "entity_id" KeyError is a script-engine error, unrelated to the move command

- **Null**: the log fragment is from the failing move action.
- **Perturbation**: read the user's log excerpt.
- **Result**: `homeassistant.helpers.script.websocket_api_script: Error executing script. Unexpected error for call_service at pos 1: 'entity_id'` — this is HA's *script engine* complaining that the user's automation YAML/UI step is missing the `entity_id` field, **before** the integration is ever invoked. Mammotion code is not in the traceback. This is an automation authoring problem (or a UI bug in the visual editor on the user's HA version), not a Mammotion bug.
- **Trajectory**: divergent against the framing that this is the same issue.
- **Mode**: deduction.

---

## Diagnosis

Two distinct things are tangled in the report:

1. **The "Unknown error" wording** is real and was caused by a bug in `async_send_command` (v0.5.31): the BLE-fallback retry could raise `NoTransportAvailableError`, which wasn't in `COMMAND_EXCEPTIONS` and so escaped to HA as a non-translated exception. **Already fixed** in 22ef353 (shipped 0.5.44, 2026-05-12). Upgrading to 0.5.45 changes the message to "Failed to send command to the mower."

2. **The underlying inability to move the Yuka** is a BLE-not-usable problem. With `CONF_MOVEMENT_USE_WIFI=False` (default) and BLE unusable, the (now-correct) error message accurately describes what is happening: there's no path to send the command. The maintainer's 0.5.44 changes added `_nudge_available` to disable the buttons entirely in that state — which is the right UX but doesn't fix the BLE-usability detection itself. That diagnosis lives in **PyMammotion**, in `BLETransport.is_usable`, beyond what's reachable from this repo.

JogibaerNr1's script error is a third, unrelated issue.

---

## Routing decision

- **No PR.** The "Unknown error" bug is already fixed in shipped code; reporter is two minor versions behind. Opening a PR against `Mammotion-HA` for it would duplicate 22ef353.
- The deeper BLE-usability question belongs in `mikey0000/PyMammotion`, not here, and needs a real device + BLE proxy to investigate.
- **Tissue candidate**: a short comment on #681 noting (a) the "Unknown error" wording fix already landed in 0.5.44 — both users should upgrade and report the new message text; (b) JogibaerNr1's script log is a separate `entity_id`-missing issue in their automation, not the integration; (c) if the new message is "Failed to send command", the next question is why BLE isn't usable on the Yuka — for which a fresh BLE-only log from `pymammotion.transport.ble` + `pymammotion.device.handle` would be the next perturbation.

Halting at routing — the substrate is set up for code PRs, and this conclusion is information back to the maintainer, not a patch.

---

## Reasoning-mode table

| Claim | Mode | Confidence |
|---|---|---|
| `strings.json` defines `command_failed` / `api_limit_exceeded` | Deduction | 99% |
| HA renders "Unknown error" for non-`HomeAssistantError` exceptions out of `async_press` | Deduction | 95% |
| v0.5.31 `async_send_command` retry path can leak `NoTransportAvailableError` if BLE also unusable | Deduction | 92% |
| 22ef353 fixed the leak by adding explicit `except NoTransportAvailableError` | Deduction | 99% |
| Popoff-fr's log shows BLE unusable with cloud working for undock/return | Deduction | 98% |
| Cloud-path movement is unreliable on Yuka firmware | Abduction (from maintainer's later gating + Mammotion app behavior) | 65% |
| JogibaerNr1's `'entity_id'` error is automation-side, not integration-side | Deduction | 97% |

## Provenance

- Worktree: `/Users/junekim/.sweep/worktrees/mikey0000__Mammotion-HA`, default branch `main`
- v0.5.31 tag dump: `git show v0.5.31:custom_components/mammotion/coordinator.py`
- Fix commit: `22ef353` "raise errors consistently" (2026-05-12)
- Follow-up: `92ee8a0` "fix an introduced bug with movement commands" (2026-05-12) — added `_async_ensure_ble_client` short-circuit on `_bluetooth_enabled=False`
- Popoff-fr log: `https://github.com/user-attachments/files/27711554/home-assistant_mammotion_2026-05-13T13-26-59.421Z.log`
- PyMammotion HEAD at `/tmp/pymammotion`
