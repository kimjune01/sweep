# Hypothesis Graph: godotengine/godot-vscode-plugin#1014

**Issue**: Function Parameter information does not show up when auto completing function name
**Repo**: godotengine/godot-vscode-plugin
**Reporter**: Goldenlion5648
**Env**: Godot 4.7 beta 2, VSCode 1.119.0, godot-tools 2.6.1, arch_linux

## H₀ — Baseline observation

User types `pri`, accepts `print()` from completion popup, expects signature help (parameter hints) to appear. Doesn't. If they type the whole `print` and then `(`, signature help works.

**Mechanism**: VSCode triggers signature help on certain characters (typically `(`) or via explicit `editor.action.triggerParameterHints` command. When the LSP-supplied completion item is "committed", the inserted text (likely including `(`) bypasses VSCode's character-trigger because it's a programmatic edit rather than a typed character. Without an attached `command: triggerParameterHints`, no signature help fires.

**Classification**: divergent observation against expectation.
**Mode**: abduction.

## H₁ — Server-side fix (upstream Godot LSP)

**Hypothesis**: The Godot LSP server should attach `command: editor.action.triggerParameterHints` (or equivalent) to function-kind `CompletionItem`s. This is the structurally correct fix.

**Provenance**: collaborator @DaelonSuzuka in #152: *"This behavior is controlled by the Language Server, which is a component of the Godot Engine itself. This extension does not control the completions, so there's nothing I can do about it."*

**Killed by**: scope. We are not patching Godot engine here. But the maintainer's prior stance is a strong signal that they may close this issue with "upstream" verdict.

**Edge**: confirms policy-risk for a client-side PR.

## H₂ — Client-side post-processing in `response_filter`

**Hypothesis**: `GDScriptLanguageClient.response_filter` already post-processes LSP responses (hover markdown, documentLink uid filter — `src/lsp/GDScriptLanguageClient.ts:213-263`). We can intercept `textDocument/completion` and append `command: { command: "editor.action.triggerParameterHints", title: "Trigger parameter hints" }` to each `CompletionItem` whose `kind` is Function (3) or Method (2). The VSCode language client will execute the command after the edit, which fires signature help.

**Perturbation** (proposed, not run — no Godot LSP locally):
1. Add a branch in `response_filter` for `sentMessage?.method === "textDocument/completion"`.
2. Normalize the result (array or `CompletionList.items`).
3. For each item with `kind in {2,3}` and no existing `command`, attach the trigger command.

**Predicted trajectory**: divergent improvement for function/method completions. No effect on variables/classes/snippets.

**Risk**:
- Maintainer may reject as "controls the completions" per the prior stance.
- If Godot LSP returns `insertText` without `(` (just the bare name), triggering parameter hints right after will show hints for the *enclosing* call, not the just-inserted function — which would be visually confusing but harmless (VSCode pops the hint, user types `(`, hint re-resolves).

**Status**: open. Not validated end-to-end (would need a live Godot 4.7 LSP + VSCode extension host).

## H₃ — Snippet-based insert in client-side `GDCompletionItemProvider`

**Hypothesis**: The empty `GDCompletionItemProvider` (`src/providers/completions.ts`) could supply function snippets like `print($0)` with `InsertTextFormat=Snippet`, which would place the cursor inside the parens, naturally triggering signature help.

**Killed by**: this duplicates the LSP's job and would conflict with LSP-supplied completions. Worse coverage, worse maintenance. **Discard.**

## Frontier

- **F1**: empirical validation of H₂ requires a Godot 4.7 beta 2 install + VSCode + the patched extension. Not done.
- **F2**: maintainer policy verdict on client-side LSP response augmentation (vs. their #152 stance on parens). Unknown.

## Decision

**Halt for human gate.** This issue's fix is structurally simple and matches existing post-processing patterns in the plugin, but:
1. Empirical validation requires a Godot install I don't have wired up.
2. Maintainer's prior position (#152) on this class of fix is "extension does not control the completions — upstream problem." That stance was about auto-parens specifically; whether it extends to a `triggerParameterHints` command attachment is unclear. A drive-by PR may be closed politely.

**Recommendation**: skip this issue OR open as a *draft* PR with a clear comment asking the maintainer if client-side augmentation is acceptable before they invest review attention. Don't ship as a normal PR.

## Reasoning mode table

| Claim | Mode | Confidence |
|---|---|---|
| Issue cause is missing `triggerParameterHints` on completion items | Abduction | 75% |
| H₂ fix would resolve the visible symptom | Deduction (LSP+VSCode protocol semantics) | 85% |
| Maintainer would accept the fix | Induction from #152 precedent | 35% |

## Pruning log

- **H₁** killed by scope (we don't patch the engine).
- **H₃** killed by duplication risk with LSP-supplied completions.
