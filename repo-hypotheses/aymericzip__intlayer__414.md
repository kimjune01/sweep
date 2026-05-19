# Hypothesis Graph: aymericzip/intlayer#414

**Issue**: Make `.vscode` directory creation optional during `npx intlayer init`.
**Maintainer's preferred shape**: detect VSCode (or fork); don't add a Y/n prompt because the command is mostly run by AI agents.

## H₀: Where is `.vscode` created?

- **Perturbation**: grep `.vscode` under `packages/`.
- **Trajectory**: divergent — three files match.
  - `packages/@intlayer/chokidar/src/init/index.ts:212-252` unconditionally creates `.vscode/extensions.json` and the directory if missing.
  - `installSkills/index.ts` already gates platform install via env-var `check()` functions for VSCode/Cursor/Windsurf/Trae.
  - `installMCP/installMCP.ts` only fires when caller passes `platform`.
- **Confirmed**: only `init/index.ts` writes `.vscode/extensions.json` unconditionally. Single site to fix.
- **Reasoning mode**: deduction. Confidence: 99%.

## H₁: Shape of the fix — what gating logic does the maintainer expect?

- **Abduction**: skip `.vscode` writes unless evidence the user is on VSCode-family editor.
- **Signals available (all cheap)**:
  - `.vscode/` already exists in repo → team uses it. Keep adding our recommendation.
  - `process.env.VSCODE === 'true'` / `TERM_PROGRAM === 'vscode'` → user is running from VSCode integrated terminal.
  - VSCode forks: `CURSOR`, `WINDSURF`, `TRAE`, `TRAE_CN`, matching `TERM_PROGRAM`.
- **Convergence with codebase convention**: `installSkills/index.ts:64-94` already encodes these exact env checks per platform. The fix should reuse the same checks rather than invent a new shape.
- **Confirmed shape**: condition = `(.vscode dir exists) || isVSCodeFamilyEditor(env)`. No prompt.
- **Reasoning mode**: deduction from existing convention. Confidence: 95%.

## H₂: Where to put the helper?

- `init/utils/` is the convention (fileSystem.ts, configManipulation.ts, etc.). Add `editorDetection.ts` there.
- **Reasoning mode**: deduction. Confidence: 95%.

## H₃: Regression risk — does gating break the "user has `.vscode` already" path?

- If `.vscode/extensions.json` exists, we read+merge. If `.vscode/` exists but no extensions.json, we still write.
- New gate: `.vscode/` exists → proceed. Preserves current behavior for VSCode users. Confirmed.

## Diagnosis

Add `isVSCodeFamilyEditor(env)` helper. Gate the `.vscode/extensions.json` block in `init/index.ts` on
`(await exists(rootDir, '.vscode')) || isVSCodeFamilyEditor(process.env)`. No Y/n prompt — matches
maintainer comment. WebStorm user (issue reporter) gets no `.vscode/` created; existing VSCode users
unaffected.

## Frontier

Closed. Single-site fix, convention exists in repo, no oscillation expected. Proceed to Phase 5
(prework is trivial — write the helper + unit tests + integrate) then Phase 8 ship.
