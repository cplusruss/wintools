# 07 Ctxmenu Complete

The Context Menu tab (`ctxmenu.py`) misses items that Explorer shows. Findings (evidence in
`temp\dump_ctxmenu.py`, `temp\flags_check.py`, `temp\handlers_check.py`,
`temp\probe_err.py`, `temp\pkg_check.py`):

1. wintools runs elevated. Windows does not load packaged (MSIX / sparse-package) shell
   extensions into elevated processes. Open in Terminal, Open project in ChatGPT, WinMerge,
   Transfer a copy..., and the Dropbox items (Copy Dropbox link, Share..., Make
   online-only, View on Dropbox.com, Manage folder access) are packaged-only: their CLSIDs
   exist only under `HKCR\PackagedCom\ClassIndex`. An unelevated `build_menu` lists all of
   them with GUID verbs.
2. `build_menu` calls `QueryContextMenu` with `CMF_NORMAL`; Explorer passes
   `CMF_EXPLORE | CMF_CANRENAME`, which adds Rename.
3. The Directory Opus Context Menu handler (`dopuslib.dll`, CLSID
   `{E9FE4040-3C93-11D4-8006-00201860E88A}`, registered as
   `Directory\shellex\ContextMenuHandlers\OpusZip`) is created but returns E_FAIL from
   `Initialize` outside Explorer/Opus. In Explorer it adds Open in Explorer, Open in new
   Folder Tab and Unlock (strings in Opus `Language\english.dll`).
4. Not in scope: cloud-file verbs (Always keep on this device, Free up space) that Explorer
   itself adds inside the Dropbox sync root; Open in new process (Shift menu only).

## User decisions

- When elevated, build the menu in a short-lived unelevated helper launched through
  Explorer; removal stays in the elevated app.
- Items from handlers that refuse to load outside Explorer get listed and are removable.

## Behaviour

### A. Unelevated helper
- `wintools.main()` checks for `--ctxmenu-dump <kind> <path> <outfile>` before anything else
  (before elevation and before QApplication is created for the GUI): runs the dump and
  exits. Works for source (`pythonw wintools.py ...`) and frozen exe (`wintools.exe ...`); reuse
  the frozen/source split of `_relaunch_args`.
- The dump builds the menu exactly as `build_menu` does (same attribution) and writes JSON:
  per item text, raw, verb, separator, children, icon (PNG, base64, or null) and source
  fields. Write to `<outfile>.tmp` then rename, so the reader never sees a partial file.
- `ctxmenu` gets a `load_menu(kind, path)` used by the page: not elevated, calls
  `build_menu` in-process (today's path); elevated, launches the helper unelevated and
  reads the JSON back into `MenuItem` / `Source`.
- Unelevated launch: through Explorer's own shell, the standard chain:
  `CoCreateInstance(CLSID_ShellWindows)` -> `FindWindowSW(CSIDL_DESKTOP, ...,
  SWC_DESKTOP, SWFO_NEEDDISPATCH)` -> `IServiceProvider.QueryService(SID_STopLevelBrowser,
  IShellBrowser)` -> `QueryActiveShellView` -> `GetItemObject(SVGIO_BACKGROUND, IDispatch)`
  -> `.Application.ShellExecute(file, args, dir, "open", 0)`. The launch function is
  injectable for tests.
- Wait for the outfile with a deadline (20 s), keeping the UI's wait cursor. Timeout or a
  helper that wrote an error: genuine error in the status label, e.g. `menu helper timed
  out`; nothing else listed. No silent fallback to the elevated build.
- Outfile in the user's temp folder, unique per call, deleted after reading.

### B. Packaged handler sources
- A CLSID found only under `HKCR\PackagedCom\ClassIndex\{CLSID}` gets
  `Source("extension", <package name>, "HKCR\PackagedCom\ClassIndex\{CLSID}", clsid,
  <package install folder or "">, "all menus")`, where package name is the package full
  name up to the first `_` (e.g. `Microsoft.WindowsTerminal`, `DropboxInc.Dropbox`).
- Removal of these keeps using the existing no-registration path (`Shell Extensions\Blocked`
  by CLSID); restore removes the block. Verify `remove`/`restore`/`removed` round-trip for
  one packaged CLSID against scratch roots.

### C. Explorer's flags
- `build_menu` and `_probe` both use `CMF_EXPLORE | CMF_CANRENAME`, so attribution by
  text matches the menu that was read (Link Shell Extension changes its label between
  calls otherwise). Rename shows as built-in.

### D. Handlers that refuse to load here
- For each enabled ContextMenuHandlers registration of the menu's classes whose CLSID
  creates (`CoCreateInstance` succeeds) but fails `Initialize` or `QueryContextMenu`: add a
  row after the live items, separated from them, text = the handler's CLSID name (e.g.
  `Directory Opus Context Menu`), checkable and removable like any classic extension
  (disables its ContextMenuHandlers registrations, restorable). `Class not registered`
  and other creation failures are not listed.
- This runs inside the dump too, so the helper and the in-process path give the same rows.
- Preview menu shows these rows as plain entries.

### Strings
- Labels and state readouts only; the timeout/helper failure text is a genuine error. No
  tooltips, no explanations.

## Ownership

`ctxmenu.py`; `wintools.py` (only the `--ctxmenu-dump` hook in `main()` and whatever
`_relaunch_args`-style helper it needs); `sandbox\test_ctxmenu_*.py` (existing and new).
Another agent is editing `envedit.py` and its tests: do not touch them.

## Tests

- Dump/load round trip: `load_menu` via the injectable launcher running the helper as a
  plain subprocess gives the same texts, verbs, separators, children and source fields as
  in-process `build_menu` for folder, file, background and drive. Icons survive (non-null
  count matches).
- The real Explorer launch chain runs once (works unelevated too) and produces the file.
- Timeout path: a launcher that does nothing gives the timeout error, no rows.
- Packaged source: a CLSID present only under PackagedCom gets the package-name label;
  remove/restore of it round-trips against scratch roots (Blocked key and record).
- Flags: the folder menu contains `Rename` as built-in.
- Refusing handler: deterministic test with `_probe`-level injection (a registered handler
  forced to the created-but-refused state) gives one checkable row with its CLSID name;
  remove/restore round-trip against scratch roots. Also print (not assert) whether the
  real Directory Opus handler row appears on this machine.
- Existing `test_ctxmenu_build.py`, `test_ctxmenu_page.py`, `test_ctxmenu_remove.py` pass.

## Rules for the implementer

- TDD: new tests first, see them fail, then implement.
- Fail loudly in data paths; narrow try/except only around genuinely optional operations
  (e.g. one handler's probe).
- Comments only for a non-obvious why. Match the surrounding style.
- `ruff check` clean on changed files; do not `ruff format` whole files.
- Byte-compile, then run every `sandbox\test_*.py` with `C:\Python\313\python.exe`,
  except `test_envedit*.py` (owned by another agent mid-change).
- No git, no worktrees. Write large files in pieces (Write ~150 lines, then Edit to
  append); never one huge Write.
- Finish with `STATUS: SUCCESS` or `STATUS: FAIL [reason]`, files changed, each test file
  with its result, and the real-machine rows printed for a folder in `C:\Dropbox`.
