# 02 Context Menu: review fixes

Fresh-context review of the first batch (ctxmenu.py) found the issues below. The user then
changed the removal mechanism for classic shell extensions (decision 2). Fix all five,
test-first. Probes the reviewer left in `temp\review_*.py` reproduce each one.

## 1. Critical: attribution by nested text

`_all_texts` flattens a handler's submenu texts and a top-level row is matched against
them. On a .png/.jpg/.bmp the real top-level "Rotate right" / "Rotate left" (verbs
`rotate90` / `rotate270`, from the ShellImagePreview handler
`{FFE2A43C-56B9-4bf5-9A79-CC6D4285608A}` under
`SystemFileAssociations\.png\ShellEx\ContextMenuHandlers`) are attributed to File Converter
`{af9b72b5-...}`, whose own submenu contains items with those texts. Removing them would
disable File Converter. Fix:

- A row is matched only against the top-level items a probed handler adds; submenu
  children of a row belong to that row's source.
- When both the real row and the probed item have a static verb (not empty, not "?"),
  the verbs must be equal.
- Empty text never matches.
- No match: the row stays "unknown" and greyed.
- `test_ctxmenu_build.py`: add an image case (make a scratch .png in %TEMP%, e.g. with
  `tweaks.write_black_png(path, 8, 8)`); for every row attributed by probing, assert its
  text is among that handler's top-level texts; on this machine assert Rotate left / right
  are not attributed to `{af9b72b5-f4e4-44b0-a3d9-b55b748efe90}`.

## 2. Important, user decision: disable menu registrations instead of the Blocked list

The Blocked list disables a CLSID for every shell role. "Give access to" and "Restore
previous versions" are also property-sheet handlers (Sharing / Previous Versions tabs),
7-Zip and Drop Here are also drag-drop handlers. The user chose:

- Classic extension rows (the CLSID has `shellex\ContextMenuHandlers` registrations): disable
  every ContextMenuHandlers registration of that CLSID, in every class key under both
  `HKCU\Software\Classes` and `HKLM\Software\Classes` (all classes, including
  `SystemFileAssociations\...`; "everywhere" still means every menu). Use the ShellExView
  method: the registration's default value becomes `-{CLSID}`.
  - Form A: the handler subkey has default value `{CLSID}`: set it to `-{CLSID}`.
  - Form B: the handler subkey is named `{CLSID}` with an empty or absent default: set the
    default to `-{CLSID}`.
  - Restore puts back exactly the previous state (the old default string, or no default
    value at all). The record entry must store every (hive\key, previous default or none)
    it touched.
  - Other roles (PropertySheetHandlers, DragDropHandlers, ColumnHandlers, icon overlays)
    are not touched.
- App-package / Explorer-command rows with no ContextMenuHandlers registration anywhere
  (GUID verbs such as Open in Terminal, WinMerge, ChatGPT; the review confirmed these have
  no other roles): the Blocked list, as before.
- A row whose CLSID has no ContextMenuHandlers registration and whose server DLL is under
  `%SystemRoot%` (Explorer internals such as the background "New" menu): builtin, greyed,
  not removable.
- The class scan must use injectable roots (extend `Roots` with the classes roots) so tests
  run against scratch keys; scanning all classes may take a second or two at Apply time,
  which is fine.
- Tests (`test_ctxmenu_remove.py`): scratch classes with a Form A and a Form B registration
  of the same fake CLSID in two classes plus a PropertySheetHandlers registration of it;
  remove writes `-{CLSID}` to both menu registrations and leaves the property-sheet one and
  the Blocked key untouched; restore returns both to their exact previous state (Form B
  without a default value again); the GUID-verb path still uses the scratch Blocked key;
  a %SystemRoot%-DLL CLSID with no registration is builtin and refused.

## 3. Minor: failed remove() deletes an older record

`ctxmenu.py:390-394` rolls back with an unconditional `_delete_record`. If the item already
had a record from an earlier removal, a later refused remove() erases it and the earlier
removal can no longer be restored from the tab. Roll back only a record this call created
(or put back its previous value). Test it with a refused write on a scratch root.

## 4. Minor: rows sharing one source toggle independently

Unchecking only "CRC SHA" keeps "7-Zip" in Preview, but Apply disables the shared 7-Zip
CLSID so both vanish. Rows with the same source must toggle together (unchecking one
unchecks every row of that source at every level; Preview reflects it), and the record's
text names all of them. Test in `test_ctxmenu_page.py`.

## 5. Minor: Apply hides a rebuild error

`apply()` calls `reload()` and then overwrites the status with the counts. If the rebuild
fails, its error must stay visible (counts and error both, or the error). Test it with a
stubbed `build_menu` that raises on the rebuild.

## Rules

- Python only via `C:\Python\313\python.exe`. No git. No new dependencies.
- Safety: never write LegacyDisable, `-{CLSID}` defaults or Blocked entries to real keys;
  scratch roots under `HKCU\Software\wintools-selftest-ctxmenu` only, deleted afterwards.
  Never invoke a menu command, never restart Explorer. Menu building is read-only and
  allowed. No large files; never grow files with `f.truncate`.
- File ownership: `ctxmenu.py` and `sandbox\test_ctxmenu_*.py` only. Another agent is
  editing clean.py / initcfg.py / test_initcfg.py: do not touch them.
- No explainer text in any user-visible string.
- `ruff check` on changed files, byte-compile, run every `sandbox\test_*.py` except
  `test_build_exe.py`; known pre-existing failure `test_registry_tree.py` (exit 1). Report
  files changed, each test result, `STATUS: SUCCESS` or `STATUS: FAIL [reason]` with
  evidence.
