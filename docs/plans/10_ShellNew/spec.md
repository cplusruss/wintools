# 10 ShellNew: hide and restore entries of Explorer's New submenu

## User decisions
- Scope: hide and restore existing New entries only. No adding entries, no reordering.
- Placement: a fifth choice "New" in the Context Menu tab's menu combo (`KINDS` in
  `ctxmenu.py`). Same tree, checkboxes, struck-through restorable rows, Preview, Apply.
- Mechanism: hiding renames the `ShellNew` key to `_ShellNew`; restoring renames it back.
  The renamed key is the record (NirSoft ShellMenuNew convention). Nothing is written to
  wintools' own `Removed` record key for these.

## Which entries Explorer shows (verified on this machine)
Checked against Explorer's own cache
`HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Discardable\PostSetup\ShellNew`
value `Classes`: the rule below reproduced it exactly (0 extra, 0 missing, 14 extensions).

For each class key named `.ext` in the merged classes view (HKCU over HKLM):
- `P` = default value of `.ext`.
- Location = `.ext\P\ShellNew` if that key exists, else `.ext\ShellNew`. No fallback when
  the `P` key exists but is invalid (`.sldasm` here: an empty `SldAssem.Document\ShellNew`
  hides a valid `.sldasm\ShellNew`, and Explorer does not show it).
- Shown when the location has a value named NullFile, FileName, Data or Command
  (case-insensitive). An empty key, or one holding only `""`, is not shown.

Merged view: compute it over `roots.classes` (HKCU first, then HKLM), not via
`HKEY_CLASSES_ROOT`, so tests can point it at temp keys. A key or value present in HKCU wins.

## Rows
- Folder (`Folder\ShellNew`) and Shortcut (`.lnk`) first, as builtin rows (grey, no
  checkbox), then a separator, then every other shown entry sorted by extension
  (case-insensitive). That is Explorer's order in the screenshot.
- Text: the location's `MenuText` (resolve `@dll,-id` with `SHLoadIndirectString`), else
  `P`'s `FriendlyTypeName` (indirect too), else `P`'s default value, else the extension.
  An indirect string that cannot be loaded (its DLL is gone) falls through to the next one.
  Keep the text exactly as the registry has it ("Verilog File Type" ends in a stray curly
  quote on this machine; show it as is).
- Icon: the file type's small icon, `SHGetFileInfo(".ext", FILE_ATTRIBUTE_NORMAL,
  SHGFI_ICON | SHGFI_SMALLICON | SHGFI_USEFILEATTRIBUTES)` through the existing `_pixmap`.
- `Source(kind="shellnew", label=ext, key=<full key path(s) of the ShellNew location>,
  clsid="", dll="", scope=<HKCU / HKLM / HKCU+HKLM>)`. `_record_name` gives
  `f"shellnew|{ext}"`.
- Hidden rows (struck through, unchecked, below a separator, as today): an extension that
  is not shown and has a `_ShellNew` key directly under `.ext` or under any direct subkey of
  `.ext`, in either hive, whose values pass the same NullFile/FileName/Data/Command test.
  Built as `Removed(name="shellnew|.ext", text, menu="new", source, regs=())` with the
  text rule above applied to the `_ShellNew` key. This lists entries hidden earlier by
  ShellMenuNew (`.amm`, `.bbsx`, `.cir`, `.contact`, `.library-ms` and others here).
- The path box and Browse button are disabled while "New" is selected; Reload stays.

## Hide and restore
Route through the existing `remove()` / `restore()` on `source.kind == "shellnew"` so
`ContextMenuPage.apply` needs no new branch.
- Hide `.ext`: in each hive of `roots.classes`, rename every `ShellNew` key directly under
  `.ext` and under each direct subkey of `.ext` to `_ShellNew`. Renaming all of them, not
  only the location, stops a second key from surfacing (the `.sldasm` case). If a
  `_ShellNew` already sits beside it (stale copy: `.qraw`, `.qsch`, `.qsym`, `.rdw`, `.dwg`
  here), delete that stale key tree first.
- Restore `.ext`: rename every `_ShellNew` under the same places back to `ShellNew`. If a
  `ShellNew` already exists beside one, raise `FileExistsError` naming the key and change
  nothing for that extension.
- Rename with `advapi32.RegRenameKey` through ctypes on the opened parent key's handle;
  raise `OSError(winerror)` on a non-zero return. No copy-and-delete.
- A rename that fails partway (HKLM refused when not elevated) renames back the keys
  already done, then re-raises.
- After any hide or restore, delete the Explorer cache key above (missing is fine), so the
  New submenu rebuilds on next open. Put its location in `Roots` (new field with the real
  key as default) so tests use a temp key.
- HKLM writes need elevation; the resulting `OSError` surfaces through `apply`'s existing
  status line. No new UI text.

## Tests: `sandbox\test_ctxmenu_shellnew.py` (new)
Use a temp `Roots` whose `classes` and cache point under
`HKCU\Software\wintools-test-shellnew\...`; delete it in `finally`. No widgets except the
last check (offscreen, as the other ctxmenu page test does).
1. `.a\ShellNew` with Command: listed. `.b\Pb\ShellNew` with FileName (`.b` default `Pb`):
   listed. `.c\ShellNew` empty: not listed. `.d` with empty `Pd\ShellNew` plus
   `.d\ShellNew` NullFile: not listed.
2. HKCU value overrides HKLM in the merged view (default of `.e` differs per hive).
3. Text precedence: MenuText > FriendlyTypeName > progid default > extension.
4. Order: Folder, Shortcut builtin and first; the rest sorted by extension.
5. Hide renames all `ShellNew` keys under the extension in both hives, replaces a stale
   `_ShellNew`, keeps its values, and deletes the cache key. Restore puts them back.
   Restore with a live `ShellNew` beside the `_ShellNew` raises `FileExistsError` and
   changes nothing.
6. Hidden list: valid `_ShellNew` listed; an empty `_ShellNew` not listed.
7. Page: "new" is in `KINDS`; selecting it disables the path box and Browse.
Also run once, not as a sandbox test: on the real registry, the shown extensions equal the
cache's `Classes` minus `Folder` (`temp\check_shellnew_rule.py` does this today).

## Rules
- Files owned: `ctxmenu.py`, new `sandbox\test_ctxmenu_shellnew.py`. Existing
  `sandbox\test_ctxmenu_*.py` may only be touched if a `KINDS` count assertion needs the new
  entry.
- TDD: write the new tests, run them and see them fail, then implement.
- `ruff check` and `ruff format --check` on changed lines, `py_compile`, then every
  `sandbox\test_ctxmenu_*.py` and `sandbox\test_wintools_window.py`.
- No explainer text anywhere in the UI. Comments only for a non-obvious why.
- Never write to the real `HKCR`/`Software\Classes` or the real cache key in tests.
