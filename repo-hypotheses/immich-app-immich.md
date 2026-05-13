# Triage Graph: immich-app/immich (kimjune01)

**Scan date:** 2026-05-09

## Scan Table

| # | Title | State | Score | Effort | Signal | Status |
|---|-------|-------|-------|--------|--------|--------|
| — | Sidebar nav links missing focus-visible outlines | NO ISSUE | 4/10 | Small (~12 lines CSS) | a11y gap | COMMITTED |

## Focus-visible outlines on sidebar nav

### Root Cause

`NavbarItem` in `@immich/ui` renders `<a>` tags without `:focus-visible` styles. Keyboard navigation through the sidebar is invisible — no focus ring appears.

### Fix (~12 lines)

CSS in `web/src/app.css` scoped to `#sidebar a:focus-visible` and `#admin-sidebar a:focus-visible`. Uses `outline-offset: -2px` (inset) to avoid clipping by overflow containers. Added `id="admin-sidebar"` to `AdminPageLayout.svelte`.

### Architectural Note

Gemini flagged: the proper fix belongs in `@immich/ui`'s NavbarItem component so all consumers benefit. This app-level workaround is scoped narrowly with ID selectors to avoid side effects.

### PR Viability: BLOCKED

**immich CONTRIBUTING.md explicitly prohibits LLM-generated PRs:**
> "We ask you not to open PRs generated with an LLM. We find that code generated like this tends to need a large amount of back-and-forth, which is a very inefficient use of our time."

This PR cannot be pushed as-is. Options:
1. File an issue describing the a11y gap and let maintainers fix it in @immich/ui
2. Manually rewrite and submit without AI tooling disclosure concerns

### Risk

Policy violation risk. Technical risk low — CSS-only change with narrow scope.

---

*Committed on branch `fix/web-focus-outlines`. Not pushed — repo bans AI-generated PRs.*
