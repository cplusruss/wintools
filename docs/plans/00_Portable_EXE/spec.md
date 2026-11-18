# 00 Portable EXE

Single self-contained, portable `wintools.exe` that runs on another Windows 11 machine with
no Python installed.

## User decisions

- Packager: **PyInstaller onefile** (installed: 6.13.0, Python `C:\Python\313\python.exe`).
- Elevation: **keep the current relaunch** (`asInvoker` manifest; on start the exe asks UAC
  via `relaunch_elevated()` and carries on unelevated if declined).
- Settings: **per machine, unchanged** (QSettings registry `HKCU\Software\wintools\wintools`,
  `%APPDATA%\clean`, `%ProgramData%\wintools`).
  Superseded 2026-10-19: QSettings moved to `<exe name>.ini` beside the exe (`wintools.ini`
  beside `wintools.py` from source); undo records stay in `HKCU\Software\wintools`.

## Behaviour

1. `build_exe.py` (project root, new): one command builds `dist\wintools.exe`.
   - Runs PyInstaller through `C:\Python\313\python.exe -m PyInstaller` with CLI flags (no
     checked-in .spec): `--onefile --windowed --noconfirm --clean --name wintools
     --icon wintools.ico`, `--distpath dist`, `--workpath temp\pyi-build`,
     `--specpath temp\pyi-build`.
   - Bundles data: every `resource\icons\*.ico` to `resource\icons` and `wintools.ico` to `.`
     (paths passed to `--add-data` must be absolute because the spec lives in temp\pyi-build).
     Do not bundle `make_tab_icons.py`.
   - Excludes modules the app never imports if it measurably shrinks the exe (e.g. tkinter);
     report the before/after size, otherwise skip.
   - Fails loudly (non-zero exit, PyInstaller output shown) when the build fails; prints the
     exe path and size in MB on success.
2. Frozen-mode fixes in `wintools.py`, nothing else changes:
   - `relaunch_elevated()`: split the argument computation into a pure helper
     `_relaunch_args()` returning `(exe, params, cwd)`.
     - Not frozen (current behaviour, keep exactly): exe = `pythonw.exe` beside
       `sys.executable` (fallback `sys.executable`), params = script path + `sys.argv[1:]`,
       cwd = script directory.
     - Frozen (`getattr(sys, "frozen", False)`): exe = `sys.executable`, params =
       `sys.argv[1:]` only (no script path), cwd = directory of `sys.executable` (never the
       `_MEI` extraction dir, which is deleted when the first instance exits).
   - `ICON_DIR` and the `# <ICON_INJECT_START>` block keep using `__file__`; under PyInstaller
     `__file__` resolves inside `sys._MEIPASS`, where the bundled files land. Verify this in
     the smoke test rather than adding a second code path. The ICON_INJECT markers must stay
     byte-identical.
   - Smoke hook: in `main()`, when env var `WINTOOLS_SMOKE_MS` is set, quit the Qt app after
     that many milliseconds (`QTimer.singleShot`) so a build can be smoke-tested
     unattended. No other behaviour change.

## Tests (TDD: write each test, see it fail, then implement)

- `sandbox\test_relaunch_args.py`: `_relaunch_args()` in both modes by monkeypatching
  `sys.frozen`, `sys.executable`, `sys.argv`; asserts exe, params (quoted with
  `subprocess.list2cmdline`) and cwd as specified above, including an argument with a space.
- `sandbox\test_build_exe.py`: runs `build_exe.py`, asserts `dist\wintools.exe` exists, then
  launches it with `--no-elevate` and env `WINTOOLS_SMOKE_MS=4000` plus
  `QT_QPA_PLATFORM=offscreen` (no window on screen) and asserts exit code 0 within 90 s.
  A startup crash in the windowed exe shows a modal error dialog and never exits, so the
  timeout is the failure signal: kill the process tree (`taskkill /f /t /pid`) on timeout
  and fail. Prints `STATUS: SUCCESS` / raises otherwise, like the other sandbox scripts.

## Rules for the implementer

- Python only via `C:\Python\313\python.exe`. No git commands. No new dependencies.
- File ownership: `build_exe.py` (new), `wintools.py` (`relaunch_elevated`, `_relaunch_args`,
  `main` smoke hook only), `sandbox\test_relaunch_args.py` (new),
  `sandbox\test_build_exe.py` (new). Touch nothing else. Build output stays in `dist\` and
  `temp\pyi-build\`.
- No explainer text in any user-visible string. Comments only for a non-obvious why. No
  docstrings.
- Lint: `ruff check` on changed files (fix); `ruff format --check` fails project-wide on
  pre-existing code, so match the surrounding style instead of reformatting.
- Byte-compile changed files, then run every `sandbox\test_*.py`. Known pre-existing
  failures, not yours: `test_registry_tree.py` (stale "match leaf should be Checked"
  assertion) and `test_orphans.py` (prints SUCCESS, exits 127). Everything else must pass.
- Final report: files changed, exe size, each test's result, `STATUS: SUCCESS` or
  `STATUS: FAIL [reason]` with what ran and what it returned.
