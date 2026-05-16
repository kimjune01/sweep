# vavallee/bindery-plugins#1 — hypothesis graph

**Issue**: after `POST /v1/books`, books land in the Calibre SQLite DB but the GUI does not show them until the user hits Ctrl+R. Reporter proposes scheduling a GUI refresh on the main thread.

**Twist**: a prior PR (#2, v0.3.0, merged 2026-04-18) already claims to fix this — it schedules `QTimer.singleShot(0, gui.library_view.model().resort)` after `add_books`. The issue is open as a follow-up of sorts; the question is whether the existing fix actually works.

## H₀ — observation: does the v0.3.0 fix actually refresh the GUI?

- **Claim**: `QTimer.singleShot(0, gui.library_view.model().resort)` is sufficient to make the newly-added book appear in `library_view`.
- **Perturbation**: read the v0.3.0 fix (`plugins/calibre-bridge/plugin/adder.py:37`), then read Calibre's model + view code to trace what `resort()` actually does.
- **Trajectory**: divergent against. `resort()` calls `db.multisort(...)` followed by `beginResetModel/endResetModel`. After reset, Qt re-reads `rowCount`, which returns `len(db.data._map_filtered)`. The new book's id is **not** in `db.data._map_filtered` because `db.new_api.add_books` only writes to the DB tables; it does not insert into the in-memory `View._map`. The legacy wrapper `LibraryDatabase.add_books` (`calibre/db/legacy.py:343-357`) calls `self.data.books_added(book_ids)` immediately after `new_api.add_books`; the bindery plugin skips that wrapper.
- **Mode**: deduction (read calibre's source).
- **Status**: confirmed — the existing fix is a no-op for showing new rows.

## H₁ — the issue's proposed fix is also incomplete

- **Claim**: the issue proposes `gui.library_view.model().books_added(len(ids or dups))` + `gui.tags_view.recount()`. This is closer to right but still missing the `db.data.books_added([ids])` step.
- **Perturbation**: read `BooksModel.books_added(num)` at `calibre/gui2/library/models.py:536-540`. It calls `beginInsertRows(QModelIndex(), 0, num-1)` + `endInsertRows()` + `count_changed()`. It does **not** update `db.data._map`. So Qt thinks rows were inserted at the top, but `rowCount` (read from `db.data._map`) is unchanged, and the new ids are still not in the view's map.
- **Trajectory**: divergent against. The issue's fix would emit insertion signals to Qt without actually inserting; subsequent renders would show stale data and `data(index)` calls would index past `db.data._map_filtered`.
- **Mode**: deduction.
- **Status**: confirmed — the issue's suggested API call is necessary but not sufficient.

## H₂ — canonical post-add refresh in Calibre

- **Claim**: the correct sequence after `db.new_api.add_books` from a non-GUI thread is what Calibre's own actions do: `gui.current_db.data.books_added([id])` → `gui.library_view.model().books_added(1)` → `gui.tags_view.recount()` → optional `gui.refresh_cover_browser()`.
- **Perturbation**: read `calibre/gui2/actions/add.py:602-608` (`refresh_gui`) and `calibre/gui2/actions/delete.py:389` (uses `gui.current_db.data.books_added(book_ids)` for the inverse op).
- **Trajectory**: divergent confirmation. Calibre itself follows this pattern. `actions/add.py:refresh_gui` is exactly what gets called after the standard "Add books" flow. The `data.books_added` happens via the `Adder` callback path (legacy `add_books` wrapper) which the bindery plugin bypassed by going directly to `new_api`.
- **Mode**: deduction.
- **Status**: confirmed — this is the fix shape.

## H₃ — thread safety

- **Claim**: scheduling the three calls inside a closure passed to `QTimer.singleShot(0, ...)` makes them run on the GUI thread, so it's safe even though the caller (`bindery-bridge-http`) is a worker thread.
- **Perturbation**: cross-check `QTimer.singleShot` semantics; v0.3.0 commit message already validated this approach for `resort`.
- **Trajectory**: convergent — already proven by the v0.3.0 commit which uses the same dispatch. We just need a fatter closure.
- **Mode**: deduction.
- **Status**: confirmed.

## H₄ — duplicates

- **Claim**: the 409 (duplicate) path must not call the refresh. Issue's acceptance criteria explicitly mentions this. The current code already guards on `if ids:`, so duplicates skip the refresh — fix preserves that.
- **Status**: trivially satisfied by fix shape.

## Fix

```python
if ids:
    new_id = int(ids[0])
    if gui is not None:
        try:
            from PyQt5.Qt import QTimer

            def _refresh():
                try:
                    gui.current_db.data.books_added([new_id])
                    gui.library_view.model().books_added(1)
                    gui.tags_view.recount()
                except Exception:
                    pass

            QTimer.singleShot(0, _refresh)
        except Exception:
            pass
    return new_id, False
```

Three changes vs. current:
1. Use `gui.current_db.data.books_added([new_id])` to insert the id into the view's `_map` — the missing step.
2. Use `gui.library_view.model().books_added(1)` (matches Calibre's `actions/add.py:refresh_gui`) instead of `.resort()`.
3. Also call `gui.tags_view.recount()` so tag/category counts update.

## Regression test

`tests/test_adder.py`: add a test that the happy-path call invokes the GUI refresh closure with the three expected calls. With the current `.resort()` code: the test sees `resort` and no `books_added`/`recount`, fails. With the fix: passes.

Note: `QTimer.singleShot(0, fn)` in unit tests without a Qt event loop won't fire `fn`. The test must either monkeypatch `QTimer.singleShot` to invoke synchronously, or assert the closure was passed. Pattern: monkeypatch `PyQt5.Qt.QTimer.singleShot` to call its second arg immediately.

## Provenance

- `adder.py` current implementation: commit `1e01c5e` (v0.4.0, 2026-05-13) tightened the duplicate path and tightened types; the `resort()` choice was inherited from PR #2 (v0.3.0, 2026-04-18). The PR description says "library view refreshes after each add", but the choice of `resort()` (vs. `books_added` + `data.books_added`) was likely a misreading of Calibre's API surface — `resort` *sounds* like a refresh trigger but only re-sorts the existing in-memory map.
- Issue #1 was filed at 2026-04-18 17:43 (9 minutes before PR #2 merged); the maintainer almost certainly opened the issue, then opened the PR believing it fixed the issue. The issue stayed open because, while the EOF bug got fixed, the GUI refresh half didn't actually work.

## Reasoning mode table

| Node | Mode | Confidence |
|------|------|-----------|
| H₀ | deduction (read calibre source) | 95% |
| H₁ | deduction | 95% |
| H₂ | deduction (canonical pattern in calibre core) | 95% |
| H₃ | deduction + prior induction (v0.3.0 PR landed) | 99% |
| H₄ | deduction | 99% |

## Frontier

Closed. Single-file change with one regression test. Standalone-mode investigation: present the package and ask for human approval before pushing.
