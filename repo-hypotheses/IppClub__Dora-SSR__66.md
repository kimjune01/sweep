# IppClub/Dora-SSR#66 — stale TS type declarations on rebuild

Issue: "TypeScript compiler uses stale type declarations when compiling Agent modules"
Reporter: dsadsasdaddas (newly created, keyboard-mash username — adversarial-looking)
Disposition: **diagnose & tissue, no PR**

## H0 — reporter's stated root cause (KILLED)

**Hypothesis:** `Tools/dora-dora/build/typescript.js` is a pre-built bundle containing user-project type definitions like `AgentPromptPack`, and was frozen at engine build time.

**Perturbation:** Read `Tools/dora-dora/src/TranspileTS.ts:34-95` (`loadTypescriptCompiler`). The file URL `/typescript.js` is loaded via `<script src>` and assigned to `globalThis.ts`, which is then used as `typeof import('typescript')`. That's the standalone TypeScript compiler bundle from the `typescript` npm package.

**Trajectory:** divergent against. `typescript.js` is the TS compiler itself (`ts.createProgram`, `ts.ScriptTarget`, etc.). It does not, has never, and could not contain `AgentPromptPack` — user code is supplied at runtime via the `CompilerHost`. The reporter's `grep "newField" typescript.js` returning no match proves nothing.

**Mode:** deduction (read the source). Confidence: 98%.

**Edge:** if `typescript.js` is not the cache, what is? Look at `CompilerHost` file resolution for the real cache.

## H1 — Monaco model cache holds stale dependency content (CONFIRMED)

**Hypothesis:** `createCompilerHost` in `TranspileTS.ts` resolves dependency files (imports like `Agent/Memory`) by checking `monaco.editor.getModel(uri)` *before* hitting disk. Once a model exists for a dependency, the compiler reuses its in-memory content forever and never re-reads disk.

**Perturbation:** Read `Tools/dora-dora/src/TranspileTS.ts:163-314`:

- `fileExists` (164-235): for any non-root file, calls `monaco.editor.getModel(uri)` first; if a model exists, returns true without consulting disk.
- `readFile` (239-255): same pattern — model takes precedence; only falls through to `Service.readSync` when no model exists.
- `getSourceFile` (261-313): same — `monaco.editor.getModel(uri).getValue()` wins over disk.
- `fileExists` line 209-216: when a dependency is found on disk for the first time, calls `monaco.editor.createModel(res.content, ...)`. This *auto-creates* a model from disk content on first compile.

So on first compile of any file that imports `Memory.ts`, a Monaco model for `Memory.ts` is auto-created with the current disk content. On subsequent compiles, that cached model is returned in preference to any fresh disk read. The cache is not bounded by file-modification time or content hash.

**Trajectory:** divergent confirming. The cache exists and behaves exactly as the symptom describes.

**Mode:** deduction. Confidence: 95%.

**Why the reporter saw it persist across engine restart:** the engine restart is irrelevant — the cache lives in the Web IDE browser tab. If the same browser tab stays open across "engine restart" (Dora SSR runtime restarts but the Tools/dora-dora SPA tab is unchanged), Monaco models persist. To clear the cache the reporter would need to reload the Web IDE page.

## H2 — server-side `/ts/build` does not push UpdateFile for transitive imports (CONFIRMED)

**Hypothesis:** `/ts/build` for a single file emits `UpdateFile` only for the root file, not its imports.

**Perturbation:** Read `Assets/Script/Dev/WebServer.yue:1495-1560`. Single-file branch loads the requested file's content from disk via `Content\load path` and emits *one* `UpdateFile` for that file. Directory branch walks all .ts/.tsx files in the directory and emits `UpdateFile` for each. Neither branch resolves imports.

**Trajectory:** divergent confirming.

**Mode:** deduction. Confidence: 95%.

This is the upstream half of the same bug: even if the browser-side cache were fixed, building `CodingAgent.ts` after editing `Memory.ts` outside the IDE would still race against any in-IDE unsaved edits, because the server has no way to know whether disk or model is canonical.

## Causal chain (confirmed)

1. User opens Web IDE; over time, models are auto-created for every imported file the compiler has ever traversed.
2. User edits `Memory.ts` *outside* the Web IDE (CLI editor, sync, etc.).
3. User runs `dora ts build -f CodingAgent.ts` from terminal.
4. Server (`/ts/build`) emits `UpdateFile` for `CodingAgent.ts` only; the in-browser Monaco model for `CodingAgent.ts` is refreshed.
5. Browser triggers `transpileTypescript("CodingAgent.ts", newContent)`.
6. Compiler resolves `import 'Agent/Memory'` via `createCompilerHost.fileExists/readFile/getSourceFile`, all of which short-circuit to the cached (stale) `Memory.ts` model.
7. TS errors: `Property 'newField' does not exist on type 'AgentPromptPack'`.

## Fix design (not implemented — needs maintainer call)

Two viable directions, both with tradeoffs:

**Option A — server-side import resolution.** On `/ts/build` for a single file, walk the file's `import` statements server-side, push `UpdateFile` for each .ts dependency in the project tree before triggering transpilation. Catches the on-disk-edited case but doesn't help if the user has unsaved IDE edits to dependencies they'd rather use.

**Option B — browser-side cache-bypass for "auto-created" models.** Track whether a model was auto-created by the compiler (vs. opened by the user in an editor pane). At the start of each `transpileTypescript` call, re-read auto-created dependency models from disk via `Service.readSync`. Preserves IDE-buffer semantics for files the user is editing. Needs a `WeakSet<ITextModel>` (or attached metadata) to remember which models were auto-created.

**Option C — clear all non-root models before each compile.** Brute-force. Loses any unsaved edits to dependencies in the IDE. Wrong.

The right answer depends on whether the maintainer treats the Web IDE buffer or the disk as the source of truth for dependencies during a CLI-triggered build. That is a product-design decision, not a fix the contributor should make unilaterally.

## Why no PR

- **Reporter's stated diagnosis is wrong** about `typescript.js` being the cache; we'd be quoting incorrect facts back to the maintainer if we shipped their suggested fix verbatim.
- **The real fix is a design call**, not a mechanical one. Option B is the clean answer but adds machinery (model provenance tracking) the maintainer may not want.
- **Reporter username is suspicious** (`dsadsasdaddas`); the report could be a test or filed in bad faith. Diagnostic comment + maintainer call is the cheap-to-vary play.
- Tissue is the right channel: corrects the misdiagnosis, names the actual culprit (Monaco model cache in `TranspileTS.ts`), and lets the maintainer decide Option A vs B.

## Frontier (open, not pursued)

- Does the IDE refresh dependency models when the file server pushes `UpdateFile`? If yes, server-side Option A is fully sufficient.
- What happens when a directory build (which DOES push UpdateFile for all files) is run after the symptom — does it clear the bug for that directory? (Probably yes.)
- Is there an existing "reload from disk" UI affordance the reporter could use as a workaround instead of restarting the engine? (Their workaround used a type assertion, suggesting no.)

## Reasoning modes

| Node | Mode | Confidence |
|------|------|------------|
| H0 killed (typescript.js not the cache) | deduction (read source) | 98% |
| H1 confirmed (Monaco cache) | deduction (read source) | 95% |
| H2 confirmed (server omits import update) | deduction (read source) | 95% |
| Fix options A/B/C | abduction | 65% |

## Pruning log

- H0 killed by reading `loadTypescriptCompiler` and confirming `typescript.js` is the compiler bundle from npm, not a project-specific generated file. The reporter's grep returning empty was a false-confirmation — it would always return empty for any user identifier because user code is never in the compiler bundle.
