# astral-sh/ty Triage Graph

## Repo Profile

- **Stars**: 18K+ (as of 2026-05-09)
- **External merge rate**: 2/30 recent PRs (very low -- nearly all merges are core team or renovate bot)
- **Structure**: `astral-sh/ty` is a distribution wrapper; actual code lives in `astral-sh/ruff` submodule. PRs go to `astral-sh/ruff` with `[ty]` prefix.
- **Shared maintainers with ruff**: MichaReiser, charliermarsh, AlexWaygood, sharkdp, carljm, zanieb
- **Existing relationship**: PR #25066 open on ruff

## Help-Wanted Issues Scanned (2026-05-09)

### Lead: #3366 -- Hover ignores client's `contentFormat` preference
- **Labels**: bug, help wanted, server
- **Mechanicality**: HIGH -- maintainer gave exact file/line, described as "should be as easy as changing the check"
- **Competing PRs**: NONE
- **Status**: PR #25073 OPEN (astral-sh/ruff)
- **Fix**: `.contains(&Markdown)` -> `.first() == Some(&Markdown)` for both hover `content_format` and completion `documentation_format`. Added 3 E2E tests.
- **Tests**: 121/121 e2e pass (0 failures)
- **URL**: https://github.com/astral-sh/ruff/pull/25073

### Deferred Issues

| # | Title | Why deferred |
|---|-------|-------------|
| 3376 | Lazy literal completions | server + memory label, non-trivial perf work |
| 3250 | Not-awaitable diagnostic context skips some steps | diagnostics, moderate complexity |
| 2644 | narrow on getattr(x, "foo") | narrowing, deep type system work |
| 2577 | Skip redundancy checks when adding union to union | carljm says unsafe due to cycle handling, needs extra tracking bit |
| 2484 | SARIF outputs | already claimed by 11happy, requires cross-crate port from ruff |
| 2276 | Auto-indent when Pylance disabled | unclear LSP mechanism, MichaReiser suggests workaround plugin |
| 2171 | Diagnostic on unsafe dunder overrides in tuple subclasses | new rule, moderate scoping work |
| 2111 | mypy/pyright rule mapping docs | PR #3336 already open (sebastianbreguel) |
| 1771 | Teach SymbolVisitor about more statements | completions, MichaReiser recently commenting, moderate+ complexity |
| 1477 | Show type alias name on hover | pierrem964 actively working, carljm confirmed design |
| 1364 | Playground crashes on rename to nothing | playground/wasm, discussion stalled on validation approach |
| 1219 | Document PYTHONPATH support | docs, mmlb working on it |
| 977 | Complete parentheses for function calls | server+completions, design discussion ongoing |
| 953 | workspace/didChangeConfiguration | pierrem964 claimed it |

## Strategy

Low external merge rate means bug fixes only. #3366 was ideal: mechanical bug, exact location given, no competition, and we already have a relationship via ruff PR #25066 (same maintainers). If this merges, next candidates: #3250 (diagnostic context) or #1364 (playground crash -- if we can resolve the validation design question).
