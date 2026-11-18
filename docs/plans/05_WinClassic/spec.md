# 05 WinClassic

Make a fresh Windows 11 23H2 install look and behave like this PC's classic setup, from the
New PC list. The source of truth is this PC (captured), not the winclassic kit.
Background, kit analysis and this PC's audit: `research.md` in this folder.

## User decisions

- Replay this PC's working setup, not the kit's doc steps. Target build: 23H2 (22631) only.
- Components: ExplorerPatcher 22631.5335.68.2, Open-Shell 4.4.191 patched (Start Menu only),
  Windhawk 1.6.1 with this PC's registered mods, 7+ Taskbar Tweaker 5.15.4, classic
  appearance (colors, metrics, Marlett, DefaultColors rename), Defender exclusion for
  `C:\Program Files\ExplorerPatcher`.
- Left out: CPL Restoration, Win10 imageres.dll.mun, wallpaper swap, kit steps 3-6, 3D
  borders reg, Classic Task Manager, Winaero Tweaker, OpenWith, OfficeKeyFix, Themes.exe.
- A Capture button refreshes the package from this PC whenever the user changes it.
- Apply is rows in the New PC list (initcfg), before Restart Explorer. No separate tab.
- Remove `darkmode` from `NEWPC_KEYS` (stays on the Tweaks page).
- Windhawk 1.6.1 installer downloaded from the official GitHub release; 7+TT 5.15.4
  downloaded from an official source.

## Package: `resource\winclassic\` (never inside the exe)

- Resolve with one helper: source run, `<folder of winclassic.py>\resource\winclassic`;
  frozen exe (`sys.frozen`), `<exe folder>\..\resource\winclassic` (the exe lives in
  `dist\`). Missing folder or file is a genuine error naming the path. `build_exe.py` must
  keep embedding only the icons.
- `installers\` (placed once by the implementer, not by Capture):
  - `ep_setup.exe`: from `C:\Dropbox\Common\cfg\pc\W11\winclassic\Step7a(2)_Install_ExplorerPatcher_30-JUL-25_pwd=pwd.zip`
    (password `pwd` if zipfile needs it). Its SHA256 must equal the installed
    `C:\Program Files\ExplorerPatcher\ep_setup.exe`
    (`3680AA912D3ED60FD4762B349701E280A3D34771B659F14809D3882ABABD64F0`); stop and report if not.
  - `openshell_setup.exe`: copy of the kit's `Step8a_OpenShell_Patched_4.4.191.exe`.
  - `windhawk_setup.exe`: v1.6.1 asset from https://github.com/ramensoftware/windhawk/releases
    (confirm the tag and asset name read-only first). Report size and SHA256.
  - `7tt_setup.exe`: 5.15.4 from tweaker.ramensoftware.com or the ramensoftware GitHub
    releases. If 5.15.4 is not obtainable from an official source, use the kit's
    `Step15_7tt_setup.exe` (5.15.2) and say so in the report.
  - `marlett.ttf`: copy of the kit's `Step_8b_marlett.ttf`.
- `capture\`: written only by Capture (below).

## Capture (button "Capture Classic" on the Initial Config page)

Reads this PC and writes `capture\` atomically: build into a sibling temp folder, then
replace, so a failed capture leaves the previous one intact. Status line shows the result
(`Captured 6 components`) or the error.

- Registry captures are JSON (one file per component): a list of
  `{hive, path, name, type, data}` with every winreg type round-tripping exactly (DWORD,
  QWORD, SZ, EXPAND_SZ, MULTI_SZ, BINARY as hex, NONE). Apply writes them back with
  `winreg`; no regedit.
- `explorerpatcher.json`: `HKCU\Software\ExplorerPatcher` tree, excluding the build-specific
  symbol caches (subkeys `explorer`, `twinui.pcshell`) and the values `CrashCounter`,
  `SymbolsLastNotifiedOSBuild`. Plus `HKCU\...\Explorer\Advanced` values `TaskbarAl`,
  `TaskbarSmallIcons`, `TaskbarSD`, `TaskbarGlomLevel`, `MMTaskbarGlomLevel`,
  `Start_ShowClassicMode`; `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\ImmersiveShell`
  `UseWin32BatteryFlyout`; and the default values of
  `HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32` and
  `...\{1eeb5b5a-06fb-4732-96b3-975c0194eb39}\InprocServer32`.
- `openshell.json`: the `Settings` subkeys under `HKCU\Software\OpenShell` only.
- `taskbartweaker.json`: the settings subkeys under `HKCU\Software\7 Taskbar Tweaker`
  (at least `Options`, `OptionsEx`); no window-position or install values. Plus the HKCU Run
  value `7 Taskbar Tweaker`.
- `appearance.json`: `HKCU\Control Panel\Colors` (all values),
  `HKCU\Control Panel\Desktop\WindowMetrics` (all values except `AppliedDPI`),
  `HKCU\Control Panel\Appearance` tree, and the HKCU Fonts value `Marlett (TrueType)`.
- Before choosing the include/exclude lists for OpenShell and 7+TT, enumerate the live trees
  read-only and list in the report which subkeys/values were captured and which were left out
  and why (anything that changes on its own at runtime would make the row's state flicker).
- `windhawk\`: `windhawk.json` = `HKLM\SOFTWARE\Windhawk` tree; plus, for each mod registered
  under `HKLM\SOFTWARE\Windhawk\Engine\Mods`, its compiled DLL(s) named by the mod's
  registry entry from `C:\ProgramData\Windhawk\Engine\Mods\<arch>\` and its source
  `C:\ProgramData\Windhawk\ModsSource\<id>.wh.cpp`. Unregistered leftover DLLs are not copied.
  Verify the exact value names and folder layout on this PC (Windhawk 1.6.1) before coding.
- `manifest.json`: capture time, `CurrentBuild` and `UBR`, and the installed versions of
  ExplorerPatcher, Open-Shell, Windhawk and 7+TT (from `clean.enumerate_uninstall_entries()`).

## Apply (New PC rows)

New module `winclassic.py` holds the steps. Each step is a Tweak-like object (`key`, `label`,
`section` = "Classic", `state()` returning True/False/None, `apply(on)` returning 0 and
raising `OSError` with a short message on failure; `apply(False)` raises
`NotImplementedError`, nothing uninstalls). They are not added to `tweaks.TWEAKS`, so they
never appear on the Tweaks pages. `initcfg` looks steps up in `tweaks.TWEAKS` plus
`winclassic.STEPS`.

Every step first checks the running `CurrentBuild` equals the captured one and fails with
`build <n>, capture is <m>` otherwise. A missing installer or capture file fails the step.

Rows, appended to `NEWPC_KEYS` in this order (before `RESTART`):

1. `defenderep` "ExplorerPatcher Defender Exclusion": `Add-MpPreference -ExclusionPath
   "C:\Program Files\ExplorerPatcher"` via PowerShell. State: path in
   `(Get-MpPreference).ExclusionPath`.
2. `explorerpatcher` "ExplorerPatcher": `ep_setup.exe /update_silent` (switch found in the
   binary's strings; confirm against ExplorerPatcher's own documentation or source and cite it
   in a comment), wait for exit, then write `explorerpatcher.json`. Setup restarts Explorer
   itself.
3. `openshell` "Open-Shell": silent install of the Start Menu feature only (Open-Shell/Classic
   Shell setup takes `/qn ADDLOCAL=StartMenu`; confirm against Open-Shell docs and cite), then
   write `openshell.json`.
4. `windhawk` "Windhawk": `windhawk_setup.exe /S` (confirm Windhawk's silent switch and cite),
   stop the `Windhawk` service, copy mod DLLs and sources into `C:\ProgramData\Windhawk`,
   write `windhawk.json`, start the service.
5. `taskbartweaker` "7+ Taskbar Tweaker": `7tt_setup.exe /S` (confirm and cite), write
   `taskbartweaker.json`.
6. `classicappearance` "Classic Appearance": write `appearance.json`; copy `marlett.ttf` to
   `%LOCALAPPDATA%\Microsoft\Windows\Fonts\` (the HKCU Fonts value points there) and load it
   (`AddFontResourceW` + `WM_FONTCHANGE`); rename
   `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\DefaultColors` to
   `DefaultColors.bak` (copy tree, then delete; already renamed counts as done).

State per row: True when the installed version equals the manifest's (where there is one) and
every captured value reads back equal; False otherwise; None when the capture is missing.
Installers run through one function (`run_installer(path, args)`) that waits for exit and
raises `OSError` on a non-zero exit code, so tests patch a single point. Restart Explorer
stays the last row, as today.

## UI (initcfg.py)

- Remove `darkmode` from `NEWPC_KEYS`; add the six keys above as a final "Classic" group.
- "Capture Classic" button left of the status label, next to "New PC". Disabled while a New
  PC run is in progress.
- No explainer text: labels, versions, states, counts, genuine errors only.

## Tests (TDD: see each fail first)

User rule: nothing may change or reconfigure this PC. Allowed writes: files inside the wintools
project folder and under %TEMP%. Everything else is read-only: no registry writes at all (not
even scratch keys), no installers, services, Defender, fonts, Recycle Bin, scheduled tasks,
system parameters or Explorer restarts.

- All registry access in `winclassic.py` goes through a small registry interface with two
  implementations: the `winreg` one used by the app and an in-memory fake used by the tests.
  Every other side effect (installer runs, PowerShell, service control, font load, file
  copies) goes through injectable functions or roots, so tests use fakes and %TEMP% folders.
- `sandbox\test_winclassic_capture.py`: capture from a fake registry tree: every winreg type round
  trips; excluded subkeys and values are absent; only registered Windhawk mods' DLLs and
  sources are copied; a failure midway leaves the previous `capture\` untouched; manifest
  fields.
- `sandbox\test_winclassic_apply.py`: with `run_installer` and the PowerShell/service calls
  patched: exact installer paths and switches per step and their order; registry writes land
  in the fake registry exactly as captured; Windhawk stop, copy, start order; DefaultColors
  rename (and already-renamed); build mismatch and missing installer fail the step with the
  expected message; state True after apply and False after one captured value is changed.
- `sandbox\test_initcfg.py`: update the key count (darkmode out, six classic keys in). Do NOT
  run this file (it uses the real Recycle Bin). Put the row-order checks (classic rows just
  before Restart Explorer, darkmode absent, no duplicate keys) in
  `sandbox\test_winclassic_rows.py`, which only inspects `initcfg.STEPS`.
- Package layout check (`sandbox\test_winclassic_package.py`): the five installer files exist,
  `ep_setup.exe` SHA256 matches, the resolver returns the same folder for a source run and a
  simulated frozen run from `dist\`.

## Finish

- Run Capture for real on this PC once (read-only on the system; it only writes
  `resource\winclassic\capture\`) and report the captured counts per component and the total
  package size.
- `ruff check` on changed files, byte-compile, run only the new `sandbox\test_winclassic_*.py`
  files. Do not run any other sandbox suite or `build_exe.py`; list them as not run in the
  report so the user can decide. Report files changed, downloaded files with size and SHA256, the cited
  sources for each silent switch, each test result, and `STATUS: SUCCESS` or
  `STATUS: FAIL [reason]` with evidence.

## Rules

- Nothing may change or reconfigure this PC (see Tests). Reading the system is fine; the real
  Capture run is allowed because it only writes `resource\winclassic\capture\`.
- Python only via `C:\Python\313\python.exe`. No git. No new dependencies. Comments only for a
  non-obvious why.
- File ownership: new `winclassic.py`, `initcfg.py`, the tests above,
  `resource\winclassic\` (installers and capture). Do not edit other modules.
- Downloads: only the two installers named above, from the named official sources.
