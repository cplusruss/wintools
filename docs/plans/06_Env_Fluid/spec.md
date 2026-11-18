# 06 Env Fluid

Make the Environment tab (`envedit.py`, `EnvPage` / `EnvTree`) fluid to edit: PATH-style
lists get drag, keyboard, context-menu, clipboard and undo editing; System and User sit
side by side. Registry, snapshot, check/write and broadcast logic are unchanged.

## User decisions

- Layout: System left, User right, vertical divider (`QSplitter(Qt.Horizontal)`, equal
  stretch). Each side keeps its own tree; the bottom button row stays shared and acts on
  the focused tree (existing `_focus_tree`).
- Editing: drag-and-drop reorder, keyboard editing, right-click menu, undo/redo.
- Extras: copy/paste entries, browse for folder, remove duplicates.
- Not wanted: drag between System and User.
- Strip explainer strings on this tab (see Strings).
- Explicit Save / Revert stays; nothing writes the registry before Save.

## Behaviour

Entries are the child rows of a list variable. "Writable" = user tree, or system tree with
`can_write_system()`. A read-only tree allows only selection, Copy and Open in Explorer.

### Undo / redo
- History of `Env` states: `[saved]` after every reload/save/restore; pointer at the end.
- After every completed mutation (edit commit, insert, delete, move, drop, paste, cut,
  browse, remove missing/duplicates, add/rename/delete variable) push `current()` if its
  `as_json()` differs from the state at the pointer; pushing drops any redo tail.
- Ctrl+Z steps back, Ctrl+Y and Ctrl+Shift+Z step forward; each re-fills both trees from
  that state via `_fill` (expansion kept) and updates the pending readout.
- Keys handled in `EnvTree.keyPressEvent` (not window shortcuts), so an open line editor
  keeps its own Ctrl+Z.

### Drag-and-drop
- Writable trees only. One or several selected entries of the same variable drag as a
  block, order kept, to a position within that same variable. Dropping on the variable row
  appends at the end. Any other target (another variable, top level, the other tree,
  mixed-parent selection, a variable row being dragged) is refused (no drop indicator).
- `dropEvent` resolves the target to `(parent, index)` and calls a plain method
  `move_entries(items, index)` that does the move; both are testable without a real drag.
  Selection stays on the moved entries.

### Keyboard (on a writable tree)
- Del: delete selection (entries and/or variables); the row after the last deleted one
  becomes current so repeated Del keeps going.
- Insert, or the Add entry button: insert a blank entry after the current entry (or at the
  end when a variable is current; a single-value variable becomes a list first, as
  `add_entry` does today) and open its editor at once. No dialog. Committing empty text
  removes the row and records nothing.
- F2 / Enter: edit the current item (value column for entries).
- Ctrl+Up / Ctrl+Down (and the Up / Down buttons): move the selected entries of one
  variable by one, as a block; blocked at the ends. Ctrl+Home / Ctrl+End: to top / bottom.
- Ctrl+C: copy selected entries one per line (a single variable row: its value).
  Ctrl+X: copy then delete. Ctrl+V: insert after the current entry (or at the end of the
  current variable), splitting the text on `;` and newlines, trimming, dropping empties.

### Variables
- Add variable (button, and context menu on empty space / variable rows): insert a blank
  top-level row and open the name editor in place; after the name commits, open the value
  editor. Empty name on commit removes the row. No dialogs.
- Committing a name that already exists in that scope (case-insensitive) reverts the edit
  and puts `<Name> already exists` in the status readout. Applies to rename too.

### Right-click menu
- Entry: Insert above, Insert below, Edit, Browse..., Open in Explorer, Copy, Cut, Paste,
  Delete, Move to top, Move to bottom.
- Variable: Add entry, Add folder..., Edit, Copy, Paste, Delete, Add variable.
- Empty area: Add variable, Paste (only when a variable is current).
- Show each action's shortcut in the menu. Read-only tree: Copy and Open in Explorer only.

### Browse for folder
- `QFileDialog.getExistingDirectory`, starting at the expanded entry when it exists.
- Browse... on an entry replaces its text; Add folder... (menu, and a bottom-row button)
  inserts the chosen folder after the current entry / at the end of the variable.
- Paths written back with backslashes.

### Open in Explorer
- Expands the entry against `merged(current())`; opens it with `os.startfile`. Missing
  path: status readout `not found: <path>`.

### Remove duplicates
- Bottom-row button next to Remove missing, same targeting rule (selected variable, else
  all lists in the focused tree). Drops every entry whose key
  (`strip().rstrip("\\").lower()`, the key `_mark` already uses) was seen earlier in that
  variable; keeps the first. Status `Removed N duplicate entries` (singular for 1).

### Strings
- Delete: `btn_broadcast` and `btn_clean` tooltips; entry tooltips "Folder or file not
  found", "Duplicate entry", "Refers to an undefined %variable%" (the red/orange/gray
  colouring stays). The tooltip that shows an entry's expanded value is a value; keep it.
- Pane titles: `System variables`, `User variables`.
- `lbl_admin`: `system read-only` when not admin, else empty.
- Save refusal: `Not saved: system variables are read-only`.
- No new tooltips, hints or prose labels. Menu items and buttons are short labels.

## Ownership

`envedit.py`, `sandbox/test_envedit.py`, new `sandbox/test_envedit_editing.py`. Touch
nothing else; if wintools.py would need a change, stop and report.

## Tests (offscreen, scratch roots exactly like `test_envedit.py`, real keys compared
before/after, broadcast stubbed)

`sandbox/test_envedit_editing.py`:
- Splitter orientation is horizontal, System widget left of User.
- Insert on an entry: blank row after it with an open editor; committing text adds it;
  committing empty removes it and leaves history unchanged.
- Del on two entries removes both; current row is the following entry.
- Ctrl+Down / Ctrl+Up on a two-entry block moves both, order kept; blocked at ends;
  Ctrl+Home / Ctrl+End.
- `move_entries` and the drop resolver: within-variable drop lands at the right index;
  drop on the variable row appends; cross-variable, top-level and mixed-parent drops are
  refused.
- Ctrl+C then Ctrl+V duplicates entries after the current one; pasting `a;b\nc` inserts
  three entries; Ctrl+X removes and the clipboard holds them.
- Undo/redo: three different mutations, Ctrl+Z three times returns to `saved` (no pending
  changes), Ctrl+Y re-applies; a new mutation after undo drops the redo tail; reload
  resets history.
- Add variable inline; duplicate name reverts with `<Name> already exists`.
- Remove duplicates keeps the first of `C:\x`, `c:\X\` and reports the count.
- Browse... with `QFileDialog.getExistingDirectory` monkeypatched; Open in Explorer with
  `os.startfile` monkeypatched (called with the expanded path; missing path gives
  `not found: ...`).
- Read-only system tree (roots.system on HKLM-like stand-in or `can_write_system`
  patched to False): Del/Insert/drag/paste do nothing; context menu has only Copy and
  Open in Explorer.
- Save after a sequence of edits writes exactly the expected scratch values.
- None of the deleted tooltip strings appear on any item or button.

`sandbox/test_envedit.py`: keep passing; update only what the layout/string changes break.

## Rules for the implementer

- TDD: write the new test first, run it and see it fail (red), then implement (green).
- Fail loudly in data paths; narrow try/except only for genuinely optional operations.
- Comments only for a non-obvious why; no docstrings beyond the existing style.
- `ruff check` clean on changed files. The repo is not `ruff format`-ed: do not reformat
  whole files; keep the surrounding style.
- Byte-compile, then run every `sandbox\test_*.py` with `C:\Python\313\python.exe`.
- No git commands, no worktrees.
- Finish with `STATUS: SUCCESS` or `STATUS: FAIL [reason]`, the files changed, and each
  test file run with its result.
