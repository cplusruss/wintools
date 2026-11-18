# 01 Initial Config

An "Initial Config" tab whose New PC button turns a fresh Windows 11 install into the
user's plain, ad-free, dark baseline, step by step, with a checklist of what it applies.

## User decisions

- New PC applies: dark mode (apps + system), black desktop with no image, black sign-in
  screen, desktop cleanup, Start button on the left, max mouse speed, the visual-effects
  set below, no Start-menu ads, no taskbar search, plus every catalog tweak that removes
  ads, tips, Bing, widgets, chat, Copilot/Recall, Spotlight, telemetry, plus file
  extensions, classic context menu, Explorer opening to This PC.
- Excluded on purpose: Security, Windows Update, Services, Storage, Gaming, Performance
  sections, and the Telemetry items location / backgroundapps / cloudclipboard. `perf`
  ("Optimize Performance") conflicts with the visual-effects set and must stay out.
- Desktop cleanup: every item in the user's Desktop folder AND the Public Desktop goes to
  the Recycle Bin (except `desktop.ini`), after one Yes/No confirm showing the count;
  This PC / user files / Network / Control Panel / "Learn about this picture" desktop
  icons hidden, Recycle Bin shown.
- The tab is a per-step checklist: every step listed with a checkbox (default all checked)
  and its live state; New PC applies only the checked steps.
- `build_exe.cmd` (double-click build) is already done; not part of this work.

## Visual effects (Performance Options > Custom, from the user's screenshot)

| Setting | Want | Mechanism |
|---|---|---|
| Animate controls and elements inside windows | off | SPI 0x1042/0x1043 CLIENTAREAANIMATION (pvParam) |
| Animate windows when minimizing and maximizing | off | SPI 0x0048/0x0049 ANIMATION, ANIMATIONINFO{cbSize, iMinAnimate} |
| Animations in the taskbar | off | HKCU ...\Explorer\Advanced TaskbarAnimations DWORD 0 |
| Enable Peek | off | HKCU Software\Microsoft\Windows\DWM EnableAeroPeek DWORD 0 |
| Fade or slide menus into view | off | SPI 0x1002/0x1003 MENUANIMATION (pv) |
| Fade or slide ToolTips into view | off | SPI 0x1016/0x1017 TOOLTIPANIMATION (pv) |
| Fade out menu items after clicking | off | SPI 0x1014/0x1015 SELECTIONFADE (pv) |
| Save taskbar thumbnail previews | ON | DWM AlwaysHibernateThumbnails DWORD 1 |
| Show shadows under mouse pointer | off | SPI 0x101A/0x101B CURSORSHADOW (pv) |
| Show shadows under windows | off | SPI 0x1024/0x1025 DROPSHADOW (pv) |
| Show thumbnails instead of icons | ON | Advanced IconsOnly DWORD 0 |
| Show translucent selection rectangle | ON | Advanced ListviewAlphaSelect DWORD 1 |
| Show window contents while dragging | ON | SPI 0x0026/0x0025 DRAGFULLWINDOWS (uiParam) |
| Slide open combo boxes | off | SPI 0x1004/0x1005 COMBOBOXANIMATION (pv) |
| Smooth edges of screen fonts | ON | SPI 0x004A/0x004B FONTSMOOTHING (uiParam) |
| Smooth-scroll list boxes | off | SPI 0x1006/0x1007 LISTBOXSMOOTHSCROLLING (pv) |
| Use drop shadows for icon labels on the desktop | ON | Advanced ListviewShadow DWORD 1 |
| (dialog shows "Custom") | 3 | HKCU ...\Explorer\VisualEffects VisualFXSetting DWORD 3 |

SPI codes are GET/SET pairs as listed; `(pv)` means the SET value goes in pvParam,
`(uiParam)` in uiParam; GET always writes through pvParam. Every SET uses
`SPIF_UPDATEINIFILE | SPIF_SENDCHANGE` (1 | 2) so it persists and applies live. The "off"
state of the whole tweak is Windows' default (every row on, VisualFXSetting 0).

## New catalog tweaks (tweaks.py), new section "Appearance", tab "System"

Each non-registry op follows the existing duck type of `FilterKeysOp` / `BlackLockScreenOp`:
attributes `on`, `off`, `off_key = None`, non-empty `path`; methods `available()`,
`read()`, `is_on()`, `write(on)`.

1. `SpiOp(get, set_, on, off, via)`: generic SystemParametersInfoW op (via = "pv" or "ui");
   `path = f"SPI 0x{set_:04X}"`. `AnimationOp` for SPI_ANIMATION's struct. Raise OSError
   (WinError) when SystemParametersInfoW returns 0.
2. `darkmode` "Dark Mode": custom op writing HKCU
   `Software\Microsoft\Windows\CurrentVersion\Themes\Personalize` AppsUseLightTheme and
   SystemUsesLightTheme (on 0 / off 1), then broadcasting
   `SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet",
   SMTO_ABORTIFHUNG, 1000)`. read() true only when both are 0.
3. `blackdesktop` "Black Desktop": custom op. on: `SetSysColors` COLOR_DESKTOP (1) to 0,
   HKCU `Control Panel\Colors` Background "0 0 0", `SystemParametersInfoW(SPI_SETDESKWALLPAPER
   0x0014, 0, "", 3)`, HKCU `Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers`
   BackgroundType DWORD 1. off: wallpaper `%SystemRoot%\Web\Wallpaper\Windows\img0.jpg`
   through the same SPI call, BackgroundType 0, color untouched. read(): HKCU
   `Control Panel\Desktop` Wallpaper == "" and Colors Background == "0 0 0".
4. `visualfx` "Lean Visual Effects": the table above as SpiOp/AnimationOp/RegOp ops.
5. `mousemax` "Max Mouse Speed": SpiOp(0x0070, 0x0071, 20, 10, "pv").
6. `desktopicons` "Desktop: Recycle Bin Only": RegOps under HKCU
   `Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel`:
   {20D04FE0-3AEA-1069-A2D8-08002B30309D}, {59031a47-3f72-44a7-89c5-5595fe6b30ee},
   {F02C1A0D-BE21-4350-88B0-7367FC96EF3C}, {5399E694-6CE5-4D6C-8FCE-1D8870FDCBA0},
   {2cc5ca98-6485-489a-920e-b3e88a6ccce3} on 1 / off DELETE;
   {645FF040-5081-101B-9F08-00AA002F954E} on 0 / off DELETE; Advanced HideIcons on 0 /
   off DELETE.
7. Move the existing `blacksignin` tweak from section "Shell" to "Appearance" (key and ops
   unchanged).

## New module initcfg.py

- `NEWPC_KEYS`, in this order:
  - Appearance: darkmode, blackdesktop, blacksignin, visualfx, mousemax, desktopicons
  - Taskbar: taskbarleft, taskbarsearch, widgets, chat, taskbarweather, stickers
  - Start menu: startads, bingsearch, searchhighlights, recommended
  - Explorer: fileext, openthispc, syncads, shortcutsuffix, storeopenwith, classicmenu
  - Telemetry/AI: telemetrysvc, telemetrytasks, enhanceprivacy, cortana, newsinterests,
    copilot, recall, activityhistory, inkpersonalization, edgetelemetry, edgediscover,
    officetelemetry, firefoxtelemetry, chrometelemetry, nvidiatelemetry, vstelemetry
  - Annoyances: lockscreenads, scoobe, windowstips, suggestedcontent, websearch,
    logonanimation
  Then two action steps: "Recycle Desktop Items" (after desktopicons) and
  "Restart Explorer" (always last).
- `desktop_dirs()`: user Desktop and Public Desktop via `SHGetKnownFolderPath`
  (FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641} follows OneDrive redirection;
  FOLDERID_PublicDesktop {C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}); fail loudly if the call
  fails.
- `desktop_items(dirs)`: every entry of those dirs except `desktop.ini` (case-insensitive),
  sorted. `recycle(paths)`: `send2trash` each (already a dependency, see clean.py); returns
  `(recycled, [(path, error)])`; one failure does not stop the rest.
- `InitConfigPage(QWidget)`, constructor takes callbacks `report(msg)`, `refresh()`,
  `restart_explorer()` from the window:
  - A datagrid styled with `keydiag.style_grid` (user's default datagrid preferences):
    columns Step, Section, State. Column 0 items are checkable, all checked by default.
    State: "on" / "off" / "n/a" for tweaks (`Tweak.state()` True/False/None), the item count
    for Recycle Desktop Items (e.g. "7 items"), blank for Restart Explorer. Row tint like
    TweakPage: lime when on, pink when off, none when n/a or an action step.
  - A "New PC" button. On click: if Recycle Desktop Items is checked and the count is > 0,
    `QMessageBox.question` "Recycle N desktop items?"; No skips only that step. Then a
    `QThread` worker applies the checked steps in order (`tweak.apply(True)`, recycle,
    then restart_explorer last, which must run on the GUI thread after the worker
    finishes). Per-step OSError is recorded, never stops the run. The button is disabled
    while running; status label shows "k of n" while running and
    "N applied   M failed" after (plus "label: error" for each failure). Afterwards the
    page re-reads every state and calls `refresh()` so the System tab updates.
  - No explainer text anywhere: labels, counts and states only.
- `wintools.py`: add the page as the FIRST tab "Initial Config" with icon `tab_initcfg`;
  shut down its worker in `closeEvent` if it has one running (wait for it).
- Icon: add `tab_initcfg` to `resource\icons\make_tab_icons.py` in the same Win7 style as
  its neighbours (256-unit drawing + hand-tuned 16 px frame): a glossy monitor with a
  green check badge (reuse `round_badge(..., GREEN, ...)`), regenerate with
  `C:\Python\313\python.exe resource\icons\make_tab_icons.py`.

## Tests (TDD: see each fail first, then implement)

NEVER run New PC, `tweak.apply`, recycle, or Restart Explorer against this machine's real
settings or desktop. The only allowed live write is one SPI round trip that restores the
original value in a `finally`.

- `sandbox\test_spiop.py`: every visualfx SpiOp/AnimationOp `read()` returns a bool/int
  without error; a mousemax round trip (read original, write the other value, read back,
  restore original in finally, assert restored).
- `sandbox\test_initcfg.py`: NEWPC_KEYS all exist in `tweaks.TWEAKS`, no duplicates, none
  in the excluded sections, `perf` absent; the new tweaks are in section "Appearance";
  `desktop_items` / `recycle` against a scratch temp folder (files, a subfolder, and a
  `desktop.ini` that must be kept); `desktop_dirs()` returns two existing dirs;
  `InitConfigPage` built offscreen with stub callbacks: row count = keys + 2, all checked,
  states read, unchecking a row removes it from the step plan (expose a pure
  `plan()`/`checked_steps()` method for this), no apply performed.
- Update existing tests for the new tab: `sandbox\test_wintools_window.py` (tab count,
  `tabText(0) == "Initial Config"`, shifted indices), `sandbox\test_tab_icons.py` (icon
  list), `sandbox\test_tweaks.py` if it pins section contents.

## Rules for the implementer

- Python only via `C:\Python\313\python.exe` (bash `/c/Python/313/python.exe`). No git. No
  new dependencies. Comments only for a non-obvious why; no docstrings.
- File ownership: `tweaks.py`, new `initcfg.py`, `wintools.py` (tab wiring + closeEvent
  only), `resource\icons\make_tab_icons.py` + regenerated `tab_initcfg.ico`, the tests named
  above. Touch nothing else.
- Lint `ruff check` on changed files; `ruff format --check` fails project-wide on old code,
  so match the surrounding style. Byte-compile changed files. Run every
  `sandbox\test_*.py` EXCEPT `test_build_exe.py` (slow rebuild). Known pre-existing
  failures, not yours: `test_registry_tree.py` (exit 1) and `test_orphans.py` (exit 127).
- Report: files changed, each test result, `STATUS: SUCCESS` or `STATUS: FAIL [reason]`
  with evidence.
