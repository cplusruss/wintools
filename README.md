# wintools

Windows 11 utility app (PyQt5): new-PC setup, tweaks, hardware info, and disk and registry cleanup in one window.

## Download

Get `wintools.exe` from the [latest release](https://github.com/cplusruss/wintools/releases/latest). It is a single portable exe: no Python, no installer.

- Settings are saved in `wintools.ini` beside the exe.
- Undo data: registry backups in `%APPDATA%\clean`, context-menu removal records in `HKCU\Software\wintools`, GPU profiles in `%ProgramData%\wintools`.
- On start it asks for elevation (UAC); if declined it keeps running unelevated. `--no-elevate` skips the prompt.
- The Classic rows of Initial Config also need the winclassic kit: unzip `wintools-winclassic-kit.zip` from the same release into the exe's folder, so the layout is:

```
wintools.exe
resource\winclassic\installers\...
resource\winclassic\capture\...
```

## Tabs

| Tab | What it does |
|---|---|
| Initial Config | Per-step New PC checklist, including the classic shell (ExplorerPatcher, Open-Shell, 7+ Taskbar Tweaker, Windhawk) replayed from a capture of this PC |
| Installer | winget, a fixed package set, Firefox policy |
| Repeat rate | Keyboard repeat delay and rate, FilterKeys presets |
| Key diagnostics | Key repeat and chatter capture (low-level keyboard hook) |
| System | Registry and service tweak catalog |
| GPU | NVIDIA settings through `nvidia-smi` |
| Hardware | CPU-Z style CPU, caches, mainboard, memory, SPD, graphics, sensors, live clocks |
| Files, Registry, Orphan paths, Uninstall | Disk cleanup, registry cleanup, dead paths, uninstall entries |
| Startup | Run keys, Startup folders, boot and logon tasks, auto-start services |
| Environment | System and user variables, PATH lists one entry per row |
| Context Menu | Explorer right-click items with reversible per-item removal, ShellNew entries |
| Empty folders, Largest files | Disk scans |

## Run from source

Requires Windows 11, Python 3.13 (`C:\Python\313\python.exe`), PyQt5 5.15 and pywin32.

```powershell
C:\Python\313\python.exe -m pip install PyQt5 pywin32 pyinstaller
C:\Python\313\python.exe C:\path\to\wintools\wintools.py
```

`wintools.vbs` launches it without a console window. From source the winclassic kit is read from `resource\winclassic` beside `wintools.py`; a fresh clone lacks `resource\winclassic\installers` (not in git), so unzip the release kit over the clone.

## Build

```powershell
C:\Python\313\python.exe C:\path\to\wintools\build_exe.py
```

Produces `dist\wintools.exe` (PyInstaller onefile, icons embedded) and `dist\wintools-winclassic-kit.zip`, and links `dist\resource` to `resource` so the local exe finds the kit.

## Tests

Contract tests are plain scripts in `sandbox\`, one per function under test; each prints `STATUS: SUCCESS` or raises.

```powershell
C:\Python\313\python.exe C:\path\to\wintools\sandbox\test_build_exe.py
```

## Third-party

- `resource\pawnio\*.bin` and `resource\release_0_2_11.zip`: PawnIO modules, LGPL-2.1 (`resource\pawnio\COPYING`).
- The winclassic kit installers belong to their respective projects and are redistributed unmodified.
