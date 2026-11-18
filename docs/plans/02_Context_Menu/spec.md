# 02 Context Menu

A "Context Menu" tab that shows the real right-click menu Windows builds, item by item,
and lets the user remove (and restore) items.

## User decisions

- Menus previewed: Folder, File, Folder background, Drive (all four, picked from a combo).
- Removal is a reversible hide: registry commands get `LegacyDisable`; shell extensions go
  on `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked`. Removed
  items stay listed, struck through, with Restore.
- Removing a shell-extension item blocks that extension everywhere (every menu it appears
  in).
- Windows built-ins with no registry source (Cut, Copy, Delete, Rename, Create shortcut,
  Properties, Paste, Open/Explore of folders) are shown greyed and are not removable.

## Proven mechanism (temp\probe_ctxmenu.py, run on this machine, read-only)

pywin32 (already bundled for send2trash) builds the exact classic menu Explorer shows:
`SHGetDesktopFolder` -> parent `IShellFolder` -> `GetUIObjectOf(hwnd, [child_pidl],
IID_IContextMenu)` -> `QueryContextMenu(CreatePopupMenu(), 0, 1, 0x7FFF, CMF_NORMAL)`, then
`GetMenuItemInfo` per item (text, separator, submenu, `hbmpItem`) and
`GetCommandString(id - 1, GCS_VERBW)` per item. Verified output for a folder: static verb
names (`openindopus`, `ClaudeCode`, `git_gui`, `copyaspath`, `PreviousVersions`), GUID verbs
for Explorer-command / app-package items (`{9F156763-...}` Open in Terminal, WinMerge,
Dropbox, ChatGPT), extension verbs (`SevenZip...`, `DropAs`), and `?` (no verb) for classic
shell extensions such as "What's locking this folder?", "Include in library",
"Pin to Start menu (Open-Shell)", "Send to". Folder background menus come from the
folder's `CreateViewObject(hwnd, IID_IContextMenu)`; drives from the `C:\` pidl.

## Module ctxmenu.py (new)

- `MenuItem`: text (with `&` stripped for display, raw kept), verb, separator flag, submenu
  children, icon `QPixmap` or None (from `hbmpItem` via `QtWin.fromHBITMAP`; the
  `HBMMENU_*` sentinel values and callback bitmaps give None), `source`.
- `build_menu(kind, path)` for kind in folder / file / background / drive; returns the
  top-level `MenuItem` list. Runs on the GUI thread (shell extensions need the STA Qt
  already set up). COM errors from building the menu itself propagate (fail loudly).
- Attribution, `Source(kind, label, key, clsid, dll, scope)` with kind one of
  `"command"`, `"extension"`, `"builtin"`:
  1. verb in the protected set {open, explore, opennewwindow, opennewprocess, opennewtab,
     find, cut, copy, paste, pastelink, delete, rename, link, properties, runas} or no
     verb and text matching the built-in Cut/Copy/Delete/Rename/Create shortcut/Properties
     -> builtin.
  2. verb is a `{GUID}` -> extension, clsid = verb.
  3. verb matches `shell\<verb>` under the menu's classes -> command (if that key has
     `ExplorerCommandHandler`, extension with that CLSID instead). Classes per kind:
     folder: Directory, Folder, AllFilesystemObjects; file: `*`, the extension, its ProgID,
     `SystemFileAssociations\<ext>`, `SystemFileAssociations\<PerceivedType>`,
     AllFilesystemObjects; background: Directory\Background; drive: Drive, Folder.
     Look up the real hive: `HKCU\Software\Classes\...` first, then
     `HKLM\Software\Classes\...`; the key returned is the one that defines the verb.
  4. otherwise probe each `shellex\ContextMenuHandlers` entry of those classes one at a
     time (`CoCreateInstance(clsid, IShellExtInit)` -> `Initialize(None, dataobject, None)`
     -> `IContextMenu.QueryContextMenu` into a scratch menu) and attribute items whose text
     (and submenu texts) that handler adds. A handler that fails to load is skipped; its
     items stay unattributed.
  5. unattributed -> builtin-like greyed row whose source label is "unknown".
  `dll` = the CLSID's `InprocServer32` default (either hive), when there is one.
- Removal store and actions, with injectable registry roots so tests can use scratch keys:
  `remove(source)`, `restore(entry)`, `removed()`.
  - command: write `LegacyDisable` (REG_SZ "") on the verb key; restore deletes it.
  - extension: write value `{CLSID}` = "" (REG_SZ) under the Blocked key; restore deletes it.
  - Record every removal under `HKCU\Software\wintools\ContextMenu\Removed` (value name
    `command|<hive>\<key>` or `extension|{CLSID}`, data = the item's display text and menu
    kind) so removed items can be listed and restored even when Windows no longer builds
    them into the menu. Only wintools's own records are listed; pre-existing
    LegacyDisable / Blocked entries are left alone.
  - Raise OSError (e.g. access denied on HKLM when not elevated) rather than masking it.

## Page (ContextMenuPage in ctxmenu.py)

- Top row: menu combo (Folder, File, Folder background, Drive), a path field with Browse
  (defaults: folder and background `%USERPROFILE%`, file `%SystemRoot%\win.ini`, drive
  `C:\`), Reload.
- Left, the preview: a QTreeWidget styled like the classic Windows menu (white
  background, 1px dark border, icon column, submenus as expanded children, separators as
  thin unselectable line rows, no header). Removable rows carry a checkbox (checked =
  keep). Built-in/unknown rows are greyed with no checkbox. Removed items (from the
  record) appear struck through at the end of their menu level after a separator, with a
  checkbox (checked = restore).
- Right: a datagrid styled with `keydiag.style_grid` (user's default datagrid preferences)
  showing the selected item's source: rows Source, Key, CLSID, DLL, Scope; path values use
  middle elision.
- Bottom: Preview button (pops a real `QMenu` at the button built from the rows currently
  kept: icons, separators, submenus, removed rows omitted) and Apply button (applies the
  pending removals / restores, then rebuilds); one-line status readout such as
  `3 removed   1 restored` or a genuine error. No explainer text anywhere.
- Build lazily: the first `showEvent` builds the menu (wait cursor), not app startup.

## wintools.py

Add the page as tab "Context Menu" with icon `tab_ctxmenu`, placed right after
"Uninstall". Touch only the tab list, the icons tuple and the import.

## Icon

Add `tab_ctxmenu` to `resource\icons\make_tab_icons.py` in the same Win7 style as its
neighbours (256-unit drawing + hand-tuned 16 px frame): a classic popup menu panel (white
rows with small icon squares and text bars, one row highlighted blue, a separator) with a
mouse pointer arrow. Regenerate with `C:\Python\313\python.exe
resource\icons\make_tab_icons.py`.

## Tests (TDD: see each fail first, then implement)

NEVER write LegacyDisable or Blocked entries to the real keys, never restart Explorer,
never invoke a menu command. Menu building is read-only and allowed against scratch
paths.

- `sandbox\test_ctxmenu_build.py`: `build_menu` for all four kinds (folder and file
  against scratch paths in %TEMP%, background of the scratch folder, drive `C:\`): non-empty,
  texts present, separators flagged, submenus nested; folder menu contains built-in rows
  (Cut/Copy/Delete/Rename/Properties) marked builtin and not removable; at least one
  command-sourced row whose key exists; GUID-verb rows attributed as extension with that
  CLSID.
- `sandbox\test_ctxmenu_remove.py`: remove / restore / removed() against scratch roots
  under `HKCU\Software\wintools-selftest-ctxmenu` (a fake verb key and a fake Blocked key):
  LegacyDisable added and removed, Blocked value added and removed, record store written
  and cleared, OSError surfaces on a refused write; delete the scratch tree afterwards.
- `sandbox\test_ctxmenu_page.py`: page offscreen with `build_menu` stubbed to a synthetic
  tree: row kinds/greying/checkboxes, unchecking marks a pending removal, Apply calls
  remove/restore with the right sources (stubbed), Preview's QMenu holds only kept rows.
- Update `sandbox\test_wintools_window.py` (tab count and shifted indices) and
  `sandbox\test_tab_icons.py` (icon list).

## Rules for the implementer

- Python only via `C:\Python\313\python.exe`. No git. No new dependencies (pywin32 and
  PyQt5's QtWinExtras are already installed). Comments only for a non-obvious why.
- File ownership: new `ctxmenu.py`; `wintools.py` (import + tab list + icons tuple only);
  `resource\icons\make_tab_icons.py` + `tab_ctxmenu.ico`; the tests named above. Another
  agent may be editing `tweaks.py` / `initcfg.py`; do not touch them.
- Lint `ruff check` on changed files; match the surrounding style (`ruff format --check`
  fails project-wide on old code). Byte-compile. Run every `sandbox\test_*.py` except
  `test_build_exe.py`. Known pre-existing failures, not yours: `test_registry_tree.py`
  (exit 1) and `test_orphans.py` (exit 127).
- Report: files changed, each test result, `STATUS: SUCCESS` or `STATUS: FAIL [reason]`
  with evidence.
