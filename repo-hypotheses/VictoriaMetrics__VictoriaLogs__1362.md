# VictoriaMetrics/VictoriaLogs#1362 — VL-Msg-Field absent until force_merge

## H₀: storage-layer issue triggered by force_merge

**Observation (from reporter + cuongleqq reproduction):**
- vlagent (syslog→jsonline path) produces rows where the JSON contains both:
  - `_msg: "missing _msg field; see ..."` (the `-defaultMsgValue` fallback)
  - `cef.extension.msg: "<actual value>"` (the CEF-extracted field)
- The user sets header `VL-Msg-Field: cef.extension.msg` on `/insert/jsonline`.
- Query immediately after ingest returns the **fallback** `_msg`.
- After `POST /internal/force_merge?partition_prefix=YYYYMMDD`, the same query returns the **promoted** `_msg`.

**Trajectory shape:** divergent — the symptom is reproducible and stable across observers.

## H₁ (confirmed): RenameField creates duplicate `_msg` fields; in-memory vs merged read disagree

**Causal chain (deduction, reading code):**

1. `app/vlinsert/jsonline/jsonline.go:116` calls `logstorage.RenameField(p.Fields, msgFields, "_msg")` with `msgFields = ["cef.extension.msg"]`.
2. `lib/logstorage/rows.go:174-188` `RenameField`:
   - Walks `oldNames`. For each, finds the first matching non-empty field and renames its `Name` to `"_msg"`.
   - **Does NOT remove or clear any pre-existing field already named `"_msg"`.**
3. Result: the field slice now contains **two** fields with `Name == "_msg"` — the original fallback and the promoted one.
4. `lib/logstorage/log_rows.go:488-568` `addFieldsInternal`:
   - Iterates all fields, appends each to `fieldsBuf` with no dedup.
   - Both `_msg` entries are stored.
5. At column-store / block level, two columns with the same canonical name `""` exist for the row. Which value the reader surfaces is implementation-defined and differs between the un-merged in-memory part and the on-disk merged part. After `force_merge`, the column store consolidates and the "real" value (or the last-written one) becomes the survivor.

**Confidence:** ~90% on the duplication mechanism (deduction from code); ~70% on the merge-resolution detail (would need a perturbation to prove the column-store picks last-write after merge vs. first-write before).

**Provenance:**
- `RenameField` introduced long ago; no recent commits to `rows.go` touching this function. The "first non-empty wins, don't remove duplicates" semantics look like an unconsidered case rather than a deliberate design choice.
- `getCanonicalFieldName` canonicalizes `_msg` → `""` (log_rows.go:575) and `addFieldsInternal` keys dedup off `fieldName` but never actually dedupes by name — it just appends.

## Maintainer discussion (in-flight)

vadimalekseev and func25 are converging on **vlagent-side** fixes (different layer):

1. Add `-syslog.msgField` flag to vlagent so its syslog parser writes `_msg` directly from `cef.extension.msg`, avoiding the duplicate.
2. Expand the default syslog `msgFields` list (`app/vlinsert/syslog/syslog.go:615` — currently just `["message"]`) to include `cef.extension.msg`.

Both fixes prevent the duplicate `_msg` from ever being emitted by vlagent. They sidestep the storage-layer bug rather than fixing it.

## Frontier edges (not pursued)

- **E1**: Fix `RenameField` to also clear/remove any pre-existing field with `newName` (or skip rename if `newName` already present). This would fix the symptom for *any* ingestion shape where both a `_msg` fallback and a configured msg-field arrive together — broader than the vlagent fix.
- **E2**: Fix `addFieldsInternal` to dedup by canonical fieldName, last-write-wins. More invasive; touches a hot path.
- **E3**: Verify the merge-resolution mechanic empirically (set up two-row ingestion, query before/after merge) to confirm which `_msg` wins in each state.

## Halt rationale

Two maintainers actively engaged with convergent direction on a **different layer** than the storage bug here. Posting a PR on E1 would:
- Compete with their in-flight design instead of complementing it.
- Touch `RenameField`, a hot path used by every insertion handler (jsonline, elasticsearch, splunk, syslog, loki).
- Land in the wrong codebase from the maintainers' POV — they want vlagent to not emit the duplicate in the first place.

The right operator move is probably to comment on the issue noting the storage-layer mechanism (so the maintainers have it as context for their vlagent fix and can decide whether to also harden `RenameField`), not to ship a PR.

## Reasoning mode table

| Claim | Mode | Confidence |
|-------|------|-----------|
| Reporter sees fallback `_msg` until force_merge | Induction (reporter+cuongleqq reproduced) | 95% |
| vlagent emits both `_msg` and `cef.extension.msg` | Deduction (cuongleqq trace + vlagent code) | 90% |
| `RenameField` creates two `_msg` fields | Deduction (read rows.go:174) | 95% |
| `addFieldsInternal` doesn't dedup | Deduction (read log_rows.go:488) | 95% |
| Merge consolidation flips the survivor | Abduction (fits symptom; not perturbed) | 70% |
| Maintainer fix is in vlagent layer | Deduction (read comments) | 95% |

## Outcome

No PR. Hypothesis graph filed; surfacing recommendation to operator: either drop a one-paragraph comment about the storage-layer duplication for the maintainers' awareness, or stand down entirely and let the in-flight vlagent fix land.
