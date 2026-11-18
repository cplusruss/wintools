# 03 Installer

An "Installer" tab that installs a fixed set of apps through winget, plus a Firefox
customization (DuckDuckGo default, plain home page, uBlock Origin) applied as Firefox
enterprise policy.

## User decisions

- Packages: Dropbox, TightVNC Server (x64), Firefox, via winget (v1.29 present).
- TightVNC: server feature only, and the tab asks once for the VNC password (masked) and
  passes it to the installer.
- Firefox customization through enterprise policy under
  `HKLM\SOFTWARE\Policies\Mozilla\Firefox` (every profile, survives updates, reversible).
- uBlock Origin installed but removable (`normal_installed`).
- The Firefox customization appears both on the Installer tab (applied after Firefox
  installs) and as a reversible tweak in the System tab's Apps section with live state.
  Not part of Initial Config's New PC.

## Addition: Python (user request, mid-build)

- Fourth package: Python 3.13 (winget id `Python.Python.3.13`; confirm read-only), the
  version this machine standardises on.
- Installs to `C:\Python\<major><minor>` (here `C:\Python\313`), derived from the
  package's version so a later version bump moves the folder with it.
- Install and Scripts directories added to PATH. Use the python.org installer options
  (https://docs.python.org/3/using/windows.html, "Installing without UI"): all users,
  `TargetDir`, `PrependPath=1`, quiet, passed with winget `--override` (which replaces
  winget's own silent switches, so the quiet switch must be included). Verify each option
  name against that page and cite it in a code comment.
- Installed state/version from the uninstall entries like the others
  (DisplayName "Python 3.13.x (64-bit)").
- Tests: exact command line including the override, folder derived from the version,
  installed-state detection with a stubbed entry.

## Addition: Everything search, latest beta (user request, mid-build)

- Fifth package: voidtools Everything (the file search tool), the newest pre-release build
  winget carries. This machine has `voidtools.Everything.Alpha` installed. Find the right
  id read-only (`winget search voidtools --source winget --disable-interactivity`,
  `winget show --id <id> -e --source winget --disable-interactivity`, no --accept-* flags):
  use the id whose latest version is the newest pre-release (Alpha/Beta channel), not the
  1.4 stable `voidtools.Everything`. Cite what you found in a code comment.
- Default winget silent install (no override needed unless the installer requires one).
- Installed state/version from the uninstall entries like the others (match the
  Everything 1.5 entry; it must not match an unrelated "Everything" substring).
- Tests: command line, installed detection with a stubbed entry.

## Addition: WinGet prerequisite for Windows 11 LTSC (user request, mid-build)

LTSC has no Store / App Installer, so winget is absent. Method from the page the user gave
(https://blog.dmitriev.de/kb/20250112-winget/): download the WinGet release asset
`Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle` from
https://github.com/microsoft/winget-cli/releases and install it with `Add-AppxPackage`.
That page installs no dependencies; a clean LTSC usually lacks them, so also install the
dependency packages published in the same release (the `DesktopAppInstaller_Dependencies`
archive, x64 entries: VCLibs, UI.Xaml, WindowsAppRuntime) via
`Add-AppxPackage -Path <bundle> -DependencyPath <x64 dependency packages>`. Use the latest
stable release (GitHub API `releases/latest`), asset names matched by pattern, not pinned
version numbers. Verify asset names against the live release page read-only (WebFetch is
fine; do not download anything while developing).

- A "WinGet" row first in the Installer grid: Installed column shows the version from
  `winget --version`, or nothing when winget is missing; checked by default when missing.
  It runs before every package. If winget is missing and the row is unchecked, each package
  row fails with a genuine error ("winget not found").
- Run the install in PowerShell from the worker (the app is elevated), downloads into a
  scratch folder under %TEMP%, deleted afterwards; any failure (download, Add-AppxPackage)
  is that row's error and stops the package rows (they cannot run without winget).
- After installing, this process's PATH is stale: resolve winget as `shutil.which("winget")`
  then `%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe`; every package command uses the
  resolved path.
- Tests: the PowerShell script content (asset patterns, dependency path, Add-AppxPackage
  call) with subprocess patched; row order (WinGet first); packages fail cleanly when winget
  is missing and the row is unchecked; packages use the resolved winget path after a
  (mocked) install. Never run the script or download anything.

## Firefox customization (verify each against the official policy reference before coding:
https://mozilla.github.io/policy-templates/ and https://firefox-admin-docs.mozilla.org/reference/policies/)

- Default search engine DuckDuckGo: `SearchEngines\Default` = "DuckDuckGo". Confirm it works
  on regular release Firefox (not only ESR); if it is ESR-only, stop and report rather than
  writing a workaround.
- Home page (from the user's screenshot of Firefox Home settings): Search ON; everything
  else off: Weather, Shortcuts (TopSites), Sponsored shortcuts (SponsoredTopSites), Stories
  (Stories, and Pocket for older builds), Sponsored stories (SponsoredStories,
  SponsoredPocket), Recent activity (Highlights), Snippets, Firefox logo. Use `FirefoxHome`
  keys where they exist (with `Locked` = 0 so the user can still change them) and the
  `Preferences` policy for the rest (weather, logo); find the exact pref names in Firefox
  documentation/source and cite them in a code comment.
- uBlock Origin: `ExtensionSettings` entry `uBlock0@raymondhill.net` with
  `installation_mode` `normal_installed` and `install_url`
  `https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi`.
  `ExtensionSettings` is one JSON value: merge into existing JSON on apply and remove only
  this key on revert; never clobber other entries. Same care for any other single-value
  JSON policy (e.g. `Preferences` if it is one value).
- Registry forms (REG_DWORD / REG_SZ / REG_MULTI_SZ JSON) exactly as the policy reference
  gives them for Windows. The existing `DisableTelemetry` value (another tweak) must be
  left alone.
- New tweak in tweaks.py: key `firefoxsetup`, tab "Apps", section "Apps", label
  "Firefox Clean Setup"; registry ops via the existing D/S helpers where possible and a
  custom op (same duck type as `FilterKeysOp`: `on`, `off`, `off_key = None`, non-empty
  `path`, `available()`, `read()`, `is_on()`, `write(on)`) for merged JSON values. Build the
  ops from a function that takes the policy root key so tests can point it at a scratch key.

## Installer tab (installer.py, new)

- `PACKAGES`: (label, winget id, uninstall-entry match) for Dropbox, TightVNC Server (x64),
  Firefox. Confirm each winget id with read-only `winget show --id <id> -e --source winget
  --disable-interactivity` (do NOT pass --accept-* flags while developing; if winget insists
  on an agreement prompt, report it instead of accepting).
- Installed state and version come from the existing `clean.enumerate_uninstall_entries()`
  (no winget list parsing): match DisplayName, show DisplayVersion.
- TightVNC: silent MSI with only the server feature, registered as a service, VNC
  authentication on, password from the prompt; find the MSI property names in TightVNC's
  documentation (e.g. ADDLOCAL, SET_PASSWORD / VALUE_OF_PASSWORD, SET_USEVNCAUTHENTICATION /
  VALUE_OF_USEVNCAUTHENTICATION) and pass them with winget `--override`. The password never
  appears in the status line, the report, any log or exception text. Empty password or
  Cancel skips TightVNC only.
- Grid via `keydiag.style_grid` (user's default datagrid preferences): columns Package,
  Installed, Status. Rows: the three packages plus a "Firefox Clean Setup" row (state
  on/off from the tweak). Column 0 checkable; default: packages not yet installed checked,
  Firefox Clean Setup checked when off. Buttons: Install (applies the checked rows) and
  Refresh. Install command per package:
  `winget install --id <id> -e --source winget --silent --accept-package-agreements
  --accept-source-agreements --disable-interactivity` (+ `--override` for TightVNC).
  Runs sequentially in a QThread; Status column shows queued / installing / installed /
  failed 0x........ (winget exit code). Treat winget's "already installed" exit code as
  installed. The Firefox row runs after the Firefox package (if checked), as
  `tweak.apply(True)`. A step failure never stops the rest. Afterwards re-read states.
- No explainer text: labels, versions, states, error codes only.
- `wintools.py`: add as tab "Installer" right after "Initial Config", icon `tab_installer`;
  touch only the import, the tab list and the icons tuple; shut the worker down in
  `closeEvent` like the other pages if it runs.
- Icon: `tab_installer` in `resource\icons\make_tab_icons.py`, same Win7 style as its
  neighbours (256-unit drawing + hand-tuned 16 px frame): a software box with a glossy green
  down arrow. Regenerate with `C:\Python\313\python.exe resource\icons\make_tab_icons.py`.

## Tests (TDD: see each fail first)

NEVER run `winget install` / `uninstall` / `upgrade`, never pass `--accept-*` flags yourself,
never write the real `HKLM\SOFTWARE\Policies\Mozilla\Firefox` key, never launch Firefox.

- `sandbox\test_firefox_policy.py`: the `firefoxsetup` ops built on a scratch root under
  `HKCU\Software\wintools-selftest-firefox`: apply writes every value with the right type and
  data; an existing foreign `ExtensionSettings` entry and other policy values survive apply
  and revert; revert removes only ours; state reads True/False correctly; scratch deleted
  afterwards. Also assert the live tweak's ops target `HKLM\SOFTWARE\Policies\Mozilla\Firefox`.
- `sandbox\test_installer.py`: page offscreen with `subprocess` / the winget runner and the
  password prompt patched: command lines per package (exact flags; TightVNC `--override`
  contains the server-only and password properties), the password absent from every
  status/report string, Cancel/empty password skips TightVNC only, a failing package does
  not stop the next, already-installed exit code shows installed, the Firefox row runs
  after the Firefox package, installed state/version from a stubbed uninstall list.
- Update `sandbox\test_wintools_window.py` (tab count, shifted indices) and
  `sandbox\test_tab_icons.py` (icon list).

## Rules

- Python only via `C:\Python\313\python.exe`. No git. No new dependencies. Comments only for
  a non-obvious why.
- File ownership: new `installer.py`, `tweaks.py` (firefoxsetup only), `wintools.py` (import,
  tab list, icons tuple, closeEvent line), `resource\icons\make_tab_icons.py` +
  `tab_installer.ico`, the tests above. Another agent is editing `ctxmenu.py` and
  `sandbox\test_ctxmenu_*.py`: do not touch them.
- `ruff check` on changed files (match surrounding style; `ruff format --check` fails
  project-wide on old code), byte-compile, run every `sandbox\test_*.py` except
  `test_build_exe.py`; known pre-existing failure `test_registry_tree.py` (exit 1). Report
  files changed, verified winget ids and policy names with their sources, each test result,
  `STATUS: SUCCESS` or `STATUS: FAIL [reason]` with evidence.
