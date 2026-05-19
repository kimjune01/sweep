# Hypothesis graph: mikey0000/Mammotion-HA#729

**Issue**: "Unable to setup device" — `Unexpected error during login: Field "data" of type Optional[DeviceRecords] in Response has invalid value {…isReceiver: 1, status: -1, batchId: …, recordId: …, …}`

**Maintainer's note**: "The integration will automatically accept shared devices on start. Looks like a bug in that part of the code."

---

## H₀ — The error originates in Mammotion-HA's `config_flow.py:248`

- **Null**: error is a passthrough from a downstream library
- **Perturbation**: grep `custom_components/` for `DeviceRecords`, `accept_share`, `isReceiver`, share-related symbols
- **Result**: zero matches. `config_flow.py:248` is a generic `except (HTTPException, Exception)` catch-all that logs whatever bubbles up from `temp_client.login_and_initiate_cloud(...)`. The string `Field "data" of type Optional[DeviceRecords] in Response has invalid value` is a mashumaro/dataclass deserialization error format.
- **Trajectory shape**: divergent against (H₀ killed)
- **Mode**: deduction
- **Edge → H₁**: error origin is in `pymammotion` (the pinned dep at `requirements: pymammotion==0.7.114b1`)

## H₁ — `Response[DeviceRecords]` is parsed against the wrong payload schema for the share-page endpoint

- **Null**: schema is correct; the failing payload is malformed
- **Perturbation**: in PyMammotion, find every site that constructs `Response[DeviceRecords]` and compare field requirements vs the payload Andre logged
- **Result**:
  - `pymammotion/http/http.py:537` — `get_user_shared_device_page() -> Response[DeviceRecords]` POSTs `/user-server/v1/share/device/page` with `statusList: [-1]` (pending shares). Docstring: "Fetches device list for a user (shared) but not accepted."
  - `pymammotion/http/model/http.py:121` — `DeviceRecord` has REQUIRED fields (no defaults): `identityId`, `iotId`, `productKey`, `deviceName`, `owned`, `status`, `bindTime`, `createTime`.
  - Andre's payload record: `{batchId, recordId, type, iotId, productKey, deviceName, initiatorIdentityId, initiatorAccount, receiverIdentityId, receiverAccount, receiverEmail, isReceiver, status, createTime, createTimestamp}` — **missing** `identityId`, `owned`, `bindTime`. Has many fields `DeviceRecord` doesn't model (`batchId`, `recordId`, `type`, `initiatorIdentityId`, `initiatorAccount`, `receiverIdentityId`, `receiverAccount`, `receiverEmail`, `isReceiver`).
  - The share-page endpoint returns a **share-notification** schema, not an owned-device schema. They share the name "device records" but the shapes differ.
- **Trajectory shape**: divergent toward H₁ (confirmed)
- **Mode**: deduction (read both sides of the contract)

## H₂ — The bug shadows the maintainer's claimed auto-accept

- **Null**: the auto-accept path runs independently of the failing parse
- **Perturbation**: read `pymammotion/client.py:900-980` (`login_and_initiate_cloud`)
- **Result**:
  ```
  device_list_resp = await mammotion_http.get_user_shared_device_page()   # FAILS to parse
  aliyun_devices: DeviceRecords = device_list_resp.data or []            # → []
  ...
  if aliyun_devices:                                                      # FALSE
      cloud_client = CloudIOTGateway(mammotion_http)
      ...
      shared_notice = await cloud_client.get_shared_notice_list()
      pending = [d.record_id for d in shared_notice.data.data if d.status == -1]
      if pending:
          await cloud_client.confirm_share(pending)                       # NEVER RUNS
  ```
  When the share-page parse fails, `device_list_resp.data` is `None`, `aliyun_devices` becomes `[]`, and the entire cloud-setup-and-auto-accept block is skipped. This is the exact symptom Andre describes — login bails before the share is accepted. His workaround (manually accept the share via another account, then log into HA) sidesteps the share-list call because there's no pending record to parse.
- **Trajectory shape**: divergent toward H₂ (confirmed) — also explains why mikey's auto-accept "should be there" but isn't running.
- **Mode**: deduction

## Diagnosis

**Root cause** (in PyMammotion, not Mammotion-HA):
`http/http.py:get_user_shared_device_page` declares its return as `Response[DeviceRecords]`, but the upstream endpoint `/user-server/v1/share/device/page?statusList=[-1]` returns share-notification records (schema: `batchId/recordId/type/initiator*/receiver*/isReceiver/status/createTime/...`), not owned-device records. `DeviceRecord` has three required fields (`identityId`, `owned`, `bindTime`) absent from the share-notification payload, so mashumaro raises `invalid value` and the whole login flow aborts.

**Cascade**: the parse failure makes `aliyun_devices` empty, which short-circuits the `if aliyun_devices:` block in `client.py:946`, which is where `confirm_share(pending)` lives. So the auto-accept never executes, and the user is stuck until they accept the share out-of-band.

**Fix shape**:
- Introduce a `SharedDeviceRecord` model matching the share-notification payload (fields: `batch_id`, `record_id`, `type`, `iot_id`, `product_key`, `device_name`, `initiator_*`, `receiver_*`, `is_receiver`, `status`, `create_time`, `create_timestamp`), wrap with `SharedDeviceRecords` (paged container).
- Change `get_user_shared_device_page` return to `Response[SharedDeviceRecords]`.
- Adjust `client.py:927` consumer (`aliyun_devices: DeviceRecords = device_list_resp.data or []`) — this variable was being used as a boolean gate for the cloud-setup block, but the gate it *should* express is "the account has any cloud devices at all," which is more accurately `device_list_owned_resp.data` (line 924) or `device_page_resp.data.records`. The gate currently fires off the *shared* list, which is wrong even when parsing succeeds.

## Cross-repo routing decision (frontier)

The issue is filed against `mikey0000/Mammotion-HA` but the patch belongs in `mikey0000/PyMammotion`. Both repos share the maintainer. Options:

1. **PR to PyMammotion** with new `SharedDeviceRecord` model and corrected return type; reference Mammotion-HA#729 in the body. Mammotion-HA picks it up on next pymammotion bump.
2. **Tissue on Mammotion-HA#729** with the diagnosis (model mismatch + cascade into auto-accept skip), pointing to the file/line in PyMammotion. Let mikey decide the fix shape on his own library.

Halting at the routing decision — the substrate is wired for one-repo-per-issue investigation, and a cross-repo PR needs operator review on framing before it goes out.

## Provenance

- `mikey0000/Mammotion-HA@main` HEAD: cloned shallow (depth 50) into `/Users/junekim/.sweep/worktrees/mikey0000__Mammotion-HA`
- `mikey0000/PyMammotion@main` cloned shallow into `/tmp/pymammotion`
- Issue context pack: `/var/folders/.../inv-ctx-triage-2026-05-18T21_25Z-mikey0000-Mammotion-HA-729.md`

## Reasoning-mode table

| Claim | Mode | Confidence |
|---|---|---|
| Mammotion-HA `config_flow.py:248` is a generic catch | Deduction | 99% |
| `DeviceRecord` requires `identityId`/`owned`/`bindTime` (no defaults) | Deduction | 99% |
| Andre's payload omits those three required fields | Deduction (vs logged payload) | 98% |
| `get_user_shared_device_page` is the failing site | Deduction | 95% |
| Cascade: failed parse → `aliyun_devices=[]` → auto-accept skipped | Deduction | 95% |
| Andre's workaround sidesteps the parse via no pending records | Abduction (consistent with the cascade) | 75% |
