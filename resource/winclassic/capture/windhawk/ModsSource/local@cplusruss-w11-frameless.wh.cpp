// ==WindhawkMod==
// @id              cplusruss-w11-frameless
// @name            Frameless Webview Apps
// @description     Event-triggered (no timers): hooks the app's own CreateWindowExW/SetWindowPos/ShowWindow so that after a webview app frames or shows a top-level window it forces DWM to render the frame with no border color, and for custom-chrome apps with a residual frame subclasses WM_NCCALCSIZE->0 to collapse it. Verbose [fl] logging to trace fresh launches.
// @version         0.26.0
// @author          rlemburg
// @include         code.exe
// @include         vscodium.exe
// @include         jan.exe
// @include         anythingllm.exe
// @include         claude.exe
// @include         chatgpt.exe
// @include         cursor.exe
// @include         discord.exe
// @include         slack.exe
// @include         obsidian.exe
// @include         signal.exe
// @include         notion.exe
// @include         spotify.exe
// @include         whatsapp.exe
// @include         ms-teams.exe
// @include         figma.exe
// @include         element.exe
// @include         Logic.exe
// @include         draw.io.exe
// @architecture    x86-64
// @compilerOptions -ldwmapi -luser32 -lcomctl32
// ==/WindhawkMod==

// ==WindhawkModReadme==
/*
# Frameless Webview Apps (instrumented)

Verbose logging build to see exactly what happens on a fresh launch. Enable Logging
on the mod and look for [fl] lines: ModInit (which process), every top-level window
created (class), each Apply (target?/subclassed?/hasFrame?), and the SetWindowPos/
ShowWindow triggers hitting a target window.
*/
// ==/WindhawkModReadme==

#include <windhawk_api.h>
#include <windhawk_utils.h>
#include <windows.h>
#include <windowsx.h>
#include <dwmapi.h>
#include <commctrl.h>
#include <set>

static std::set<HWND> g_subclassed;

static PCWSTR CurrentExeName() {
    static WCHAR name[MAX_PATH] = L"";
    if (!name[0]) {
        WCHAR path[MAX_PATH];
        if (GetModuleFileNameW(NULL, path, MAX_PATH)) {
            PCWSTR slash = wcsrchr(path, L'\\');
            wcscpy_s(name, MAX_PATH, slash ? slash + 1 : path);
        }
    }
    return name;
}

static bool IsSubclassApp() {
    PCWSTR e = CurrentExeName();
    return 0 == _wcsicmp(e, L"code.exe") ||
           0 == _wcsicmp(e, L"vscodium.exe") ||
           0 == _wcsicmp(e, L"jan.exe") ||
           0 == _wcsicmp(e, L"Logic.exe");
}

// Some webview apps draw their own titlebar but mark NO -webkit-app-region: drag, so
// Chromium returns HTCLIENT across the whole top and the collapsed-frame window can't
// be moved. For these, synthesize a caption: a top band reads as HTCAPTION, minus a
// left strip (the menu bar) and a right strip (the app's own window buttons) so those
// still take clicks. Tune the three constants to the app's titlebar layout.
static bool IsCaptionSynthApp() {
    return 0 == _wcsicmp(CurrentExeName(), L"Logic.exe");
}
static const int SYNTH_CAPTION_H = 30;   // px from the top treated as the titlebar
static const int SYNTH_MENU_W    = 250;  // left strip reserved for the menu bar
static const int SYNTH_BTN_W     = 140;  // right strip reserved for window buttons

static bool IsTargetClass(LPCWSTR cls) {
    if (!cls) return false;
    return 0 == wcscmp(cls, L"Chrome_WidgetWin_1") ||
           0 == wcscmp(cls, L"Chrome_WidgetWin_0") ||
           0 == wcscmp(cls, L"Tauri Window");
}

static bool IsTargetWindow(HWND hWnd) {
    WCHAR cls[64] = L"";
    if (GetClassNameW(hWnd, cls, ARRAYSIZE(cls)) <= 0 || !IsTargetClass(cls)) return false;
    if (GetWindow(hWnd, GW_OWNER)) return false;
    LONG s = GetWindowLongW(hWnd, GWL_STYLE);
    if (s & WS_CHILD) return false;
    return (s & (WS_THICKFRAME | WS_CAPTION)) != 0;
}

static bool HasFrame(HWND hWnd) {
    RECT wr, cr;
    if (!GetWindowRect(hWnd, &wr) || !GetClientRect(hWnd, &cr)) return false;
    return (wr.right - wr.left) > cr.right || (wr.bottom - wr.top) > cr.bottom;
}

// The maximized window rect is inflated by win32k for EACH frame style so the frame tucks
// off-screen: WS_THICKFRAME adds the ~4px sizing border, WS_CAPTION (= WS_BORDER|WS_DLGFRAME)
// adds the ~3px fixed border. With WM_NCCALCSIZE=0 that whole overhang is visible client
// bleeding onto the neighbor monitors. Strip both before a maximize so it sizes to the exact
// work area; re-add on restore so edges resize and the caption behaves. WS_CAPTION goes too,
// so IsTargetWindow won't match while maximized -- fine: the subclass is tracked by HWND and
// the SC_RESTORE / WM_WINDOWPOSCHANGED paths (which run regardless) put the styles back.
static const LONG FRAME_STYLES = WS_THICKFRAME | WS_CAPTION;
static void SetFrameStyles(HWND hWnd, bool on) {
    LONG s = GetWindowLongW(hWnd, GWL_STYLE);
    LONG ns = on ? (s | FRAME_STYLES) : (s & ~FRAME_STYLES);
    if (ns != s) {
        SetWindowLongW(hWnd, GWL_STYLE, ns);
        Wh_Log(L"[fl] SetFrameStyles hwnd=%p on=%d style=0x%08X", hWnd, (int)on, (unsigned)ns);
    }
}

LRESULT CALLBACK SubProc(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam, DWORD_PTR) {
    if (uMsg == WM_NCCALCSIZE) {
        if (wParam && IsZoomed(hWnd)) Wh_Log(L"[fl] NCCALC maximized hwnd=%p ->0 (subclass wins)", hWnd);
        return 0;
    }
    if (uMsg == WM_GETMINMAXINFO) {
        // Frame is collapsed (WM_NCCALCSIZE=0), but Windows still sizes a maximized
        // WS_THICKFRAME window to work-area + frame, so it overhangs onto the
        // neighbor monitors. Clamp the maximized rect to this monitor's work area.
        LRESULT r = DefSubclassProc(hWnd, uMsg, wParam, lParam);
        HMONITOR mon = MonitorFromWindow(hWnd, MONITOR_DEFAULTTONEAREST);
        MONITORINFO mi = { sizeof(mi) };
        if (mon && GetMonitorInfoW(mon, &mi)) {
            MINMAXINFO* mmi = (MINMAXINFO*)lParam;
            mmi->ptMaxPosition.x = mi.rcWork.left - mi.rcMonitor.left;
            mmi->ptMaxPosition.y = mi.rcWork.top  - mi.rcMonitor.top;
            mmi->ptMaxSize.x     = mi.rcWork.right  - mi.rcWork.left;
            mmi->ptMaxSize.y     = mi.rcWork.bottom - mi.rcWork.top;
            if (mmi->ptMaxTrackSize.x < mmi->ptMaxSize.x) mmi->ptMaxTrackSize.x = mmi->ptMaxSize.x;
            if (mmi->ptMaxTrackSize.y < mmi->ptMaxSize.y) mmi->ptMaxTrackSize.y = mmi->ptMaxSize.y;
            Wh_Log(L"[fl] GETMINMAXINFO hwnd=%p set maxPos=%d,%d maxSize=%dx%d", hWnd,
                   mmi->ptMaxPosition.x, mmi->ptMaxPosition.y, mmi->ptMaxSize.x, mmi->ptMaxSize.y);
        }
        return r;
    }
    if (uMsg == WM_SYSCOMMAND) {
        // Drop WS_THICKFRAME just before a maximize (snap / Win+Up / titlebar dbl-click)
        // so win32k sizes the maximized window to the exact work area -- no classic-frame
        // inflation onto the neighbor monitors. Re-add it on restore so edges resize.
        UINT sc = (UINT)(wParam & 0xFFF0);
        if (sc == SC_MAXIMIZE) SetFrameStyles(hWnd, false);
        else if (sc == SC_RESTORE) SetFrameStyles(hWnd, true);
        return DefSubclassProc(hWnd, uMsg, wParam, lParam);
    }
    if (uMsg == WM_WINDOWPOSCHANGED) {
        // Safety net for restores that skip WM_SYSCOMMAND/ShowWindow (SetWindowPlacement):
        // once un-maximized, put the frame styles back so the window stays resizable and
        // keeps its caption. Read live by DefWindowProc and our NCHITTEST grips -> no
        // SWP_FRAMECHANGED needed.
        LONG s = GetWindowLongW(hWnd, GWL_STYLE);
        if (!IsZoomed(hWnd) && (s & FRAME_STYLES) != FRAME_STYLES)
            SetWindowLongW(hWnd, GWL_STYLE, s | FRAME_STYLES);
        return DefSubclassProc(hWnd, uMsg, wParam, lParam);
    }
    if (uMsg == WM_NCHITTEST) {
        // WM_NCCALCSIZE=0 collapses the non-client area, so DefWindowProc no longer
        // reports the resize-border codes -> edges read HTCLIENT and can't be grabbed.
        // Re-add resize grips: an edge strip that the app calls HTCLIENT becomes HT*.
        // App-drawn titlebar (HTCAPTION) and buttons are left untouched.
        LRESULT hit = DefSubclassProc(hWnd, uMsg, wParam, lParam);
        if (hit == HTCLIENT && !IsZoomed(hWnd) &&
            (GetWindowLongW(hWnd, GWL_STYLE) & WS_THICKFRAME)) {
            RECT wr;
            GetWindowRect(hWnd, &wr);
            int x = GET_X_LPARAM(lParam), y = GET_Y_LPARAM(lParam);
            int b = GetSystemMetrics(SM_CXSIZEFRAME) + GetSystemMetrics(SM_CXPADDEDBORDER);
            if (b < 8) b = 8;  // classic frame is thin; floor keeps the strip grabbable
            bool L = x < wr.left + b,    R = x >= wr.right - b;
            bool T = y < wr.top + b,     B = y >= wr.bottom - b;
            if (T && L) return HTTOPLEFT;
            if (T && R) return HTTOPRIGHT;
            if (B && L) return HTBOTTOMLEFT;
            if (B && R) return HTBOTTOMRIGHT;
            if (L) return HTLEFT;
            if (R) return HTRIGHT;
            if (T) return HTTOP;
            if (B) return HTBOTTOM;
        }
        // Synthesize a draggable caption for apps whose custom titlebar exposes no
        // drag region. Top band -> HTCAPTION, but leave the menu strip (left) and the
        // app's own window buttons (right) as HTCLIENT so they keep taking clicks.
        if (hit == HTCLIENT && IsCaptionSynthApp()) {
            RECT wr; GetWindowRect(hWnd, &wr);
            int relx = GET_X_LPARAM(lParam) - wr.left;
            int rely = GET_Y_LPARAM(lParam) - wr.top;
            int w = wr.right - wr.left;
            if (rely >= 0 && rely < SYNTH_CAPTION_H) {
                static int n = 0;
                if (n < 40) { Wh_Log(L"[fl] synth top-hit relx=%d rely=%d w=%d", relx, rely, w); n++; }
                if (relx >= SYNTH_MENU_W && relx < w - SYNTH_BTN_W) return HTCAPTION;
            }
        }
        return hit;
    }
    return DefSubclassProc(hWnd, uMsg, wParam, lParam);
}

using SetWindowPos_t = decltype(&SetWindowPos);
SetWindowPos_t SetWindowPos_orig;

static void Apply(HWND hWnd, PCWSTR from) {
    if (!IsTargetWindow(hWnd)) return;
    if (IsZoomed(hWnd))
        Wh_Log(L"[fl] Apply(%s) zoomed hwnd=%p hasFrame=%d subclassed=%d", from, hWnd,
               (int)HasFrame(hWnd), (int)(g_subclassed.count(hWnd) != 0));
    int ncr = DWMNCRP_ENABLED;
    DwmSetWindowAttribute(hWnd, DWMWA_NCRENDERING_POLICY, &ncr, sizeof(ncr));
    COLORREF none = DWMWA_COLOR_NONE;
    DwmSetWindowAttribute(hWnd, DWMWA_BORDER_COLOR, &none, sizeof(none));
    if (!IsSubclassApp()) return;
    if (HasFrame(hWnd)) {
        // Frame present -> the app re-took its window and our WM_NCCALCSIZE=0 subclass
        // is no longer on top (Jan re-subclasses mid-startup). Re-assert: drop ours,
        // re-add ON TOP of the app's, then recalc so ours wins.
        WindhawkUtils::RemoveWindowSubclassFromAnyThread(hWnd, SubProc);
        if (WindhawkUtils::SetWindowSubclassFromAnyThread(hWnd, SubProc, 0)) g_subclassed.insert(hWnd);
        SetWindowPos_orig(hWnd, NULL, 0, 0, 0, 0,
                          SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
        Wh_Log(L"[fl] re-asserted(%s) hwnd=%p", from, hWnd);
    } else if (g_subclassed.find(hWnd) == g_subclassed.end()) {
        if (WindhawkUtils::SetWindowSubclassFromAnyThread(hWnd, SubProc, 0)) g_subclassed.insert(hWnd);
    }
    // If it's already maximized-and-overhanging when we (re)attach -- e.g. right after a
    // live recompile with the window left maximized -- drop WS_THICKFRAME and pull it onto
    // the work area directly, so it isn't re-inflated. No user restore/re-maximize needed.
    if (IsZoomed(hWnd)) {
        HMONITOR mon = MonitorFromWindow(hWnd, MONITOR_DEFAULTTONEAREST);
        MONITORINFO mi = { sizeof(mi) };
        RECT wr;
        if (mon && GetMonitorInfoW(mon, &mi) && GetWindowRect(hWnd, &wr)) {
            RECT w = mi.rcWork;
            if (wr.left < w.left || wr.top < w.top || wr.right > w.right || wr.bottom > w.bottom) {
                Wh_Log(L"[fl] reapply-maximized hwnd=%p win(%d,%d %dx%d)->work(%d,%d %dx%d)", hWnd,
                       wr.left, wr.top, wr.right - wr.left, wr.bottom - wr.top,
                       w.left, w.top, w.right - w.left, w.bottom - w.top);
                SetFrameStyles(hWnd, false);
                SetWindowPos_orig(hWnd, NULL, w.left, w.top, w.right - w.left, w.bottom - w.top,
                                  SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
            }
        }
    }
}

BOOL WINAPI SetWindowPos_hook(HWND hWnd, HWND after, int x, int y, int cx, int cy, UINT flags) {
    BOOL r = SetWindowPos_orig(hWnd, after, x, y, cx, cy, flags);
    if (hWnd && IsTargetWindow(hWnd)) Apply(hWnd, L"SetWindowPos");
    return r;
}

using ShowWindow_t = decltype(&ShowWindow);
ShowWindow_t ShowWindow_orig;
BOOL WINAPI ShowWindow_hook(HWND hWnd, int nCmdShow) {
    // Chromium's own maximize/restore is ShowWindow(SW_MAXIMIZE / SW_RESTORE). Toggle
    // WS_THICKFRAME BEFORE the call so the maximize computes a work-area-exact rect.
    if (hWnd && IsTargetWindow(hWnd)) {
        if (nCmdShow == SW_MAXIMIZE || nCmdShow == SW_SHOWMAXIMIZED) SetFrameStyles(hWnd, false);
        else if (nCmdShow == SW_RESTORE || nCmdShow == SW_SHOWNORMAL) SetFrameStyles(hWnd, true);
    }
    BOOL r = ShowWindow_orig(hWnd, nCmdShow);
    if (hWnd && IsTargetWindow(hWnd)) Apply(hWnd, L"ShowWindow");
    return r;
}

using CreateWindowExW_t = decltype(&CreateWindowExW);
CreateWindowExW_t CreateWindowExW_orig;
HWND WINAPI CreateWindowExW_hook(DWORD ex, LPCWSTR cn, LPCWSTR wn, DWORD st, int x, int y,
                                 int w, int h, HWND par, HMENU mn, HINSTANCE in, LPVOID pm) {
    HWND hWnd = CreateWindowExW_orig(ex, cn, wn, st, x, y, w, h, par, mn, in, pm);
    if (hWnd && !par) {
        WCHAR cls[64] = L""; GetClassNameW(hWnd, cls, ARRAYSIZE(cls));
        Wh_Log(L"[fl] CreateWin class='%s' hwnd=%p", cls, hWnd);
        Apply(hWnd, L"CreateWin");
    }
    return hWnd;
}

static bool IsFrameMetric(int i) {
    return i == SM_CXFRAME || i == SM_CYFRAME || i == SM_CXPADDEDBORDER;
}

using GetSystemMetrics_t = decltype(&GetSystemMetrics);
GetSystemMetrics_t GetSystemMetrics_orig;
int WINAPI GetSystemMetrics_hook(int nIndex) {
    // These apps run with WM_NCCALCSIZE=0 -> no non-client frame. But Chromium still
    // offsets its MAXIMIZED window by GetSystemMetrics(SM_CXSIZEFRAME)+SM_CXPADDEDBORDER
    // (its GetClientAreaInsets), pushing it ~4px past the monitor onto the neighbor
    // screens where that gap shows as a gray border. Report a zero frame so it (and the
    // OS default maximize) sit flush on the work area. Consistent with the real frame
    // being 0 here; the NCHITTEST resize grips floor their width so they still work.
    if (IsFrameMetric(nIndex)) {
        static int n = 0;
        if (n < 4) { Wh_Log(L"[fl] GetSystemMetrics(%d)->0", nIndex); n++; }
        return 0;
    }
    return GetSystemMetrics_orig(nIndex);
}

using GetSystemMetricsForDpi_t = decltype(&GetSystemMetricsForDpi);
GetSystemMetricsForDpi_t GetSystemMetricsForDpi_orig;
int WINAPI GetSystemMetricsForDpi_hook(int nIndex, UINT dpi) {
    // DPI-aware variant -- the one modern Chromium actually calls for GetClientAreaInsets.
    if (IsFrameMetric(nIndex)) {
        static int n = 0;
        if (n < 4) { Wh_Log(L"[fl] GetSystemMetricsForDpi(%d,%u)->0", nIndex, dpi); n++; }
        return 0;
    }
    return GetSystemMetricsForDpi_orig(nIndex, dpi);
}

static BOOL CALLBACK EnumProc(HWND hWnd, LPARAM) {
    DWORD pid = 0;
    GetWindowThreadProcessId(hWnd, &pid);
    if (pid == GetCurrentProcessId()) Apply(hWnd, L"Enum");
    return TRUE;
}

BOOL Wh_ModInit(void) {
    Wh_Log(L"[fl] ModInit exe=%s", CurrentExeName());
    Wh_SetFunctionHook((void*)SetWindowPos, (void*)SetWindowPos_hook, (void**)&SetWindowPos_orig);
    Wh_SetFunctionHook((void*)ShowWindow, (void*)ShowWindow_hook, (void**)&ShowWindow_orig);
    Wh_SetFunctionHook((void*)CreateWindowExW, (void*)CreateWindowExW_hook, (void**)&CreateWindowExW_orig);
    if (IsSubclassApp()) {
        Wh_SetFunctionHook((void*)GetSystemMetrics, (void*)GetSystemMetrics_hook, (void**)&GetSystemMetrics_orig);
        Wh_SetFunctionHook((void*)GetSystemMetricsForDpi, (void*)GetSystemMetricsForDpi_hook, (void**)&GetSystemMetricsForDpi_orig);
        Wh_Log(L"[fl] frame-metric hooks installed");
    }
    return TRUE;
}

void Wh_ModAfterInit(void) {
    Wh_Log(L"[fl] AfterInit enumerating");
    EnumWindows(EnumProc, 0);
}

void Wh_ModUninit(void) {
    for (HWND hWnd : g_subclassed) {
        WindhawkUtils::RemoveWindowSubclassFromAnyThread(hWnd, SubProc);
        SetWindowPos(hWnd, NULL, 0, 0, 0, 0,
                     SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
    }
    g_subclassed.clear();
}
