# WinClassic research (2026-10-13)

Sources: read-only study of `C:\Dropbox\Common\cfg\pc\W11\winclassic` and a read-only audit of this PC.
Nothing was installed, imported or changed.

## This PC (the reference machine)

Windows 11 Pro 23H2, build 22631.4249, 100% scaling, 8 monitors.
Classic look is active: colors and metrics are the classic scheme "cplusruss" (ButtonFace 212 208 200,
Hilight 10 36 106, Tahoma fonts), and visual styles are off in-process. The registry still names
Aero.msstyles with ThemeActive 1; the classic rendering comes from Windhawk mods.

| Component | State here | Notes |
|---|---|---|
| ExplorerPatcher | 22631.5335.68.2 installed | Same SHA256 as `ep_setup.exe` in `Step7a(2)_Install_ExplorerPatcher_30-JUL-25_pwd=pwd.zip`. Service `ep_dwm_...` running. `C:\Windows\dxgi.dll` loader present. |
| EP settings | Match `Step7a(2)_ExplorerPatcher_22621.3880.66.6.reg` 80 of 81 | Only `SkinMenus` differs (live 0, kit 1). `Step7a_Install_ExplorerPatcher.reg` is superseded. |
| Open-Shell | 4.4.191-hlvioynt (patched), Start Menu component only | HKLM Run `-autorun`. Settings match `ClassicShellConfig.xml` 59 of 61 (`RecentProgKeys` Digits, `ShutdownCommand` CommandLogOff live). `Step8a...reg` only 9 of 12 (`TaskbarLook` Glass live, `SkinC1` absent). |
| Step9 StartMenuDLL | Copied to `C:\Windows` only | Not loaded; explorer and StartMenu.exe load the Program Files copy. The patched 4.4.191 installer makes Step9 unnecessary. |
| Windhawk | 1.6.1 (kit installer is 1.5.1) | Service and `\WindhawkRunUITask`. Six enabled local mods: `local@cplusruss-w11` (merged 14 classic mods, composition classic, explorerStyle classicNavigationBar, style vista), `local@cplusruss-w11-winlogon` (classic theme enable), `local@cplusruss-w11-shell` (classic toasts), `local@cplusruss-w11-applications` (visio, SLDWORKS), `local@cplusruss-w11-frameless` (webview apps), `local@allegro`. |
| 002b Windhawk zip | Not used | 0 of its 49 compiled mod DLLs exist here. |
| 7+ Taskbar Tweaker | 5.15.4 running (kit 5.15.2) | HKCU Run `-hidewnd` plus a common StartUp shortcut. Live differs from `Step15_TaskbarTweaker.reg`: `tray_icons_padding` 6 (kit 2), `1318069999` 2 (kit 3), `1318070012` 0 (kit 1). |
| Marlett | Per-user install, same hash as `Step_8b_marlett.ttf` | `HKCU\...\Fonts` "Marlett (TrueType)". |
| Step13 ribbon removal | Applied | `Virtualized_{D17F1E1A-...}_FileExplorerCommandUI` = 2. |
| Step12 3D borders | Not applied | `UserPreferencesMask` 90,12,01,80,10,00,00,00 live. |
| Themes.exe 1.5.6 | Copied to `C:\Windows`, not registered | |
| Winaero Tweaker 1.63 | Installed, used only for Disable Copilot | wintools already has a Copilot tweak. |
| OpenWith Enhanced 1.15 | Files present, shell extension not confirmed | |
| tm_cfg classic Task Manager | Effectively absent | Task Manager redirected to Process Hacker 2 via IFEO Debugger. |
| Wallpaper swap, Win10 imageres.dll.mun, CPL Restoration, Unused steps 3-6, Step24 | Absent | |

## Kit facts that matter for automation

- Doc (000_Instructions.docx) steps: 1 tm_cfg, 7 ExplorerPatcher + reg, 8 Open-Shell + reg, 9 StartMenuDLL (alternative to 8), 10 desk.cpl (manual, not in kit), 11 delete `HKLM\...\Themes\DefaultColors`, 12-15 optional. No steps 2-6 or 16-19.
- Doc preface: Defender exclusion `C:\Program Files\ExplorerPatcher` (manual PowerShell).
- Installer types: tm_cfg and Winaero are Inno Setup (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`); Windhawk, 7+TT and OpenWith are NSIS (`/S`). ExplorerPatcher and the patched Open-Shell installer types were not identified (Open-Shell registers an MSI product `{73FFADE2-3C58-457E-81A6-6B218B512F45}`).
- `Step7a_2_Install_ExplorerPatcher_26-NOV-25__NO.exe` is EP 26100.4946.69.6 (a 24H2 build); not what this PC runs.
- `Step7a_Install_ExplorerPatcher.zip` holds a zero-byte exe (broken).
- `Step6_ScheduledTask.reg` and `Step3-5_ScheduledTasks.txt` disagree on the task name.
- `000_OfficeKeyFix.exe` kills and restarts Explorer; other effects unknown.
