# Triage Graph: withastro/prettier-plugin-astro (kimjune01)

**Scan date:** 2026-05-09
**Mode:** dry-run

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| 308 | Formatter adds significant whitespace inside expressions | OPEN | 8.45 | Medium-High | Princesseuh P4:important, 3.5yr open | INVESTIGATED |

## T308: Whitespace inside expressions

### Root Cause

Two cooperating mechanisms:

1. **`embed.ts:95`** — expressions wrapped as `group(['{', indent([softline, astroDoc]), softline, '}'])`. The `softline` breaks to newline when group breaks. JSX collapses whitespace; Astro preserves it literally.

2. **`index.ts:95-109`** — empty text nodes between children converted to `line`/`hardline`. Whitespace between `{a} {b}` becomes a line break in formatted output.

The Astro compiler parses templates as HTML-like (whitespace-preserving) but delegates expression formatting to Babel's JSX parser via `textToDoc`. JSX whitespace rules applied, HTML whitespace rendered. Structural mismatch.

### Fix

- `embed.ts:95`: avoid `softline` when expression is inline child where whitespace is significant — use `""` instead
- `index.ts`: text-node-to-`line` between adjacent expressions needs to preserve original whitespace intent

**Challenge:** embed function doesn't have parent/sibling context. This is architectural, not a simple rule tweak.

### Effort: Medium-High (2-4 days)

Risk of breaking existing snapshots. Need careful edge case handling (long expressions that genuinely need wrapping vs inline ones that must not introduce whitespace).

### PR Viability: GOOD

3.5 years of community reports. gersomvg signaled intent Oct 2024 but no PR appeared. Clean fix has high merge probability. Builds Astro ecosystem trust.

---

*Dry run — no remote side effects.*
