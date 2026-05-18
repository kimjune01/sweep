# Sekai-World/sekai-viewer#666 — VIRTUAL SINGER partvoice files not loading

**Issue.** VIRTUAL SINGER (VS) lines in card side-stories produce "voice file failed to load" toasts. A few side-stories work (reporter cites Airi "Always Looking Ahead" part 1); most don't.

**System under investigation.** `src/utils/storyLoader.ts::getTalkVoiceUrl` + `src/utils/voiceFinder.ts::fixVoiceUrl`, against the public minio bucket `sekai-jp-assets`.

---

## H₀ — partvoice path construction misses real bundle for VS in non-piapro units

**Abduction (mode: deduction once data confirmed).** Path construction is keyed on `chara2d.assetName` and `chara2d.unit`. For VS characters, `assetName` is bare (`21miku`, `24luka`, …) and `unit` reflects the borrowing unit (`light_sound`, `idol`, `street`, `theme_park`, `school_refusal`, `piapro`). Asset storage uses the `v2_` prefix for non-piapro VS bundles. The current `else` branch (assetName not starting with `v2_`/`clb`) only tries:

1. `sound/scenario/part_voice/${assetName}_${unit}/`
2. `sound/scenario/voice/part_voice_${assetName}_${unit}/`

Both miss `part_voice_v2_${assetName}_${unit}/`, which is where non-piapro VS partvoices actually live.

**Perturbation.** Listed `sound/scenario/voice/part_voice*` on the live bucket.

```
part_voice_21miku_idol/                 # exists (legacy)
part_voice_21miku_piapro/               # exists
part_voice_22rin_piapro/                # exists  ... etc piapro only
part_voice_v2_21miku_idol/
part_voice_v2_21miku_light_sound/
part_voice_v2_21miku_street/
part_voice_v2_21miku_theme_park/
part_voice_v2_21miku_school_refusal/
part_voice_v2_21miku_piapro/
... (same matrix for 22rin, 23len, 24luka, 25meiko, 26kaito)
```

VS partvoice file naming inside `part_voice_v2_21miku_light_sound/`:
```
partvoice_01_021_band.mp3
partvoice_02_021_band.mp3
...
```

**Trajectory shape.** Divergent — evidence settles. The bundle distribution explains exactly which side-stories work and which don't:

| Card unit | chara2d.unit | Code attempts                                            | Bucket has                                  | Loads? |
|-----------|--------------|----------------------------------------------------------|---------------------------------------------|--------|
| MMJ (idol)         | `idol`           | `part_voice_21miku_idol`         | `part_voice_21miku_idol` (legacy) + v2 variant | ✅ |
| VBS (street)       | `street`         | `part_voice_21miku_street`       | only `part_voice_v2_21miku_street`          | ❌ |
| LON (light_sound)  | `light_sound`    | `part_voice_21miku_light_sound`  | only `part_voice_v2_21miku_light_sound`     | ❌ |
| WxS (theme_park)   | `theme_park`     | `part_voice_21miku_theme_park`   | only `part_voice_v2_21miku_theme_park`      | ❌ |
| 25-ji (school_refusal) | `school_refusal` | `part_voice_21miku_school_refusal` | only `part_voice_v2_21miku_school_refusal` | ❌ |
| Piapro             | `piapro`         | `part_voice_21miku_piapro`       | both `part_voice_21miku_piapro` and v2      | ✅ |

The reporter says Airi (MMJ) "Always Looking Ahead" part 1 works — consistent with `part_voice_21miku_idol/` existing as a legacy bundle. Other side stories that feature VS in non-idol/non-piapro contexts all fail — exactly the cells with no non-v2 bundle.

**Kill condition.** A working non-piapro VS partvoice load with chara2d.unit ∈ {street, light_sound, theme_park, school_refusal} would falsify this. None observed; all such cells have only v2 bundles.

**Edge (status: confirmed).** Add a third lookup attempt in `getTalkVoiceUrl`'s else branch: `sound/scenario/voice/part_voice_v2_${chara}/${VoiceId}.mp3`.

---

## H₀.1 — provenance

- The else branch was added in `af57318 feat(voiceFinder): implement voice normalization and retrieval functions`. Comment header lists three intended attempts; step 3 is "if still not found, check `/voice/part_voice_${chara}/`" — but that's identical to step 2's target. Looks like a copy-paste: step 3 was meant to inject `v2_`, but the prefix was dropped.
- `errorVoices` map at top of `voiceFinder.ts` (commented out) references `part_voice_v2_24luka_light_sound` — the author knew the v2 prefix variant existed but didn't wire it into the fallback chain.
- No upstream PR addresses VS partvoice. `gh pr list --search "partvoice OR part_voice"` is empty.

---

## Fix shape

Append a v2-injected attempt to the existing else branch:

```ts
if (fixedVoiceUrl === null) {
  const v2PartVoiceUrl = `sound/scenario/voice/part_voice_v2_${chara}/${VoiceId}.mp3`;
  fixedVoiceUrl = await fixVoiceUrl(voiceMap, region, VoiceId, v2PartVoiceUrl);
}
```

Inside the existing `else` (non-v2/non-clb assetName), after the two current attempts.

**Why not unconditional v2-first?** chara2d.assetName already starting with `v2_` is the V2-3D fallback character (when a v2 model is reused for older characters). Those bundles really do live at `part_voice_${chara}` without a doubled `v2_` prefix. The two paths address different cases.

**Why not also try piapro suffix as fallback?** The scenario data ties VoiceId to a specific chara2d via `talkData.TalkCharacters[0].Character2dId`, which carries the unit. Cross-unit lookups would risk pulling the wrong line. Keep the change minimal: same unit, just try the v2-prefixed bundle.

---

## Graph state

| Node | Status | Mode | Confidence |
|------|--------|------|------------|
| H₀ — missing v2_ prefix in non-piapro VS partvoice lookup | confirmed | deduction + induction (bucket listing) | 95% |
| H₀.1 — provenance, copy-paste in step 3 | partial | inductive read of commit + comment | 80% |

## Frontier

- Verify a representative `partvoice_NN_021_band.mp3` HEAD 200 after fix lands.
- CN/EN/KR/TW regions: `fixVoiceUrl` short-circuits to passthrough for non-jp regions, so the change is scoped to jp behaviorally. Other regions retain current passthrough behavior.

---

## Round 2 — H₁ supersedes H₀: the failing talks have `Character2dId === 0`

**Re-investigation (2026-05-18).** Re-checked the previous round against live scenario data. The "v1 VS partvoice references" the H₀ table predicts do not appear in any of the 50 most-recent card-episode scenarios sampled. The reporter's working anchor (Airi "Always Looking Ahead" part 1/2) was misread: it works because that scenario contains **zero partvoice voices** (every voice is `voice_card_*` under the scenario's own bundle), not because the `21miku_idol` legacy bundle saved it. H₀ in the original table is therefore unsupported by the current data and the working-anchor explanation is wrong. The bug behind #666 is a different one.

### H₁ — `TalkCharacters[0].Character2dId === 0` short-circuits the partvoice fallback

- **Null:** the fallback at storyLoader.ts:866–901 requires `chara2d` to be defined. `useMediaUrlForLive2D` (storyLoader.ts:614) and `useProcessedScenarioData` (storyLoader.ts:404) both pass `chara2d = undefined` whenever `talkData.TalkCharacters[0].Character2dId` is `0`. Off-screen / `？？？` speaker talks set this to `0` in the master data. For those talks, `getTalkVoiceUrl` returns `null` even when the file exists on the CDN.
- **Perturbation.** Fetch `res012_no054/012054_touya01.asset`, count partvoice lines by `Character2dId` of their owning Talk, then probe the CDN for each missing line.
- **Result:**
  - 9 partvoice voices total; **2 owned by talks with `Character2dId === 0`** (WindowDisplayName: `？？？`):
    - `partvoice_35_023` (Len, "023")
    - `partvoice_08_022` (Rin, "022")
  - Both files exist on the bucket:
    - `sound/scenario/voice/part_voice_v2_23len_street/partvoice_35_023.mp3` → 200
    - `sound/scenario/voice/part_voice_v2_22rin_street/partvoice_08_022.mp3` → 200
  - Both VS characters appear in `AppearCharacters` of the same scenario (`Character2dId 313 = v2_23len_street`, `307 = v2_22rin_street`) — so the right costume bundle is recoverable from data already available at load time.
  - Cross-sample 50 most-recent card episodes: 33 scenarios carry partvoice; 3 of those have at least one `Character2dId === 0` partvoice line. Consistent with the reporter's "multiple errors per affected story" anchor.
- **Trajectory.** Divergent in favor. Every broken voice traced by HEAD-probe is present on the bucket; the only path that could fetch it is the one the code skips.
- **Shape.** Divergent → ship the fix.

### H₁.1 — character id is recoverable from the VoiceId

Voice ids consistently match `partvoice_<NN>_<CCC>(_<unit>)?` where `CCC` is the three-digit character id (`021`=Miku … `026`=Kaito) and `_<unit>` (optional) tracks the unit costume (`_band`, `_idol`, `_street`, `_night`, `_wonder`, `_piapro`). Across 50 scanned scenarios the regex matches every partvoice id. Confidence 95%.

### H₁.2 — a substitute chara2d already lives in `AppearCharacters`

In the 50-scenario sample, every off-screen VS speaker had a matching `characterId` already present in `AppearCharacters` via a `v2_` chara2d. Falling back to that chara2d routes the lookup to a `part_voice_v2_<assetName>_<unit>/` bundle that does contain the bare-suffix file. For the pathological case where the VS doesn't appear on stage at all, the `_piapro` directory exists for all six singers and is a safe terminal fallback.

### Fix (revised)

The original H₀ fix (`append v2-injected attempt`) is still safe — it costs at most one extra 404 — but it is **insufficient on its own**: the failing talks never reach the else branch at all, because `chara2d` is `undefined`. The real fix is upstream of `getTalkVoiceUrl`: when `Character2dId === 0` and the voice is a `partvoice_*` line, derive a usable chara2d from the VoiceId + `AppearCharacters`.

```ts
// storyLoader.ts — used at both ~404 and ~614
const VS_NAMES = ["miku", "rin", "len", "luka", "meiko", "kaito"];
const VS_CHAR_IDS = new Set([21, 22, 23, 24, 25, 26]);

function resolveChara2dForTalk(
  talkData: TalkData,
  chara2Ds: ICharacter2D[],
  appearCharacters: { Character2dId: number }[]
): ICharacter2D | undefined {
  const direct = talkData.TalkCharacters[0]?.Character2dId;
  if (direct) return chara2Ds.find((c) => c.id === direct);

  const voiceId = talkData.Voices[0]?.VoiceId ?? "";
  const m = voiceId.match(/^partvoice_\d{1,3}_(\d{3})(?:_[a-z_]+)?$/);
  if (!m) return undefined;
  const charId = parseInt(m[1], 10);
  if (!VS_CHAR_IDS.has(charId)) return undefined;

  const appearIds = new Set(appearCharacters.map((a) => a.Character2dId));
  const fromAppear = chara2Ds.find(
    (c) =>
      c.characterId === charId &&
      appearIds.has(c.id) &&
      c.assetName.startsWith("v2_")
  );
  if (fromAppear) return fromAppear;

  const idx = charId - 21;
  return chara2Ds.find(
    (c) =>
      c.characterId === charId &&
      c.assetName === `v2_${20 + idx + 1}${VS_NAMES[idx]}` &&
      c.unit === "piapro"
  );
}
```

Then at the two call sites replace the inline `chara2d` resolution with `resolveChara2dForTalk(talkData, chara2Ds, AppearCharacters)`. `AppearCharacters` is already part of the scenario data (`snData.AppearCharacters`).

**Safety:**
1. `Character2dId !== 0` path is byte-identical to today.
2. VoiceId without the `partvoice_NN_CCC` pattern → returns `undefined`, identical to today.
3. Guard `VS_CHAR_IDS` keeps non-VS off-screen speakers on today's behavior.
4. `fixVoiceUrl` already tolerates a missing file (returns `null`), so a wrong-costume guess degrades to today's "voice missing" outcome — never to a wrong-voice play.

### Graph state (revised)

| Node | Status | Mode | Confidence |
|------|--------|------|------------|
| H₀ — missing v2_ prefix in non-piapro VS partvoice lookup | **unsupported** by current data; kept for provenance | deduction over bucket listing | unable to reproduce |
| H₁ — `Character2dId === 0` skips partvoice fallback | confirmed | deduction + induction (HEAD probes, n=2 / sample n=50) | 90% |
| H₁.1 — VoiceId encodes character id | confirmed | induction (every partvoice id in n=50 matches regex) | 95% |
| H₁.2 — AppearCharacters carries a usable v2 chara2d | confirmed (in-sample); piapro fallback for the empty case | deduction + induction | 85% |

### Frontier (revised)

- F1: pure off-screen scenarios (VS never on stage). Helper falls back to the `piapro` costume; not yet exercised in sample. Predicted convergent.
- F2: any non-VS partvoice with `Character2dId === 0`. Guarded out by `VS_CHAR_IDS`; preserves today's behavior.
- F3: confirm under #666 EN region: `fixVoiceUrl` is jp-only, so EN passthrough returns the path as-is regardless. The reporter is on Chrome 145 with sekai-viewer 1.18.0 but does not specify region; this fix is jp-scoped behaviorally.

### Pruning log (Round 2)

- Killed (Round 2): H₀'s claim that the working anchor (Airi card 129) succeeds because `part_voice_21miku_idol/` exists as a legacy bundle. The scenario in fact contains zero partvoice lines — there is nothing to fail. The legacy `21miku_idol` bundle is real but unrelated to the reporter's working case.
- Killed (Round 2): "normalize regex strips `_band`/`_idol`/etc." — neither `normalizeVoiceName` regex matches those suffixes, and both ends of the lookup normalize identically, so suffix-mismatch is not the cause.
