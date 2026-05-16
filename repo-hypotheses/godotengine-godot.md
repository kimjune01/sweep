# Triage Graph: godotengine/godot

## Issue #119358 — Dragging from empty space in FileSystem with Split Mode drags selected file

**Status:** fix committed, ready for PR
**Labels:** bug, topic:gui
**Hypothesis:** H2-state (UI state leak — selection state leaks into drag initiation)

### Evidence chain

1. **Symptom:** Click empty space in file list panel, begin drag -> selected files appear as drag payload
2. **Root cause:** `get_drag_data_fw` in `filesystem_dock.cpp` had no guard on whether the drag point corresponds to a selected item. The `for` loop always collects all selected items regardless of click target.
3. **Fix:** Added `get_item_at_position` check (returns -1 for empty space) AND `!is_selected(item)` guard (prevents dragging when clicking unselected item during deadzone). Returns `Variant()` early for both cases.

### Review provenance

- **Codex:** Identified the missing empty-space guard
- **Gemini:** Identified the cursor-drift-during-deadzone scenario — clicking an unselected item and moving the mouse within the drag deadzone threshold could still trigger drag of the old selection. Recommended `!files->is_selected(item)` guard. Applied.

### Risk assessment

- **Scope:** Single function, two-line guard
- **Regression surface:** Drag-and-drop in FileSystem dock only
- **Test coverage:** Manual testing required (editor UI)
