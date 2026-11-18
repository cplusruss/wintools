// ==WindhawkMod==
// @id              cplusruss-w11-applications
// @name            cplusruss W11 Applications
// @description     Per-application appearance tweaks for non-shell apps the x86-64 monolith doesn't reach. Visio (32-bit Office 2007): classic controls + an OS-version spoof so its command-bar toolbars render classic gray instead of Office blue. SolidWorks: forces menus to classic (non-themed) Win32 gray, leaving the rest of the app themed.
// @version         2.1.0
// @author          rlemburg
// @include         visio.exe
// @include         SLDWORKS.exe
// @architecture    x86
// @architecture    x86-64
// @compilerOptions -luxtheme -luser32
// ==/WindhawkMod==

// ==WindhawkModReadme==
/*
# cplusruss W11 Applications

A container mod for per-application tweaks, sibling to the `cplusruss-w11` shell
monolith. The monolith is `@architecture x86-64` only, so 32-bit apps (or apps
needing a bespoke tweak) never get touched by it. This mod fills those gaps.

To add an app: add an `// @include <exe>.exe`, add it to `AppId`/`DetectApp()`,
and add a `case` in `Wh_ModInit()`. Both `x86` and `x86-64` are declared so a
64-bit app needs only the include line.

## Visio (`visio.exe`)
Visio 2007 (`Office12\VISIO.EXE`) is a **32-bit** process, so the x86-64 monolith
never loads into it and it stays themed while the rest of the desktop is classic.
It gets two complementary features:

1. **Classic theme** -- disables visual styles within the process
   (`SetThemeAppProperties(0)` + uxtheme hooks below), so menus, dialogs and
   common controls render classic 3D gray. Also forces `SPI_GETFLATMENU`->FALSE
   for classic native menus/dialogs.
2. **OS-version spoof** -- the command-bar toolbar gradient is OS-version-gated;
   `mso.dll` paints Office blue on Vista+ and classic gray on older Windows. The
   built-in "Windows XP" compat mode does this on Win7 but not Win11 (its shim
   fakes `GetVersion[Ex]` but not `ntdll!RtlGetVersion`, which Office reads). We
   hook every version query so the lie is total. Target OS is the
   `visioSpoofVersion` setting; **Windows 2000** gives the grayest result.

## Known limitation (intentionally not solved)
Office 2007's command-bar **popup menus** (`MsoCommandBarPopup`) keep a light
(near-white) body. mso owner-draws them with hardcoded computed colors via
`ExtTextOut(ETO_OPAQUE)` -- they ignore theme, OS version, and `SPI_GETFLATMENU`.
A per-paint recolor (subclass the popup window, remap light backgrounds) was
attempted but gave inconsistent results, so it was removed. The toolbars,
toolbar dropdowns, menu bar, dialogs and controls are classic; only the popup
menu bodies stay light.

## SolidWorks (`SLDWORKS.exe`)
SolidWorks is 64-bit, so the x86-64 shell monolith *does* reach it -- but the
monolith deliberately runs almost nothing there (only its msg-box font fix)
because a whole-process classic theme makes the Save As dialog's dropdowns
flicker. This mod adds a narrower tweak instead: it hooks `OpenThemeData` /
`OpenThemeDataEx` / `OpenThemeDataForDpi` and returns `NULL` **only** for the
`"MENU"` theme class, plus forces `SPI_GETFLATMENU`->FALSE. Result: menus render
classic gray 3D while every other control (including the flicker-prone Save As
dropdowns) stays themed and untouched.

Caveat: this only declasses standard Win32 menus drawn by `user32`. Any menu
SolidWorks owner-draws itself won't change (same class of limitation as Office's
command-bar popups above). If some menus stay themed, broaden `WantsMenuClass`
from an exact `"MENU"` match to a case-insensitive substring.
*/
// ==/WindhawkModReadme==

// ==WindhawkModSettings==
/*
- visioSpoofVersion: win2000
  $name: Visio - spoofed Windows version
  $description: >-
    Office 2007 command-bar toolbars render per OS version. "Windows 2000" /
    "Windows XP" both give classic gray toolbars (instead of Office blue);
    "Don't spoof" reverts them to blue. Changing this needs a full Visio restart.
  $options:
  - win2000: Windows 2000 (5.0)
  - winxp: Windows XP SP3 (5.1)
  - none: Don't spoof (real OS)
*/
// ==/WindhawkModSettings==

#include <windows.h>
#include <uxtheme.h>

// ===========================================================================
// Which application are we in?  (chosen once per process in Wh_ModInit)
// ===========================================================================
enum AppId {
    APP_OTHER = 0,
    APP_VISIO,
    APP_SOLIDWORKS,
};

static AppId g_app = APP_OTHER;

static AppId DetectApp(void) {
    WCHAR path[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) {
        return APP_OTHER;
    }
    PCWSTR exe = wcsrchr(path, L'\\');
    exe = exe ? exe + 1 : path;

    if (_wcsicmp(exe, L"visio.exe") == 0)    return APP_VISIO;
    if (_wcsicmp(exe, L"sldworks.exe") == 0) return APP_SOLIDWORKS;
    return APP_OTHER;
}

// Hook a named export of a module if it exists; skip (and log) if absent.
static void HookExport(HMODULE hMod, const char* name, void* hook, void** orig) {
    if (!hMod) {
        Wh_Log(L"module missing for export %S -- skipping", name);
        return;
    }
    void* addr = (void*)GetProcAddress(hMod, name);
    if (!addr) {
        Wh_Log(L"export %S not found -- skipping", name);
        return;
    }
    if (!Wh_SetFunctionHook(addr, hook, orig)) {
        Wh_Log(L"Failed to hook export %S", name);
    }
}

// ===========================================================================
// Feature: Classic theme -- disable visual styles within this process.
// ===========================================================================
typedef BOOL   (WINAPI* IsThemeActive_t)(void);
typedef BOOL   (WINAPI* IsAppThemed_t)(void);
typedef HTHEME (WINAPI* OpenThemeData_t)(HWND, LPCWSTR);
typedef HTHEME (WINAPI* OpenThemeDataEx_t)(HWND, LPCWSTR, DWORD);
typedef HTHEME (WINAPI* OpenThemeDataForDpi_t)(HWND, LPCWSTR, UINT);
typedef HTHEME (WINAPI* GetWindowTheme_t)(HWND);
typedef HRESULT(WINAPI* GetCurrentThemeName_t)(LPWSTR, int, LPWSTR, int, LPWSTR, int);
typedef BOOL   (WINAPI* SystemParametersInfoW_t)(UINT, UINT, PVOID, UINT);
typedef BOOL   (WINAPI* SystemParametersInfoA_t)(UINT, UINT, PVOID, UINT);

static IsThemeActive_t         pIsThemeActive_orig;
static IsAppThemed_t           pIsAppThemed_orig;
static OpenThemeData_t         pOpenThemeData_orig;
static OpenThemeDataEx_t       pOpenThemeDataEx_orig;
static OpenThemeDataForDpi_t   pOpenThemeDataForDpi_orig;
static GetWindowTheme_t        pGetWindowTheme_orig;
static GetCurrentThemeName_t   pGetCurrentThemeName_orig;
static SystemParametersInfoW_t pSystemParametersInfoW_orig;
static SystemParametersInfoA_t pSystemParametersInfoA_orig;

static bool g_classicTheme = false;   // Visio: declass the whole process
static bool g_classicMenus = false;   // SolidWorks: declass only the "MENU" theme class

// True when this uxtheme class list names the Win32 menu class. Guards against
// atom/ordinal "pointers" (high word zero) before deref, mirroring the shell mod.
static bool WantsMenuClass(LPCWSTR cls) {
    if (!cls || !(*((WORD*)&cls + 1))) return false;
    return _wcsicmp(cls, L"MENU") == 0;
}

static BOOL   WINAPI IsThemeActive_hook(void)                      { return FALSE; }
static BOOL   WINAPI IsAppThemed_hook(void)                        { return FALSE; }

// Menus-only mode (SolidWorks): declass JUST the menu class, leave the rest
// themed. Full mode (Visio): declass everything by returning NULL outright.
static HTHEME WINAPI OpenThemeData_hook(HWND h, LPCWSTR cls) {
    if (g_classicMenus && !WantsMenuClass(cls)) return pOpenThemeData_orig(h, cls);
    return NULL;
}
static HTHEME WINAPI OpenThemeDataEx_hook(HWND h, LPCWSTR cls, DWORD f) {
    if (g_classicMenus && !WantsMenuClass(cls)) return pOpenThemeDataEx_orig(h, cls, f);
    return NULL;
}
static HTHEME WINAPI OpenThemeDataForDpi_hook(HWND h, LPCWSTR cls, UINT dpi) {
    if (g_classicMenus && !WantsMenuClass(cls)) return pOpenThemeDataForDpi_orig(h, cls, dpi);
    return NULL;
}
static HTHEME WINAPI GetWindowTheme_hook(HWND)                     { return NULL; }

// Office probes the active theme by name; report "no current theme".
static HRESULT WINAPI GetCurrentThemeName_hook(LPWSTR f, int cf, LPWSTR c, int cc,
                                               LPWSTR s, int cs) {
    if (f && cf > 0) f[0] = L'\0';
    if (c && cc > 0) c[0] = L'\0';
    if (s && cs > 0) s[0] = L'\0';
    return E_FAIL;
}

// Force classic (non-flat) native menus/dialogs in this process.
static BOOL WINAPI SystemParametersInfoW_hook(UINT a, UINT p, PVOID v, UINT f) {
    if (a == SPI_GETFLATMENU && v) { *(BOOL*)v = FALSE; return TRUE; }
    return pSystemParametersInfoW_orig(a, p, v, f);
}
static BOOL WINAPI SystemParametersInfoA_hook(UINT a, UINT p, PVOID v, UINT f) {
    if (a == SPI_GETFLATMENU && v) { *(BOOL*)v = FALSE; return TRUE; }
    return pSystemParametersInfoA_orig(a, p, v, f);
}

static void ClassicTheme_Install(void) {
    SetThemeAppProperties(0);

    HMODULE hUx = GetModuleHandleW(L"uxtheme.dll");
    if (!hUx) hUx = LoadLibraryW(L"uxtheme.dll");
    if (hUx) {
        HookExport(hUx, "IsThemeActive",       (void*)IsThemeActive_hook,       (void**)&pIsThemeActive_orig);
        HookExport(hUx, "IsAppThemed",         (void*)IsAppThemed_hook,         (void**)&pIsAppThemed_orig);
        HookExport(hUx, "OpenThemeData",       (void*)OpenThemeData_hook,       (void**)&pOpenThemeData_orig);
        HookExport(hUx, "OpenThemeDataEx",     (void*)OpenThemeDataEx_hook,     (void**)&pOpenThemeDataEx_orig);
        HookExport(hUx, "OpenThemeDataForDpi", (void*)OpenThemeDataForDpi_hook, (void**)&pOpenThemeDataForDpi_orig);
        HookExport(hUx, "GetWindowTheme",      (void*)GetWindowTheme_hook,      (void**)&pGetWindowTheme_orig);
        HookExport(hUx, "GetCurrentThemeName", (void*)GetCurrentThemeName_hook, (void**)&pGetCurrentThemeName_orig);
    } else {
        Wh_Log(L"uxtheme.dll unavailable -- only SetThemeAppProperties applied");
    }

    HMODULE hUser = GetModuleHandleW(L"user32.dll");
    HookExport(hUser, "SystemParametersInfoW", (void*)SystemParametersInfoW_hook, (void**)&pSystemParametersInfoW_orig);
    HookExport(hUser, "SystemParametersInfoA", (void*)SystemParametersInfoA_hook, (void**)&pSystemParametersInfoA_orig);

    g_classicTheme = true;
}

// Repaint already-built windows of THIS process (live enable/disable).
static BOOL CALLBACK RepaintChildProc(HWND hChild, LPARAM) {
    SendMessageW(hChild, WM_THEMECHANGED, 0, 0);
    InvalidateRect(hChild, NULL, TRUE);
    return TRUE;
}
static BOOL CALLBACK RepaintTopProc(HWND hWnd, LPARAM) {
    DWORD pid = 0;
    GetWindowThreadProcessId(hWnd, &pid);
    if (pid == GetCurrentProcessId()) {
        SendMessageW(hWnd, WM_THEMECHANGED, 0, 0);
        EnumChildWindows(hWnd, RepaintChildProc, 0);
        InvalidateRect(hWnd, NULL, TRUE);
    }
    return TRUE;
}
static void ClassicTheme_Refresh(void) { EnumWindows(RepaintTopProc, 0); }
static void ClassicTheme_Restore(void) {
    SetThemeAppProperties(STAP_ALLOW_NONCLIENT | STAP_ALLOW_CONTROLS |
                          STAP_ALLOW_WEBCONTENT);
    EnumWindows(RepaintTopProc, 0);
}

// ===========================================================================
// Feature: Classic menus only -- declass the Win32 "MENU" theme class so menus
//   render classic gray 3D while every other control stays themed. Narrower
//   than ClassicTheme_Install on purpose: SolidWorks' Save As dropdowns flicker
//   under a whole-process declass, so we touch only the menu class.
// ===========================================================================
static void ClassicMenus_Install(void) {
    HMODULE hUx = GetModuleHandleW(L"uxtheme.dll");
    if (!hUx) hUx = LoadLibraryW(L"uxtheme.dll");
    if (hUx) {
        HookExport(hUx, "OpenThemeData",       (void*)OpenThemeData_hook,       (void**)&pOpenThemeData_orig);
        HookExport(hUx, "OpenThemeDataEx",     (void*)OpenThemeDataEx_hook,     (void**)&pOpenThemeDataEx_orig);
        HookExport(hUx, "OpenThemeDataForDpi", (void*)OpenThemeDataForDpi_hook, (void**)&pOpenThemeDataForDpi_orig);
    } else {
        Wh_Log(L"uxtheme.dll unavailable -- classic menus not installed");
    }

    // Classic raised (non-flat) native menus to match the declassed gray body.
    HMODULE hUser = GetModuleHandleW(L"user32.dll");
    HookExport(hUser, "SystemParametersInfoW", (void*)SystemParametersInfoW_hook, (void**)&pSystemParametersInfoW_orig);
    HookExport(hUser, "SystemParametersInfoA", (void*)SystemParametersInfoA_hook, (void**)&pSystemParametersInfoA_orig);

    g_classicMenus = true;
}

// ===========================================================================
// Feature: Version spoof -> report an older Windows to mso.dll
//   mso.dll's command-bar renderer branches on the OS version: Vista+ -> blue
//   Office toolbars; XP/2000 -> classic gray. We hook EVERY version query
//   (incl. ntdll!RtlGetVersion, which the OS compat shim leaves alone on Win11)
//   so the lie is total. Target OS comes from the visioSpoofVersion setting.
// ===========================================================================
typedef DWORD (WINAPI* GetVersion_t)(void);
typedef BOOL  (WINAPI* GetVersionExA_t)(LPOSVERSIONINFOA);
typedef BOOL  (WINAPI* GetVersionExW_t)(LPOSVERSIONINFOW);
typedef LONG  (NTAPI*  RtlGetVersion_t)(LPOSVERSIONINFOW);   // RTL_OSVERSIONINFOW layout == OSVERSIONINFOW
typedef void  (NTAPI*  RtlGetNtVersionNumbers_t)(DWORD*, DWORD*, DWORD*);

static GetVersion_t              pGetVersion_orig;
static GetVersionExA_t           pGetVersionExA_orig;
static GetVersionExW_t           pGetVersionExW_orig;
static RtlGetVersion_t           pRtlGetVersion_orig;
static RtlGetNtVersionNumbers_t  pRtlGetNtVersionNumbers_orig;

// Spoofed OS values (default Windows 2000 SP4). Set in VersionSpoof_Install.
static DWORD        g_spoofMajor = 5;
static DWORD        g_spoofMinor = 0;
static DWORD        g_spoofBuild = 2195;
static WORD         g_spoofSp    = 4;
static const WCHAR* g_spoofCsdW  = L"Service Pack 4";
static const CHAR*  g_spoofCsdA  =  "Service Pack 4";

static DWORD WINAPI GetVersion_hook(void) {
    return (DWORD)((g_spoofBuild << 16) | (g_spoofMinor << 8) | g_spoofMajor);
}

static void PatchCommonW(LPOSVERSIONINFOW p) {
    p->dwMajorVersion = g_spoofMajor;
    p->dwMinorVersion = g_spoofMinor;
    p->dwBuildNumber  = g_spoofBuild;
    p->dwPlatformId   = VER_PLATFORM_WIN32_NT;
    lstrcpynW(p->szCSDVersion, g_spoofCsdW, ARRAYSIZE(p->szCSDVersion));
    if (p->dwOSVersionInfoSize >= sizeof(OSVERSIONINFOEXW)) {
        LPOSVERSIONINFOEXW e = (LPOSVERSIONINFOEXW)p;
        e->wServicePackMajor = g_spoofSp;
        e->wServicePackMinor = 0;
        e->wProductType      = VER_NT_WORKSTATION;
    }
}

static BOOL WINAPI GetVersionExW_hook(LPOSVERSIONINFOW p) {
    BOOL r = pGetVersionExW_orig(p);
    if (r && p) PatchCommonW(p);
    return r;
}
static BOOL WINAPI GetVersionExA_hook(LPOSVERSIONINFOA p) {
    BOOL r = pGetVersionExA_orig(p);
    if (r && p) {
        p->dwMajorVersion = g_spoofMajor;
        p->dwMinorVersion = g_spoofMinor;
        p->dwBuildNumber  = g_spoofBuild;
        p->dwPlatformId   = VER_PLATFORM_WIN32_NT;
        lstrcpynA(p->szCSDVersion, g_spoofCsdA, ARRAYSIZE(p->szCSDVersion));
        if (p->dwOSVersionInfoSize >= sizeof(OSVERSIONINFOEXA)) {
            LPOSVERSIONINFOEXA e = (LPOSVERSIONINFOEXA)p;
            e->wServicePackMajor = g_spoofSp;
            e->wServicePackMinor = 0;
            e->wProductType      = VER_NT_WORKSTATION;
        }
    }
    return r;
}
static LONG NTAPI RtlGetVersion_hook(LPOSVERSIONINFOW p) {
    LONG r = pRtlGetVersion_orig(p);
    if (p) PatchCommonW(p);
    return r;
}
static void NTAPI RtlGetNtVersionNumbers_hook(DWORD* major, DWORD* minor, DWORD* build) {
    if (pRtlGetNtVersionNumbers_orig) pRtlGetNtVersionNumbers_orig(major, minor, build);
    if (major) *major = g_spoofMajor;
    if (minor) *minor = g_spoofMinor;
    if (build) *build = 0xF0000000 | g_spoofBuild;
}

// Returns false if the user disabled the spoof.
static bool LoadSpoofSettings(void) {
    PCWSTR v = Wh_GetStringSetting(L"visioSpoofVersion");
    bool enabled = true;
    if (wcscmp(v, L"none") == 0) {
        enabled = false;
    } else if (wcscmp(v, L"winxp") == 0) {
        g_spoofMajor = 5; g_spoofMinor = 1; g_spoofBuild = 2600; g_spoofSp = 3;
        g_spoofCsdW = L"Service Pack 3"; g_spoofCsdA = "Service Pack 3";
    } else {  // "win2000" (default)
        g_spoofMajor = 5; g_spoofMinor = 0; g_spoofBuild = 2195; g_spoofSp = 4;
        g_spoofCsdW = L"Service Pack 4"; g_spoofCsdA = "Service Pack 4";
    }
    Wh_FreeStringSetting(v);
    return enabled;
}

static void VersionSpoof_Install(void) {
    if (!LoadSpoofSettings()) {
        Wh_Log(L"version spoof disabled by setting");
        return;
    }
    HMODULE hK32   = GetModuleHandleW(L"kernel32.dll");
    HMODULE hNtdll = GetModuleHandleW(L"ntdll.dll");
    HookExport(hK32,   "GetVersion",             (void*)GetVersion_hook,             (void**)&pGetVersion_orig);
    HookExport(hK32,   "GetVersionExA",          (void*)GetVersionExA_hook,          (void**)&pGetVersionExA_orig);
    HookExport(hK32,   "GetVersionExW",          (void*)GetVersionExW_hook,          (void**)&pGetVersionExW_orig);
    HookExport(hNtdll, "RtlGetVersion",          (void*)RtlGetVersion_hook,          (void**)&pRtlGetVersion_orig);
    HookExport(hNtdll, "RtlGetNtVersionNumbers", (void*)RtlGetNtVersionNumbers_hook, (void**)&pRtlGetNtVersionNumbers_orig);
}

// ===========================================================================
// Windhawk lifecycle -- per-app dispatch
// ===========================================================================
BOOL Wh_ModInit(void) {
    g_app = DetectApp();

    switch (g_app) {
        case APP_VISIO:
            // Install the version lie before anything queries it.
            VersionSpoof_Install();  // older OS -> classic gray command-bar toolbars
            ClassicTheme_Install();  // disable visual styles -> classic controls/menu bar
            break;
        case APP_SOLIDWORKS:
            ClassicMenus_Install();  // declass only the "MENU" class -> classic gray menus
            break;
        default:
            Wh_Log(L"cplusruss-w11-applications: no tweaks registered for this process");
            break;
    }
    return TRUE;
}

void Wh_ModAfterInit(void) {
    if (g_classicTheme || g_classicMenus) ClassicTheme_Refresh();
}

void Wh_ModUninit(void) {
    if (g_classicTheme)      ClassicTheme_Restore();
    else if (g_classicMenus) ClassicTheme_Refresh();  // drop cached menu themes -> re-theme
}
