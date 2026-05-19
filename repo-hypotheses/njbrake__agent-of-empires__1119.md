# njbrake/agent-of-empires#1119 — Cockpit blank-screen on `tapClientLookup` OOB

**Verdict: HALT at Phase 0 — no contributor opening.**

## Halt rationale

Three converging signals, each sufficient on its own:

1. **Maintainer-self-PR pattern.** Reporter `@Seluj78` has open PR #1236 on the same area (`feat(cockpit): surface set_mode rejection, fold tall queued-prompts strip`). Issue body cites internal file:line (`web/src/hooks/useCockpit.ts:51`, `cockpitTypes.ts:710-716`, `CockpitRuntime.tsx:85-87`) — reads as a maintainer's post-mortem, not an open invitation. Matches [[maintainer-self-pr-halt]]: when reporter is also working in the area, the issue is a public worklog.

2. **Bug is upstream, not in this repo.** The error fires inside `@assistant-ui/tap` (transitive dep). Stack trace shows `tapClientLookup` → `useSyncExternalStore` → cockpit unwind. The only thing repo-side could do is a workaround; the actual fix lives in `assistant-ui/assistant-ui`.

3. **Upstream is already engaged.** Seluj78 filed `assistant-ui/assistant-ui#4051` on 2026-05-15 at @Yonom's explicit request (Yonom is the assistant-ui maintainer). React 19.2.4 + `createRoot` was specifically called out as a case Yonom wants a fresh issue for. The maintainer-to-maintainer channel is live.

## What an outside PR would even look like

Options exhausted:
- **Patch the dep.** Not a contribution to aoe; would be a PR against `assistant-ui/assistant-ui` — different repo, different investigation.
- **Workaround in cockpit (`key={sessionId}` on `AssistantRuntimeProvider`, debounce `messages` rebuild, etc.).** Plausible, but Seluj78 already has the area open in #1236 and is in direct contact with the upstream maintainer. A speculative workaround PR from an outsider would either duplicate what Seluj78 ships next or get closed in favor of the upstream fix.
- **Add a repro test.** No clean repro exists (issue body says "Best-guess (without a clean repro)"). Producing one is the substance of the upstream investigation, not a drive-by contribution.

## Provenance

- Context pack: `inv-ctx-triage-2026-05-19T00_00Z-njbrake-agent-of-empires-1119.md`
- Related PR: njbrake/agent-of-empires#1236 (Seluj78, open, cockpit area)
- Upstream tracker: assistant-ui/assistant-ui#4051
- Halt memory: [[maintainer-self-pr-halt]]

## Frontier (closed)

No open edges. Re-open only if: (a) Seluj78 explicitly comments asking for outside help, or (b) upstream ships a fix and aoe needs a bump-and-test PR.
