# 04 Always On (New PC additions)

## User request

"In New PC also turn on screen saver, blank 10 minutes. Disable sleep, turn off disks,
hibernate etc (computer on all the time) - power options - always on."

## Decisions (orchestrator)

- Display turn-off timeout is NOT changed (not asked; the blank screen saver covers the
  screen).
- Power settings change the ACTIVE power scheme, both AC and DC, through powrprof.dll
  (PowerGetActiveScheme, PowerReadACValueIndex / PowerReadDCValueIndex,
  PowerWriteACValueIndex / PowerWriteDCValueIndex, PowerSetActiveScheme to apply,
  LocalFree for the scheme GUID) via ctypes, not by parsing powercfg output (localized).

## New tweaks (tweaks.py)

1. `screensaver` "Blank Screen Saver 10 min", section "Appearance", tab "System":
   - `SCRNSAVE.EXE` (REG_SZ) under `HKCU\Control Panel\Desktop` = full path of
     `%SystemRoot%\System32\scrnsave.scr` (the Blank screen saver); off: DELETE.
   - SPI_GETSCREENSAVEACTIVE 0x0010 / SPI_SETSCREENSAVEACTIVE 0x0011 (value in uiParam):
     on 1, off 0.
   - SPI_GETSCREENSAVETIMEOUT 0x000E / SPI_SETSCREENSAVETIMEOUT 0x000F (seconds in
     uiParam): on 600; off 600 too (revert switches the saver off, the timeout is left).
   Reuse `SpiOp` (via "ui"); verify the SPI codes and parameter placement against the
   SystemParametersInfo docs and cite them.
2. `alwayson` "Always On Power", section "Performance", tab "System": one custom op
   (duck type like `FilterKeysOp`: `on`, `off`, `off_key = None`, non-empty `path`,
   `available()`, `read()`, `is_on()`, `write(on)`) over these settings, AC and DC each:
   - Sleep after: SUB_SLEEP {238c9fa8-0aad-41ed-83f4-97be242c8f20} /
     STANDBYIDLE {29f6c1db-86da-48c5-9fdb-f2b67b1f44da} -> 0 (never)
   - Hibernate after: SUB_SLEEP / HIBERNATEIDLE {9d7815a6-7ee4-497e-8888-515a05f02364} -> 0
   - Hybrid sleep: SUB_SLEEP / HYBRIDSLEEP {94ac6d29-73ce-41a6-809f-6363ba21b47e} -> 0 (off)
   - Turn off hard disk after: SUB_DISK {0012ee47-9041-4b5d-9b77-535fba8b1442} /
     DISKIDLE {6738e2c4-e8a5-4a42-b16a-e040e769756e} -> 0 (never)
   - USB selective suspend: {2a737441-1930-4402-8d77-b2bebba308a3} /
     {48e6b7a6-50f5-4782-a5d4-53bb8f07e226} -> 0 (disabled)
   Verify every GUID against Microsoft's power setting docs (or `powercfg /aliases` /
   `powercfg /qh` output read-only) and cite them. A setting the machine's scheme does not
   have (e.g. hybrid sleep on some systems) is skipped, not an error; state() covers the
   settings that exist. `off` restores the Windows Balanced defaults for these settings
   (look them up in Microsoft's documentation and cite them; do not guess).
   `read()` true only when every existing setting reads its "on" value for AC and DC.
   Errors from powrprof (non-zero return) raise OSError with the code.
   Note: "Performance" is an excluded section for the rest of New PC; `alwayson` is listed
   explicitly by key, which is fine, but update the excluded-section assertion in
   test_initcfg.py to allow exactly this key.
3. Existing `hibernate` tweak ("Disable Hibernation", HibernateEnabled 0) joins New PC as is.

## initcfg.NEWPC_KEYS

Append `screensaver` to the Appearance group (after `desktopicons`), and add `alwayson`
and `hibernate` as a new group right after the Appearance group (before the Recycle step's
neighbours stay as they are: the Recycle step must remain directly after `desktopicons`,
so put `screensaver` before `desktopicons` and `alwayson`, `hibernate` after the Recycle
step, i.e. at the start of the Taskbar group's position). Update the step-list assertions
in `sandbox\test_initcfg.py` accordingly.

## Tests (TDD: see each fail first)

NEVER change this machine's real power scheme or screen saver except the round trips below.
- `sandbox\test_spiop.py`: assert the `screensaver` ops exactly (codes, on/off, via,
  SCRNSAVE.EXE path); a self-restoring round trip of SPI_SETSCREENSAVETIMEOUT only (read the
  original, set original+60, read back, restore in finally, assert restored). Do not toggle
  the screen saver active state live.
- `sandbox\test_always_on.py` (new): every GUID constant; read() returns bool against the
  live scheme (read-only); write() tested against a scratch power scheme: duplicate the
  active scheme with PowerDuplicateScheme, operate on the duplicate's GUID (make the op's
  target scheme injectable), never PowerSetActiveScheme in tests, delete the duplicate with
  PowerDeleteScheme in a finally; assert AC/DC values after write(True) and after
  write(False) equal the documented defaults; a missing setting is skipped.
- `sandbox\test_initcfg.py`: the new keys and positions.

## Rules

- Python only via `C:\Python\313\python.exe`. No git. No new dependencies. Comments only for
  a non-obvious why.
- File ownership: `tweaks.py` (new ops and tweaks only), `initcfg.py` (NEWPC_KEYS only),
  `sandbox\test_spiop.py`, `sandbox\test_initcfg.py`, `sandbox\test_always_on.py` (new).
  Another agent is reviewing the repo read-only; nothing else is being edited.
- No explainer text in any user-visible string.
- `ruff check` on changed files (match surrounding style; `ruff format --check` fails
  project-wide on old code), byte-compile, run every `sandbox\test_*.py` except
  `test_build_exe.py`; known pre-existing failure `test_registry_tree.py` (exit 1). Confirm
  afterwards that the live active scheme's values and the screen saver settings are
  exactly what they were before you started (record them first). Report files changed, the
  cited GUIDs/defaults with sources, each test result, `STATUS: SUCCESS` or
  `STATUS: FAIL [reason]` with evidence.
