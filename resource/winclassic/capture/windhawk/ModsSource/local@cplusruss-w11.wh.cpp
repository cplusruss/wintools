// ==WindhawkMod==
// @id              cplusruss-w11
// @name            cplusruss W11 Classic (combined)
// @description     Combined classic-theme tweaks: Aero Tray, Classic Explorer nav bar & treeview, Classic Theme Explorer Lite, Classic Task Dialog Fix, Classic Theme transparency fix, Clientedge Everywhere, Fix Classic Theme Maximized Windows, Message Box Fix, Modernize Folder Picker, Classic File Picker, Classic Taskbar 3D Buttons, DWM Unextend Frames, Eradicate Immersive Menus
// @version         1.0.0
// @author          cplusruss (combines mods by aubymori, m417z, Anixx, Waldemar/CyprinusCarpio, ephemeralViolette)
// @include         *
// @include         dllhost.exe
// @exclude         jan.exe
// @exclude         code.exe
// @exclude         cursor.exe
// @exclude         discord.exe
// @exclude         slack.exe
// @exclude         obsidian.exe
// @exclude         signal.exe
// @exclude         githubdesktop.exe
// @exclude         postman.exe
// @exclude         notion.exe
// @exclude         spotify.exe
// @exclude         whatsapp.exe
// @exclude         ms-teams.exe
// @exclude         figma.exe
// @exclude         element.exe
// @exclude         Logic.exe
// @exclude         Zoom.exe
// @exclude         draw.io.exe
// @architecture    x86-64
// @architecture    x86
// @compilerOptions -lpsapi -lgdi32 -luxtheme -lshell32 -lcomctl32 -lole32 -loleaut32 -lversion -lshlwapi -lruntimeobject -lUxTheme -luser32 -DWINVER=0x0A00
// ==/WindhawkMod==

// ==WindhawkModReadme==
/*
# cplusruss W11 Classic (combined)

A single mod merging 14 classic-theme Windhawk sub-mods. Each sub-mod's
code lives in its own C++ namespace; one set of lifecycle functions dispatches
to them, guarding explorer-only features so they only run inside explorer.exe.

Note: 'Classic Theme Enable with extended compatibility' is intentionally NOT
merged here -- it targets winlogon.exe / early boot and is kept as its own mod.
*/
// ==/WindhawkModReadme==

// ==WindhawkModSettings==
/*
- composition: default
  $name: Theme mode
  $description: Force the tray overflow to use a certain theme.
  $options:
  - default: Default
  - aero: Aero
  - basic: Aero Basic
  - classic: Windows Classic
- customizetext: Customize...
  $name: "\"Customize...\" link text"
- customizetooltip: Click here to select what icons appear on the taskbar.
  $name: "\"Customize...\" link tooltip"
- explorerStyle: classicNavigationBar
  $name: Explorer style
  $options:
  - classicNavigationBar: Classic navigation bar
  - classicRibbonUI: Classic ribbon UI (no tabs)
- FoldersText: default
  $name: Folders Pane Text
  $description: If you want a custom text to be displayed on the folders pane, change this text. 'default' will source the text from localized system resources.
- DrawLines: true
  $name: Draw Dotted Lines
  $description: Use TVS_HASLINES style. Disable for a more XP-like look.
- HotTracking: false
  $name: Item Hot Tracking
  $description: Use TVS_TRACKSELECT style. Enable for a more XP-like look.
- LinesAtRoot: false
  $name: Lines At Root
  $description: Use TVS_LINESATROOT style.
- GradientBackground: false
  $name: Gradient Background
  $description: Draw a gradient in the header. Enable for a more accurate XP-like look.
- DrawButtons: true
  $name: Draw +/- Buttons
  $description: Should the mod draw it's own +/- buttons. Disable only if not using Classic theme.
- AlternateLineColor: Automatic
  $name: Alternate line color
  $description: Use highlight color instead of shadow color for drawing lines. May produce better results on some dark themes.
  $options:
    - False: Use default color.
    - True: Use alternate color.
    - Automatic: Use alternate color if the default color's contrast is too low.
- CloseButtonXOffset: 0
  $name: Horizontal close button offset
- CloseButtonYOffset: 0
  $name: Vertical close button offset
- style: vista
  $name: Message box style
  $options:
  - nt4: Windows 95/NT 4.0
  - xp: Windows 98-XP
  - vista: Windows Vista-10 1703
- explorer: true
  $name: Apply to Explorer
  $description: Applies to Explorer itself, including desktop, navigation pane, main Explorer view, open/save dialogs, and the main taskbar menu.
- nosettingsicon: true
  $name: No "Taskbar settings" icon
  $description: Removes the icon from the "Taskbar settings" entry in the taskbar menu
- sound: true
  $name: Apply to Volume tray icon
- network: true
  $name: Apply to Network tray icon
- defender: true
  $name: Apply to Windows Security
- narrator: true
  $name: Apply to Narrator
*/
// ==/WindhawkModSettings==

#include <windhawk_api.h>
#include <algorithm>
#include <cmath>
#include <vector>
#include <winrt/base.h>
#include <winrt/windows.foundation.collections.h>
#include <initguid.h>
#include <shlobj.h>
#include <inspectable.h>
#include <psapi.h>
#include <shdeprecated.h>
#include <shlwapi.h>
#include <synchapi.h>
#include <uxtheme.h>
#include <vsstyle.h>
#include <vssym32.h>
#include <windows.h>
#include <windowsx.h>
#include <wingdi.h>
#include <wrl.h>
#include <windhawk_utils.h>

// ============================================================
// ===== shared: host-process detection
// ============================================================
namespace {
bool g_inExplorer = false;
bool g_inSolidWorks = false;

PCWSTR CurrentExeName() {
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

bool IsEradicateExcluded() {
    PCWSTR exe = CurrentExeName();
    return 0 == _wcsicmp(exe, L"windhawk.exe") ||
        0 == _wcsicmp(exe, L"dwm.exe") ||
        0 == _wcsicmp(exe, L"ShellExperienceHost.exe") ||
        0 == _wcsicmp(exe, L"wlanext.exe") ||
        0 == _wcsicmp(exe, L"svchost.exe") ||
        0 == _wcsicmp(exe, L"SearchIndexer.exe") ||
        0 == _wcsicmp(exe, L"consent.exe");
}

bool IsMaximizedExcluded() {
    PCWSTR exe = CurrentExeName();
    return 0 == _wcsicmp(exe, L"windhawk.exe") ||
        0 == _wcsicmp(exe, L"conhost.exe") ||
        0 == _wcsicmp(exe, L"consent.exe") ||
        0 == _wcsicmp(exe, L"dwm.exe") ||
        0 == _wcsicmp(exe, L"lsass.exe") ||
        0 == _wcsicmp(exe, L"winlogon.exe") ||
        0 == _wcsicmp(exe, L"logonui.exe") ||
        0 == _wcsicmp(exe, L"ApplicationFrameHost.exe") ||
        0 == _wcsicmp(exe, L"gameinputsvc.exe") ||
        0 == _wcsicmp(exe, L"svchost.exe");
}

bool IsBrowserExcluded() {
    PCWSTR exe = CurrentExeName();
    return 0 == _wcsicmp(exe, L"firefox.exe") ||
        0 == _wcsicmp(exe, L"chrome.exe") ||
        0 == _wcsicmp(exe, L"msedge.exe") ||
        0 == _wcsicmp(exe, L"brave.exe") ||
        0 == _wcsicmp(exe, L"opera.exe") ||
        0 == _wcsicmp(exe, L"vivaldi.exe") ||
        0 == _wcsicmp(exe, L"chromium.exe") ||
        0 == _wcsicmp(exe, L"thorium.exe") ||
        0 == _wcsicmp(exe, L"librewolf.exe") ||
        0 == _wcsicmp(exe, L"waterfox.exe") ||
        0 == _wcsicmp(exe, L"floorp.exe") ||
        0 == _wcsicmp(exe, L"zen.exe");
}

bool IsSolidWorks() { return 0 == _wcsicmp(CurrentExeName(), L"sldworks.exe"); }
}  // anonymous namespace

// ============================================================
// ===== aero-tray
// ============================================================
namespace AeroTray {

const UINT LINK_AREA_HEIGHT = 43;
const UINT LINK_AREA_PADDING = 16;

const UINT ICON_AREA_PADDING = 7;
const UINT ICON_PADDING = 18;

const UINT FLYOUT_OFFSET = 8;

#define RECTWIDTH(rect)  ((rect).right - (rect).left)
#define RECTHEIGHT(rect) ((rect).bottom - (rect).top)

typedef enum
{
    TM_DEFAULT = 0,
    TM_AERO,
    TM_BASIC,
    TM_CLASSIC
} THEMEMODE;

struct
{
    THEMEMODE                    thememode;
    WindhawkUtils::StringSetting customizetext;
    WindhawkUtils::StringSetting customizetooltip;
} settings;

HTHEME  g_hTheme              =  NULL;
HWND    g_hCustomizeLink      =  NULL;
HWND    g_hCustomizeTooltip   =  NULL;
BOOL    g_bCustomizeHovered   = FALSE;
BOOL    g_bCustomizeDown      = FALSE;
BOOL    g_bCustomizeCapturing = FALSE;
HCURSOR g_hcArrow             =  NULL;
HCURSOR g_hcHand              =  NULL;

bool UseComposition(void)
{
    switch (settings.thememode)
    {
        case TM_DEFAULT:
            return IsCompositionActive();
        case TM_AERO:
            return true;
        case TM_BASIC:
        case TM_CLASSIC:
            return false;
    }
}

/**
  * Get the menu font (for classic theme).
  * This creates a new GDI object, so be sure to destroy it once you're done!
  */
HFONT GetMenuFont(bool underline = false)
{
    NONCLIENTMETRICSW ncm = { sizeof(NONCLIENTMETRICSW) };
    if (SystemParametersInfoW(
        SPI_GETNONCLIENTMETRICS,
        sizeof(NONCLIENTMETRICSW),
        &ncm,
        NULL
    ))
    {
        if (underline)
        {
            ncm.lfMenuFont.lfUnderline = TRUE;
        }
        return CreateFontIndirectW(&ncm.lfMenuFont);
    }
    return NULL;
}

/* Get the tray chevron. Needed for a hack. */
HWND GetTrayChevron(void)
{
    HWND hTaskbar = FindWindowW(L"Shell_TrayWnd", NULL);
    if (hTaskbar)
    {
        HWND hNotify = FindWindowExW(hTaskbar, NULL, L"TrayNotifyWnd", NULL);
        if (hNotify)
        {
            return FindWindowExW(hNotify, NULL, L"Button", NULL);
        }
    }
    return NULL;
}

#define CTrayOverflow_Window(pThis) *((HWND *)pThis + 3)
#define CTrayOverflow_Toolbar(pThis) *((HWND *)pThis + 11)

/* Make the tray toolbar draw using the system theme */
LRESULT (* CTrayNotify__OnCDNotify_orig)(void *, HWND, LPNMTBCUSTOMDRAW);
LRESULT CTrayNotify__OnCDNotify_hook(
    void             *pThis,
    HWND              hWnd,
    LPNMTBCUSTOMDRAW  lpnmtbcd
)
{
    if (lpnmtbcd->nmcd.dwDrawStage == CDDS_PREPAINT)
    {
        return CDRF_NOTIFYITEMDRAW;
    }
    else if (lpnmtbcd->nmcd.dwDrawStage == 0x10001)
    {
        return TBCDRF_NOOFFSET;
    }
    return CDRF_DODEFAULT;
}

/* Apply appropriate border style */
void (* CTrayOverflow__EnsureBorder_orig)(void *, HWND);
void CTrayOverflow__EnsureBorder_hook(
    void *pThis,
    HWND  hWnd
)
{
    DWORD dwStyle = GetWindowLongPtrW(hWnd, GWL_STYLE);
    if (UseComposition())
    {
        dwStyle |= (WS_THICKFRAME | WS_DLGFRAME);
    }
    else
    {
        dwStyle |= WS_BORDER;
    }
    SetWindowLongPtrW(hWnd, GWL_STYLE, dwStyle);
}

/* Adjust a window's position to be pushed away from the taskbar */
POINT AdjustWindowPosForTaskbar(HWND hWnd)
{
    HMONITOR hm = MonitorFromWindow(hWnd, MONITOR_DEFAULTTONEAREST);
    HDC hDC = GetDC(hWnd);
    int offset = MulDiv(FLYOUT_OFFSET, GetDeviceCaps(hDC, LOGPIXELSY), 96);

    RECT rc;
    GetWindowRect(hWnd, &rc);

    MONITORINFO mi = { sizeof(MONITORINFO) };
    GetMonitorInfoW(hm, &mi);

    int dx = 0, dy = 0;
    PLONG plrc = (PLONG)&rc;
    PLONG plwrc = (PLONG)&mi.rcWork;
    for (int i = 0; i < 4; i++)
    {
        int curOffset = plwrc[i] - plrc[i];
        curOffset = (curOffset < 0) ? -curOffset : curOffset;

        if (curOffset < offset)
        {
            int *set = (i % 2 == 0) ? &dx : &dy;
            if (i > 1)
            {
                *set -= offset - curOffset;
            }
            else
            {
                *set += offset - curOffset;
            }
        }
    }
    return { rc.left + dx, rc.top + dy };
}

/* Add space between taskbar and tray overflow for Aero */
void (* CTrayOverflow__PositionWindow_orig)(void *);
void CTrayOverflow__PositionWindow_hook(
    void *pThis
)
{
    CTrayOverflow__PositionWindow_orig(pThis);

    HWND hWnd = CTrayOverflow_Window(pThis);
    if (hWnd && UseComposition())
    {
        POINT pt = AdjustWindowPosForTaskbar(hWnd);
        SetWindowPos(
            hWnd, NULL,
            pt.x, pt.y,
            0, 0,
            SWP_NOSIZE | SWP_NOZORDER
        );
    }
}

/* To get item count */
__int64 (* CTrayItemManager__GetItemCountHelper)(void *pThis, int i1, int i2);

#define CTrayOverflow_CTrayItemManager(pThis) (void *)*((__int64 *)pThis + 5)

/* Add space for link area and add margin to icon area */
bool (* CTrayOverflow_SizeWindows_orig)(void *);
bool CTrayOverflow_SizeWindows_hook(
    void *pThis
)
{
    CTrayOverflow_SizeWindows_orig(pThis);

    HWND hWnd = CTrayOverflow_Window(pThis);
    HDC hDC = GetDC(hWnd);

    RECT rc;
    GetClientRect(hWnd, &rc);

    rc.bottom += MulDiv(LINK_AREA_HEIGHT, GetDeviceCaps(hDC, LOGPIXELSY), 96);

    HWND hToolbar = CTrayOverflow_Toolbar(pThis);
    if (hToolbar)
    {
        int nMargin = MulDiv(ICON_AREA_PADDING, GetDeviceCaps(hDC, LOGPIXELSY), 96);
        SetWindowPos(
            hToolbar, NULL,
            nMargin, nMargin,
            0, 0,
            SWP_NOSIZE | SWP_NOZORDER
        );
        rc.right += nMargin * 2;
        rc.bottom += nMargin * 2;

        /**
          * Windows 7 and 8 always used 3 items per row on this.
          * However, Windows 10 will use two items per row whenever there is 3 or 4
          * items on it. The following code adjusts the sizes to make it always use
          * 3 items per row again.
          */
    
        void *ptim = CTrayOverflow_CTrayItemManager(pThis);
        if (ptim)
        {
            __int64 nItems = CTrayItemManager__GetItemCountHelper(
                ptim, 3, 0
            );
            if (nItems == 3 || nItems == 4)
            {
                int nLinkAreaHeight = MulDiv(LINK_AREA_HEIGHT, GetDeviceCaps(hDC, LOGPIXELSY), 96);
                int nItemSize = LOWORD(SendMessageW(hToolbar, TB_GETBUTTONSIZE, NULL, NULL));

                RECT rcToolbar = { 0 };
                switch (nItems)
                {
                    case 3:
                        rcToolbar.right = nItemSize * 3;
                        rcToolbar.bottom = nItemSize;
                        break;
                    case 4:
                        rcToolbar.right = nItemSize * 3;
                        rcToolbar.bottom = nItemSize * 2;
                        break;
                }

                SetWindowPos(
                    hToolbar, NULL,
                    0, 0,
                    RECTWIDTH(rcToolbar),
                    RECTHEIGHT(rcToolbar),
                    SWP_NOMOVE | SWP_NOZORDER
                );

                SetRectEmpty(&rc);
                rc.right = (nMargin * 2) + RECTWIDTH(rcToolbar);
                rc.bottom = (nMargin * 2) + RECTHEIGHT(rcToolbar) + nLinkAreaHeight;
            }
        }
    }

    if (g_hCustomizeLink)
    {
        RECT rcLink;
        GetWindowRect(g_hCustomizeLink, &rcLink);
        int nLinkMargin = MulDiv(LINK_AREA_PADDING, GetDeviceCaps(hDC, LOGPIXELSY), 96);
        int nLinkAreaHeight = MulDiv(LINK_AREA_HEIGHT, GetDeviceCaps(hDC, LOGPIXELSY), 96);

        if (RECTWIDTH(rc) < RECTWIDTH(rcLink) + (nLinkMargin * 2))
        {
            rc.right = RECTWIDTH(rcLink) + (nLinkMargin * 2);
        }

        SetWindowPos(
            g_hCustomizeLink,
            NULL,
            rc.left + ((RECTWIDTH(rc) / 2) - (RECTWIDTH(rcLink) / 2)),
            rc.top + (rc.bottom - nLinkAreaHeight) + ((nLinkAreaHeight / 2) - (RECTHEIGHT(rcLink) / 2)),
            0, 0,
            SWP_NOSIZE | SWP_NOZORDER
        );

        if (hToolbar)
        {
            int nMargin = MulDiv(ICON_AREA_PADDING, GetDeviceCaps(hDC, LOGPIXELSY), 96);
            RECT rcToolbar;
            GetClientRect(hToolbar, &rcToolbar);
            if (RECTWIDTH(rc) - (nMargin * 2) > RECTWIDTH(rcToolbar))
            {
                SetWindowPos(
                    hToolbar, NULL,
                    rc.left + ((RECTWIDTH(rc) / 2) - (RECTWIDTH(rcToolbar) / 2)),
                    nMargin,
                    0, 0,
                    SWP_NOSIZE | SWP_NOZORDER
                );
            }
        }
    }

    AdjustWindowRect(
        &rc,
        GetWindowLongPtrW(hWnd, GWL_STYLE),
        FALSE
    );

    SetWindowPos(
        hWnd,
        NULL,
        0, 0,
        RECTWIDTH(rc),
        RECTHEIGHT(rc),
        SWP_NOMOVE | SWP_NOZORDER
    );

    ReleaseDC(hWnd, hDC);
    CTrayOverflow__PositionWindow_hook(pThis);
    return true;
}

/* Reduce tray button padding */
void (* CTrayOverflow_UpdateButtonMetrics_orig)(void *);
void CTrayOverflow_UpdateButtonMetrics_hook(
    void *pThis
)
{
    HWND hToolbar = CTrayOverflow_Toolbar(pThis);
    if (hToolbar)
    {
        SendMessageW(hToolbar, TB_SETPADDING, NULL, MAKELPARAM(ICON_PADDING, ICON_PADDING));
    }
}

/* Draw icon and link area backgrounds */
LRESULT (* CTrayOverflow__OnPaint_orig)(void *, HDC);
LRESULT CTrayOverflow__OnPaint_hook(
    void *pThis,
    HDC   hdcOut
)
{
    HWND hWnd = CTrayOverflow_Window(pThis);
    PAINTSTRUCT ps;
    HDC hDC;

    if (hdcOut)
    {
        hDC = hdcOut;
        if (!GetClipBox(hDC, &ps.rcPaint))
        {
            SetRectEmpty(&ps.rcPaint);
        }
        ps.fRestore = FALSE;
    }
    else
    {
        hDC = BeginPaint(hWnd, &ps);
        ps.fRestore = TRUE;
    }

    RECT rc = { 0 };
    GetClientRect(hWnd, &rc);

    int nAreaHeight = MulDiv(LINK_AREA_HEIGHT, GetDeviceCaps(hDC, LOGPIXELSY), 96);

    rc.top = rc.bottom - nAreaHeight;
    if (g_hTheme)
    {
        DrawThemeBackground(
            g_hTheme,
            hDC,
            FLYOUT_LINKAREA,
            0,
            &rc,
            NULL
        );
    }
    else
    {
        FillRect(
            hDC,
            &rc,
            GetSysColorBrush(COLOR_3DFACE)
        );
    }

    rc.bottom = rc.top;
    rc.top = 0;

    if (g_hTheme)
    {
        DrawThemeBackground(
            g_hTheme,
            hDC,
            6,
            0,
            &rc,
            NULL
        );
    }
    else
    {
        FillRect(
            hDC,
            &rc,
            GetSysColorBrush(COLOR_WINDOW)
        );
    }

    if (ps.fRestore)
    {
        EndPaint(hWnd, &ps);
    }

    return 0;
}

/* Prevent DWM composition attribute from being set */
void (* CTrayOverflow__UpdateColors_orig)(void *);
void CTrayOverflow__UpdateColors_hook(
    void *pThis
)
{
    return;
}

LRESULT PaintCustomizeLink(
    HWND hWnd,
    HDC  hDC
)
{
    BOOL bHover;

    POINT pt;
    GetCursorPos(&pt);
    RECT rc;
    GetWindowRect(hWnd, &rc);
    
    bHover = PtInRect(&rc, pt) || GetFocus() == hWnd;

    RECT rcClient;
    GetClientRect(hWnd, &rcClient);

    DTTOPTS opts = { sizeof(DTTOPTS) };
    if (IsCompositionActive())
    {
        opts.dwFlags = DTT_COMPOSITED;
    }

    RECT rcPaint;
    GetClipBox(hDC, &rcPaint);

    DrawThemeParentBackground(hWnd, hDC, NULL);

    if (g_hTheme)
    {
        int bkOld = SetBkMode(hDC, TRANSPARENT);
        DrawThemeTextEx(
            g_hTheme,
            hDC,
            FLYOUT_LINK,
            bHover ? FLYOUTLINK_HOVER : FLYOUTLINK_NORMAL,
            settings.customizetext.get(),
            -1,
            DT_CENTER,
            &rcClient,
            &opts
        );
        SetBkMode(hDC, bkOld);
    }
    else
    {
        HFONT hfMenu = GetMenuFont(bHover);
        HFONT hfOld = (HFONT)SelectObject(hDC, hfMenu);
        COLORREF crBkOld = SetBkColor(hDC, GetSysColor(COLOR_3DFACE));
        COLORREF crOld = SetTextColor(hDC, GetSysColor(COLOR_HOTLIGHT));

        DrawTextW(
            hDC,
            settings.customizetext.get(),
            -1,
            &rcClient,
            NULL
        );

        SetTextColor(hDC, crOld);
        SetBkColor(hDC, crBkOld);
        SelectObject(hDC, hfOld);
        DeleteObject(hfMenu);
    }

    return 0;
}

LRESULT CALLBACK CustomizeLinkSubclassProc(
    HWND      hWnd,
    UINT      uMsg,
    WPARAM    wParam,
    LPARAM    lParam,
    DWORD_PTR dwRefData
)
{
    switch (uMsg)
    {
        case WM_PAINT:
        {
            PAINTSTRUCT ps;
            HDC hDC = BeginPaint(hWnd, &ps);
            LRESULT lr = PaintCustomizeLink(hWnd, hDC);
            EndPaint(hWnd, &ps);
            return lr;
        }
        case WM_PRINTCLIENT:
        {
            return PaintCustomizeLink(hWnd, (HDC)wParam);
        }
        /* Repaint and set cursor on hover */
        case WM_MOUSEMOVE:
        {
            POINT pt;
            pt.x = GET_X_LPARAM(lParam);
            pt.y = GET_Y_LPARAM(lParam);

            RECT rc;
            GetClientRect(hWnd, &rc);

            BOOL bHovered = g_bCustomizeHovered;
            if (IsWindowEnabled(hWnd) && PtInRect(&rc, pt))
            {
                if (!g_bCustomizeCapturing && SetCapture(hWnd))
                {
                    g_bCustomizeCapturing = TRUE;
                }
                g_bCustomizeHovered = TRUE;
            }
            else
            {
                if (g_bCustomizeCapturing && ReleaseCapture())
                {
                    g_bCustomizeCapturing = FALSE;
                }
                g_bCustomizeHovered = FALSE;
                g_bCustomizeDown = FALSE;
            }

            if (g_bCustomizeHovered != bHovered)
            {
                SetCursor(g_bCustomizeHovered ? g_hcHand : g_hcArrow);
                InvalidateRect(hWnd, NULL, TRUE);
            }
            break;
        }
        /* Unhover when it's hidden */
        case WM_SHOWWINDOW:
            if (!wParam && g_bCustomizeHovered)
            {
                g_bCustomizeHovered = FALSE;
                if (g_bCustomizeCapturing && ReleaseCapture())
                {
                    g_bCustomizeCapturing = FALSE;
                }
            }
            return 0;
        case WM_LBUTTONDOWN:
            g_bCustomizeDown = TRUE;
            break;
        /* Hide tray overflow and open Notification Area Icons CPL */
        case WM_LBUTTONUP:
            if (g_bCustomizeDown)
            {
                g_bCustomizeDown = FALSE;
                HWND hChevron = GetTrayChevron();
                if (hChevron)
                {
                    SendMessageW(hChevron, WM_LBUTTONUP, NULL, NULL);
                }
                ShellExecuteW(
                    NULL,
                    L"open",
                    L"explorer.exe",
                    L"shell:::{26EE0668-A00A-44D7-9371-BEB064C98683}\\0\\::{05D7B0F4-2121-4EFF-BF6B-ED3F69B894D9}",
                    NULL,
                    SW_SHOWNORMAL
                );
            }
            break;
        case WM_CAPTURECHANGED:
            g_bCustomizeCapturing = FALSE;
            g_bCustomizeHovered = FALSE;
            return 0;
    }

    return DefSubclassProc(hWnd, uMsg, wParam, lParam);
}

LPCWSTR LINK_TEXT_FORMAT = L"<A id=\"customize\">%s</A>";

/* Create link window */
HRESULT (* CTrayOverflow_RuntimeClassInitialize_orig)(void *, HWND, void *, void *, void *);
HRESULT CTrayOverflow_RuntimeClassInitialize_hook(
    void *pThis,
    HWND  hUnused,
    void *ptoe,
    void *ptla,
    void *ptch
)
{
    HRESULT hr = CTrayOverflow_RuntimeClassInitialize_orig(
        pThis, hUnused, ptoe, ptla, ptch
    );
    if (SUCCEEDED(hr))
    {
        HWND hWnd = CTrayOverflow_Window(pThis);
        if (hWnd)
        {
            WCHAR szText[1024];
            wsprintfW(szText, LINK_TEXT_FORMAT, settings.customizetext.get());

            g_hCustomizeLink = CreateWindowExW(
                NULL,
                L"SysLink",
                szText,
                WS_CHILD | LWS_TRANSPARENT,
                0, 0,
                0, 0,
                hWnd,
                NULL,
                GetModuleHandleW(NULL),
                NULL
            );

            if (g_hCustomizeLink)
            {
                /* This gets kicked out or something?? Very odd. */
                SetParent(g_hCustomizeLink, hWnd);

                WindhawkUtils::SetWindowSubclassFromAnyThread(
                    g_hCustomizeLink, CustomizeLinkSubclassProc, NULL
                );

                SIZE sz;
                HDC hDC = GetDC(g_hCustomizeLink);
                if (g_hTheme)
                {
                    RECT rcTemp;
                    if (SUCCEEDED(GetThemeTextExtent(
                        g_hTheme,
                        hDC,
                        FLYOUT_LINK,
                        FLYOUTLINK_NORMAL,
                        settings.customizetext.get(),
                        -1,
                        NULL,
                        NULL,
                        &rcTemp
                    )))
                    {
                        sz.cx = RECTWIDTH(rcTemp);
                        sz.cy = RECTHEIGHT(rcTemp);
                    }
                }
                else
                {
                    HFONT hfMenu = GetMenuFont();
                    HFONT hfOld = (HFONT)SelectObject(hDC, hfMenu);
                    GetTextExtentPoint32W(
                        hDC,
                        settings.customizetext.get(),
                        wcslen(settings.customizetext.get()),
                        &sz
                    );
                    SelectObject(hDC, hfOld);
                    DeleteObject(hfMenu);
                }
                ReleaseDC(g_hCustomizeLink, hDC);

                SetWindowPos(
                    g_hCustomizeLink,
                    NULL,
                    0, 0,
                    sz.cx, sz.cy,
                    SWP_SHOWWINDOW | SWP_NOMOVE | SWP_NOZORDER
                );

                g_hCustomizeTooltip = CreateWindowExW(
                    WS_EX_TOPMOST,
                    TOOLTIPS_CLASSW,
                    NULL,
                    WS_POPUP | TTS_NOPREFIX | TTS_ALWAYSTIP,
                    0, 0, 0, 0,
                    g_hCustomizeLink,
                    NULL, 0, NULL
                );

                if (g_hCustomizeTooltip)
                {
                    TTTOOLINFOW ti = { sizeof(TTTOOLINFOW) };
                    ti.uFlags = TTF_SUBCLASS;
                    ti.hwnd = g_hCustomizeLink;
                    ti.lpszText = (LPWSTR)settings.customizetooltip.get();
                    GetClientRect(g_hCustomizeLink, &ti.rect);

                    SendMessageW(g_hCustomizeTooltip, TTM_ADDTOOLW, NULL, (LPARAM)&ti);
                }
            }
        }
    }
    return hr;
}

/*
 * Patch StartIsBack in memory to prevent it from overriding standard explorer
 * behavior and thus breaking the mod.
 */
void PatchStartIsBack(HMODULE hModule)
{
    const wchar_t *pattern = L"NotifyIconOverflowWindow";

    MODULEINFO info = {0};
    GetModuleInformation(
        GetCurrentProcess(),
        hModule,
        &info,
        sizeof(MODULEINFO)
    );

    DWORD_PTR base = (size_t)info.lpBaseOfDll;
    size_t size = (size_t)info.SizeOfImage;
    size_t patternLen = wcslen(pattern) * 2;

    for (size_t i = 0; i < size - patternLen; i++)
    {
        bool found = true;

        for (size_t j = 0; j < patternLen; j++)
        {
            found = *((char *)pattern + j) == *(char *)(base + i + j);

            if (!found)
            {
                break;
            }
        }

        if (found)
        {
            size_t ptr = base + i;

            MEMORY_BASIC_INFORMATION mbi;
            VirtualQuery((wchar_t *)ptr, &mbi, sizeof(MEMORY_BASIC_INFORMATION));

            if (!VirtualProtect(mbi.BaseAddress, mbi.RegionSize, PAGE_READWRITE, &mbi.Protect))
            {
                return;
            }

            wcsncpy((wchar_t *)ptr, L"BYEBYEBYEBYEBYEBYEBYEBYE", patternLen);

            DWORD dwOldProtect;
            VirtualProtect(mbi.BaseAddress, mbi.RegionSize, mbi.Protect, &dwOldProtect);

            return;
        }
    }
}

#define LoadIntSetting(NAME) settings.NAME = Wh_GetIntSetting(L ## #NAME)
#define LoadStringSetting(NAME) settings.NAME = WindhawkUtils::StringSetting::make(L ## #NAME)

void LoadSettings(void)
{
    LoadStringSetting(customizetext);
    LoadStringSetting(customizetooltip);

    LPCWSTR szThemeMode = Wh_GetStringSetting(L"composition");
    if (!wcscmp(szThemeMode, L"aero"))
    {
        settings.thememode = TM_AERO;
    }
    else if (!wcscmp(szThemeMode, L"basic"))
    {
        settings.thememode = TM_BASIC;
    }
    else if (!wcscmp(szThemeMode, L"classic"))
    {
        settings.thememode = TM_CLASSIC;
    }
    else
    {
        settings.thememode = TM_DEFAULT;
    }
    Wh_FreeStringSetting(szThemeMode);
}

const WindhawkUtils::SYMBOL_HOOK hooks[] = {
    /* Make the tray toolbar draw using the system theme */
    {
        {
            L"protected: __int64 __cdecl CTrayNotify::_OnCDNotify(struct HWND__ *,struct _NMTBCUSTOMDRAW *)"
        },
        &CTrayNotify__OnCDNotify_orig,
        CTrayNotify__OnCDNotify_hook,
        false
    },
    /* Apply appropriate border style */
    {
        {
            L"private: void __cdecl CTrayOverflow::_EnsureBorder(struct HWND__ *)"
        },
        &CTrayOverflow__EnsureBorder_orig,
        CTrayOverflow__EnsureBorder_hook,
        false
    },
    /* Add space between taskbar and tray overflow for Aero */
    {
        {
            L"private: void __cdecl CTrayOverflow::_PositionWindow(void)"
        },
        &CTrayOverflow__PositionWindow_orig,
        CTrayOverflow__PositionWindow_hook,
        false
    },
    {
        {
            L"private: __int64 __cdecl CTrayItemManager::_GetItemCountHelper(int,int)const "
        },
        &CTrayItemManager__GetItemCountHelper,
        nullptr,
        false
    },
    /* Add space for link area and add margin to icon area */
    {
        {
            L"public: bool __cdecl CTrayOverflow::SizeWindows(void)"
        },
        &CTrayOverflow_SizeWindows_orig,
        CTrayOverflow_SizeWindows_hook,
        false
    },
    /* Reduce tray button padding */
    {
        {
            L"private: void __cdecl CTrayOverflow::UpdateButtonMetrics(void)"
        },
        &CTrayOverflow_UpdateButtonMetrics_orig,
        CTrayOverflow_UpdateButtonMetrics_hook,
        false
    },
    /* Draw icon and link area backgrounds */
    {
        {
            L"private: __int64 __cdecl CTrayOverflow::_OnPaint(struct HDC__ *)"
        },
        &CTrayOverflow__OnPaint_orig,
        CTrayOverflow__OnPaint_hook,
        false
    },
    /* Prevent DWM composition attribute from being set */
    {
        {
            L"private: void __cdecl CTrayOverflow::_UpdateColors(void)"
        },
        &CTrayOverflow__UpdateColors_orig,
        CTrayOverflow__UpdateColors_hook,
        false
    },
    /* Create link window */
    {
        {
            L"public: long __cdecl CTrayOverflow::RuntimeClassInitialize(struct HWND__ *,class TrayOverflowEvents *,struct ITaskListAnimation *,struct ITrayComponentHost *)"
        },
        &CTrayOverflow_RuntimeClassInitialize_orig,
        CTrayOverflow_RuntimeClassInitialize_hook,
        false
    }
};

LPCWSTR SIB_PATH = L"%PROGRAMFILES(X86)%\\StartIsBack\\StartIsBack64.dll";
LPCWSTR SIB_PATH_USER = L"%LOCALAPPDATA%\\StartIsBack\\StartIsBack64.dll";

BOOL Wh_ModInit(void)
{
    LoadSettings();

    WCHAR szSIBPath[MAX_PATH];
    ExpandEnvironmentStringsW(SIB_PATH, szSIBPath, MAX_PATH);

    HMODULE hSib = LoadLibraryW(szSIBPath);
    if (!hSib)
    {
        WCHAR szUserSIBPath[MAX_PATH];
        ExpandEnvironmentStringsW(SIB_PATH_USER, szUserSIBPath, MAX_PATH);
        hSib = LoadLibraryW(szUserSIBPath);
    }

    if (hSib)
    {
        PatchStartIsBack(hSib);
    }

    if (settings.thememode != TM_CLASSIC)
    {
        g_hTheme = OpenThemeData(NULL, L"Flyout");
    }
    g_hcArrow = LoadCursorW(NULL, IDC_ARROW);
    g_hcHand = LoadCursorW(NULL, IDC_HAND);

    if (!WindhawkUtils::HookSymbols(
        GetModuleHandleW(NULL),
        hooks,
        ARRAYSIZE(hooks)
    ))
    {
        Wh_Log(L"Failed to hook one or more symbol functions");
        return FALSE;
    }
    return TRUE;
}

BOOL Wh_ModSettingsChanged(PBOOL pbReload)
{
    *pbReload = TRUE;
    return TRUE;
}

void Wh_ModUninit(void)
{
    if (g_hCustomizeLink)
    {
        DestroyWindow(g_hCustomizeLink);
    }
}

}  // namespace AeroTray
#undef RECTWIDTH
#undef RECTHEIGHT
#undef CTrayOverflow_Window
#undef CTrayOverflow_Toolbar
#undef CTrayOverflow_CTrayItemManager
#undef LoadIntSetting
#undef LoadStringSetting

// ============================================================
// ===== explorer-frame-classic
// ============================================================
namespace ExplorerFrameClassic {

// Source code is published under The GNU General Public License v3.0.
//
// For bug reports and feature requests, please open an issue here:
// https://github.com/ramensoftware/windhawk-mods/issues
//
// For pull requests, development takes place here:
// https://github.com/m417z/my-windhawk-mods






enum class ExplorerStyle {
    classicNavigationBar,
    classicRibbonUI,
};

struct {
    ExplorerStyle explorerStyle;
} g_settings;

std::atomic<bool> g_fileExplorerExtensionsLoaded;

#pragma region WASDK
namespace WASDK {

// C3C01020-320C-5CF6-9D24-D396BBFA4D8B
constexpr winrt::guid IID_IUIElement{
    0xC3C01020,
    0x320C,
    0x5CF6,
    {0x9D, 0x24, 0xD3, 0x96, 0xBB, 0xFA, 0x4D, 0x8B}};

// FE08F13D-DC6A-5495-AD44-C2D8D21863B0
constexpr winrt::guid IID_IFrameworkElement{
    0xFE08F13D,
    0xDC6A,
    0x5495,
    {0xAD, 0x44, 0xC2, 0xD8, 0xD2, 0x18, 0x63, 0xB0}};

// C4496219-9014-58A1-B4AD-C5044913A5BB
constexpr winrt::guid IID_Controls_IGrid{
    0xC4496219,
    0x9014,
    0x58A1,
    {0xB4, 0xAD, 0xC5, 0x04, 0x49, 0x13, 0xA5, 0xBB}};

// clang-format off
struct IUIElement : ::IInspectable {
    virtual int32_t __stdcall get_DesiredSize(winrt::Windows::Foundation::Size*) noexcept = 0;
    virtual int32_t __stdcall get_AllowDrop(bool*) noexcept = 0;
    virtual int32_t __stdcall put_AllowDrop(bool) noexcept = 0;
    virtual int32_t __stdcall get_Opacity(double*) noexcept = 0;
    virtual int32_t __stdcall put_Opacity(double) noexcept = 0;
    virtual int32_t __stdcall get_Clip(void**) noexcept = 0;
    virtual int32_t __stdcall put_Clip(void*) noexcept = 0;
    virtual int32_t __stdcall get_RenderTransform(void**) noexcept = 0;
    virtual int32_t __stdcall put_RenderTransform(void*) noexcept = 0;
    virtual int32_t __stdcall get_Projection(void**) noexcept = 0;
    virtual int32_t __stdcall put_Projection(void*) noexcept = 0;
    virtual int32_t __stdcall get_Transform3D(void**) noexcept = 0;
    virtual int32_t __stdcall put_Transform3D(void*) noexcept = 0;
    virtual int32_t __stdcall get_RenderTransformOrigin(winrt::Windows::Foundation::Point*) noexcept = 0;
    virtual int32_t __stdcall put_RenderTransformOrigin(winrt::Windows::Foundation::Point) noexcept = 0;
    virtual int32_t __stdcall get_IsHitTestVisible(bool*) noexcept = 0;
    virtual int32_t __stdcall put_IsHitTestVisible(bool) noexcept = 0;
    virtual int32_t __stdcall get_Visibility(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_Visibility(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_RenderSize(winrt::Windows::Foundation::Size*) noexcept = 0;
    virtual int32_t __stdcall get_UseLayoutRounding(bool*) noexcept = 0;
    virtual int32_t __stdcall put_UseLayoutRounding(bool) noexcept = 0;
    virtual int32_t __stdcall get_Transitions(void**) noexcept = 0;
    virtual int32_t __stdcall put_Transitions(void*) noexcept = 0;
    virtual int32_t __stdcall get_CacheMode(void**) noexcept = 0;
    virtual int32_t __stdcall put_CacheMode(void*) noexcept = 0;
    virtual int32_t __stdcall get_IsTapEnabled(bool*) noexcept = 0;
    virtual int32_t __stdcall put_IsTapEnabled(bool) noexcept = 0;
    virtual int32_t __stdcall get_IsDoubleTapEnabled(bool*) noexcept = 0;
    virtual int32_t __stdcall put_IsDoubleTapEnabled(bool) noexcept = 0;
    virtual int32_t __stdcall get_CanDrag(bool*) noexcept = 0;
    virtual int32_t __stdcall put_CanDrag(bool) noexcept = 0;
    virtual int32_t __stdcall get_IsRightTapEnabled(bool*) noexcept = 0;
    virtual int32_t __stdcall put_IsRightTapEnabled(bool) noexcept = 0;
    virtual int32_t __stdcall get_IsHoldingEnabled(bool*) noexcept = 0;
    virtual int32_t __stdcall put_IsHoldingEnabled(bool) noexcept = 0;
    virtual int32_t __stdcall get_ManipulationMode(uint32_t*) noexcept = 0;
    virtual int32_t __stdcall put_ManipulationMode(uint32_t) noexcept = 0;
    virtual int32_t __stdcall get_PointerCaptures(void**) noexcept = 0;
    virtual int32_t __stdcall get_ContextFlyout(void**) noexcept = 0;
    virtual int32_t __stdcall put_ContextFlyout(void*) noexcept = 0;
    virtual int32_t __stdcall get_CompositeMode(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_CompositeMode(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_Lights(void**) noexcept = 0;
    virtual int32_t __stdcall get_CanBeScrollAnchor(bool*) noexcept = 0;
    virtual int32_t __stdcall put_CanBeScrollAnchor(bool) noexcept = 0;
    virtual int32_t __stdcall get_ExitDisplayModeOnAccessKeyInvoked(bool*) noexcept = 0;
    virtual int32_t __stdcall put_ExitDisplayModeOnAccessKeyInvoked(bool) noexcept = 0;
    virtual int32_t __stdcall get_IsAccessKeyScope(bool*) noexcept = 0;
    virtual int32_t __stdcall put_IsAccessKeyScope(bool) noexcept = 0;
    virtual int32_t __stdcall get_AccessKeyScopeOwner(void**) noexcept = 0;
    virtual int32_t __stdcall put_AccessKeyScopeOwner(void*) noexcept = 0;
    virtual int32_t __stdcall get_AccessKey(void**) noexcept = 0;
    virtual int32_t __stdcall put_AccessKey(void*) noexcept = 0;
    virtual int32_t __stdcall get_KeyTipPlacementMode(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_KeyTipPlacementMode(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_KeyTipHorizontalOffset(double*) noexcept = 0;
    virtual int32_t __stdcall put_KeyTipHorizontalOffset(double) noexcept = 0;
    virtual int32_t __stdcall get_KeyTipVerticalOffset(double*) noexcept = 0;
    virtual int32_t __stdcall put_KeyTipVerticalOffset(double) noexcept = 0;
    virtual int32_t __stdcall get_KeyTipTarget(void**) noexcept = 0;
    virtual int32_t __stdcall put_KeyTipTarget(void*) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusKeyboardNavigation(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusKeyboardNavigation(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusUpNavigationStrategy(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusUpNavigationStrategy(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusDownNavigationStrategy(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusDownNavigationStrategy(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusLeftNavigationStrategy(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusLeftNavigationStrategy(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusRightNavigationStrategy(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusRightNavigationStrategy(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_KeyboardAccelerators(void**) noexcept = 0;
    virtual int32_t __stdcall get_KeyboardAcceleratorPlacementTarget(void**) noexcept = 0;
    virtual int32_t __stdcall put_KeyboardAcceleratorPlacementTarget(void*) noexcept = 0;
    virtual int32_t __stdcall get_KeyboardAcceleratorPlacementMode(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_KeyboardAcceleratorPlacementMode(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_HighContrastAdjustment(uint32_t*) noexcept = 0;
    virtual int32_t __stdcall put_HighContrastAdjustment(uint32_t) noexcept = 0;
    virtual int32_t __stdcall get_TabFocusNavigation(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_TabFocusNavigation(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_OpacityTransition(void**) noexcept = 0;
    virtual int32_t __stdcall put_OpacityTransition(void*) noexcept = 0;
    virtual int32_t __stdcall get_Translation(winrt::Windows::Foundation::Numerics::float3*) noexcept = 0;
    virtual int32_t __stdcall put_Translation(winrt::Windows::Foundation::Numerics::float3) noexcept = 0;
    virtual int32_t __stdcall get_TranslationTransition(void**) noexcept = 0;
    virtual int32_t __stdcall put_TranslationTransition(void*) noexcept = 0;
    virtual int32_t __stdcall get_Rotation(float*) noexcept = 0;
    virtual int32_t __stdcall put_Rotation(float) noexcept = 0;
    virtual int32_t __stdcall get_RotationTransition(void**) noexcept = 0;
    virtual int32_t __stdcall put_RotationTransition(void*) noexcept = 0;
    virtual int32_t __stdcall get_Scale(winrt::Windows::Foundation::Numerics::float3*) noexcept = 0;
    virtual int32_t __stdcall put_Scale(winrt::Windows::Foundation::Numerics::float3) noexcept = 0;
    virtual int32_t __stdcall get_ScaleTransition(void**) noexcept = 0;
    virtual int32_t __stdcall put_ScaleTransition(void*) noexcept = 0;
    virtual int32_t __stdcall get_TransformMatrix(winrt::Windows::Foundation::Numerics::float4x4*) noexcept = 0;
    virtual int32_t __stdcall put_TransformMatrix(winrt::Windows::Foundation::Numerics::float4x4) noexcept = 0;
    virtual int32_t __stdcall get_CenterPoint(winrt::Windows::Foundation::Numerics::float3*) noexcept = 0;
    virtual int32_t __stdcall put_CenterPoint(winrt::Windows::Foundation::Numerics::float3) noexcept = 0;
    virtual int32_t __stdcall get_RotationAxis(winrt::Windows::Foundation::Numerics::float3*) noexcept = 0;
    virtual int32_t __stdcall put_RotationAxis(winrt::Windows::Foundation::Numerics::float3) noexcept = 0;
    virtual int32_t __stdcall get_ActualOffset(winrt::Windows::Foundation::Numerics::float3*) noexcept = 0;
    virtual int32_t __stdcall get_ActualSize(winrt::Windows::Foundation::Numerics::float2*) noexcept = 0;
    virtual int32_t __stdcall get_XamlRoot(void**) noexcept = 0;
    virtual int32_t __stdcall put_XamlRoot(void*) noexcept = 0;
    virtual int32_t __stdcall get_Shadow(void**) noexcept = 0;
    virtual int32_t __stdcall put_Shadow(void*) noexcept = 0;
    virtual int32_t __stdcall get_RasterizationScale(double*) noexcept = 0;
    virtual int32_t __stdcall put_RasterizationScale(double) noexcept = 0;
    virtual int32_t __stdcall get_FocusState(int32_t*) noexcept = 0;
    virtual int32_t __stdcall get_UseSystemFocusVisuals(bool*) noexcept = 0;
    virtual int32_t __stdcall put_UseSystemFocusVisuals(bool) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusLeft(void**) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusLeft(void*) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusRight(void**) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusRight(void*) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusUp(void**) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusUp(void*) noexcept = 0;
    virtual int32_t __stdcall get_XYFocusDown(void**) noexcept = 0;
    virtual int32_t __stdcall put_XYFocusDown(void*) noexcept = 0;
    virtual int32_t __stdcall get_IsTabStop(bool*) noexcept = 0;
    virtual int32_t __stdcall put_IsTabStop(bool) noexcept = 0;
    virtual int32_t __stdcall get_TabIndex(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_TabIndex(int32_t) noexcept = 0;
    virtual int32_t __stdcall add_KeyUp(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_KeyUp(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_KeyDown(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_KeyDown(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_GotFocus(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_GotFocus(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_LostFocus(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_LostFocus(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_DragStarting(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_DragStarting(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_DropCompleted(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_DropCompleted(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_CharacterReceived(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_CharacterReceived(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_DragEnter(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_DragEnter(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_DragLeave(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_DragLeave(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_DragOver(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_DragOver(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_Drop(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_Drop(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PointerPressed(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PointerPressed(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PointerMoved(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PointerMoved(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PointerReleased(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PointerReleased(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PointerEntered(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PointerEntered(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PointerExited(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PointerExited(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PointerCaptureLost(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PointerCaptureLost(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PointerCanceled(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PointerCanceled(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PointerWheelChanged(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PointerWheelChanged(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_Tapped(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_Tapped(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_DoubleTapped(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_DoubleTapped(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_Holding(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_Holding(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ContextRequested(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ContextRequested(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ContextCanceled(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ContextCanceled(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_RightTapped(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_RightTapped(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ManipulationStarting(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ManipulationStarting(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ManipulationInertiaStarting(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ManipulationInertiaStarting(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ManipulationStarted(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ManipulationStarted(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ManipulationDelta(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ManipulationDelta(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ManipulationCompleted(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ManipulationCompleted(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_AccessKeyDisplayRequested(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_AccessKeyDisplayRequested(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_AccessKeyDisplayDismissed(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_AccessKeyDisplayDismissed(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_AccessKeyInvoked(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_AccessKeyInvoked(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ProcessKeyboardAccelerators(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ProcessKeyboardAccelerators(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_GettingFocus(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_GettingFocus(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_LosingFocus(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_LosingFocus(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_NoFocusCandidateFound(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_NoFocusCandidateFound(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PreviewKeyDown(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PreviewKeyDown(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_PreviewKeyUp(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_PreviewKeyUp(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_BringIntoViewRequested(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_BringIntoViewRequested(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall Measure(winrt::Windows::Foundation::Size) noexcept = 0;
    virtual int32_t __stdcall Arrange(winrt::Windows::Foundation::Rect) noexcept = 0;
    virtual int32_t __stdcall CapturePointer(void*, bool*) noexcept = 0;
    virtual int32_t __stdcall ReleasePointerCapture(void*) noexcept = 0;
    virtual int32_t __stdcall ReleasePointerCaptures() noexcept = 0;
    virtual int32_t __stdcall AddHandler(void*, void*, bool) noexcept = 0;
    virtual int32_t __stdcall RemoveHandler(void*, void*) noexcept = 0;
    virtual int32_t __stdcall TransformToVisual(void*, void**) noexcept = 0;
    virtual int32_t __stdcall InvalidateMeasure() noexcept = 0;
    virtual int32_t __stdcall InvalidateArrange() noexcept = 0;
    virtual int32_t __stdcall UpdateLayout() noexcept = 0;
    virtual int32_t __stdcall CancelDirectManipulations(bool*) noexcept = 0;
    virtual int32_t __stdcall StartDragAsync(void*, void**) noexcept = 0;
    virtual int32_t __stdcall StartBringIntoView() noexcept = 0;
    virtual int32_t __stdcall StartBringIntoViewWithOptions(void*) noexcept = 0;
    virtual int32_t __stdcall TryInvokeKeyboardAccelerator(void*) noexcept = 0;
    virtual int32_t __stdcall Focus(int32_t, bool*) noexcept = 0;
    virtual int32_t __stdcall StartAnimation(void*) noexcept = 0;
    virtual int32_t __stdcall StopAnimation(void*) noexcept = 0;
};

struct IFrameworkElement : ::IInspectable {
    virtual int32_t __stdcall get_Triggers(void**) noexcept = 0;
    virtual int32_t __stdcall get_Resources(void**) noexcept = 0;
    virtual int32_t __stdcall put_Resources(void*) noexcept = 0;
    virtual int32_t __stdcall get_Tag(void**) noexcept = 0;
    virtual int32_t __stdcall put_Tag(void*) noexcept = 0;
    virtual int32_t __stdcall get_Language(void**) noexcept = 0;
    virtual int32_t __stdcall put_Language(void*) noexcept = 0;
    virtual int32_t __stdcall get_ActualWidth(double*) noexcept = 0;
    virtual int32_t __stdcall get_ActualHeight(double*) noexcept = 0;
    virtual int32_t __stdcall get_Width(double*) noexcept = 0;
    virtual int32_t __stdcall put_Width(double) noexcept = 0;
    virtual int32_t __stdcall get_Height(double*) noexcept = 0;
    virtual int32_t __stdcall put_Height(double) noexcept = 0;
    virtual int32_t __stdcall get_MinWidth(double*) noexcept = 0;
    virtual int32_t __stdcall put_MinWidth(double) noexcept = 0;
    virtual int32_t __stdcall get_MaxWidth(double*) noexcept = 0;
    virtual int32_t __stdcall put_MaxWidth(double) noexcept = 0;
    virtual int32_t __stdcall get_MinHeight(double*) noexcept = 0;
    virtual int32_t __stdcall put_MinHeight(double) noexcept = 0;
    virtual int32_t __stdcall get_MaxHeight(double*) noexcept = 0;
    virtual int32_t __stdcall put_MaxHeight(double) noexcept = 0;
    virtual int32_t __stdcall get_HorizontalAlignment(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_HorizontalAlignment(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_VerticalAlignment(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_VerticalAlignment(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_Margin(struct struct_Microsoft_UI_Xaml_Thickness*) noexcept = 0;
    virtual int32_t __stdcall put_Margin(struct struct_Microsoft_UI_Xaml_Thickness) noexcept = 0;
    virtual int32_t __stdcall get_Name(void**) noexcept = 0;
    virtual int32_t __stdcall put_Name(void*) noexcept = 0;
    virtual int32_t __stdcall get_BaseUri(void**) noexcept = 0;
    virtual int32_t __stdcall get_DataContext(void**) noexcept = 0;
    virtual int32_t __stdcall put_DataContext(void*) noexcept = 0;
    virtual int32_t __stdcall get_AllowFocusOnInteraction(bool*) noexcept = 0;
    virtual int32_t __stdcall put_AllowFocusOnInteraction(bool) noexcept = 0;
    virtual int32_t __stdcall get_FocusVisualMargin(struct struct_Microsoft_UI_Xaml_Thickness*) noexcept = 0;
    virtual int32_t __stdcall put_FocusVisualMargin(struct struct_Microsoft_UI_Xaml_Thickness) noexcept = 0;
    virtual int32_t __stdcall get_FocusVisualSecondaryThickness(struct struct_Microsoft_UI_Xaml_Thickness*) noexcept = 0;
    virtual int32_t __stdcall put_FocusVisualSecondaryThickness(struct struct_Microsoft_UI_Xaml_Thickness) noexcept = 0;
    virtual int32_t __stdcall get_FocusVisualPrimaryThickness(struct struct_Microsoft_UI_Xaml_Thickness*) noexcept = 0;
    virtual int32_t __stdcall put_FocusVisualPrimaryThickness(struct struct_Microsoft_UI_Xaml_Thickness) noexcept = 0;
    virtual int32_t __stdcall get_FocusVisualSecondaryBrush(void**) noexcept = 0;
    virtual int32_t __stdcall put_FocusVisualSecondaryBrush(void*) noexcept = 0;
    virtual int32_t __stdcall get_FocusVisualPrimaryBrush(void**) noexcept = 0;
    virtual int32_t __stdcall put_FocusVisualPrimaryBrush(void*) noexcept = 0;
    virtual int32_t __stdcall get_AllowFocusWhenDisabled(bool*) noexcept = 0;
    virtual int32_t __stdcall put_AllowFocusWhenDisabled(bool) noexcept = 0;
    virtual int32_t __stdcall get_Style(void**) noexcept = 0;
    virtual int32_t __stdcall put_Style(void*) noexcept = 0;
    virtual int32_t __stdcall get_Parent(void**) noexcept = 0;
    virtual int32_t __stdcall get_FlowDirection(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_FlowDirection(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_RequestedTheme(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_RequestedTheme(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_IsLoaded(bool*) noexcept = 0;
    virtual int32_t __stdcall get_ActualTheme(int32_t*) noexcept = 0;
    virtual int32_t __stdcall add_Loaded(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_Loaded(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_Unloaded(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_Unloaded(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_DataContextChanged(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_DataContextChanged(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_SizeChanged(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_SizeChanged(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_LayoutUpdated(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_LayoutUpdated(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_Loading(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_Loading(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_ActualThemeChanged(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_ActualThemeChanged(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall add_EffectiveViewportChanged(void*, winrt::event_token*) noexcept = 0;
    virtual int32_t __stdcall remove_EffectiveViewportChanged(winrt::event_token) noexcept = 0;
    virtual int32_t __stdcall FindName(void*, void**) noexcept = 0;
    virtual int32_t __stdcall SetBinding(void*, void*) noexcept = 0;
    virtual int32_t __stdcall GetBindingExpression(void*, void**) noexcept = 0;
};

struct Controls_IGrid : ::IInspectable {
    virtual int32_t __stdcall get_RowDefinitions(void**) noexcept = 0;
    virtual int32_t __stdcall get_ColumnDefinitions(void**) noexcept = 0;
    virtual int32_t __stdcall get_BackgroundSizing(int32_t*) noexcept = 0;
    virtual int32_t __stdcall put_BackgroundSizing(int32_t) noexcept = 0;
    virtual int32_t __stdcall get_BorderBrush(void**) noexcept = 0;
    virtual int32_t __stdcall put_BorderBrush(void*) noexcept = 0;
    virtual int32_t __stdcall get_BorderThickness(struct struct_Microsoft_UI_Xaml_Thickness*) noexcept = 0;
    virtual int32_t __stdcall put_BorderThickness(struct struct_Microsoft_UI_Xaml_Thickness) noexcept = 0;
    virtual int32_t __stdcall get_CornerRadius(struct struct_Microsoft_UI_Xaml_CornerRadius*) noexcept = 0;
    virtual int32_t __stdcall put_CornerRadius(struct struct_Microsoft_UI_Xaml_CornerRadius) noexcept = 0;
    virtual int32_t __stdcall get_Padding(struct struct_Microsoft_UI_Xaml_Thickness*) noexcept = 0;
    virtual int32_t __stdcall put_Padding(struct struct_Microsoft_UI_Xaml_Thickness) noexcept = 0;
    virtual int32_t __stdcall get_RowSpacing(double*) noexcept = 0;
    virtual int32_t __stdcall put_RowSpacing(double) noexcept = 0;
    virtual int32_t __stdcall get_ColumnSpacing(double*) noexcept = 0;
    virtual int32_t __stdcall put_ColumnSpacing(double) noexcept = 0;
};

struct IRowDefinition : ::IInspectable {
    virtual int32_t __stdcall get_Height(struct struct_Microsoft_UI_Xaml_GridLength*) noexcept = 0;
    virtual int32_t __stdcall put_Height(struct struct_Microsoft_UI_Xaml_GridLength) noexcept = 0;
    virtual int32_t __stdcall get_MaxHeight(double*) noexcept = 0;
    virtual int32_t __stdcall put_MaxHeight(double) noexcept = 0;
    virtual int32_t __stdcall get_MinHeight(double*) noexcept = 0;
    virtual int32_t __stdcall put_MinHeight(double) noexcept = 0;
    virtual int32_t __stdcall get_ActualHeight(double*) noexcept = 0;
};
// clang-format on

enum Visibility : int32_t {
    Visible = 0,
    Collapsed = 1,
};

}  // namespace WASDK
#pragma endregion  // WASDK

VS_FIXEDFILEINFO* GetModuleVersionInfo(HMODULE hModule, UINT* puPtrLen) {
    void* pFixedFileInfo = nullptr;
    UINT uPtrLen = 0;

    HRSRC hResource =
        FindResource(hModule, MAKEINTRESOURCE(VS_VERSION_INFO), RT_VERSION);
    if (hResource) {
        HGLOBAL hGlobal = LoadResource(hModule, hResource);
        if (hGlobal) {
            void* pData = LockResource(hGlobal);
            if (pData) {
                if (!VerQueryValue(pData, L"\\", &pFixedFileInfo, &uPtrLen) ||
                    uPtrLen == 0) {
                    pFixedFileInfo = nullptr;
                    uPtrLen = 0;
                }
            }
        }
    }

    if (puPtrLen) {
        *puPtrLen = uPtrLen;
    }

    return (VS_FIXEDFILEINFO*)pFixedFileInfo;
}

bool IsVersionAtLeast(HMODULE hModule,
                      WORD major,
                      WORD minor,
                      WORD build,
                      WORD qfe) {
    VS_FIXEDFILEINFO* fixedFileInfo = GetModuleVersionInfo(hModule, nullptr);
    if (!fixedFileInfo) {
        return false;
    }

    WORD moduleMajor = HIWORD(fixedFileInfo->dwFileVersionMS);
    WORD moduleMinor = LOWORD(fixedFileInfo->dwFileVersionMS);
    WORD moduleBuild = HIWORD(fixedFileInfo->dwFileVersionLS);
    WORD moduleQfe = LOWORD(fixedFileInfo->dwFileVersionLS);

    if (moduleMajor != major) {
        return moduleMajor > major;
    }

    if (moduleMinor != minor) {
        return moduleMinor > minor;
    }

    if (moduleBuild != build) {
        return moduleBuild > build;
    }

    return moduleQfe >= qfe;
}

bool IsExplorerVersionAtLeast(WORD major, WORD minor, WORD build, WORD qfe) {
    return IsVersionAtLeast(nullptr, major, minor, build, qfe);
}

bool IsFileExplorerExtensionsVersionAtLeast(WORD major,
                                            WORD minor,
                                            WORD build,
                                            WORD qfe) {
    HMODULE hModule = GetModuleHandle(L"FileExplorerExtensions.dll");
    if (!hModule) {
        return false;
    }

    return IsVersionAtLeast(hModule, major, minor, build, qfe);
}

std::optional<bool> IsOsFeatureEnabled(UINT32 featureId) {
    enum FEATURE_ENABLED_STATE {
        FEATURE_ENABLED_STATE_DEFAULT = 0,
        FEATURE_ENABLED_STATE_DISABLED = 1,
        FEATURE_ENABLED_STATE_ENABLED = 2,
    };

#pragma pack(push, 1)
    struct RTL_FEATURE_CONFIGURATION {
        unsigned int featureId;
        unsigned __int32 group : 4;
        FEATURE_ENABLED_STATE enabledState : 2;
        unsigned __int32 enabledStateOptions : 1;
        unsigned __int32 unused1 : 1;
        unsigned __int32 variant : 6;
        unsigned __int32 variantPayloadKind : 2;
        unsigned __int32 unused2 : 16;
        unsigned int payload;
    };
#pragma pack(pop)

    using RtlQueryFeatureConfiguration_t =
        int(NTAPI*)(UINT32, int, INT64*, RTL_FEATURE_CONFIGURATION*);
    static RtlQueryFeatureConfiguration_t pRtlQueryFeatureConfiguration = []() {
        HMODULE hNtDll = LoadLibraryW(L"ntdll.dll");
        return hNtDll ? (RtlQueryFeatureConfiguration_t)GetProcAddress(
                            hNtDll, "RtlQueryFeatureConfiguration")
                      : nullptr;
    }();

    if (!pRtlQueryFeatureConfiguration) {
        Wh_Log(L"RtlQueryFeatureConfiguration not found");
        return std::nullopt;
    }

    RTL_FEATURE_CONFIGURATION feature = {0};
    INT64 changeStamp = 0;
    HRESULT hr =
        pRtlQueryFeatureConfiguration(featureId, 1, &changeStamp, &feature);
    if (SUCCEEDED(hr)) {
        Wh_Log(L"RtlQueryFeatureConfiguration result for %u: %d", featureId,
               feature.enabledState);

        switch (feature.enabledState) {
            case FEATURE_ENABLED_STATE_DISABLED:
                return false;
            case FEATURE_ENABLED_STATE_ENABLED:
                return true;
            case FEATURE_ENABLED_STATE_DEFAULT:
                return std::nullopt;
        }
    } else {
        Wh_Log(L"RtlQueryFeatureConfiguration error for %u: %08X", featureId,
               hr);
    }

    return std::nullopt;
}

bool HandleNavigationBarControl(IUnknown* navigationBarControl) {
    winrt::com_ptr<WASDK::IUIElement> uiElement;
    (*(IUnknown**)((BYTE*)navigationBarControl + 0x08))
        ->QueryInterface(WASDK::IID_IUIElement, uiElement.put_void());
    if (!uiElement) {
        return false;
    }

    uiElement->put_Visibility(WASDK::Visibility::Collapsed);

    winrt::com_ptr<WASDK::IFrameworkElement> frameworkElement;
    uiElement->QueryInterface(WASDK::IID_IFrameworkElement,
                              frameworkElement.put_void());
    if (!frameworkElement) {
        return false;
    }

    winrt::com_ptr<::IInspectable> parent;
    frameworkElement->get_Parent(parent.put_void());
    if (!parent) {
        return false;
    }

    winrt::com_ptr<WASDK::Controls_IGrid> grid;
    parent->QueryInterface(WASDK::IID_Controls_IGrid, grid.put_void());
    if (!grid) {
        return false;
    }

    winrt::com_ptr<winrt::impl::abi<winrt::Windows::Foundation::Collections::
                                        IVector<WASDK::IRowDefinition*>>::type>
        rowDefinitions;
    grid->get_RowDefinitions(rowDefinitions.put_void());
    if (!rowDefinitions) {
        return false;
    }

    winrt::com_ptr<WASDK::IRowDefinition> rowDefinition;
    rowDefinitions->GetAt(1, rowDefinition.put());
    if (!rowDefinition) {
        return false;
    }

    rowDefinition->put_MaxHeight(0);
    return true;
}

using XamlIslandViewAdapter_get_DesiredSizeInPhysicalPixels_t =
    HRESULT(WINAPI*)(PVOID pThis, SIZE* size);
XamlIslandViewAdapter_get_DesiredSizeInPhysicalPixels_t
    XamlIslandViewAdapter_get_DesiredSizeInPhysicalPixels_Original;
HRESULT WINAPI
XamlIslandViewAdapter_get_DesiredSizeInPhysicalPixels_Hook(PVOID pThis,
                                                           SIZE* size) {
    Wh_Log(L">");

    HRESULT ret =
        XamlIslandViewAdapter_get_DesiredSizeInPhysicalPixels_Original(pThis,
                                                                       size);

    if (SUCCEEDED(ret) &&
        g_settings.explorerStyle == ExplorerStyle::classicNavigationBar) {
        int originalCy = size->cy;
        size->cy = MulDiv(size->cy, 90, 136);
        Wh_Log(L"%d -> %d", originalCy, size->cy);
    }

    return ret;
}

using Feature_NavigationBarControl_OnApplyTemplate_t =
    HRESULT(WINAPI*)(PVOID pThis);
Feature_NavigationBarControl_OnApplyTemplate_t
    Feature_NavigationBarControl_OnApplyTemplate_Original;
HRESULT WINAPI Feature_NavigationBarControl_OnApplyTemplate_Hook(PVOID pThis) {
    Wh_Log(L">");

    if (g_settings.explorerStyle == ExplorerStyle::classicNavigationBar) {
        static size_t offset =
            IsFileExplorerExtensionsVersionAtLeast(2125, 4200, 50, 0) ? 0x40
                                                                      : 0x08;

        HandleNavigationBarControl(*(IUnknown**)((BYTE*)pThis + offset));
    }

    return Feature_NavigationBarControl_OnApplyTemplate_Original(pThis);
}

using CommandBarExtension_GetHeight_t =
    int(WINAPI*)(PVOID pThis,
                 const winrt::Windows::Foundation::Size* sizeIn,
                 winrt::Windows::Foundation::Size* sizeOut);
CommandBarExtension_GetHeight_t CommandBarExtension_GetHeight_Original;
int WINAPI CommandBarExtension_GetHeight_Hook(
    PVOID pThis,
    const winrt::Windows::Foundation::Size* sizeIn,
    winrt::Windows::Foundation::Size* sizeOut) {
    Wh_Log(L">");

    int ret = CommandBarExtension_GetHeight_Original(pThis, sizeIn, sizeOut);

    if (g_settings.explorerStyle == ExplorerStyle::classicNavigationBar) {
        static const float newHeight =
            IsExplorerVersionAtLeast(10, 0, 22621, 3958) ? 0 : 6;
        sizeOut->Height = newHeight;
    }

    return ret;
}

using CanShowModernNavBar_t = bool(WINAPI*)(PVOID pThis);
CanShowModernNavBar_t CanShowModernNavBar_Original;
bool WINAPI CanShowModernNavBar_Hook(PVOID pThis) {
    Wh_Log(L">");

    if (g_settings.explorerStyle == ExplorerStyle::classicNavigationBar) {
        return false;
    }

    return CanShowModernNavBar_Original(pThis);
}

using CachedExplorerExtensionState_IsModernNavBarAvailable_t =
    bool(WINAPI*)(PVOID pThis);
CachedExplorerExtensionState_IsModernNavBarAvailable_t
    CachedExplorerExtensionState_IsModernNavBarAvailable_Original;
bool WINAPI
CachedExplorerExtensionState_IsModernNavBarAvailable_Hook(PVOID pThis) {
    Wh_Log(L">");

    if (g_settings.explorerStyle == ExplorerStyle::classicNavigationBar) {
        return false;
    }

    return CachedExplorerExtensionState_IsModernNavBarAvailable_Original(pThis);
}

using CoCreateInstance_t = decltype(&CoCreateInstance);
CoCreateInstance_t CoCreateInstance_Original;
HRESULT WINAPI CoCreateInstance_Hook(REFCLSID rclsid,
                                     LPUNKNOWN pUnkOuter,
                                     DWORD dwClsContext,
                                     REFIID riid,
                                     LPVOID* ppv) {
    constexpr winrt::guid CLSID_XamlIslandViewAdapter{
        0x6480100B,
        0x5A83,
        0x4D1E,
        {0x9F, 0x69, 0x8A, 0xE5, 0xA8, 0x8E, 0x9A, 0x33}};

    if (IsEqualCLSID(rclsid, CLSID_XamlIslandViewAdapter) &&
        g_settings.explorerStyle == ExplorerStyle::classicRibbonUI) {
        Wh_Log(L">");

        return REGDB_E_CLASSNOTREG;
    }

    return CoCreateInstance_Original(rclsid, pUnkOuter, dwClsContext, riid,
                                     ppv);
}

bool HookExplorerFrameSymbols() {
    HMODULE module = LoadLibraryEx(L"explorerframe.dll", nullptr,
                                   LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module) {
        Wh_Log(L"Couldn't load explorerframe.dll");
        return false;
    }

    WindhawkUtils::SYMBOL_HOOK explorerFrameDllHooks[] = {
        {
            {LR"(bool __cdecl CanShowModernNavBar(void))"},
            &CanShowModernNavBar_Original,
            CanShowModernNavBar_Hook,
            true,  // Before Win11 24H2.
        },
        {
            {LR"(public: static bool __cdecl CachedExplorerExtensionState::IsModernNavBarAvailable(void))"},
            &CachedExplorerExtensionState_IsModernNavBarAvailable_Original,
            CachedExplorerExtensionState_IsModernNavBarAvailable_Hook,
            true,  // Since Win11 24H2.
        },
    };

    if (!HookSymbols(module, explorerFrameDllHooks,
                     ARRAYSIZE(explorerFrameDllHooks))) {
        Wh_Log(L"HookSymbols failed");
        return false;
    }

    return true;
}

bool HookWindowsUIFileExplorerSymbols() {
    if (IsExplorerVersionAtLeast(10, 0, 26100, 0)) {
        if (!IsExplorerVersionAtLeast(10, 0, 26100, 1591)) {
            return true;
        }
    } else if (IsExplorerVersionAtLeast(10, 0, 22621, 0)) {
        if (!IsExplorerVersionAtLeast(10, 0, 22621, 4111)) {
            return true;
        }
    } else {
        return true;
    }

    constexpr UINT kFileExplorerTabLineFix = 51960011;
    if (!IsOsFeatureEnabled(kFileExplorerTabLineFix).value_or(true)) {
        return true;
    }

    HMODULE module = LoadLibraryEx(L"Windows.UI.FileExplorer.dll", nullptr,
                                   LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module) {
        Wh_Log(L"Couldn't load Windows.UI.FileExplorer.dll");
        return false;
    }

    // Windows.UI.FileExplorer.dll
    WindhawkUtils::SYMBOL_HOOK hooks[] = {
        {
            {LR"(public: virtual long __cdecl XamlIslandViewAdapter::get_DesiredSizeInPhysicalPixels(struct tagSIZE *))"},
            &XamlIslandViewAdapter_get_DesiredSizeInPhysicalPixels_Original,
            XamlIslandViewAdapter_get_DesiredSizeInPhysicalPixels_Hook,
            true,
        },
    };

    if (!HookSymbols(module, hooks, ARRAYSIZE(hooks))) {
        Wh_Log(L"HookSymbols failed");
        return false;
    }

    return true;
}

bool HookFileExplorerExtensionsSymbols(HMODULE module) {
    WindhawkUtils::SYMBOL_HOOK fileExplorerExtensionsDllHooks[] = {
        {
            {LR"(public: void __cdecl winrt::FileExplorerExtensions::implementation::NavigationBarControl::OnApplyTemplate(void))"},
            &Feature_NavigationBarControl_OnApplyTemplate_Original,
            Feature_NavigationBarControl_OnApplyTemplate_Hook,
        },
        {
            {LR"(public: virtual int __cdecl winrt::impl::produce<struct winrt::FileExplorerExtensions::factory_implementation::CommandBarExtension,struct winrt::WindowsUdk::UI::Shell::IFileExplorerCommandBarExtensionStatics>::GetHeight(struct winrt::Windows::Foundation::Size,struct winrt::Windows::Foundation::Size *))"},
            &CommandBarExtension_GetHeight_Original,
            CommandBarExtension_GetHeight_Hook,
        },
    };

    if (!HookSymbols(module, fileExplorerExtensionsDllHooks,
                     ARRAYSIZE(fileExplorerExtensionsDllHooks))) {
        Wh_Log(L"HookSymbols failed");
        return false;
    }

    return true;
}

HMODULE GetFileExplorerExtensionsModuleHandle() {
    return GetModuleHandle(L"FileExplorerExtensions.dll");
}

void HandleLoadedModuleIfFileExplorerExtensions(HMODULE module,
                                                LPCWSTR lpLibFileName) {
    if (!g_fileExplorerExtensionsLoaded &&
        GetFileExplorerExtensionsModuleHandle() == module &&
        !g_fileExplorerExtensionsLoaded.exchange(true)) {
        Wh_Log(L"Loaded %s", lpLibFileName);

        if (HookFileExplorerExtensionsSymbols(module)) {
            Wh_ApplyHookOperations();
        }
    }
}

using LoadLibraryExW_t = decltype(&LoadLibraryExW);
LoadLibraryExW_t LoadLibraryExW_Original;
HMODULE WINAPI LoadLibraryExW_Hook(LPCWSTR lpLibFileName,
                                   HANDLE hFile,
                                   DWORD dwFlags) {
    HMODULE module = LoadLibraryExW_Original(lpLibFileName, hFile, dwFlags);
    if (module) {
        HandleLoadedModuleIfFileExplorerExtensions(module, lpLibFileName);
    }

    return module;
}

void LoadSettings() {
    PCWSTR explorerStyle = Wh_GetStringSetting(L"explorerStyle");
    g_settings.explorerStyle = ExplorerStyle::classicNavigationBar;
    if (wcscmp(explorerStyle, L"classicRibbonUI") == 0) {
        g_settings.explorerStyle = ExplorerStyle::classicRibbonUI;
    }
    Wh_FreeStringSetting(explorerStyle);
}

BOOL Wh_ModInit() {
    Wh_Log(L">");

    LoadSettings();

    if (!HookExplorerFrameSymbols()) {
        return FALSE;
    }

    if (!HookWindowsUIFileExplorerSymbols()) {
        return FALSE;
    }

    if (HMODULE fileExplorerExtensionsModule =
            GetFileExplorerExtensionsModuleHandle()) {
        g_fileExplorerExtensionsLoaded = true;
        if (!HookFileExplorerExtensionsSymbols(fileExplorerExtensionsModule)) {
            return FALSE;
        }
    } else {
        Wh_Log(L"File explorer extensions module not loaded yet");

        HMODULE kernelBaseModule = GetModuleHandle(L"kernelbase.dll");
        auto pKernelBaseLoadLibraryExW =
            (decltype(&LoadLibraryExW))GetProcAddress(kernelBaseModule,
                                                      "LoadLibraryExW");
        WindhawkUtils::Wh_SetFunctionHookT(pKernelBaseLoadLibraryExW,
                                           LoadLibraryExW_Hook,
                                           &LoadLibraryExW_Original);
    }

    WindhawkUtils::Wh_SetFunctionHookT(CoCreateInstance, CoCreateInstance_Hook,
                                       &CoCreateInstance_Original);

    return TRUE;
}

void Wh_ModAfterInit() {
    Wh_Log(L">");

    if (!g_fileExplorerExtensionsLoaded) {
        if (HMODULE fileExplorerExtensionsModule =
                GetFileExplorerExtensionsModuleHandle()) {
            if (!g_fileExplorerExtensionsLoaded.exchange(true)) {
                Wh_Log(L"Got FileExplorerExtensions.dll");

                if (HookFileExplorerExtensionsSymbols(
                        fileExplorerExtensionsModule)) {
                    Wh_ApplyHookOperations();
                }
            }
        }
    }
}

void Wh_ModUninit() {
    Wh_Log(L">");
}

void Wh_ModSettingsChanged() {
    Wh_Log(L">");

    LoadSettings();
}

}  // namespace ExplorerFrameClassic

// ============================================================
// ===== classic-explorer-treeview
// ============================================================
namespace ClassicExplorerTreeview {

#define GET_X_LPARAM(lp) ((int)(short)LOWORD(lp))
#define GET_Y_LPARAM(lp) ((int)(short)HIWORD(lp))

#define CSB_PTHIS_OFFSET 16
#define TV_MENUITEM_ID 2121420



// Mod settings
bool g_settingDrawDottedLines = true;
bool g_settingLinesAtRoot = false;
bool g_settingDrawButtons = true;
bool g_settingsGradientBackground = false;
bool g_settingsHotTracking = false;
WindhawkUtils::StringSetting g_settingLineColorOption;
WindhawkUtils::StringSetting g_settingFoldersPaneText;
int g_settingCloseButtonXOffset = 0;
int g_settingCloseButtonYOffset = 0;

int g_lineColorOptionInt = 2;
wchar_t g_defaultFoldersPaneText[32];
wchar_t g_menuTreeviewText[32];
wchar_t g_closeText[32];
wchar_t g_toolBandText[32];

std::vector<unsigned int> g_knownBrowserBandIds;

enum FEWExtraFlags
{
    MOUSE_OVER_BUTTON = 1 << 0,
    MOUSE_PRESSED = 1 << 1,
    MOUSE_TRACING = 1 << 2,
    COM_POINTERS = 1 << 3,
    TREEVIEW_VIS = 1 << 4
};

class FEWExtra // File Explorer Window Extra things
{
    Microsoft::WRL::ComPtr<IShellBrowser> pShellBrowser;
    Microsoft::WRL::ComPtr<IPropertyBag> pPropertyBag;
    // Microsoft::WRL::ComPtr<IWebBrowser2> pWebBrowser;

public:
    HWND hSTWC = nullptr; // ShellTabWindowClass
    HWND hCNS = nullptr;  // CtrlNotifySink
    HWND hNSTC = nullptr; // NamespaceTreeControl
    HWND hTV = nullptr;   // Treeview
    int eFlags = 0;
    void* csb = nullptr; // Ptr to 'this' of the CShellBrowser

    FEWExtra(HWND hS, IShellBrowser* psb)
    {
        hSTWC = hS;
        pShellBrowser = psb;
        csb = pShellBrowser.Get();
        csb = static_cast<char*>(csb) - CSB_PTHIS_OFFSET;
    }

    void populateCOMPointers()
    {
        static GUID SID_FrameManager =
        {
            0x31e4fa78,
            0x02b4,
            0x419f,
            {0x94, 0x30, 0x7b, 0x75, 0x85, 0x23, 0x7c, 0x77}
        };
        static GUID SID_PerBrowserPropertyBag =
        {
            0xa3b24a0a,
            0x7b68,
            0x448d,
            {0x99, 0x79, 0xc7, 0x00, 0x05, 0x9c, 0x3a, 0xd1}
        };
        /*static GUID SID_IWebBrowserApp =
        {
            0x0002df05,
            0x0000,
            0x0000, 
            {0xc0,0x00, 0x00,0x00,0x00,0x00,0x00,0x46}
        };*/

        Microsoft::WRL::ComPtr<IUnknown> frame;
        Microsoft::WRL::ComPtr<IServiceProvider> serviceProvider;
        pShellBrowser.As(&serviceProvider);
        serviceProvider->QueryService(SID_FrameManager, IID_PPV_ARGS(&frame));
        frame.As(&serviceProvider);
        serviceProvider->QueryService(SID_PerBrowserPropertyBag, IID_PPV_ARGS(&pPropertyBag));
        // serviceProvider->QueryService(SID_IWebBrowserApp, IID_PPV_ARGS(&pWebBrowser));

        eFlags |= COM_POINTERS;
    }

    void SetTreeviewVisible(bool visible)
    {
        if ((eFlags & COM_POINTERS) == 0)
        {
            populateCOMPointers();
        }
        VARIANT val;
        VariantInit(&val);
        val.vt = VT_BOOL;
        val.boolVal = visible ? VARIANT_TRUE : VARIANT_FALSE;
        pPropertyBag->Write(L"PageSpaceControlSizer_Visible", &val);
    }

    void ModifyToolbarMenu(HMENU hMenu)
    {
        // The menu entry disappears on navigation to a new folder, so we need to check
        // if it still exists.
        if (!hMenu) return;
        size_t itemIndex = GetMenuItemCount(hMenu);
        for (size_t i = 0; i < itemIndex; i++)
        {
            UINT itemID = GetMenuItemID(hMenu, i);
            if (itemID == TV_MENUITEM_ID)
            {
                CheckMenuItem(hMenu, TV_MENUITEM_ID, (eFlags & TREEVIEW_VIS) ? MF_CHECKED : MF_UNCHECKED);
                return;
            }
        }
        AppendMenu(hMenu, MF_STRING | ((eFlags & TREEVIEW_VIS) ? MF_CHECKED : MF_UNCHECKED), TV_MENUITEM_ID, g_menuTreeviewText);
    }
};

//Used to keep track of the extra data assigned to each file explorer window
std::vector<FEWExtra> g_FEWExtras;

// Euclidean color distance
double ColorDistance(DWORD color1, DWORD color2)
{
    int b1 = (color1 & 0xFF);
    int g1 = ((color1 >> 8) & 0xFF);
    int r1 = ((color1 >> 16) & 0xFF);

    int b2 = (color2 & 0xFF);
    int g2 = ((color2 >> 8) & 0xFF);
    int r2 = ((color2 >> 16) & 0xFF);

    return std::sqrt(std::pow(r2 - r1, 2) + std::pow(g2 - g1, 2) + std::pow(b2 - b1, 2));
}

void DrawExpandoButton(HWND hTree, HDC hdc, HTREEITEM hItem)
{
    RECT rect;
    TreeView_GetItemRect(hTree, hItem, &rect, TRUE);

    // Get system colors
    bool useHighlight = false;
    DWORD windowColor = GetSysColor(COLOR_WINDOW);
    DWORD shadowColor = GetSysColor(COLOR_3DSHADOW);
    DWORD highlightColor = GetSysColor(COLOR_3DHIGHLIGHT);

    // Check the line color option and set the useHighlight flag accordingly
    if (g_lineColorOptionInt == 1)
    {
        useHighlight = true;
    }
    else if (g_lineColorOptionInt == 2)
    {
        // Calculate the color distances
        double distanceShadow = ColorDistance(windowColor, shadowColor);
        double distanceHighlight = ColorDistance(windowColor, highlightColor);

        // Determine whether to use highlight based on color distances
        if (distanceHighlight > distanceShadow)
        {
            useHighlight = true;
        }
    }

    // Even though the item height should be 16, I'm accomodating some more heights
    UINT itemHeight = TreeView_GetItemHeight(hTree);
    switch(itemHeight)
    {
    default:
    case 16:
        rect.left -= 34;
        rect.top += 4;
        break;
    case 18:
        rect.left -= 33;
        rect.top += 6;
        break;
    }

    // Define a TVITEM struct to retrieve the number of children for the specified item
    TVITEM tvi;
    tvi.mask = TVIF_CHILDREN; // Specify that we are interested in the number of children
    tvi.hItem = hItem; // Set the handle of the tree view item

    // Check if the item is at the top level by comparing the left position of the rectangle
    // to either 10 or -10 based on the value of g_settingLinesAtRoot
    bool isTopLevel = rect.left <= (g_settingLinesAtRoot ? 10 : -10);

    // Check if the setting to draw buttons is enabled and the node is not a top-level node when lines at root is disabled
    // and the node has one or more children
    if (!(isTopLevel && !g_settingLinesAtRoot) && TreeView_GetItem(hTree, &tvi) && tvi.cChildren > 0)
    {
        // Get the state of the item
        UINT state = TreeView_GetItemState(hTree, hItem, TVIS_EXPANDED);

        // Create a solid brush with the window color and select it into the device context
        HBRUSH brush = CreateSolidBrush(windowColor);
        HBRUSH original = (HBRUSH)SelectObject(hdc, brush);

        // Define the rectangle for the button
        RECT buttonRect;
        buttonRect.left = rect.left;
        buttonRect.top = rect.top;
        buttonRect.right = rect.left + 9;
        buttonRect.bottom = rect.top + 9;

        // Fill the rectangle with the brush color and delete the brush
        FillRect(hdc, &buttonRect, brush);
        DeleteObject(brush);

        // Create a new brush with the highlight color if useHighlight is true, otherwise shadowColor
        brush = CreateSolidBrush(useHighlight ? highlightColor : shadowColor);

        // Draw a frame around the button rectangle with the new brush and delete the brush
        FrameRect(hdc, &buttonRect, brush);
        DeleteObject(brush);

        // Restore the original brush to the device context
        SelectObject(hdc, original);

        // Create a pen with a solid style and the button text color, and select it into the device context
        HPEN hPen = CreatePen(PS_SOLID, 1, GetSysColor(COLOR_BTNTEXT));
        HPEN hOldPen = (HPEN)SelectObject(hdc, hPen);

        // Draw a +/- symbol in the item's button based on its expanded state
        if (state & TVIS_EXPANDED)
        {
            MoveToEx(hdc, rect.left + 2, rect.top + 4, NULL);
            LineTo(hdc, rect.left + 7, rect.top + 4);
        }
        else
        {
            MoveToEx(hdc, rect.left + 2, rect.top + 4, NULL);
            LineTo(hdc, rect.left + 7, rect.top + 4);
            MoveToEx(hdc, rect.left + 4, rect.top + 2, NULL);
            LineTo(hdc, rect.left + 4, rect.top + 7);
        }

        // Restore the original pen to the device context and delete the pen
        SelectObject(hdc, hOldPen);
        DeleteObject(hPen);
    }
}

int GetThemedBandOffset()  // extremely retarded and only semi-accurate
{
    NONCLIENTMETRICS ncm;
    ncm.cbSize = sizeof(NONCLIENTMETRICS);
    SystemParametersInfo(SPI_GETNONCLIENTMETRICS, sizeof(NONCLIENTMETRICS),
                         &ncm, 0);
    int size = std::round(abs(ncm.lfMenuFont.lfHeight) / 1.21f - 1.21f);
    if (size < 7)
        size++;
    if (size > 16)
        size--;
    if (size > 11)
        size += (size - 11);
    size -= 8;
    return size;
}

void SetCloseButtonRect(RECT &rect)
{
    rect.left = rect.right - 24 + g_settingCloseButtonXOffset;
    rect.right -= 4 - g_settingCloseButtonXOffset;
    rect.bottom = rect.top + 19 + g_settingCloseButtonYOffset;
    rect.top += 2 + g_settingCloseButtonYOffset;
}

typedef void (*__cdecl CSBSetBrowserBarState_t)(void*, unsigned int, void*, int, void*);
CSBSetBrowserBarState_t CSBSetBrowserBarStateOriginal;
void __cdecl CSBSetBrowserBarStateHook(void* pThis, unsigned int var1, void* var2, int var3, void* var4)
{
    // This function gets called when a InfoBand is about to be shown or hidden.
    // var 3: -1 = toggle, 0 = off, 1 = on
    // We need to keep track of the band ids, so that they can be hidden when the mod treeview is shown.

    if(std::find(g_knownBrowserBandIds.begin(), g_knownBrowserBandIds.end(), var1) == g_knownBrowserBandIds.end())
    {
        g_knownBrowserBandIds.push_back(var1);
    }
    if(var3 == -1 || var3 == 1)
    {
        for(FEWExtra& f : g_FEWExtras)
        {
            if(f.csb == pThis)
            {
                f.SetTreeviewVisible(false);
                break;
            }
        }
    }

    CSBSetBrowserBarStateOriginal(pThis, var1, var2, var3, var4);
}

LRESULT CALLBACK CtrlNotSinkSubclassProc(_In_ HWND hWnd,
        _In_ UINT uMsg,
        _In_ WPARAM wParam,
        _In_ LPARAM lParam,
        _In_ DWORD_PTR dwRefData)
{
    if(uMsg == WM_SHOWWINDOW) //Mod treeview is hidden/shown
    {
        HWND stwc = GetParent(GetParent(GetParent(hWnd)));
        for(FEWExtra& f : g_FEWExtras)
        {
            if(f.hSTWC == stwc)
            {
                if(wParam) //wParam - bool for hide/show
                {
                    f.eFlags |= TREEVIEW_VIS;
                    // Hide every known browser band
                    for(unsigned int id : g_knownBrowserBandIds)
                        CSBSetBrowserBarStateHook(f.csb, id, NULL, 0, NULL);
                }
                else
                    f.eFlags &= ~TREEVIEW_VIS;
                break;
            }
        }
    }
    return DefSubclassProc(hWnd, uMsg, wParam, lParam);
}

LRESULT CALLBACK NTCSubclassProc(_In_ HWND hWnd,
                                 _In_ UINT uMsg,
                                 _In_ WPARAM wParam,
                                 _In_ LPARAM lParam,
                                 _In_ DWORD_PTR dwRefData)
{
    switch (uMsg)
    {
    case WM_NOTIFY:
    {
        if(!g_settingDrawButtons)
            break;

        LPNMHDR lpnmh = (LPNMHDR)lParam;
        switch (lpnmh->code)
        {
        case NM_CUSTOMDRAW: // Handle custom drawing notifications sent by the treeview control
        {
            HWND hTree = FindWindowEx(hWnd, NULL, L"SysTreeView32", NULL); // Find the treeview control
            LPNMTVCUSTOMDRAW pCustomDraw = (LPNMTVCUSTOMDRAW)lParam;
            if(pCustomDraw->nmcd.dwDrawStage == CDDS_PREPAINT)
            {
                return CDRF_NOTIFYITEMDRAW;
            }
            if(pCustomDraw->nmcd.dwDrawStage == CDDS_ITEMPREPAINT)
            {
                return CDRF_NOTIFYPOSTPAINT;
            }
            if(pCustomDraw->nmcd.dwDrawStage == CDDS_ITEMPOSTPAINT)
            {
                HTREEITEM hItem = reinterpret_cast<HTREEITEM>(pCustomDraw->nmcd.dwItemSpec);
                DrawExpandoButton(hTree, pCustomDraw->nmcd.hdc, hItem);
                return S_OK;
            }
        }
        break;
        case TVN_ITEMEXPANDED: //If a item is expanded, redraw the treeview to fix graphical issues
        {
            HWND hwndTreeView = lpnmh->hwndFrom;
            InvalidateRect(hwndTreeView, NULL, TRUE);
            return S_OK;
        }
        break;
        }
    }
    break;
    case WM_PAINT:
    {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);

        // Get the themed band offset and calculate the rectangle for the background, and draw it
        int themeBandOffset = GetThemedBandOffset();
        RECT rect;
        GetClientRect(hWnd, &rect);
        long origBottom = rect.bottom;

        HBRUSH brush = CreateSolidBrush(GetSysColor(COLOR_BTNFACE));
        HBRUSH original = (HBRUSH)SelectObject(hdc, brush);
        FillRect(hdc, &rect, brush);
        SelectObject(hdc, original);
        DeleteObject(brush);

        if(g_settingsGradientBackground)
        {
            HTHEME hThemeRebar = OpenThemeData(NULL, L"REBAR");
            if(hThemeRebar)
            {
                DrawThemeBackground(hThemeRebar, hdc, RP_BACKGROUND, 0, &rect, NULL);
                CloseThemeData(hThemeRebar);
            }
        }

        long origTop = rect.top;

        // Create and fill the top line of the rebar
        HBRUSH rebarLineTop = CreateSolidBrush(GetSysColor(COLOR_3DSHADOW));
        rect.top = origTop + 22 + themeBandOffset;
        rect.bottom = rect.top + 1;
        FillRect(hdc, &rect, rebarLineTop);
        DeleteObject(rebarLineTop);

        // Create and fill the bottom line of the rebar
        HBRUSH rebarLineBottom = CreateSolidBrush(GetSysColor(COLOR_3DHIGHLIGHT));
        rect.top += 1;
        rect.bottom += 1;
        FillRect(hdc, &rect, rebarLineBottom);
        DeleteObject(rebarLineBottom);

        long origLeft = rect.left;
        long origRight = rect.right;

        //Get flags for this NSTC
        int eFlags = 0;
        size_t s = g_FEWExtras.size();
        for (size_t i = 0; i < s; i++)
        {
            if (hWnd == g_FEWExtras[i].hNSTC)
            {
                eFlags = g_FEWExtras[i].eFlags;
                break;
            }
        }

        // If the mouse is over the button, draw the X button frame
        if (eFlags & MOUSE_OVER_BUTTON)
        {
            RECT buttonFrame;
            GetClientRect(hWnd, &buttonFrame);
            SetCloseButtonRect(buttonFrame);
            // If a theme is enabled, draw the theme correct button frame
            HTHEME hThemeToolbar = OpenThemeData(hWnd, L"TOOLBAR");
            if(hThemeToolbar)
            {
                DrawThemeBackground(hThemeToolbar, hdc, TP_BUTTON,  eFlags & MOUSE_PRESSED ? TS_PRESSED : TS_HOT, &buttonFrame, NULL);
                CloseThemeData(hThemeToolbar);
            }
            else
                DrawEdge(hdc, &buttonFrame,
                         eFlags & MOUSE_PRESSED ? BDR_SUNKENOUTER : BDR_RAISEDINNER,
                         BF_RECT);
        }

        // Create a brush for the close button
        HBRUSH closeColor = CreateSolidBrush(GetSysColor(COLOR_BTNTEXT));

        // draw the close button
        // ##    ##
        rect.top = origTop + 7 + g_settingCloseButtonYOffset;
        rect.left = origRight - 18 + g_settingCloseButtonXOffset;
        rect.bottom = rect.top + 1;
        rect.right = rect.left + 2;
        if (eFlags & MOUSE_OVER_BUTTON && eFlags & MOUSE_PRESSED)
        {
            rect.left += 1;
            rect.right += 1;
            rect.top += 1;
            rect.bottom += 1;
        }
        FillRect(hdc, &rect, closeColor);

        rect.left += 6;
        rect.right += 6;
        FillRect(hdc, &rect, closeColor);

        //  ##  ##
        rect.top += 1;
        rect.bottom += 1;
        rect.left -= 1;
        rect.right -= 1;
        FillRect(hdc, &rect, closeColor);

        rect.left -= 4;
        rect.right -= 4;
        FillRect(hdc, &rect, closeColor);

        //   ####
        rect.top += 1;
        rect.bottom += 1;
        rect.left += 1;
        rect.right += 3;
        FillRect(hdc, &rect, closeColor);

        //    ##
        rect.top += 1;
        rect.bottom += 1;
        rect.left += 1;
        rect.right -= 1;
        FillRect(hdc, &rect, closeColor);

        // reset and draw last three lines in reverse cause easier math
        // ##    ##
        rect.top = origTop + 13 + g_settingCloseButtonYOffset;
        rect.left = origRight - 18 + g_settingCloseButtonXOffset;
        rect.bottom = rect.top + 1;
        rect.right = rect.left + 2;
        if (eFlags & MOUSE_OVER_BUTTON && eFlags & MOUSE_PRESSED)
        {
            rect.left += 1;
            rect.right += 1;
            rect.top += 1;
            rect.bottom += 1;
        }
        FillRect(hdc, &rect, closeColor);

        rect.left += 6;
        rect.right += 6;
        FillRect(hdc, &rect, closeColor);

        //  ##  ##
        rect.top -= 1;
        rect.bottom -= 1;
        rect.left -= 1;
        rect.right -= 1;
        FillRect(hdc, &rect, closeColor);

        rect.left -= 4;
        rect.right -= 4;
        FillRect(hdc, &rect, closeColor);

        //   ####
        rect.top -= 1;
        rect.bottom -= 1;
        rect.left += 1;
        rect.right += 3;
        FillRect(hdc, &rect, closeColor);

        DeleteObject(closeColor);

        rect.top = origTop;
        rect.bottom = origBottom;
        rect.left = origLeft;
        rect.right = origRight;

        SetTextColor(hdc, GetSysColor(COLOR_BTNTEXT));
        SetBkColor(hdc, GetSysColor(COLOR_BTNFACE));

        if(!g_settingsGradientBackground)
        {
            //Draw the etched edge around the NSTC
            DrawEdge(hdc, &rect, EDGE_ETCHED, BF_RECT);
        }

        SelectObject(hdc, original);

        // Get the font and draw the folder pane text
        NONCLIENTMETRICS ncm;
        ncm.cbSize = sizeof(NONCLIENTMETRICS);
        SystemParametersInfo(SPI_GETNONCLIENTMETRICS, 0, &ncm, 0);

        HFONT hFont = CreateFontIndirect(&ncm.lfMenuFont);
        HFONT hFontOrig = (HFONT)SelectObject(hdc, hFont);
        SetTextColor(hdc, GetSysColor(COLOR_BTNTEXT));

        PCWSTR foldersPaneText = g_settingFoldersPaneText.get();
        unsigned int foldersPaneTextLength;
        SetBkMode(hdc, TRANSPARENT);
        if (lstrcmpW(foldersPaneText, L"default") == 0)
        {
            foldersPaneTextLength = wcslen(g_defaultFoldersPaneText);
            TextOut(hdc, 8, 5, g_defaultFoldersPaneText,
                    foldersPaneTextLength);
        }
        else
        {
            foldersPaneTextLength = wcslen(foldersPaneText);
            TextOut(hdc, 8, 5, foldersPaneText, foldersPaneTextLength);
        }

        SelectObject(hdc, hFontOrig);
        DeleteObject(hFont);
        EndPaint(hWnd, &ps);
    }
    break;
    case WM_SETCURSOR:
    {
        //Set the cursor to the default cursor, because this window does not handle this message by default
        //so sometimes the wrong cursor would be displayed
        SetCursor(LoadCursor(NULL, IDC_ARROW));
        return TRUE;
    }
    break;
    case WM_MOUSEMOVE:
    {
        // Get the x and y coordinates of the mouse
        int xPos = GET_X_LPARAM(lParam);
        int yPos = GET_Y_LPARAM(lParam);

        RECT rect;
        GetClientRect(hWnd, &rect);

        // Set the rect to the X button bounds
        SetCloseButtonRect(rect);

        // Check if the mouse is inside the rectangle
        bool mouseInside = false;
        if (xPos >= rect.left && xPos <= rect.right && yPos >= rect.top &&
                yPos <= rect.bottom)
        {
            mouseInside = true;
        }

        // Iterate through the list of subclassed NSTCs
        size_t s = g_FEWExtras.size();
        for (size_t i = 0; i < s; i++)
        {
            // Check if the current window handle matches the one in the list
            if (hWnd == g_FEWExtras[i].hNSTC)
            {
                // If mouse is inside, set the flag, else clear it. Redraw the window
                if (mouseInside)
                {
                    InvalidateRect(hWnd, &rect, FALSE);
                    g_FEWExtras[i].eFlags |= MOUSE_OVER_BUTTON;
                }
                else if (g_FEWExtras[i].eFlags & MOUSE_OVER_BUTTON)
                {
                    g_FEWExtras[i].eFlags &= ~MOUSE_OVER_BUTTON;
                    InvalidateRect(hWnd, &rect, FALSE);
                }
                // If the mouse is not being traced, trace it so that we know when it leaves the window
                // so that we can stop drawing the raised button edge
                if (!(g_FEWExtras[i].eFlags & MOUSE_TRACING))
                {
                    g_FEWExtras[i].eFlags |= MOUSE_TRACING;
                    TRACKMOUSEEVENT tme{};
                    tme.cbSize = sizeof(TRACKMOUSEEVENT);
                    tme.dwFlags = TME_LEAVE;
                    tme.hwndTrack = hWnd;
                    TrackMouseEvent(&tme);
                }
                break;
            }
        }
    }
    break;
    case WM_LBUTTONDOWN: // If the left mouse button is pressed, set the flag and redraw
    {
        size_t s = g_FEWExtras.size();
        for (size_t i = 0; i < s; i++)
        {
            if (hWnd == g_FEWExtras[i].hNSTC)
            {
                RECT rect;
                GetClientRect(hWnd, &rect);
                SetCloseButtonRect(rect);
                InvalidateRect(hWnd, &rect, FALSE);
                g_FEWExtras[i].eFlags |= MOUSE_PRESSED;
                break;
            }
        }
    }
    break;
    case WM_MOUSELEAVE: //If the mouse leaves the window, clear the flag and redraw so that the raised frame disappears
    {
        size_t s = g_FEWExtras.size();
        for (size_t i = 0; i < s; i++)
        {
            if (hWnd == g_FEWExtras[i].hNSTC)
            {
                RECT rect;
                GetClientRect(hWnd, &rect);
                SetCloseButtonRect(rect);
                g_FEWExtras[i].eFlags &= ~MOUSE_PRESSED;
                g_FEWExtras[i].eFlags &= ~MOUSE_TRACING;
                g_FEWExtras[i].eFlags &= ~MOUSE_OVER_BUTTON;
                InvalidateRect(hWnd, &rect, FALSE);
                break;
            }
        }
    }
    break;
    case WM_LBUTTONUP:
    {
        // Iterate through all subclassed NSTC windows
        size_t s = g_FEWExtras.size();
        //size_t i = 0;
        for (size_t i = 0; i < s; i++)
        {
            // Check if the current window matches and the mouse is pressed
            if (hWnd == g_FEWExtras[i].hNSTC && g_FEWExtras[i].eFlags & MOUSE_PRESSED)
            {
                // Reset the mouse pressed flag
                g_FEWExtras[i].eFlags &= ~MOUSE_PRESSED;
                break;
            }
        }

        int xPos = GET_X_LPARAM(lParam);
        int yPos = GET_Y_LPARAM(lParam);
        RECT rect;
        GetClientRect(hWnd, &rect);
        SetCloseButtonRect(rect);

        // Check if the mouse click is within the button rectangle
        if (xPos >= rect.left && xPos <= rect.right && yPos >= rect.top && yPos <= rect.bottom)
        {
            for (size_t i = 0; i < s; i++)
            {
                if (hWnd == g_FEWExtras[i].hNSTC)
                {
                    // Remove the flag so that the button edge won't be drawn after the treeview is enabled again
                    g_FEWExtras[i].eFlags &= ~MOUSE_OVER_BUTTON;
                    g_FEWExtras[i].SetTreeviewVisible(false);
                    break;
                }
            }
        }
    }
    break;
    case WM_RBUTTONUP:
    {
        // Open info band context menu
        POINT p;
	    p.x = GET_X_LPARAM(lParam);
	    p.y = GET_Y_LPARAM(lParam);
	    ClientToScreen(hWnd, &p);

        static std::wstring menuItem = L"";
        if(menuItem == L"")
        {
            menuItem += g_closeText;
            menuItem += L" ";
            menuItem += g_toolBandText;
        }

        HMENU hMenu = CreatePopupMenu();
        AppendMenuW(hMenu, MF_STRING, 1, menuItem.c_str());
        int sel = TrackPopupMenu(hMenu, TPM_RETURNCMD, p.x, p.y, 0, hWnd, NULL);
	    DestroyMenu(hMenu);

        if(sel == 1) // Close the treeview
        {
            for (size_t i = 0; i < g_FEWExtras.size(); i++)
            {
                if (hWnd == g_FEWExtras[i].hNSTC)
                {
                    g_FEWExtras[i].SetTreeviewVisible(false);
                    break;
                }
            }
        }
    }
    break;
    case WM_SIZE:
    {
        // Static variable to track if resizing is in progress
        static bool resizing = false;
        if (!resizing) // If not currently resizing
        {
            resizing = true; // Set resizing flag to true
            RECT rect; // Create a RECT struct to hold window dimensions

            // Get the parent window of the current window
            HWND ctrlNotSink = GetParent(hWnd);
            GetWindowRect(ctrlNotSink, &rect); // Get the screen coordinates of the parent window
            MapWindowPoints(NULL, GetParent(ctrlNotSink), (POINT*)&rect, 2); // Map the screen coordinates to client coordinates
            int ctrlNotSinkXOffset = rect.left; // Get the x offset of the parent window
            int ctrlNotSinkYOffset = rect.top; // Get the y offset of the parent window
            GetClientRect(ctrlNotSink, &rect); // Get the client area dimensions of the parent window

            // Resize the parent window to fit the client area
            SetWindowPos(
                ctrlNotSink, 0, 0, ctrlNotSinkYOffset, rect.right + ctrlNotSinkXOffset + 1,
                rect.bottom,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSENDCHANGING);

            // Resize the current window to fit the client area of the parent window
            GetClientRect(ctrlNotSink, &rect); // Get the client area dimensions of the parent window
            SetWindowPos(hWnd, 0, 0, 0, rect.right, rect.bottom,
                         SWP_NOZORDER | SWP_NOACTIVATE);

            // Find the treeview window within the current window
            HWND treeview = FindWindowEx(hWnd, NULL, L"SysTreeView32", NULL);
            GetClientRect(hWnd, &rect); // Get the client area dimensions of the current window

            // Modify the style of the treeview to remove the client edge
            LONG lStyle = GetWindowLong(treeview, GWL_EXSTYLE);
            lStyle &= ~WS_EX_CLIENTEDGE;
            SetWindowLong(treeview, GWL_EXSTYLE, lStyle);

            // Calculate and set the position and size of the treeview window
            int themedBandOffset = GetThemedBandOffset(); // Get themed band offset
            SetWindowPos(treeview, 0, 2, 24 + themedBandOffset,
                         rect.right - 4, rect.bottom - 26 - themedBandOffset,
                         SWP_NOZORDER | SWP_NOSENDCHANGING);

            // Redraw the parent window, current window, and treeview window
            InvalidateRect(ctrlNotSink, NULL, true);
            InvalidateRect(hWnd, NULL, true);
            InvalidateRect(treeview, NULL, true);

            resizing = false; // Set resizing flag back to false
        }
        return S_OK;
    }
    break;

    case WM_DESTROY: // Remove the entry in the global vector
        g_FEWExtras.erase(std::remove_if(
                              g_FEWExtras.begin(), g_FEWExtras.end(),
                              [hWnd](FEWExtra ne)
        {
            return ne.hNSTC == hWnd;
        }));
        return 0;
        break;
    }

    return DefSubclassProc(hWnd, uMsg, wParam, lParam);
}

LRESULT CALLBACK TVSubclassProc(_In_ HWND hWnd,
                                _In_ UINT uMsg,
                                _In_ WPARAM wParam,
                                _In_ LPARAM lParam,
                                _In_ DWORD_PTR dwRefData)
{
    if (uMsg == WM_SETCURSOR)
    {
        SetCursor(LoadCursor(NULL, IDC_ARROW)); //Remove hand cursor
        return S_OK;
    }
    else if(uMsg == TV_FIRST+74) //Remove top margin
    {
        wParam = 0;
    }
    else if(uMsg == TVM_SETINDENT) //Set full indent
    {
        wParam = 19;
    }
    else if(uMsg == TVM_SETITEMHEIGHT) //Set item height to the accurate value
    {
        wParam = 16;
    }
    else if (uMsg == TVM_INSERTITEM)
    {
        //Ensure that iIntegral is set to 1 for every item to achieve accurate item height
        LPTVINSERTSTRUCT lpis = (LPTVINSERTSTRUCT)lParam;
        lpis->itemex.iIntegral = 1;
    }
    else if (uMsg == TVM_SETITEM) // Quick access item workaround
    {
        LPTVITEMEXW lptvi = (LPTVITEMEXW)lParam;
        if (lptvi->mask & TVIF_INTEGRAL)
        {
            lptvi->iIntegral = 1;
        }
    }
    else if(uMsg == WM_SYSCOLORCHANGE && g_lineColorOptionInt == 2)
    {
        //If the automatic line color setting is enabled, new best color needs to be set
        DWORD windowColor = GetSysColor(COLOR_WINDOW);
        DWORD shadowColor = GetSysColor(COLOR_3DSHADOW);
        DWORD highlightColor = GetSysColor(COLOR_3DHIGHLIGHT);

        // Calculate the color distances
        double distanceShadow = ColorDistance(windowColor, shadowColor);
        double distanceHighlight = ColorDistance(windowColor, highlightColor);

        TreeView_SetLineColor(hWnd, distanceHighlight > distanceShadow ? highlightColor : shadowColor);
    }
    return DefSubclassProc(hWnd, uMsg, wParam, lParam);
}

typedef HWND (*__cdecl NSCCreateTreeview_t)(void*, HWND);
NSCCreateTreeview_t NSCCreateTreeviewOriginal;
HWND __cdecl NSCCreateTreeviewHook(void* pThis, HWND hWnd)
{
    // Get the original member function to create the treeview so that it can be modified
    HWND treeview = NSCCreateTreeviewOriginal(pThis, hWnd);

    // Apply the modifications only if the treeview is created in file explorer window proper
    wchar_t root[20];
    HWND stwc = GetParent(GetParent(GetParent(GetParent(hWnd))));
    GetClassName(stwc, root, 20);
    if (lstrcmpW(root, L"ShellTabWindowClass") == 0)
    {
        if (WindhawkUtils::SetWindowSubclassFromAnyThread(hWnd, NTCSubclassProc,
                NULL))
        {
            WindhawkUtils::SetWindowSubclassFromAnyThread(GetParent(hWnd), CtrlNotSinkSubclassProc, NULL);
            WindhawkUtils::SetWindowSubclassFromAnyThread(treeview, TVSubclassProc, NULL);
            for(FEWExtra& f : g_FEWExtras)
            {
                if(f.hSTWC == stwc)
                {
                    f.hCNS = GetParent(hWnd);
                    f.hNSTC = hWnd;
                    f.hTV = treeview;
                    break;
                }
            }

            // Set the style of the treeview
            DWORD dwStyle = TVS_HASBUTTONS | TVS_EDITLABELS |
                            TVS_SHOWSELALWAYS | WS_TABSTOP | WS_CLIPCHILDREN |
                            WS_CLIPSIBLINGS | WS_VISIBLE | WS_CHILD;
            if (g_settingLinesAtRoot)
                dwStyle |= TVS_LINESATROOT;
            if(g_settingDrawDottedLines)
                dwStyle |= TVS_HASLINES;
            if(g_settingsHotTracking)
                dwStyle |= TVS_TRACKSELECT;

            SetWindowLongPtrW(treeview, GWL_STYLE, dwStyle);

            TreeView_SetIndent(treeview, 20);
            TreeView_SetItemHeight(treeview, 16);

            // Set dotted line color. Shadow color is default
            DWORD highlightColor = GetSysColor(COLOR_3DHIGHLIGHT);
            if(g_lineColorOptionInt == 1) //highlight color
            {
                TreeView_SetLineColor(treeview, highlightColor);
            }
            else if(g_lineColorOptionInt == 2) //automatic color
            {
                DWORD windowColor = GetSysColor(COLOR_WINDOW);
                DWORD shadowColor = GetSysColor(COLOR_3DSHADOW);

                // Calculate the color distances
                double distanceShadow = ColorDistance(windowColor, shadowColor);
                double distanceHighlight = ColorDistance(windowColor, highlightColor);

                TreeView_SetLineColor(treeview, distanceHighlight > distanceShadow ? highlightColor : shadowColor);
            }
            // Set the extended style to bring back the classic tooltip
            DWORD exStyle = TreeView_GetExtendedStyle(treeview);
            exStyle &= ~TVS_EX_RICHTOOLTIP;
            TreeView_SetExtendedStyle(treeview, exStyle, TVS_EX_RICHTOOLTIP);
        }
    }

    return treeview;
}

// Remove pin icons
typedef HRESULT (*__cdecl NSCSetStateImageList_t)(struct _IMAGELIST*);
NSCSetStateImageList_t NSCASetStateImageListOriginal;
HRESULT __cdecl NSCSetStateImageListHook(struct _IMAGELIST* himagelist)
{
    return S_OK;
}

typedef void (*__cdecl CSBAddBrowserBarMenuItems_t)(void*, HMENU);
CSBAddBrowserBarMenuItems_t CSBAddBrowserBarMenuItemsOriginal;
void __cdecl CSBAddBrowserBarMenuItemsHook(void* pThis, HMENU hMenu)
{
    // This gets called when CShellBrowser populates the View menu.
    // If no menu items are added by this function, hook or original,
    // the submenu disappears.
    // There is a small bug that happens when the original function adds
    // exactly one item: the submenu label is singular, even though there
    // are two entries - one added by the original function, and one by
    // this hook.
    CSBAddBrowserBarMenuItemsOriginal(pThis, hMenu);
    for(FEWExtra &f : g_FEWExtras)
    {
        if(f.csb == pThis)
        {
            f.ModifyToolbarMenu(hMenu);
            break;
        }
    }
}

typedef HRESULT (*__cdecl CSBOnViewCommand_t)(void*, unsigned long, long);
CSBOnViewCommand_t CSBOnViewCommandOriginal;
HRESULT __cdecl CSBOnViewCommandHook(void* pThis, unsigned long a, long b)
{
    // This processes commands from the View menu, including the command of
    // the added menu item.

    if(a == TV_MENUITEM_ID)
    {
        for(FEWExtra& f : g_FEWExtras)
        {
            if(f.csb == pThis)
            {
                // Switch mod treeview visibility
                f.SetTreeviewVisible((f.eFlags & TREEVIEW_VIS) == 0);
                break;
            }
        }
        return S_OK;
    }

    return CSBOnViewCommandOriginal(pThis, a, b);
}

typedef HRESULT (*__cdecl FileCabinet_CreateViewWindow2_t)(IShellBrowser*, void*, IShellView*, IShellView*, void*, HWND*);
FileCabinet_CreateViewWindow2_t FileCabinet_CreateViewWindow2Original;
HRESULT __cdecl FileCabinet_CreateViewWindow2Hook(IShellBrowser* psb, void* var1, IShellView* psv1, IShellView* psv2, void* var2, HWND* hWnd)
{
    // This gets called on the creation of a file explorer window.
    // We get the COM interfaces from here, it's far more reliable than
    // the undocumented message used earlier.

    HRESULT hRes = FileCabinet_CreateViewWindow2Original(psb, var1, psv1, psv2, var2, hWnd);
    HWND stwc = GetParent(*hWnd); //?????
    g_FEWExtras.push_back(FEWExtra(stwc, psb));
    return hRes;
}

BOOL Wh_ModInit()
{
    Wh_Log(L"Classic Explorer Treeview Init");

    HMODULE hExplorerFrame = LoadLibraryW(L"explorerframe.dll");

    if (!hExplorerFrame)
    {
        Wh_Log(L"Failed to load explorerframe.dll");
        return FALSE;
    }

    // Define the symbol hooks for required member functions
    WindhawkUtils::SYMBOL_HOOK explorerframe_dll_hooks[] =
    {
        {   {
                L"private: struct HWND__ * __cdecl CNscTree::_CreateTreeview(struct HWND__ *)"
            },
            (void**)&NSCCreateTreeviewOriginal,
            (void*)NSCCreateTreeviewHook,
            FALSE
        },
        // This one is optional because it doesn't exist on Win7
        {   {
                L"public: virtual long __cdecl CNscTree::SetStateImageList(struct _IMAGELIST *)"
            },
            (void**)&NSCASetStateImageListOriginal,
            (void*)NSCSetStateImageListHook,
            TRUE
        },
        {   {
                L"long __cdecl FileCabinet_CreateViewWindow2(struct IShellBrowser *,struct tagFolderSetDataBase *,struct IShellView *,struct IShellView *,struct tagRECT *,struct HWND__ * *)"
            },
            (void**)&FileCabinet_CreateViewWindow2Original,
            (void*)FileCabinet_CreateViewWindow2Hook,
            FALSE
        },
        {   {
                L"private: void __cdecl CShellBrowser::_SetBrowserBarState(unsigned int,struct _GUID const *,int,struct _ITEMIDLIST_ABSOLUTE const *)"
            },
            (void**)&CSBSetBrowserBarStateOriginal,
            (void*)CSBSetBrowserBarStateHook,
            FALSE
        },
        {   {
                L"private: void __cdecl CShellBrowser::_AddBrowserBarMenuItems(struct HMENU__ *)"
            },
            (void**)&CSBAddBrowserBarMenuItemsOriginal,
            (void*)CSBAddBrowserBarMenuItemsHook,
            FALSE
        },
        {   {
                L"private: __int64 __cdecl CShellBrowser::_OnCommand(unsigned __int64,__int64)"
            },
            (void**)&CSBOnViewCommandOriginal,
            (void*)CSBOnViewCommandHook,
            FALSE
        }
    };
    // Hook the symbols in explorerframe.dll, return FALSE if any of the symbols cannot be hooked
    if (!WindhawkUtils::HookSymbols(hExplorerFrame, explorerframe_dll_hooks, 6))
    {
        Wh_Log(L"Failed to hook one or more member functions in ExplorerFrame.dll");
        return FALSE;
    }

    // Load mod settings
    g_settingDrawDottedLines = Wh_GetIntSetting(L"DrawLines");
    g_settingLinesAtRoot = Wh_GetIntSetting(L"LinesAtRoot");
    g_settingDrawButtons = Wh_GetIntSetting(L"DrawButtons");
    g_settingsGradientBackground = Wh_GetIntSetting(L"GradientBackground");
    g_settingsHotTracking = Wh_GetIntSetting(L"HotTracking");
    g_settingLineColorOption =
        WindhawkUtils::StringSetting::make(L"AlternateLineColor");
    g_settingFoldersPaneText =
        WindhawkUtils::StringSetting::make(L"FoldersText");
    g_settingCloseButtonXOffset = Wh_GetIntSetting(L"CloseButtonXOffset");
    g_settingCloseButtonYOffset = Wh_GetIntSetting(L"CloseButtonYOffset");

    // Set the line color option based on the string setting
    g_lineColorOptionInt = 0;
    if (wcscmp(g_settingLineColorOption.get(), L"true") == 0)
    {
        g_lineColorOptionInt = 1;
    }
    else if (wcscmp(g_settingLineColorOption.get(), L"Automatic") == 0)
    {
        g_lineColorOptionInt = 2;
    }

    //Load the applicable localized texts from ieframe
    HMODULE hIeFrame = LoadLibraryW(L"ieframe.dll");
    if(hIeFrame)
    {
        if (wcscmp(g_settingFoldersPaneText.get(), L"default") == 0)
        {
            if (LoadStringW(hIeFrame, 12919, g_defaultFoldersPaneText, 32) == 0)
            {
                Wh_Log(L"Unable to load localized text resource: ieframe 12919");
                std::wstring def = L"Folders";
                def.copy(g_defaultFoldersPaneText, 32);
            }
        }
        if (LoadStringW(hIeFrame, 3010, g_menuTreeviewText, 32) == 0)
        {
            Wh_Log(L"Unable to load localized text resource: ieframe 3010");
            std::wstring def = L"Treeview";
            def.copy(g_menuTreeviewText, 32);
        }
        if (LoadStringW(hIeFrame, 41298, g_toolBandText, 32) == 0)
        {
            Wh_Log(L"Unable to load localized text resource: ieframe 41298");
            std::wstring def = L"toolbar";
            def.copy(g_toolBandText, 32);
        }
        if (LoadStringW(hIeFrame, 12719, g_closeText, 32) == 0)
        {
            Wh_Log(L"Unable to load localized text resource: ieframe 12719");
            std::wstring def = L"Close";
            def.copy(g_closeText, 32);
        }
        FreeLibrary(hIeFrame);
    }

    Wh_Log(L"Classic Explorer Treeview init completed successfully.");
    return TRUE;
}


void Wh_ModUninit()
{
    Wh_Log(L"Classic Explorer Treeview uninit");
    size_t s = g_FEWExtras.size();
    Wh_Log(L"Removing subclasses from %u controls.", s);
    for (size_t i = 0; i < s; i++) // Loop through the subclassed controls
    {
        if(g_FEWExtras[i].hCNS == nullptr) continue; //if this is null then all are.
        // Remove subclasses
        WindhawkUtils::RemoveWindowSubclassFromAnyThread(g_FEWExtras[i].hCNS, CtrlNotSinkSubclassProc);
        WindhawkUtils::RemoveWindowSubclassFromAnyThread(g_FEWExtras[i].hNSTC, NTCSubclassProc);
        WindhawkUtils::RemoveWindowSubclassFromAnyThread(g_FEWExtras[i].hTV, TVSubclassProc);
    }
    Wh_Log(L"Classic Explorer Treeview uninit completed successfully.");
}

void Wh_ModSettingsChanged()
{
    g_settingDrawDottedLines = Wh_GetIntSetting(L"DrawLines");
    g_settingLinesAtRoot = Wh_GetIntSetting(L"LinesAtRoot");
    g_settingDrawButtons = Wh_GetIntSetting(L"DrawButtons");
    g_settingsGradientBackground = Wh_GetIntSetting(L"GradientBackground");
    g_settingsHotTracking = Wh_GetIntSetting(L"HotTracking");
    g_settingLineColorOption =
        WindhawkUtils::StringSetting::make(L"AlternateLineColor");
    g_settingFoldersPaneText =
        WindhawkUtils::StringSetting::make(L"FoldersText");
    g_settingCloseButtonXOffset = Wh_GetIntSetting(L"CloseButtonXOffset");
    g_settingCloseButtonYOffset = Wh_GetIntSetting(L"CloseButtonYOffset");

    // Set the line color option based on the string setting
    g_lineColorOptionInt = 0;
    if (wcscmp(g_settingLineColorOption.get(), L"true") == 0)
    {
        g_lineColorOptionInt = 1;
    }
    else if (wcscmp(g_settingLineColorOption.get(), L"Automatic") == 0)
    {
        g_lineColorOptionInt = 2;
    }
}

}  // namespace ClassicExplorerTreeview
#undef CSB_PTHIS_OFFSET
#undef TV_MENUITEM_ID

// ============================================================
// ===== classic-theme-explorer-lite
// ============================================================
namespace ClassicThemeExplorerLite {

using CreateWindowExW_t = decltype(&CreateWindowExW);
CreateWindowExW_t CreateWindowExW_Orig;
HWND WINAPI CreateWindowExW_Hook(DWORD dwExStyle,LPCWSTR lpClassName,LPCWSTR lpWindowName,DWORD dwStyle,int X,int Y,int nWidth,int nHeight,HWND hWndParent,HMENU hMenu,HINSTANCE hInstance,LPVOID lpParam) {
    wchar_t wszClassName[200];
    ZeroMemory(wszClassName, 200);
    if ((((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"TrayNotifyWnd"))
    {
        dwExStyle |= WS_EX_STATICEDGE;
    }
    if ((((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"NotifyIconOverflowWindow"))
    {
        dwExStyle |= WS_EX_STATICEDGE;
    }

//  Disable this block if you don't want 3D borders in folders
    if ((((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"SysListView32"))
    {
        GetClassNameW(hWndParent, wszClassName, 200);
        if (!wcscmp(wszClassName, L"SHELLDLL_DefView"))
        {
            GetClassNameW(GetParent(hWndParent), wszClassName, 200);
            if (wcscmp(wszClassName, L"Progman"))
            {
                dwExStyle |= WS_EX_CLIENTEDGE;
            }
        }
    }

    if ( (((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"ReBarWindow32"))
    {
        GetClassNameW(hWndParent, wszClassName, 200);
        if (!wcscmp(wszClassName, L"Shell_TrayWnd"))
        {
            dwStyle |= RBS_BANDBORDERS;
        }
    }

    HWND hWnd = CreateWindowExW_Orig(dwExStyle,lpClassName,lpWindowName,dwStyle,X,Y,nWidth,nHeight,hWndParent,hMenu,hInstance,lpParam);

    return hWnd;
}
using SetWindowLongPtrW_t = decltype(&SetWindowLongPtrW);
SetWindowLongPtrW_t SetWindowLongPtrW_Orig;
LONG_PTR SetWindowLongPtrW_Hook(HWND hWnd, int nIndex, LONG_PTR dwNewLong) {
    WCHAR lpClassName[200];
    ZeroMemory(lpClassName, 200);
    GetClassNameW(hWnd, lpClassName, 200);
    HWND hWndParent = GetParent(hWnd);

    if ( (((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"TrayNotifyWnd"))
    {
        if (nIndex == GWL_EXSTYLE)
        {
            dwNewLong |= WS_EX_STATICEDGE;
        }
    }
    if ( (((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"NotifyIconOverflowWindow"))
    {
        if (nIndex == GWL_EXSTYLE)
        {
            dwNewLong |= WS_EX_STATICEDGE;
        }
    }

    if ( (((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"ReBarWindow32"))
    {
        wchar_t wszClassName[200];
        ZeroMemory(wszClassName, 200);
        GetClassNameW(hWndParent, wszClassName, 200);
        if (!wcscmp(wszClassName, L"Shell_TrayWnd"))
        {
            if (nIndex == GWL_STYLE)
            {
                dwNewLong |= RBS_BANDBORDERS;
            }
        }
    }

    return SetWindowLongPtrW_Orig(hWnd, nIndex, dwNewLong);
}

HTHEME(*pOriginalOpenThemeDataForDpi)(HWND hWnd, LPCWSTR pszClassList, UINT dpi);
HTHEME OpenThemeDataForDpiHook(HWND hWnd, LPCWSTR pszClassList, UINT dpi)
{
    if ( (*((WORD*)&(pszClassList)+1)) && !wcscmp(pszClassList, L"Taskband2")) {
        return (HTHEME)0xDEADBEEF;
    } else if ( (*((WORD*)&(pszClassList)+1)) && !wcscmp(pszClassList, L"TrayNotifyFlyout")) {
        return (HTHEME)0xDEADBEFF;
    }

    return pOriginalOpenThemeDataForDpi(hWnd, pszClassList, dpi);
}

HRESULT(*pOriginalGetThemeMetric)(HTHEME hTheme, HDC hdc, int iPartId, int iStateId, int iPropId, int* piVal);
HRESULT GetThemeMetricHook(HTHEME hTheme, HDC hdc, int iPartId, int iStateId, int iPropId, int* piVal) {

    if (hTheme == (HTHEME)0xDEADBEFF && iPropId == TMT_WIDTH && iPartId == 3 && iStateId == 0)
    {
        *piVal = GetSystemMetrics(SM_CXICON);
    }
    else if (hTheme == (HTHEME)0xDEADBEFF && iPropId == TMT_HEIGHT && iPartId == 3 && iStateId == 0)
    {
        *piVal = GetSystemMetrics(SM_CYICON);
    }
    return S_OK;
}


HRESULT(*pOriginalGetThemeMargins)(HTHEME hTheme, HDC hdc, int iPartId, int iStateId, int iPropId, LPCRECT prc, MARGINS* pMargins);
HRESULT GetThemeMarginsHook(HTHEME hTheme, HDC hdc, int iPartId, int iStateId, int iPropId, LPCRECT prc, MARGINS* pMargins) {

    HRESULT hr = S_OK;
    if (hTheme)
    {
        hr = pOriginalGetThemeMargins(
            hTheme,
            hdc,
            iPartId,
            iStateId,
            iPropId,
            prc,
            pMargins
        );
    }

    if (hTheme == (HTHEME)0xDEADBEEF && iPropId == TMT_CONTENTMARGINS && iPartId == 5 && iStateId == 1) {
        // task list button measurements
        pMargins->cxLeftWidth = 4;
        pMargins->cyTopHeight = 3;
        pMargins->cxRightWidth = 4;
        pMargins->cyBottomHeight = 3;
    } else if (hTheme == (HTHEME)0xDEADBEEF && iPropId == TMT_CONTENTMARGINS && iPartId == 1 && iStateId == 0) {
        // task list measurements
        pMargins->cxLeftWidth = 0;
        pMargins->cyTopHeight = 0;
        pMargins->cxRightWidth = 4;
        pMargins->cyBottomHeight = 0;
    } else if (hTheme == (HTHEME)0xDEADBEEF && iPropId == TMT_SIZINGMARGINS && iPartId == 5 && iStateId == 1) {
        pMargins->cxLeftWidth = 0;
        pMargins->cyTopHeight = 10;
        pMargins->cxRightWidth = 0;
        pMargins->cyBottomHeight = 10;
    } else if (hTheme == (HTHEME)0xDEADBEFF && iPropId == TMT_CONTENTMARGINS && iPartId == 3 && iStateId == 0) {
        pMargins->cxLeftWidth = 4; // GetSystemMetrics(SM_CXICONSPACING);
        pMargins->cyTopHeight = 4; // GetSystemMetrics(SM_CYICONSPACING);
        pMargins->cxRightWidth = 4; //GetSystemMetrics(SM_CXICONSPACING);
        pMargins->cyBottomHeight = 4; // GetSystemMetrics(SM_CYICONSPACING);
    }

    HWND hShell_TrayWnd = FindWindowEx(NULL, NULL, L"Shell_TrayWnd", NULL);
    if (hShell_TrayWnd) {
        LONG dwStyle = 0;
        dwStyle = GetWindowLongW(hShell_TrayWnd, GWL_STYLE);
        dwStyle |= WS_DLGFRAME;
        SetWindowLongW(hShell_TrayWnd, GWL_STYLE, dwStyle);
        dwStyle &= ~WS_DLGFRAME;
        SetWindowLongW(hShell_TrayWnd, GWL_STYLE, dwStyle);
    }

    HWND hWnd = NULL;
    do {
        hWnd = FindWindowEx(
            NULL,
            hWnd,
            L"Shell_SecondaryTrayWnd",
            NULL
        );
        if (hWnd) {
            LONG dwStyle = 0;
            dwStyle = GetWindowLongW(hWnd, GWL_STYLE);
            dwStyle |= WS_DLGFRAME;
            SetWindowLongW(hWnd, GWL_STYLE, dwStyle);
            dwStyle &= ~WS_DLGFRAME;
            SetWindowLongW(hWnd, GWL_STYLE, dwStyle);
        }
    } while (hWnd);

    return S_OK;
}

HRESULT(*pOriginalDrawThemeTextEx)(HTHEME hTheme, HDC hdc, int iPartId, int iStateId, LPCWSTR pszText, int cchText, DWORD dwTextFlags, LPRECT pRect, const DTTOPTS* pOptions);
HRESULT DrawThemeTextExHook(HTHEME hTheme, HDC hdc, int iPartId, int iStateId, LPCWSTR pszText, int cchText, DWORD dwTextFlags, LPRECT pRect, const DTTOPTS* pOptions) {

    COLORREF bc = GetBkColor(hdc);
    COLORREF fc = GetTextColor(hdc);
    int mode = SetBkMode(hdc, TRANSPARENT);

        wchar_t text[200];
    GetWindowTextW(GetForegroundWindow(), text, 200);

    BOOL bIsActiveUnhovered = (iPartId == 5 && iStateId == 5);
    BOOL bIsInactiveUnhovered = (iPartId == 5 && iStateId == 1);
    BOOL bIsInactiveHovered = (iPartId == 5 && iStateId == 2);
    BOOL bIsActiveHovered = bIsInactiveHovered && !wcscmp(text, pszText);

    SetTextColor(hdc, GetSysColor(COLOR_BTNTEXT));

    NONCLIENTMETRICSW ncm;
    ncm.cbSize = sizeof(NONCLIENTMETRICSW);
    SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(NONCLIENTMETRICSW), &ncm, 0);

    HFONT hFont = NULL;
    if (bIsActiveUnhovered || bIsActiveHovered)
    {
        ncm.lfCaptionFont.lfWeight = FW_BOLD;
    }
    else
    {
        ncm.lfCaptionFont.lfWeight = FW_NORMAL;
    }
    hFont = CreateFontIndirectW(&(ncm.lfCaptionFont));

    if (iPartId == 5 && iStateId == 0) // clock
    {
        pRect->top += 2;
    }

    HGDIOBJ hOldFont = SelectObject(hdc, hFont);
    DrawTextW(
        hdc,
        pszText,
        cchText, 
        pRect,
        dwTextFlags
    );
    SelectObject(hdc, hOldFont);
    DeleteObject(hFont);
    SetBkColor(hdc, bc);
    SetTextColor(hdc, fc);
    SetBkMode(hdc, mode);

    return S_OK;
}

HRESULT(*pOriginalDrawThemeBackground)(HTHEME hTheme, HDC hdc, int iPartId, int iStateId, LPRECT pRect, LPCRECT pClipRect);
HRESULT DrawThemeBackgroundHook(HTHEME hTheme, HDC hdc, int iPartId, int iStateId, LPRECT pRect, LPCRECT pClipRect) {
    if (TRUE) {
        if (iPartId == 4 && iStateId == 1) {
            COLORREF bc = GetBkColor(hdc);
            COLORREF fc = GetTextColor(hdc);
            int mode = SetBkMode(hdc, TRANSPARENT);

            SetTextColor(hdc, GetSysColor(COLOR_BTNTEXT));

            NONCLIENTMETRICSW ncm;
            ncm.cbSize = sizeof(NONCLIENTMETRICSW);
            SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(NONCLIENTMETRICSW), &ncm, 0);

            HFONT hFont = CreateFontIndirectW(&(ncm.lfCaptionFont));

            HGDIOBJ hOldFont = SelectObject(hdc, hFont);
            DWORD dwTextFlags = DT_SINGLELINE | DT_CENTER | DT_VCENTER;
            RECT rc = *pRect;
            rc.bottom -= 7;
            DrawTextW(
                hdc,
                L"\u2026",
                -1, 
                &rc,
                dwTextFlags
            );
            SelectObject(hdc, hOldFont);
            DeleteObject(hFont);
            SetBkColor(hdc, bc);
            SetTextColor(hdc, fc);
            SetBkMode(hdc, mode);
        }
        return S_OK;
    }

    return pOriginalDrawThemeBackground(hTheme, hdc, iPartId, iStateId, pRect, pClipRect);
}

BOOL Wh_ModInit() {

    HMODULE hUxtheme = GetModuleHandle(L"uxtheme.dll");

    Wh_SetFunctionHook((void*)GetProcAddress(hUxtheme, "OpenThemeDataForDpi"), (void*)OpenThemeDataForDpiHook, (void**)&pOriginalOpenThemeDataForDpi);
    
    Wh_SetFunctionHook((void*)GetProcAddress(hUxtheme, "GetThemeMetric"), (void*)GetThemeMetricHook, (void**)&pOriginalGetThemeMetric);
    
    Wh_SetFunctionHook((void*)GetProcAddress(hUxtheme, "GetThemeMargins"), (void*)GetThemeMarginsHook, (void**)&pOriginalGetThemeMargins);

    Wh_SetFunctionHook((void*)GetProcAddress(hUxtheme, "DrawThemeTextEx"), (void*)DrawThemeTextExHook, (void**)&pOriginalDrawThemeTextEx);

    Wh_SetFunctionHook((void*)GetProcAddress(hUxtheme, "DrawThemeBackground"), (void*)DrawThemeBackgroundHook, (void**)&pOriginalDrawThemeBackground);

    Wh_SetFunctionHook((void*)CreateWindowExW,
                       (void*)CreateWindowExW_Hook,
                       (void**)&CreateWindowExW_Orig);
    Wh_SetFunctionHook((void*)SetWindowLongPtrW,
                       (void*)SetWindowLongPtrW_Hook,
                       (void**)&SetWindowLongPtrW_Orig);

    return TRUE;
}

}  // namespace ClassicThemeExplorerLite

// ============================================================
// ===== classic-taskbar-buttons-lite-vs-without-spacing
// ============================================================
namespace ClassicTaskbarButtonsLite {

typedef struct tagBUTTONRENDERINFOSTATES {
    char data[12];
} BUTTONRENDERINFOSTATES, *PBUTTONRENDERINFOSTATES;

/* Remove clock hover effect */
typedef void (*__cdecl GDIHelpers_FillRectARGB_t)(HDC, LPCRECT, BYTE, DWORD, bool);
GDIHelpers_FillRectARGB_t GDIHelpers_FillRectARGB_orig;
void __cdecl GDIHelpers_FillRectARGB_hook(
    HDC     hDC,
    LPCRECT lprc,
    BYTE    btUnknown,
    DWORD   dwUnknown,
    bool    bUnknown
)
{
    return;
}

/* Draw taskbar item */
typedef void (*__cdecl CTaskBtnGroup__DrawBar_t)(void *, HDC, void *, PBUTTONRENDERINFOSTATES);
CTaskBtnGroup__DrawBar_t CTaskBtnGroup__DrawBar_orig;
void __cdecl CTaskBtnGroup__DrawBar_hook(
    void *pThis,
    HDC   hDC,
    void *pRenderInfo,
    PBUTTONRENDERINFOSTATES pRenderStates
)
{
    LPRECT lprcDest = (LPRECT)((char *)pRenderInfo + 4);

    HTHEME hTheme = OpenThemeData(NULL, L"BUTTON");

    if (hTheme) {
        int iStateId = PBS_NORMAL; 

        if (pRenderStates->data[2]) {

            iStateId = PBS_PRESSED; // or use PBS_HOT if you prefer

        } else if (pRenderStates->data[4]) {

            iStateId = PBS_PRESSED;

        }

        // Draw the button with the current theme.

        DrawThemeBackground(hTheme, hDC, BP_PUSHBUTTON, iStateId, lprcDest, NULL);


        // Close the theme data handle when done.

        CloseThemeData(hTheme);
    } else
    {
        // Fallback to non-themed drawing if themes are not available.

        UINT uState = DFCS_BUTTONPUSH;
        if (pRenderStates->data[2])
        {
            uState |= DFCS_CHECKED;
        }
        else if (pRenderStates->data[4])
        {
            uState |= DFCS_PUSHED;
        }

        DrawFrameControl(hDC, lprcDest, DFC_BUTTON, uState);
    };


    /* If button is pushed in, offset the rect for the icon and text draw */
    if (pRenderStates->data[2]
    ||  pRenderStates->data[4])
    {
        lprcDest->top++;
        lprcDest->bottom++;
        lprcDest->left++;
        lprcDest->right++;
    }

    return;
}

BOOL Wh_ModInit(void)
{
    HMODULE hExplorer = GetModuleHandleW(NULL);

    WindhawkUtils::SYMBOL_HOOK hooks[] = {
        {
            {
                L"void __cdecl GDIHelpers::FillRectARGB(struct HDC__ *,struct tagRECT const *,unsigned char,unsigned long,bool)"
            },
            &GDIHelpers_FillRectARGB_orig,
            GDIHelpers_FillRectARGB_hook,
            FALSE
        },
        {
            {
                L"private: void __cdecl CTaskBtnGroup::_DrawBar(struct HDC__ *,struct BUTTONRENDERINFO const &,struct BUTTONRENDERINFOSTATES const &)"
            },
            &CTaskBtnGroup__DrawBar_orig,
            CTaskBtnGroup__DrawBar_hook,
            FALSE
        }
    };

    if (!WindhawkUtils::HookSymbols(hExplorer, hooks, ARRAYSIZE(hooks)))
    {
        Wh_Log(L"Failed to hook one or more functions");
        return FALSE;
    }

    return TRUE;
}

}  // namespace ClassicTaskbarButtonsLite

// ============================================================
// ===== classic-taskdlg-fix
// ============================================================
namespace ClassicTaskdlgFix {

/* Calling conventions */
#ifdef _WIN64
#   define THISCALL  __cdecl
#   define STHISCALL L"__cdecl"
#else
#   define THISCALL  __thiscall
#   define STHISCALL L"__thiscall"
#endif

/* Only available in Windows 10 1607 and up. */ 
typedef UINT (WINAPI *GetSystemDpiForProcess_t)(HANDLE);
GetSystemDpiForProcess_t GetSystemDpiForProcess;

typedef LPSIZE (* THISCALL DirectUI_CCPushButton_GetContentSize_t)(void *, LPSIZE, int, void *, HDC);
DirectUI_CCPushButton_GetContentSize_t DirectUI_CCPushButton_GetContentSize_orig;
LPSIZE THISCALL DirectUI_CCPushButton_GetContentSize_hook(
    void   *pThis,
    LPSIZE  psz,
    int     i1,
    void   *pSurface,
    HDC     hDC       /* Not actually a real device context :/ */
)
{
    /* Get original metrics */
    DirectUI_CCPushButton_GetContentSize_orig(
        pThis, psz, i1, pSurface, hDC
    );

    int dpi;
    if (GetSystemDpiForProcess)
    {
        dpi = GetSystemDpiForProcess(GetCurrentProcess());
    }
    else
    {
        dpi = 96;
    }

    psz->cy += MulDiv(7, dpi, 96);

    return psz;
}

#ifdef _WIN64
#   define PATHCACHE_VALNAME L"last-comctl32-v6-path"
#else
#   define PATHCACHE_VALNAME L"last-comctl32-v6-path-wow64"
#endif

#define COMCTL_582_SEARCH    L"microsoft.windows.common-controls_6595b64144ccf1df_5.82"

/* Load the ComCtl32 module */
HMODULE LoadComCtlModule(void)
{
    HMODULE hComCtl = LoadLibraryW(L"comctl32.dll");
    if (!hComCtl)
    {
        return NULL;
    }

    WCHAR szPath[MAX_PATH];
    GetModuleFileNameW(hComCtl, szPath, MAX_PATH);

    WCHAR szv6Path[MAX_PATH];
    BOOL bNoCache = FALSE;
    if (!Wh_GetStringValue(PATHCACHE_VALNAME, szv6Path, MAX_PATH))
    {
        bNoCache = TRUE;
    }

    /**
      * the !bNoCache check here is nested because we only want to fall through
      * to the cacher if the current comctl32 path is NOT 5.82.
      */
    if (wcsstr(szPath, COMCTL_582_SEARCH)
    || wcsstr(szPath, L"\\Windows\\System32")
    || wcsstr(szPath, L"\\Windows\\SysWOW64"))
    {
        if (!bNoCache)
        {
            hComCtl = LoadLibraryW(szv6Path);
        }
    }
    else if (bNoCache || wcsicmp(szPath, szv6Path))
    {
        Wh_SetStringValue(PATHCACHE_VALNAME, szPath);
    }

    return hComCtl;
}

BOOL Wh_ModInit(void)
{
    HMODULE hComCtl32 = LoadComCtlModule();
    if (!hComCtl32)
    {
        Wh_Log(L"Failed to load comctl32.dll");
        return FALSE;
    }

    HMODULE hUser32 = LoadLibraryW(L"user32.dll");
    if (hUser32)
    {
        GetSystemDpiForProcess = (GetSystemDpiForProcess_t)GetProcAddress(hUser32, "GetSystemDpiForProcess");
    }

    WindhawkUtils::SYMBOL_HOOK hook = {
        {
            L"public: virtual struct tagSIZE "
            STHISCALL
            L" DirectUI::CCPushButton::GetContentSize(int,int,class DirectUI::Surface *)"
        },
        &DirectUI_CCPushButton_GetContentSize_orig,
        DirectUI_CCPushButton_GetContentSize_hook,
        false
    };

    if (!HookSymbols(hComCtl32, &hook, 1))
    {
        Wh_Log(L"Failed to hook DirectUI::CCPushButton::GetContentSize");
        return FALSE;
    }

    return TRUE;
}

}  // namespace ClassicTaskdlgFix
#undef THISCALL
#undef STHISCALL
#undef PATHCACHE_VALNAME
#undef COMCTL_582_SEARCH

// ============================================================
// ===== classic-theme-transparency-fix
// ============================================================
namespace ClassicThemeTransparencyFix {

typedef HRESULT (WINAPI *DwmIsCompositionEnabled_t)(BOOL *);
DwmIsCompositionEnabled_t DwmIsCompositionEnabled_orig;
HRESULT WINAPI DwmIsCompositionEnabled_hook(BOOL *pfEnabled)
{
    *pfEnabled = FALSE;
    return S_OK;
}

typedef BOOL (WINAPI *IsCompositionActive_t)(void);
IsCompositionActive_t IsCompositionActive_orig;
BOOL WINAPI IsCompositionActive_hook()
{
    return FALSE;
}

BOOL Wh_ModInit()
{
    HMODULE dwmapiModule = LoadLibraryExW(L"dwmapi.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    FARPROC pFunction = GetProcAddress(dwmapiModule, "DwmIsCompositionEnabled");
    WindhawkUtils::Wh_SetFunctionHookT((void*)pFunction, (void*)DwmIsCompositionEnabled_hook, (void**)&DwmIsCompositionEnabled_orig);
    HMODULE uxthemeModule = LoadLibraryExW(L"uxtheme.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    pFunction = GetProcAddress(uxthemeModule, "IsCompositionActive");
    WindhawkUtils::Wh_SetFunctionHookT((void*)pFunction, (void*)IsCompositionActive_hook, (void**)&IsCompositionActive_orig);
    return TRUE;
}

}  // namespace ClassicThemeTransparencyFix

// ============================================================
// ===== clientedge-in-apps
// ============================================================
namespace ClientedgeInApps {

using CreateWindowExW_t = decltype(&CreateWindowExW);
CreateWindowExW_t CreateWindowExW_Orig;
HWND WINAPI CreateWindowExW_Hook(DWORD dwExStyle,LPCWSTR lpClassName,LPCWSTR lpWindowName,
DWORD dwStyle,int X,int Y,int nWidth,int nHeight,HWND hWndParent,HMENU hMenu,HINSTANCE hInstance,LPVOID lpParam) {

    WCHAR wszClassName[256];
    ZeroMemory(wszClassName, 256);

    // Explorer and XP-like File Picker

    if ((((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"SysListView32")) {
        GetClassNameW(hWndParent, wszClassName, 256);
        if (!wcscmp(wszClassName, L"SHELLDLL_DefView")) {
            GetClassNameW(GetParent(hWndParent), wszClassName, 256);
            if (wcscmp(wszClassName, L"Progman")) {
                dwExStyle |= WS_EX_CLIENTEDGE;
            }
        }
    }

    // Classic Notepad

    if ((((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"Edit")) {
        GetClassNameW(hWndParent, wszClassName, 256);
        if (!wcscmp(wszClassName, L"Notepad")) {
            dwExStyle |= WS_EX_CLIENTEDGE;
        }
    }

    // Internet Explorer

    if ((((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"Shell DocObject View")) {
        GetClassNameW(hWndParent, wszClassName, 256);
        if (!wcscmp(wszClassName, L"TabWindowClass")) {
            dwExStyle |= WS_EX_CLIENTEDGE;
        }
    }

    // Wolfram Mathematica

    if ((((ULONG_PTR)lpClassName & ~(ULONG_PTR)0xffff) != 0) && !wcscmp(lpClassName, L"NotebookContent")) {
        GetClassNameW(hWndParent, wszClassName, 256);
        if (!wcscmp(wszClassName, L"NotebookFrame")) {
            DWORD_PTR dwParentExStyle = GetWindowLongPtrW(hWndParent, GWL_EXSTYLE);
            if (!(dwParentExStyle & WS_EX_TOOLWINDOW)) {
                dwExStyle |= WS_EX_CLIENTEDGE;
            }
        }
    }

    return CreateWindowExW_Orig(dwExStyle,lpClassName,lpWindowName,dwStyle,X,Y,nWidth,nHeight,hWndParent,hMenu,hInstance,lpParam);
}

BOOL Wh_ModInit(void)
{
        Wh_SetFunctionHook((void*)CreateWindowExW, (void*)CreateWindowExW_Hook, (void**)&CreateWindowExW_Orig);

    return TRUE;
}

}  // namespace ClientedgeInApps

// ============================================================
// ===== classic-maximized-windows-fix
// ============================================================
namespace ClassicMaximizedWindowsFix {

CRITICAL_SECTION g_criticalSection;
std::vector<HWND> g_affectedWindows;
std::vector<HWND> g_fakeUndoWindows;

// === DPI HELPERS === //
// These are only available in Windows 10, version 1607 and newer.
unsigned int (WINAPI *g_pGetDpiForWindow)(HWND);
int (WINAPI *g_pGetSystemMetricsForDpi)(int, unsigned int);

/*
 * GetSystemMetricsForWindow: Get the system metrics for a given window.
 *
 * This function is per-monitor DPI aware when available.
 */
int GetSystemMetricsForWindow(HWND hWnd, int nIndex)
{
    if (g_pGetDpiForWindow && g_pGetSystemMetricsForDpi)
    {
        unsigned int dpi = g_pGetDpiForWindow(hWnd);
        return g_pGetSystemMetricsForDpi(nIndex, dpi);
    }
    else
    {
        return GetSystemMetrics(nIndex);
    }
}

/*
 * ApplyWindowMasking: Applies a mask to the window to clip the borders drawn
 *                     by the window manager.
 */
LRESULT ApplyWindowMasking(HWND hWnd)
{
    BOOL canLock = TryEnterCriticalSection(&g_criticalSection);
    int sizeBorders =
        GetSystemMetricsForWindow(hWnd, SM_CXSIZEFRAME) +
        GetSystemMetricsForWindow(hWnd, SM_CXPADDEDBORDER);
    RECT rcWindow;
    HRGN hRgn = NULL;

    if (canLock)
    {
        GetWindowRect(hWnd, &rcWindow);

        int cxWindow = rcWindow.right - rcWindow.left;
        int cyWindow = rcWindow.bottom - rcWindow.top;

        // SetWindowRgn transfers ownership of the HRGN to the operating system, so it's not
        // our responsibility to clean.
        hRgn = CreateRectRgn(
            0 + sizeBorders, 0 + sizeBorders,
            cxWindow - sizeBorders, cyWindow - sizeBorders
        );

        g_affectedWindows.push_back(hWnd);
    
        // If the window is marked as "fake undo", then remove that flag.
        std::vector<HWND>::iterator i;
        if ((i = std::find(g_fakeUndoWindows.begin(), g_fakeUndoWindows.end(), hWnd)) != g_fakeUndoWindows.end())
        {
            std::vector<HWND>::iterator newEnd = std::remove(g_fakeUndoWindows.begin(), g_fakeUndoWindows.end(), hWnd);
            g_fakeUndoWindows.erase(newEnd, g_fakeUndoWindows.end());
        }
            
        LeaveCriticalSection(&g_criticalSection);
    }

    if (hRgn != NULL && SetWindowRgn(hWnd, hRgn, TRUE))
    {
        return S_OK;
    }

    return E_FAIL;
}

/*
 * FakeUndoWindowMasking: Fakes removing the window mask by applying a massive one
 *                        over the window.
 *
 * This is required in order to fix a small bug with Aero Snap, where removing the
 * mask properly breaks the snap positioning for the first time the window is snapped
 * after maximising (unless the window is resized).
 *
 * TODO: Find a better solution. Needless to say, this is pretty ugly and it would be
 * preferable that a mask isn't leftover at all.
 */
LRESULT FakeUndoWindowMasking(HWND hWnd)
{
    std::vector<HWND>::iterator i;

    BOOL canLock = TryEnterCriticalSection(&g_criticalSection);

    if (canLock)
    {
        if ((i = std::find(g_affectedWindows.begin(), g_affectedWindows.end(), hWnd)) != g_affectedWindows.end())
        {
            std::vector<HWND>::iterator newEnd = std::remove(g_affectedWindows.begin(), g_affectedWindows.end(), hWnd);
            g_affectedWindows.erase(newEnd, g_affectedWindows.end());
            g_fakeUndoWindows.push_back(hWnd);

            HRGN hRgn = CreateRectRgn(
                0, 0,
                99999, 99999
            );

            SetWindowRgn(hWnd, hRgn, TRUE);
        }

        LeaveCriticalSection(&g_criticalSection);

        return S_OK;
    }

    return E_FAIL;
}

/*
 * UndoWindowMasking: Removes the masking region set by ApplyWindowMasking.
 */
LRESULT UndoWindowMasking(HWND hWnd)
{
    std::vector<HWND>::iterator i;

    BOOL canLock = TryEnterCriticalSection(&g_criticalSection);

    if (canLock)
    {
        if ((i = std::find(g_affectedWindows.begin(), g_affectedWindows.end(), hWnd)) != g_affectedWindows.end())
        {
            std::vector<HWND>::iterator newEnd = std::remove(g_affectedWindows.begin(), g_affectedWindows.end(), hWnd);
            g_affectedWindows.erase(newEnd, g_affectedWindows.end());

            SetWindowRgn(hWnd, NULL, TRUE);
        }

        LeaveCriticalSection(&g_criticalSection);

        return S_OK;
    }

    return E_FAIL;
}

/*
 * HandleMaxForWindow: Handle the window position changed event and set a region 
 */
void HandleMaxForWindow(HWND hWnd, UINT uMsg)
{
    if (hWnd && (uMsg == WM_WINDOWPOSCHANGED))
    {
        /* General window style stuff */
        DWORD dwStyle = GetWindowLongPtrW(hWnd, GWL_STYLE);
        if (dwStyle & WS_MAXIMIZE && dwStyle & WS_CAPTION && !(dwStyle & WS_CHILD))
        {
            /* Check if window is truly maximized to the full size of the screen */
            int sizeBorders =
                GetSystemMetricsForWindow(hWnd, SM_CXSIZEFRAME) +
                GetSystemMetricsForWindow(hWnd, SM_CXPADDEDBORDER);

            /**
             * Get the info for the monitor the window is on.
             * This contains rcWork, which accounts for the taskbar.
             */
            HMONITOR hm = MonitorFromWindow(hWnd, MONITOR_DEFAULTTONEAREST);
            MONITORINFO mi;
            mi.cbSize = sizeof(MONITORINFO);
            GetMonitorInfoW(hm, &mi);
            
            /* Add border size to rcWork */
            InflateRect(&mi.rcWork, sizeBorders, sizeBorders);
            
            RECT rcWnd;
            GetWindowRect(hWnd, &rcWnd);

            /* Compare the sizes. */
            if (rcWnd.right - rcWnd.left != mi.rcWork.right - mi.rcWork.left
            ||  rcWnd.bottom - rcWnd.top != mi.rcWork.bottom - mi.rcWork.top)
            {
                return;
            }

            if (std::find(g_affectedWindows.begin(), g_affectedWindows.end(), hWnd) == g_affectedWindows.end())
            {
                ApplyWindowMasking(hWnd);
            }
        }
        else
        {
            FakeUndoWindowMasking(hWnd);
        }
    }
}

typedef LRESULT (WINAPI *DefWindowProcA_t)(HWND, UINT, WPARAM, LPARAM);
DefWindowProcA_t DefWindowProcA_orig;
LRESULT WINAPI DefWindowProcA_hook(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam)
{
    LRESULT result = DefWindowProcA_orig(hWnd, uMsg, wParam, lParam);

    HandleMaxForWindow(hWnd, uMsg);

    return result;
}

typedef LRESULT (WINAPI *DefWindowProcW_t)(HWND, UINT, WPARAM, LPARAM);
DefWindowProcW_t DefWindowProcW_orig;
LRESULT WINAPI DefWindowProcW_hook(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam)
{
    LRESULT result = DefWindowProcW_orig(hWnd, uMsg, wParam, lParam);

    HandleMaxForWindow(hWnd, uMsg);

    return result;
}

/*
 * ThemePostWndProc_hook: Leverage theme hooks being available to hook window procedures globally.
 *
 * Since the theme engine is available for most applications, even for the majority of classic theme
 * users since Windows 8, it is possible to take advantage of one of its hooks in order to globally
 * hook window procedure handling.
 *
 * To my knowledge, this will only fail for 16-bit applications (which Windhawk cannot hook anyways)
 * and windows owned by certain system processes (such as CSRSS).
 */
typedef BOOL (CALLBACK *ThemePostWndProc_t)(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam, LRESULT *plResult, void **ppvParam);
ThemePostWndProc_t ThemePostWndProc_orig;
BOOL CALLBACK ThemePostWndProc_hook(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam, LRESULT *plResult, void **ppvParam)
{
    BOOL result = ThemePostWndProc_orig(hWnd, uMsg, wParam, lParam, plResult, ppvParam);

    HandleMaxForWindow(hWnd, uMsg);

    return result;
}

/*
 * InitCriticalSections: Setup data-access locks.
 */
bool InitCriticalSections()
{
    if (!InitializeCriticalSectionAndSpinCount(&g_criticalSection, 0x400))
        return false;

    return true;
}

/*
 * CleanCriticalSections: Clean up data-access locks.
 */
void CleanCriticalSections()
{
    DeleteCriticalSection(&g_criticalSection);
}

// The mod is being initialized, load settings, hook functions, and do other
// initialization stuff if required.
BOOL Wh_ModInit()
{
    Wh_Log(L"Init " WH_MOD_ID L" version " WH_MOD_VERSION);

    InitCriticalSections();

    HMODULE user32 = LoadLibraryW(L"user32.dll");
    HMODULE uxtheme = LoadLibraryExW(L"uxtheme.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);

    // Init DPI helpers:
    *(FARPROC *)&g_pGetDpiForWindow = GetProcAddress(user32, "GetDpiForWindow");
    *(FARPROC *)&g_pGetSystemMetricsForDpi = GetProcAddress(user32, "GetSystemMetricsForDpi");

    FARPROC pDefWindowProcW = GetProcAddress(user32, "DefWindowProcW");

    Wh_SetFunctionHook(
        (void *)pDefWindowProcW,
        (void *)DefWindowProcW_hook,
        (void **)&DefWindowProcW_orig
    );

    FARPROC pDefWindowProcA = GetProcAddress(user32, "DefWindowProcA");

    Wh_SetFunctionHook(
        (void *)pDefWindowProcA,
        (void *)DefWindowProcA_hook,
        (void **)&DefWindowProcA_orig
    );

    WindhawkUtils::SYMBOL_HOOK uxthemeDllHooks[] = {
        {
            {
                #ifdef _WIN64
                L"int __cdecl ThemePostWndProc(struct HWND__ *,unsigned int,unsigned __int64,__int64,__int64 *,void * *)"
                #else
                L"int __stdcall ThemePostWndProc(struct HWND__ *,unsigned int,unsigned int,long,long *,void * *)"
                #endif
            },
            &ThemePostWndProc_orig,
            ThemePostWndProc_hook
        }
    };

    HookSymbols(uxtheme, uxthemeDllHooks, ARRAYSIZE(uxthemeDllHooks));

    Wh_Log(L"Finished init");

    return TRUE;
}

// The mod is being unloaded, free all allocated resources.
void Wh_ModUninit()
{
    Wh_Log(L"Uninit");

    CleanCriticalSections();
}

}  // namespace ClassicMaximizedWindowsFix

// ============================================================
// ===== msg-box-font-fix
// ============================================================
namespace MsgBoxFontFix {

HMODULE g_hUser32 = NULL;
enum MESSAGEBOXSTYLE
{
    MBS_NT4,
    MBS_XP,
    MBS_VISTA,
} g_mbStyle = MBS_VISTA;

/* Only available in Windows 10 version 1607 and greater. */

/* Imported from win32u.dll */
typedef INT_PTR (WINAPI *NtUserCallOneParam_t)(DWORD dwParam, DWORD xpfnProc);
NtUserCallOneParam_t NtUserCallOneParam = nullptr;
typedef INT_PTR (NTAPI *NtUserCallHwnd_t)(HWND hwnd, DWORD xpfnProc);
NtUserCallHwnd_t NtUserCallHwnd = nullptr;

/* New in Windows 11 24H2. Using old method breaks. */
typedef INT_PTR (WINAPI *NtUserMessageBeep_t)(DWORD dwBeep);
NtUserMessageBeep_t NtUserMessageBeep = nullptr;
typedef INT_PTR (WINAPI *NtUserSetMsgBox_t)(HWND hwnd);
NtUserSetMsgBox_t NtUserSetMsgBox = nullptr;

HFONT (__fastcall *GetMessageBoxFontForDpi_orig)(UINT);
HFONT __fastcall GetMessageBoxFontForDpi_hook(
    UINT nDpi
)
{
    NONCLIENTMETRICSW ncm;
    ncm.cbSize = sizeof(NONCLIENTMETRICSW);
    if (SystemParametersInfoForDpi(
        SPI_GETNONCLIENTMETRICS,
        sizeof(NONCLIENTMETRICSW),
        &ncm,
        0,
        nDpi
    ))
    {
        return CreateFontIndirectW(&ncm.lfMessageFont);
    }
    return NULL;
}

#pragma region "Classic style"

typedef struct _MSGBOXDATA {
    // BEGIN MSGBOXPARAMS
    UINT        cbSize;
    HWND        hwndOwner;
    HINSTANCE   hInstance;
    LPCWSTR     lpszText;
    LPCWSTR     lpszCaption;
    DWORD       dwStyle;
    LPCWSTR     lpszIcon;
    DWORD_PTR   dwContextHelpId;
    MSGBOXCALLBACK      lpfnMsgBoxCallback;
    DWORD       dwLanguageId;
    // END MSGBOXPARAMS
    HWND    HWNDOwner;
    DWORD   dwPadding;
    WORD    wLanguageId;
    const INT *pidButton;
    LPCWSTR *ppszButtonText;
    DWORD   cButtons;
    UINT    DefButton;
    UINT    CancelId;
    DWORD   dwTimeout;
    HWND *phwndList;
    DWORD   dwReserved[20];
} MSGBOXDATA, *PMSGBOXDATA, *LPMSGBOXDATA;

typedef struct _TEB64 {
	UCHAR ignored[0x0800];
	ULONG_PTR Win32ClientInfo[0x3E];
} TEB64, *PTEB64;

typedef struct _DESKTOPINFO
{
	DWORD ignored[12];
	int cntMBox;
} DESKTOPINFO, *PDESKTOPINFO;

typedef struct _CLIENTINFO64 {
	DWORD64 CI_flags;
	DWORD64 cSpins;
	DWORD dwExpWinVer;
	DWORD dwCompatFlags;
	DWORD dwCompatFlags2;
	DWORD dwTIFlags;
	PDESKTOPINFO pDeskInfo;
} CLIENTINFO64, *PCLIENTINFO64;

inline PCLIENTINFO64 GetClientInfo()
{
    PTEB64 teb = (PTEB64)NtCurrentTeb();
// This breaks on real 32-bit Windows, it's WOW64 specific.
// But literally nobody uses that anymore, so who cares.
#ifndef _WIN64
	teb = *(PTEB64 *)((LPBYTE)teb + 0x0F70);
#endif
    return (PCLIENTINFO64)teb->Win32ClientInfo;
}

static CONST WCHAR szEmpty[] = L"";

// IDs and such
#define MAX_RES_STRING 256
#define UNICODE_RLM 0x200F  // RIGHT-TO-LEFT MARK      (RLM)
#define IDUSERICON      20
#define BUTTONCODE	  0x80
#define STATICCODE	  0x82
#define SFI_PLAYEVENTSOUND 57
#define SFI_SETMSGBOX      89

// Macros
#define MAXUSHORT       (0xFFFF)
#define IS_PTR(p)       ((((ULONG_PTR)(p)) & ~MAXUSHORT) != 0)
#define PTR_TO_ID(p)    ((USHORT)(((ULONG_PTR)(p)) & MAXUSHORT))
#define SYSMET(i)               GetSystemMetrics( SM_##i )
#define XPixFromXDU(x, cxChar)       MulDiv(x, cxChar, 4)
#define YPixFromYDU(y, cyChar)       MulDiv(y, cyChar, 8)
#define XDUFromXPix(x, cxChar)       MulDiv(x, 4, cxChar)
#define YDUFromYPix(y, cyChar)       MulDiv(y, 8, cyChar)
#define NextWordBoundary(p)     ((PBYTE)(p) + ((ULONG_PTR)(p) & 1))
#define NextDWordBoundary(p)    ((PBYTE)(p) + ((ULONG_PTR)(-(LONG_PTR)(p)) & 3))
#define USERGLOBALLOCK(h, p)   p = (LPWSTR)GlobalLock((HANDLE)(h))
#define USERGLOBALUNLOCK(h)             GlobalUnlock((HANDLE)(h))
#define max(a,b) (((a) > (b)) ? (a) : (b))
#define min(a,b) (((a) < (b)) ? (a) : (b))

// Dialog unit dimensions
#define DU_OUTERMARGIN    7
#define DU_INNERMARGIN    10
#define DU_BTNGAP         4   // D.U. of space between buttons
#define DU_BTNHEIGHT      14  // D.U. of button height
#define DU_BTNWIDTH       50  // D.U. of minimum button width in a message box

// Custom struct and function because we can't use gpsi
typedef struct tagMSGBOXMETRICS
{
    WORD cxMsgFontChar;
    WORD cyMsgFontChar;
    WORD wMaxBtnSize;
    HFONT hCaptionFont;
    HFONT hMessageFont;
} MSGBOXMETRICS, *LPMSGBOXMETRICS;
MSGBOXMETRICS mbm;

int GetCharDimensions(HDC hdc, TEXTMETRICW *lptm, int *lpcy)
{
    TEXTMETRICW tm;

    if (!GetTextMetricsW(hdc, &tm)) // _GetTextMetricsW
    {
        // Fallback to global system font: (NT User caches this information, but we don't have access u_u)
        GetTextMetricsW(GetDC(nullptr), &tm);

        if (tm.tmAveCharWidth == 0)
        {
            // Ultimate fallback:
            tm.tmAveCharWidth = 8;
        }
    }

    if (lptm)
    {
        *lptm = tm;
    }

    if (lpcy)
    {
        *lpcy = tm.tmHeight;
    }

    // Variable-width fonts calculate a true average rather than relying on tmAveCharWidth.
    if (tm.tmPitchAndFamily & TMPF_FIXED_PITCH)
    {
        static const WCHAR wszAvgChars[] = L"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";

        SIZE size;
        if (GetTextExtentPoint32W(hdc, wszAvgChars, ARRAYSIZE(wszAvgChars) - 1, &size)) // GreGetTextExtentW
        {
            // The above string is 26 * 2 characters. + 1 rounds the result.
            return ((size.cx / 26) + 1) / 2;
        }
    }

    return tm.tmAveCharWidth;
}

UINT MB_FindLongestString(HDC hdc, LPCWSTR *ppszButtonText, DWORD cButtons)
{
    UINT wRetVal;
    int i, iMaxLen = 0, iNewMaxLen;
    LPCWSTR szMaxStr;
    SIZE sizeOneChar;
    SIZE sizeMaxStr;
    WCHAR szOneChar[2] = L"0";

    for (i = 800; i <= 810; i++) {
        WCHAR szCurStr[256];
        LoadStringW(g_hUser32, i, szCurStr, 256);
        if ((iNewMaxLen = wcslen(szCurStr)) > iMaxLen) {
            iMaxLen = iNewMaxLen;
            szMaxStr = szCurStr;
        }
    }

    // Modification from original NT4 func: account for any custom strings.
    // Don't want any custom message boxes cutting off text.
    for (i = 0; i < (int)cButtons; i++)
    {
        LPCWSTR szCurStr = ppszButtonText[i];
        if ((iNewMaxLen = wcslen(szCurStr)) > iMaxLen)
        {
            iMaxLen = iNewMaxLen;
            szMaxStr = szCurStr;
        }
    }

    /*
     * Find the longest string
     */
    GetTextExtentPointW(hdc, szOneChar, 1, &sizeOneChar);
    GetTextExtentPointW(hdc, szMaxStr, iMaxLen, &sizeMaxStr);
    wRetVal = (UINT)(sizeMaxStr.cx + (sizeOneChar.cx * 2));

    return wRetVal;
}

BOOL GetMessageBoxMetrics(LPMSGBOXMETRICS pmbm, LPCWSTR *ppszButtonText, DWORD cButtons)
{  
    if (!pmbm)
        return FALSE;

    ZeroMemory(pmbm, sizeof(MSGBOXMETRICS));
    BOOL succeeded = TRUE;
    HDC hDesktopDC = GetDC(NULL);
    HDC hMemDC = CreateCompatibleDC(hDesktopDC);

    HFONT hf = GetMessageBoxFontForDpi_hook(GetDeviceCaps(hMemDC, LOGPIXELSX));
    SelectObject(hMemDC, hf);

    NONCLIENTMETRICSW ncm;
    ncm.cbSize = sizeof(NONCLIENTMETRICSW);
    SystemParametersInfoForDpi(
        SPI_GETNONCLIENTMETRICS,
        sizeof(ncm),
        &ncm,
        0,
        GetDeviceCaps(hMemDC, LOGPIXELSX)
    );
    
    TEXTMETRICW tm;
    int iAverageCharHeight;
    int iAverageCharWidth = GetCharDimensions(hMemDC, nullptr, &iAverageCharHeight);
    succeeded = GetTextMetricsW(hMemDC, &tm);
    if (succeeded)
    {
        pmbm->cxMsgFontChar = iAverageCharWidth;
        pmbm->cyMsgFontChar = tm.tmHeight;
        pmbm->wMaxBtnSize = (g_mbStyle == MBS_NT4)
            ? MB_FindLongestString(hMemDC, ppszButtonText, cButtons)
            : XPixFromXDU(DU_BTNWIDTH, iAverageCharWidth);
        pmbm->hCaptionFont = CreateFontIndirectW(&ncm.lfCaptionFont);
        pmbm->hMessageFont = hf;
    }

    DeleteDC(hMemDC);
    ReleaseDC(NULL, hDesktopDC);
    return succeeded;
}

UINT MB_GetIconOrdNum(UINT rgBits)
{
    switch (rgBits & MB_ICONMASK) {
    case MB_USERICON:
    case MB_ICONHAND:
        return PtrToUlong(IDI_HAND);

    case MB_ICONQUESTION:
        return PtrToUlong(IDI_QUESTION);

    case MB_ICONEXCLAMATION:
        return PtrToUlong(IDI_EXCLAMATION);

    case MB_ICONASTERISK:
        return PtrToUlong(IDI_ASTERISK);
    }

    return 0;
}


UINT MB_FindDlgTemplateSize(LPMSGBOXDATA lpmb)
{
    ULONG_PTR cbLen;
    UINT cbT;
    UINT i;
    UINT wCount;

    wCount = lpmb->cButtons;

    /* Start with dialog header's size */
    cbLen = (ULONG_PTR)NextWordBoundary(sizeof(DLGTEMPLATE) + sizeof(WCHAR));
    cbLen = (ULONG_PTR)NextWordBoundary(cbLen + sizeof(WCHAR));
    cbLen += wcslen(lpmb->lpszCaption) * sizeof(WCHAR) + sizeof(WCHAR);
    cbLen += sizeof(WORD);                   // Font height
    cbLen = (ULONG_PTR)NextDWordBoundary(cbLen);

    /* Check if an icon is present */
    if (lpmb->dwStyle & MB_ICONMASK)
        cbLen += (ULONG_PTR)NextDWordBoundary(sizeof(DLGITEMTEMPLATE) + 7 * sizeof(WCHAR));

    /* Find the number of buttons in the msg box */
    for (i = 0; i < wCount; i++) {
        cbLen = (ULONG_PTR)NextWordBoundary(cbLen + sizeof(DLGITEMTEMPLATE) +
            (2 * sizeof(WCHAR)));
        cbT = (wcslen(lpmb->ppszButtonText[i]) + 1) * sizeof(WCHAR);
        cbLen = (ULONG_PTR)NextWordBoundary(cbLen + cbT);
        cbLen += sizeof(WCHAR);
        cbLen = (ULONG_PTR)NextDWordBoundary(cbLen);
    }

    /* Add in the space required for the text message (if there is one) */
    if (lpmb->lpszText != NULL) {
        cbLen = (ULONG_PTR)NextWordBoundary(cbLen + sizeof(DLGITEMTEMPLATE) +
            (2 * sizeof(WCHAR)));
        cbT = (wcslen(lpmb->lpszText) + 1) * sizeof(WCHAR);
        cbLen = (ULONG_PTR)NextWordBoundary(cbLen + cbT);
        cbLen += sizeof(WCHAR);
        cbLen = (ULONG_PTR)NextDWordBoundary(cbLen);
    }

    return (UINT)cbLen;
}

LPBYTE MB_UpdateDlgHdr(
    LPDLGTEMPLATE lpDlgTmp,
    long lStyle,
    long lExtendedStyle,
    BYTE bItemCount,
    int iX,
    int iY,
    int iCX,
    int iCY,
    LPWSTR lpszCaption,
    int cchCaptionLen)
{
    LPTSTR lpStr;
    RECT rc;

    rc.left = iX + SYSMET(CXFIXEDFRAME) + SYSMET(CXPADDEDBORDER);
    rc.top = iY + SYSMET(CYFIXEDFRAME) + SYSMET(CXPADDEDBORDER);
    rc.right = iX + iCX - SYSMET(CXFIXEDFRAME) + SYSMET(CXPADDEDBORDER);
    rc.bottom = iY + iCY - SYSMET(CYFIXEDFRAME) + SYSMET(CXPADDEDBORDER);
    rc.top += SYSMET(CYCAPTION);

    lpDlgTmp->style = lStyle;
    lpDlgTmp->dwExtendedStyle = lExtendedStyle;
    lpDlgTmp->cdit = bItemCount;
    lpDlgTmp->x = XDUFromXPix(rc.left, mbm.cxMsgFontChar);
    lpDlgTmp->y = YDUFromYPix(rc.top, mbm.cyMsgFontChar);
    lpDlgTmp->cx = XDUFromXPix(rc.right - rc.left, mbm.cxMsgFontChar);
    lpDlgTmp->cy = YDUFromYPix(rc.bottom - rc.top, mbm.cyMsgFontChar);

    /*
     * Move pointer to variable length fields.  No menu resource for
     * message box, a zero window class (means dialog box class).
     */
    lpStr = (LPWSTR)(lpDlgTmp + 1);
    *lpStr++ = 0;                           // Menu
    lpStr = (LPWSTR)NextWordBoundary(lpStr);
    *lpStr++ = 0;                           // Class
    lpStr = (LPWSTR)NextWordBoundary(lpStr);

    /*
     * NOTE: iCaptionLen may be less than the length of the Caption string;
     * So, DO NOT USE lstrcpy();
     */
    RtlCopyMemory(lpStr, lpszCaption, cchCaptionLen * sizeof(WCHAR));
    lpStr += cchCaptionLen;
    *lpStr++ = TEXT('\0');

    /* Font height of 0x7FFF means use the message box font */
    *lpStr++ = 0x7FFF;

    return NextDWordBoundary(lpStr);
}

LPBYTE MB_UpdateDlgItem(
    LPDLGITEMTEMPLATE lpDlgItem,
    int iCtrlId,
    long lStyle,
    long lExtendedStyle,
    int iX,
    int iY,
    int iCX,
    int iCY,
    LPWSTR lpszText,
    UINT cchTextLen,
    int iControlClass)
{
    LPWSTR lpStr;
    BOOL fIsOrdNum;


    lpDlgItem->x = XDUFromXPix(iX, mbm.cxMsgFontChar);
    lpDlgItem->y = YDUFromYPix(iY, mbm.cyMsgFontChar);
    lpDlgItem->cx = XDUFromXPix(iCX, mbm.cxMsgFontChar);
    lpDlgItem->cy = YDUFromYPix(iCY, mbm.cyMsgFontChar);
    lpDlgItem->id = (WORD)iCtrlId;
    lpDlgItem->style = lStyle;
    lpDlgItem->dwExtendedStyle = lExtendedStyle;

    if (iControlClass == STATICCODE &&
        (((lStyle & 0x0F) == SS_LEFT) || ((lStyle & 0x0F) == SS_RIGHT)))
    {
        lpDlgItem->cx++;
        lpDlgItem->cy++;
    }

    lpStr = (LPWSTR)(lpDlgItem + 1);

    *lpStr++ = 0xFFFF;
    *lpStr++ = (BYTE)iControlClass;
    lpStr = (LPWSTR)NextWordBoundary(lpStr);

    fIsOrdNum = ((*lpszText == 0xFFFF) && (cchTextLen == sizeof(DWORD) / sizeof(WCHAR)));

    RtlCopyMemory(lpStr, lpszText, cchTextLen * sizeof(WCHAR));
    lpStr = lpStr + cchTextLen;
    if (!fIsOrdNum)
    {
        *lpStr = TEXT('\0');
        lpStr = (LPWSTR)NextWordBoundary(lpStr + 1);
    }

    *lpStr++ = 0;

    return NextDWordBoundary(lpStr);
}

LPBYTE MB_AddPushButtons(
    LPDLGITEMTEMPLATE  lpDlgTmp,
    LPMSGBOXDATA       lpmb,
    UINT               wLEdge,
    UINT               wBEdge)
{
    UINT   wYValue;
    UINT   i;
    UINT   wHeight;
    UINT   wCount = lpmb->cButtons;

    wHeight = YPixFromYDU(DU_BTNHEIGHT, mbm.cyMsgFontChar);

    wYValue = wBEdge - wHeight;         // Y coord for push buttons

    for (i = 0; i < wCount; i++) {

        lpDlgTmp = (LPDLGITEMTEMPLATE)MB_UpdateDlgItem(
            lpDlgTmp,                       /* Ptr to template */
            lpmb->pidButton[i],             /* Control Id */
            WS_TABSTOP | WS_CHILD | WS_VISIBLE | (i == 0 ? WS_GROUP : 0) |
            ((UINT)i == lpmb->DefButton ? BS_DEFPUSHBUTTON : BS_PUSHBUTTON),
            0,
            wLEdge,                         /* X coord */
            wYValue,                        /* Y coord */
            mbm.wMaxBtnSize,                /* CX */
            wHeight,                        /* CY */
            (LPWSTR)lpmb->ppszButtonText[i],        /* String for button */
            (UINT)wcslen(lpmb->ppszButtonText[i]),/* Length */
            BUTTONCODE);

        /* Get the X coord for the next push button */
        wLEdge += mbm.wMaxBtnSize + XPixFromXDU(DU_BTNGAP, mbm.cxMsgFontChar);
    }

    return (LPBYTE)lpDlgTmp;
}

void MB_CopyToClipboard(HWND hwndDlg)
{
    LPCWSTR lpszRead;
    LPWSTR lpszAll, lpszWrite;
    HANDLE hData;
    static  CONST WCHAR   szLine[] = L"---------------------------\r\n";
    UINT cBufSize, i, cWrote;
    LPMSGBOXDATA lpmb;

    if (!(lpmb = (LPMSGBOXDATA)GetWindowLongPtr(hwndDlg, GWLP_USERDATA))) {
        return;
    }

    if (!OpenClipboard(hwndDlg)) {
        return;
    }

    /*
     * Calculate the buffer size:
     *      - the message text can be all \n, that will become \r\n
     *      - there are a few extra \r\n (that's why 8)
     */
    cBufSize = (lpmb->lpszCaption ? wcslen(lpmb->lpszCaption) : 0) +
        (lpmb->lpszText ? 2 * wcslen(lpmb->lpszText) : 0) +
        4 * sizeof(szLine) +
        lpmb->cButtons * mbm.wMaxBtnSize +
        8;

    cBufSize *= sizeof(WCHAR);

    if (!(hData = GlobalAlloc(LHND, (LONG)(cBufSize)))) {
        goto CloseClip;
    }

    USERGLOBALLOCK(hData, lpszAll);

    cWrote = wsprintf(lpszAll, L"%s%s\r\n%s",
        szLine,
        lpmb->lpszCaption ? lpmb->lpszCaption : L"",
        szLine);

    lpszWrite = lpszAll + cWrote;
    lpszRead = lpmb->lpszText;
    /*
     * Change \n to \r\n in the text
     */
    for (i = 0; *lpszRead; i++) {

        if (*lpszRead == L'\n')
            *lpszWrite++ = L'\r';

        *lpszWrite++ = *lpszRead++;
    }

    cWrote = wsprintf(lpszWrite, L"\r\n%s", szLine);
    lpszWrite += cWrote;

    /*
     * Remove & from the button texts
     */
    for (i = 0; i < lpmb->cButtons; i++) {

        lpszRead = lpmb->ppszButtonText[i];
        while (*lpszRead) {
            if (*lpszRead != L'&') {
                *lpszWrite++ = *lpszRead;
            }
            lpszRead++;
        }
        *lpszWrite++ = L' ';
        *lpszWrite++ = L' ';
        *lpszWrite++ = L' ';
    }
    wsprintf(lpszWrite, L"\r\n%s\0", szLine);

    USERGLOBALUNLOCK(hData);

    EmptyClipboard();

    SetClipboardData(CF_UNICODETEXT, hData);

CloseClip:
    CloseClipboard();

}

INT_PTR CALLBACK MB_DlgProc(
    HWND hwndDlg,
    UINT wMsg,
    WPARAM wParam,
    LPARAM lParam)
{
    HWND hwndT;
    int iCount;
    LPMSGBOXDATA lpmb;
    HWND hwndOwner;
    PVOID lpfnCallback;
    BOOL bTimedOut = FALSE;

    switch (wMsg) {
    case WM_CTLCOLORDLG:
    case WM_CTLCOLORSTATIC:
        return DefWindowProcW(hwndDlg, WM_CTLCOLORMSGBOX,
            wParam, lParam);

    case WM_TIMER:
        if (!bTimedOut) {
            bTimedOut = TRUE;
            EndDialog(hwndDlg, IDTIMEOUT);
        }
        break;

    case WM_NCDESTROY:
        if ((lpmb = (LPMSGBOXDATA)GetWindowLongPtr(hwndDlg, GWLP_USERDATA))) {
            if (lpmb->dwTimeout != INFINITE) {
                KillTimer(hwndDlg, 0);
                lpmb->dwTimeout = INFINITE;
            }
        }
        return DefWindowProcW(hwndDlg, wMsg,
            wParam, lParam);


    case WM_INITDIALOG:
    {
        lpmb = (LPMSGBOXDATA)lParam;
        SetWindowLongPtr(hwndDlg, GWLP_USERDATA, (ULONG_PTR)lParam);

        if (NtUserSetMsgBox)
            NtUserSetMsgBox(hwndDlg);
        else
            NtUserCallHwnd(hwndDlg, SFI_SETMSGBOX);

        if (lpmb->dwStyle & MB_TOPMOST) {
            SetWindowPos(hwndDlg,
                HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE);
        }

        if (lpmb->dwStyle & MB_USERICON) {
            SendDlgItemMessage(hwndDlg, IDUSERICON, STM_SETICON, (WPARAM)(lpmb->lpszIcon), 0);
            iCount = ALERT_SYSTEM_WARNING;
        }
        else {
            /*
             * Generate an alert notification
             */
            switch (lpmb->dwStyle & MB_ICONMASK) {
            case MB_ICONWARNING:
                iCount = ALERT_SYSTEM_WARNING;
                break;

            case MB_ICONQUESTION:
                iCount = ALERT_SYSTEM_QUERY;
                break;

            case MB_ICONERROR:
                iCount = ALERT_SYSTEM_ERROR;
                break;

            case MB_ICONINFORMATION:
            default:
                iCount = ALERT_SYSTEM_INFORMATIONAL;
                break;
            }
        }

        NotifyWinEvent(EVENT_SYSTEM_ALERT, hwndDlg, OBJID_ALERT, iCount);

        hwndT = GetWindow(hwndDlg, GW_CHILD);
        iCount = lpmb->DefButton;
        while (iCount--)
            hwndT = GetWindow(hwndT, GW_HWNDNEXT);

        SetFocus(hwndT);

        hwndT = hwndDlg;

        if (lpmb->CancelId == 0) {
            HMENU hMenu;

            if (hMenu = GetSystemMenu(hwndDlg, FALSE)) {
                DeleteMenu(hMenu, SC_CLOSE, (UINT)MF_BYCOMMAND);
            }
        }

        if ((lpmb->dwStyle & MB_TYPEMASK) == MB_OK) {
            hwndDlg = GetDlgItem(hwndDlg, IDOK);

            if (hwndDlg != NULL) {
                SetWindowLongPtr(hwndDlg, GWLP_ID, IDCANCEL);
            }
        }

        if (lpmb->dwTimeout != INFINITE) {
            if (SetTimer(hwndT, 0, lpmb->dwTimeout, NULL) == 0) {
                /*
                 * Couldn't create the timer, so "clear" out the timeout value
                 * for future reference.
                 */
                lpmb->dwTimeout = INFINITE;
            }
        }

        // Hack because XP's positioning code is broken on 10
        // This centers it properly
        HMONITOR hm = MonitorFromWindow(hwndT, MONITOR_DEFAULTTOPRIMARY);
        MONITORINFO mi;
        mi.cbSize = sizeof(mi);
        GetMonitorInfoW(hm, &mi);
        RECT rc;
        GetWindowRect(hwndT, &rc);
        int x = (mi.rcWork.right - mi.rcWork.left) / 2;
        x -= (rc.right - rc.left) / 2;
        int y = (mi.rcWork.bottom - mi.rcWork.top) / 2;
        y -= (rc.bottom - rc.top) /2;

        // Tile effect
        int cntMBox = GetClientInfo()->pDeskInfo->cntMBox;
        x += cntMBox * SYSMET(CXSIZE);
        y += cntMBox * SYSMET(CYSIZE);

        // Make sure it stays in the screen
        if ((x + (rc.right - rc.left)) > mi.rcWork.right)
        {
            x = mi.rcWork.right - SYSMET(CXEDGE) - (rc.right - rc.left);
        }

        if (y + (rc.bottom - rc.top) > mi.rcWork.bottom)
        {
            y = mi.rcWork.bottom - SYSMET(CYEDGE) - (rc.bottom - rc.top);
            if (y < mi.rcWork.top)
            {
                y = mi.rcMonitor.bottom - SYSMET(CYEDGE) - (rc.bottom - rc.top);
            }
        }

        SetWindowPos(
            hwndT,
            NULL,
            x, y,
            0, 0,
            SWP_NOZORDER | SWP_NOSIZE
        );

        return FALSE;
    }
    case WM_COMMAND:
        switch (LOWORD(wParam)) {
        case IDOK:
        case IDCANCEL:
            //
            // Check if a control exists with the given ID; This
            // check is needed because DlgManager returns IDCANCEL
            // blindly when ESC is pressed even if a button with
            // IDCANCEL is not present.
            //
            if (!GetDlgItem(hwndDlg, LOWORD(wParam)))
                return FALSE;


            // else FALL THRO....This is intentional.
        case IDABORT:
        case IDIGNORE:
        case IDNO:
        case IDRETRY:
        case IDYES:
        case IDTRYAGAIN:
        case IDCONTINUE:
            EndDialog(hwndDlg, LOWORD(wParam));
            break;

        default:
            return FALSE;
            break;
        }
        break;

    case WM_COPY:
        MB_CopyToClipboard(hwndDlg);
        break;

    default:
        return FALSE;
    }

    return TRUE;
}

int SoftModalMessageBox_XP(
    LPMSGBOXDATA lpmb)
{
    LPBYTE              lpDlgTmp;
    int                 cyIcon, cxIcon;
    int                 cxButtons;
    int                 cxMBMax;
    int                 cxText, cyText, xText;
    int                 cxBox, cyBox;
    int                 cxFoo, cxCaption;
    int                 xMB, yMB;
    HDC                 hdc;
    DWORD               wIconOrdNum;
    DWORD               wCaptionLen;
    DWORD               wTextLen;
    WORD                OrdNum[2];  // Must be an array or WORDs
    RECT                rc;
    RECT                rcWork;
    HCURSOR             hcurOld;
    DWORD               dwStyleMsg, dwStyleText;
    DWORD               dwExStyleMsg = 0;
    DWORD               dwStyleDlg;
    HWND                hwndOwner;
    LPWSTR              lpsz;
    int                 iRetVal = 0;
    HICON               hIcon;
    HGLOBAL             hTemplate = NULL;
    HGLOBAL             hCaption = NULL;
    HGLOBAL             hText = NULL;
    HINSTANCE           hInstMsg = lpmb->hInstance;
    SIZE                size;
    HFONT               hFontOld = NULL;
    int                 cntMBox;
    HMONITOR            hMonitor;
    MONITORINFO         mi;

    GetMessageBoxMetrics(&mbm, lpmb->ppszButtonText, lpmb->cButtons);

    dwStyleMsg = lpmb->dwStyle;

    if (dwStyleMsg & MB_RIGHT) {
        dwExStyleMsg |= WS_EX_RIGHT;
    }

    if (!IS_PTR(lpmb->lpszCaption)) {
        /*
         * Won't ever be NULL because MessageBox sticks "Error!" on error.
         */
        if (hInstMsg && (hCaption = LocalAlloc(LPTR, MAX_RES_STRING * sizeof(WCHAR)))) {
            lpsz = (LPWSTR)hCaption;
            LoadString(hInstMsg, PTR_TO_ID(lpmb->lpszCaption), lpsz, MAX_RES_STRING);
        }
        else {
            lpsz = NULL;
        }

        lpmb->lpszCaption = lpsz ? lpsz : szEmpty;
    }

    if (!IS_PTR(lpmb->lpszText)) {
        // NULL not allowed
        if (hInstMsg && (hText = LocalAlloc(LPTR, MAX_RES_STRING * sizeof(WCHAR)))) {
            lpsz = (LPWSTR)hText;
            LoadString(hInstMsg, PTR_TO_ID(lpmb->lpszText), lpsz, MAX_RES_STRING);
        }
        else {
            lpsz = NULL;
        }

        lpmb->lpszText = lpsz ? lpsz : szEmpty;
    }

    if ((dwStyleMsg & MB_RTLREADING) ||
        (lpmb->lpszText != NULL && (lpmb->lpszText[0] == UNICODE_RLM) &&
            (lpmb->lpszText[1] == UNICODE_RLM))) {
        //
        // Set Mirroring so that MessageBox and its child controls
        // get mirrored. Otherwise, the message box and its child controls
        // are Left-To-Right.
        //
        dwExStyleMsg |= WS_EX_LAYOUTRTL;

        //
        // And turn off any conflicting flags.
        //
        dwExStyleMsg &= ~WS_EX_RIGHT;
        if (dwStyleMsg & MB_RTLREADING) {
            dwStyleMsg &= ~MB_RTLREADING;
            dwStyleMsg ^= MB_RIGHT;
        }
    }

    if ((dwStyleMsg & MB_ICONMASK) == MB_USERICON)
        hIcon = LoadIcon(hInstMsg, lpmb->lpszIcon);
    else
        hIcon = NULL;

    // For compatibility reasons, we still allow the message box to come up.
    hwndOwner = lpmb->hwndOwner;

getthedc:
    // Check if we're out of cache DCs until robustness...
    if (!(hdc = GetDCEx(NULL, NULL, DCX_WINDOW | DCX_CACHE))) {

        /*
         * The above call might fail for TIF_RESTRICTED processes
         * so check for the DC from the owner window
         */
        if (!(hdc = GetDCEx(hwndOwner, NULL, DCX_WINDOW | DCX_CACHE)))
            goto SMB_Exit;
    }

    // Figure out the types and dimensions of buttons
    cxButtons = (lpmb->cButtons * mbm.wMaxBtnSize) + ((lpmb->cButtons - 1) * XPixFromXDU(DU_BTNGAP, mbm.cxMsgFontChar));

    // Ditto for the icon, if there is one.  If not, cxIcon & cyIcon are 0.

    if (wIconOrdNum = MB_GetIconOrdNum(dwStyleMsg)) {
        cxIcon = SYSMET(CXICON) + XPixFromXDU(DU_INNERMARGIN, mbm.cxMsgFontChar);
        cyIcon = SYSMET(CYICON);
    }
    else
        cxIcon = cyIcon = 0;

    hFontOld = (HFONT)SelectObject(hdc, mbm.hCaptionFont);

    // Find the max between the caption text and the buttons
    wCaptionLen = wcslen(lpmb->lpszCaption);
    GetTextExtentPointW(hdc, lpmb->lpszCaption, wCaptionLen, &size);
    cxCaption = size.cx + 2 * SYSMET(CXSIZE);

    //
    // The max width of the message box is 5/8 of the work area for most
    // countries.  We will then try 6/8 and 7/8 if it won't fit.  Then
    // we will use whole screen.
    //
    hMonitor = MonitorFromWindow(hwndOwner, MONITOR_DEFAULTTOPRIMARY);
    mi.cbSize = sizeof(MONITORINFO);
    GetMonitorInfoW(hMonitor, &mi);
    CopyRect(&rcWork, &mi.rcWork);
    cxMBMax = MulDiv(rcWork.right - rcWork.left, 5, 8);

    cxFoo = 2 * XPixFromXDU(DU_OUTERMARGIN, mbm.cxMsgFontChar);

    SelectObject(hdc, mbm.hMessageFont);

    //
    // If the text doesn't fit in 5/8, try 7/8 of the screen
    //
ReSize:
    //
    // The message box is as big as needed to hold the caption/text/buttons,
    // but not bigger than the maximum width.
    //

    cxBox = cxMBMax - 2 * SYSMET(CXFIXEDFRAME);

    // Ask DrawText for the right cx and cy
    rc.left = 0;
    rc.top = 0;
    rc.right = cxBox - cxFoo - cxIcon;
    rc.bottom = rcWork.bottom - rcWork.top;
    cyText = DrawTextExW(hdc, (LPWSTR)lpmb->lpszText, -1, &rc,
        DT_CALCRECT | DT_WORDBREAK | DT_EXPANDTABS |
        DT_NOPREFIX | DT_EXTERNALLEADING | DT_EDITCONTROL, NULL);
    //
    // Make sure we have enough width to hold the buttons, in addition to
    // the icon+text.  Always force the buttons.  If they don't fit, it's
    // because the working area is small.
    //
    //
    // The buttons are centered underneath the icon/text.
    //
    cxText = rc.right - rc.left + cxIcon + cxFoo;
    cxBox = min(cxBox, max(cxText, cxCaption));
    cxBox = max(cxBox, cxButtons + cxFoo);
    cxText = cxBox - cxFoo - cxIcon;

    //
    // Now we know the text width for sure.  Really calculate how high the
    // text will be.
    //
    rc.left = 0;
    rc.top = 0;
    rc.right = cxText;
    rc.bottom = rcWork.bottom - rcWork.top;
    cyText = DrawTextExW(hdc, (LPWSTR)lpmb->lpszText, -1, &rc, DT_CALCRECT | DT_WORDBREAK
        | DT_EXPANDTABS | DT_NOPREFIX | DT_EXTERNALLEADING | DT_EDITCONTROL, NULL);

    // Find the window size.
    cxBox += 2 * SYSMET(CXFIXEDFRAME);
    cyBox = 2 * SYSMET(CYFIXEDFRAME) + SYSMET(CYCAPTION) + YPixFromYDU(2 * DU_OUTERMARGIN +
        DU_INNERMARGIN + DU_BTNHEIGHT, mbm.cyMsgFontChar);

    cyBox += max(cyIcon, cyText);

    //
    // If the message box doesn't fit on the working area, we'll try wider
    // sizes successively:  6/8 of work then 7/8 of screen.
    //
    if (cyBox > rcWork.bottom - rcWork.top) {
        int cxTemp;

        cxTemp = MulDiv(rcWork.right - rcWork.left, 6, 8);

        if (cxMBMax == MulDiv(rcWork.right - rcWork.left, 5, 8)) {
            cxMBMax = cxTemp;
            goto ReSize;
        }
        else if (cxMBMax == cxTemp) {
            // then let's try with rcMonitor
            CopyRect(&rcWork, &mi.rcMonitor);
            cxMBMax = MulDiv(rcWork.right - rcWork.left, 7, 8);
            goto ReSize;
        }
    }

    if (hFontOld) {
        SelectObject(hdc, hFontOld);
    }
    ReleaseDC(NULL, hdc);

    // Find the window position
    cntMBox = GetClientInfo()->pDeskInfo->cntMBox;

    xMB = (rcWork.left + rcWork.right - cxBox) / 2 + (cntMBox * SYSMET(CXSIZE));
    xMB = max(xMB, rcWork.left);
    yMB = (rcWork.top + rcWork.bottom - cyBox) / 2 + (cntMBox * SYSMET(CYSIZE));
    yMB = max(yMB, rcWork.top);

    //
    // Bottom, right justify if we're going off the screen--but leave a
    // little gap.
    //
    if (xMB + cxBox > rcWork.right) {
        xMB = rcWork.right - SYSMET(CXEDGE) - cxBox;
    }

    //
    // Pin to the working area.  If it won't fit, then pin to the screen
    // height.  Bottom justify it at least if too big even for that, so
    // that the buttons are visible.
    //
    if (yMB + cyBox > rcWork.bottom) {
        yMB = rcWork.bottom - SYSMET(CYEDGE) - cyBox;
        if (yMB < rcWork.top) {
            yMB = mi.rcMonitor.bottom - SYSMET(CYEDGE) - cyBox;
        }
    }

    wTextLen = wcslen(lpmb->lpszText);

    // Find out the memory required for the Dlg template and try to alloc it
    hTemplate = LocalAlloc(LPTR, MB_FindDlgTemplateSize(lpmb));
    if (!hTemplate) {
        goto SMB_Exit;
    }

    lpDlgTmp = (LPBYTE)hTemplate;

    //
    // Setup the dialog style for the message box
    //
    dwStyleDlg = WS_POPUPWINDOW | WS_CAPTION | DS_ABSALIGN | DS_NOIDLEMSG |
        DS_SETFONT | DS_3DLOOK;

    if ((dwStyleMsg & MB_MODEMASK) == MB_SYSTEMMODAL) {
        dwStyleDlg |= DS_SYSMODAL | DS_SETFOREGROUND;
    }
    else {
        dwStyleDlg |= DS_MODALFRAME | WS_SYSMENU;
    }

    if (dwStyleMsg & MB_SETFOREGROUND) {
        dwStyleDlg |= DS_SETFOREGROUND;
    }

    // Add the Header of the Dlg Template
    // BOGUS !!!  don't ADD bools
    lpDlgTmp = MB_UpdateDlgHdr((LPDLGTEMPLATE)lpDlgTmp, dwStyleDlg, dwExStyleMsg,
        (BYTE)(lpmb->cButtons + (wIconOrdNum != 0) + (lpmb->lpszText != NULL)),
        xMB, yMB, cxBox, cyBox, (LPWSTR)lpmb->lpszCaption, wCaptionLen);

    //
    // Center the buttons
    //

    cxFoo = (cxBox - 2 * SYSMET(CXFIXEDFRAME) - cxButtons) / 2;

    lpDlgTmp = MB_AddPushButtons((LPDLGITEMTEMPLATE)lpDlgTmp, lpmb, cxFoo,
        cyBox - SYSMET(CYCAPTION) - (2 * SYSMET(CYFIXEDFRAME)) -
        YPixFromYDU(DU_OUTERMARGIN, mbm.cyMsgFontChar));

    // Add Icon, if any, to the Dlg template
    //
    // The icon is always top justified.  If the text is shorter than the
    // height of the icon, we center it.  Otherwise the text will start at
    // the top.
    //
    if (wIconOrdNum) {
        OrdNum[0] = 0xFFFF;  // To indicate that an Ordinal number follows
        OrdNum[1] = (WORD)wIconOrdNum;

        lpDlgTmp = MB_UpdateDlgItem((LPDLGITEMTEMPLATE)lpDlgTmp, IDUSERICON,        // Control Id
            SS_ICON | WS_GROUP | WS_CHILD | WS_VISIBLE, 0,
            XPixFromXDU(DU_OUTERMARGIN, mbm.cxMsgFontChar),   // X co-ordinate
            YPixFromYDU(DU_OUTERMARGIN, mbm.cyMsgFontChar),   // Y co-ordinate
            0, 0,          // For Icons, CX and CY are ignored, can be zero
            (LPWSTR)OrdNum,    // Ordinal number of Icon
            ARRAYSIZE(OrdNum), // Length of OrdNum
            STATICCODE);
    }

    // Add the Text of the Message to the Dlg Template
    if (lpmb->lpszText) {
        //
        // Center the text if shorter than the icon.
        //
        if (cyText >= cyIcon)
            cxFoo = 0;
        else
            cxFoo = (cyIcon - cyText) / 2;

        dwStyleText = SS_NOPREFIX | WS_GROUP | WS_CHILD | WS_VISIBLE | SS_EDITCONTROL;
        if (dwStyleMsg & MB_RIGHT) {
            dwStyleText |= SS_RIGHT;
            xText = cxBox - (SYSMET(CXSIZE) + cxText);
        }
        else {
            dwStyleText |= SS_LEFT;
            xText = cxIcon + XPixFromXDU(DU_INNERMARGIN, mbm.cxMsgFontChar);
        }

        MB_UpdateDlgItem((LPDLGITEMTEMPLATE)lpDlgTmp, -1, dwStyleText, dwExStyleMsg, xText,
            YPixFromYDU(DU_OUTERMARGIN, mbm.cyMsgFontChar) + cxFoo,
            cxText, cyText,
            (LPWSTR)lpmb->lpszText, wTextLen, STATICCODE);
    }

    // The dialog template is ready

    //
    // Set the normal cursor
    //
    hcurOld = SetCursor(LoadCursorW(NULL, IDC_ARROW));

    lpmb->lpszIcon = (LPWSTR)hIcon;

    if (!(lpmb->dwStyle & MB_USERICON))
    {
        int wBeep = LOWORD(lpmb->dwStyle & MB_ICONMASK);
        if (NtUserMessageBeep)
            NtUserMessageBeep(wBeep);
        else
            NtUserCallOneParam(wBeep, SFI_PLAYEVENTSOUND);
    }

    iRetVal = (int)DialogBoxIndirectParamW(g_hUser32,
        (LPCDLGTEMPLATEW)hTemplate, hwndOwner,
        MB_DlgProc, (LPARAM)lpmb);

    //
    // Fix up return value
    if (iRetVal == -1)
        iRetVal = 0;                /* Messagebox should also return error */

    //
    // If the messagebox contains only OK button, then its ID is changed as
    // IDCANCEL in MB_DlgProc; So, we must change it back to IDOK irrespective
    // of whether ESC is pressed or Carriage return is pressed;
    //
    if (((dwStyleMsg & MB_TYPEMASK) == MB_OK) && iRetVal)
        iRetVal = IDOK;


    //
    // Restore the previous cursor
    //
    if (hcurOld)
        SetCursor(hcurOld);

SMB_Exit:
    if (hTemplate)
    {
        LocalFree(hTemplate);
    }

    if (hCaption)
    {
        LocalFree(hCaption);
    }

    if (hText)
    {
        LocalFree(hText);
    }

    if (mbm.hCaptionFont)
    {
        DeleteObject(mbm.hCaptionFont);
    }

    if (mbm.hMessageFont)
    {
        DeleteObject(mbm.hMessageFont);
    }

    return iRetVal;
}

int (WINAPI *SoftModalMessageBox_orig)(LPMSGBOXDATA);
int WINAPI SoftModalMessageBox_hook(LPMSGBOXDATA lpmb)
{
    if (g_mbStyle != MBS_VISTA)
        return SoftModalMessageBox_XP(lpmb);
    return SoftModalMessageBox_orig(lpmb);
}

#pragma endregion // "Classic style"

void LoadSettings(void)
{
    LPCWSTR pszStyle = Wh_GetStringSetting(L"style");
    if (0 == wcscmp(pszStyle, L"nt4"))
    {
        g_mbStyle = MBS_NT4;
    }
    else if (0 == wcscmp(pszStyle, L"xp"))
    {
        g_mbStyle = MBS_XP;
    }
    else
    {
        g_mbStyle = MBS_VISTA;
    }
    Wh_FreeStringSetting(pszStyle);
}

const WindhawkUtils::SYMBOL_HOOK user32DllHooks[] = {
    {
        {
            L"struct HFONT__ * "
#ifdef _WIN64
            L"__cdecl"
#else
            L"__stdcall"
#endif
            L" GetMessageBoxFontForDpi(unsigned int)"
        },
        &GetMessageBoxFontForDpi_orig,
        GetMessageBoxFontForDpi_hook,
        false
    }
};

BOOL Wh_ModInit(void)
{
    LoadSettings();

    // Load undocumented functions for playing message box sound and incrementing message box count
    HMODULE hWin32U = GetModuleHandleW(L"win32u.dll");
    if (!hWin32U)
    {
        Wh_Log(L"Failed to get handle to win32u.dll");
        return FALSE;
    }
    NtUserCallOneParam = (NtUserCallOneParam_t)GetProcAddress(hWin32U, "NtUserCallOneParam");
    NtUserMessageBeep = (NtUserMessageBeep_t)GetProcAddress(hWin32U, "NtUserMessageBeep");
    if (!NtUserCallOneParam && !NtUserMessageBeep)
    {
        Wh_Log(L"Failed to find NtUserCallOneParam or NtUserMessageBeep in win32u.dll");
        return FALSE;
    }

    NtUserCallHwnd = (NtUserCallHwnd_t)GetProcAddress(hWin32U, "NtUserCallHwnd");
    NtUserSetMsgBox = (NtUserSetMsgBox_t)GetProcAddress(hWin32U, "NtUserSetMsgBox");
    if (!NtUserCallHwnd && !NtUserSetMsgBox)
    {
        Wh_Log(L"Failed to find NtUserCallHwnd or NtUserSetMsgBox in win32u.dll");
        return FALSE;
    }

    g_hUser32 = GetModuleHandleW(L"user32.dll");
    void *SoftModalMessageBox = (void *)GetProcAddress(g_hUser32, "SoftModalMessageBox");
    if (!SoftModalMessageBox)
    {
        Wh_Log(L"Failed to find SoftModalMessageBox in user32.dll");
        return FALSE;
    }

    if (!Wh_SetFunctionHook(
        SoftModalMessageBox,
        (void *)SoftModalMessageBox_hook,
        (void **)&SoftModalMessageBox_orig
    ))
    {
        Wh_Log(L"Failed to hook SoftModalMessageBox in user32.dll");
        return FALSE;
    }

    if (!WindhawkUtils::HookSymbols(
        g_hUser32,
        user32DllHooks,
        ARRAYSIZE(user32DllHooks)
    ))
    {
        Wh_Log(L"Failed to hook GetMessageBoxFontForDpi in user32.dll");
        return FALSE;
    }

    return TRUE;
}

void Wh_ModSettingsChanged(void)
{
    LoadSettings();
}

}  // namespace MsgBoxFontFix
#undef MAX_RES_STRING
#undef UNICODE_RLM
#undef IDUSERICON
#undef BUTTONCODE
#undef STATICCODE
#undef SFI_PLAYEVENTSOUND
#undef SFI_SETMSGBOX
#undef MAXUSHORT
#undef IS_PTR
#undef PTR_TO_ID
#undef SYSMET
#undef XPixFromXDU
#undef YPixFromYDU
#undef XDUFromXPix
#undef YDUFromYPix
#undef NextWordBoundary
#undef NextDWordBoundary
#undef USERGLOBALLOCK
#undef USERGLOBALUNLOCK
#undef max
#undef min
#undef DU_OUTERMARGIN
#undef DU_INNERMARGIN
#undef DU_BTNGAP
#undef DU_BTNHEIGHT
#undef DU_BTNWIDTH

// ============================================================
// ===== modernize-folder-picker-dialog
// ============================================================
namespace ModernizeFolderPicker {

#define RETURN_IF_FAILED(hr) if (FAILED(hr)) return SHBrowseForFolderW_orig(lpbi)

#define E_CANCELLED (HRESULT)0x800704C7


using SHBrowseForFolderW_t = decltype(&SHBrowseForFolderW);
SHBrowseForFolderW_t SHBrowseForFolderW_orig = nullptr;
PIDLIST_ABSOLUTE WINAPI SHBrowseForFolderW_hook(
    LPBROWSEINFOW lpbi
)
{
    if (!lpbi) return NULL;

    /* Make the dialog */
    winrt::com_ptr<IFileOpenDialog> pDialog = nullptr;
    RETURN_IF_FAILED(CoCreateInstance(
        CLSID_FileOpenDialog,
        NULL,
        CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&pDialog)
    ));

    /* Make it pick a folder instead of a file */
    RETURN_IF_FAILED(pDialog->SetOptions(
        FOS_PICKFOLDERS | FOS_PATHMUSTEXIST | FOS_FILEMUSTEXIST
    ));

    if (lpbi->lpszTitle && *lpbi->lpszTitle)
    {
        RETURN_IF_FAILED(pDialog->SetTitle(lpbi->lpszTitle));
    }

    /* Tell it where to start */
    if (lpbi->pidlRoot)
    {
        /* We have to convert from PIDLIST_ABSOLUTE -> IShellItem * */
        winrt::com_ptr<IShellItem> pRoot = nullptr;
        RETURN_IF_FAILED(SHCreateItemFromIDList(
            lpbi->pidlRoot,
            IID_PPV_ARGS(&pRoot)
        ));
        RETURN_IF_FAILED(pDialog->SetFolder(pRoot.get()));
    }

    HRESULT hr = pDialog->Show(lpbi->hwndOwner);
    if (FAILED(hr))
    {
        /* For whatever reason, the dialog being cancelled counts as a fail */
        if (hr != E_CANCELLED)
        {
            return SHBrowseForFolderW_orig(lpbi);
        }
        else
        {
            return NULL;
        }
    }

    IShellItem *pResult = nullptr;
    RETURN_IF_FAILED(pDialog->GetResult(&pResult));

    LPWSTR pszPath = nullptr;
    hr = pResult->GetDisplayName(SIGDN_FILESYSPATH, &pszPath);
    pResult->Release();
    pResult = nullptr;
    RETURN_IF_FAILED(hr);

    /* Convert from wide character string to PIDLIST_ABSOLUTE */
    if (pszPath) {
        PIDLIST_ABSOLUTE result = ILCreateFromPathW(pszPath);
        CoTaskMemFree(pszPath);
        return result;
    }

    return NULL;
}

BOOL Wh_ModInit(void)
{
    if (!WindhawkUtils::Wh_SetFunctionHookT(
        SHBrowseForFolderW,
        SHBrowseForFolderW_hook,
        &SHBrowseForFolderW_orig
    ))
    {
        Wh_Log(L"Failed to hook SHBrowseForFolderW");
        return FALSE;
    }

    return TRUE;
}

}  // namespace ModernizeFolderPicker
#undef RETURN_IF_FAILED
#undef E_CANCELLED

// ============================================================
// ===== classic-file-picker-dialog
// ============================================================
namespace ClassicFilePickerDialog {

#ifdef _WIN64
#define CALCON __cdecl
#define SCALCON L" __cdecl "
#else
#define CALCON __thiscall
#define SCALCON L" __stdcall "
#endif

typedef int (CALCON *IsCommonItemDialogAvailable)(void);
IsCommonItemDialogAvailable IsCommonItemDialogAvailable_orig;

int CALCON IsCommonItemDialogAvailable_hook(void) {return 0;}

typedef long (CALCON *CFileOpenSave__s_CreateInstance)(int, GUID*, void**);
CFileOpenSave__s_CreateInstance CFileOpenSave__s_CreateInstance_orig;

long CALCON CFileOpenSave__s_CreateInstance_hook(int param_1, GUID *param_2, void **param_3) {
    param_1 = (param_1 > 1) ? param_1 -= 2 : param_1;
    return CFileOpenSave__s_CreateInstance_orig(param_1, param_2, param_3);
}

BOOL Wh_ModInit() {
    HMODULE module = LoadLibrary(L"comdlg32.dll");

    WindhawkUtils::SYMBOL_HOOK comdlg32DllHooks[] = {
        {
            {L"int" SCALCON L"IsCommonItemDialogAvailable(void)"},
            (void**)&IsCommonItemDialogAvailable_orig,
            (void*)IsCommonItemDialogAvailable_hook,
        },
        {
            {L"public: static long" SCALCON L"CFileOpenSave::s_CreateInstance(enum DIALOGINITFLAGS,struct _GUID const &,void * *)"},
            (void**)&CFileOpenSave__s_CreateInstance_orig,
            (void*)CFileOpenSave__s_CreateInstance_hook,
        }
    };

    WindhawkUtils::HookSymbols(module, comdlg32DllHooks, ARRAYSIZE(comdlg32DllHooks));

    return TRUE;
}

}  // namespace ClassicFilePickerDialog
#undef CALCON
#undef SCALCON

// ============================================================
// ===== eradicate-immersive-menus
// ============================================================
namespace EradicateImmersiveMenus {

struct {
    BOOL explorer;
    /* Tray icons are always 64-bit */
#ifdef _WIN64
    BOOL sound;
    BOOL network;
    BOOL defender;
    BOOL nosettingsicon;
    BOOL narrator;
#endif
} settings;

/* ImmersiveContextMenuHelper::CanApplyOwnerDrawToMenu */
typedef bool (__fastcall *ICMH_CAODTM_t)(HMENU, HWND);

#define ORIG(MODULE) \
ICMH_CAODTM_t ICMH_CAODTM_orig_ ## MODULE = nullptr;

ORIG(shell32)
ORIG(ExplorerFrame)
/* Explorer and tray icons are always 64-bit */
#ifdef _WIN64
ORIG(explorer)
ORIG(twinui)
ORIG(twinui_pcshell)
ORIG(SndVolSSO)
ORIG(pnidui)
ORIG(SecurityHealthSSO)
ORIG(Narrator)
#endif

/** 
  * __fastcall is needed, or else stack corruption occurs
  * in x86-32 applications.
  */
bool __fastcall ICMH_CAODTM_hook(
    HMENU hMenu,
    HWND hWnd
)
{
    return false;
}

/* Prevent "Taskbar settings" icon from being set */
#ifdef _WIN64
using SetMenuItemInfoW_t = decltype(&SetMenuItemInfoW);
SetMenuItemInfoW_t SetMenuItemInfoW_orig;
BOOL SetMenuItemInfoW_hook(
    HMENU            hMenu,
    UINT             item,
    BOOL             fByPosition,
    LPCMENUITEMINFOW lpmii
)
{
    /* homestuck reference??? */
    if (settings.nosettingsicon && (!fByPosition && item == 413))
    {
        return TRUE;
    }

    return SetMenuItemInfoW_orig(
        hMenu,
        item,
        fByPosition,
        lpmii
    );
}
#endif

/**
  * Hooks ImmersiveContextMenuHelper::CanApplyOwnerDrawToMenu for a given DLL.
  * There are many DLLs that have this function, so each one needs to be accounted for.
  */
inline bool HookICMH_CAODTM(LPCWSTR lpDll, ICMH_CAODTM_t *pOrig)
{
    HMODULE hModule;

    /* If lpDll is NULL, patch the current process instead */
    if (lpDll == NULL)
    {
        hModule = GetModuleHandleW(NULL);
    }
    else
    {
        hModule = LoadLibraryW(lpDll);
    }

    if (!hModule)
    {
        Wh_Log(L"Failed to load %s", lpDll);
        return false;
    }

    WindhawkUtils::SYMBOL_HOOK hook = {
        {
            L"bool "
#ifdef _WIN64
            L"__cdecl"
#else
            L"__stdcall"
#endif
            L" ImmersiveContextMenuHelper::CanApplyOwnerDrawToMenu(struct HMENU__ *,struct HWND__ *)"
        },
        pOrig,
        ICMH_CAODTM_hook,
        true
    };

    bool bHookSuccess = WindhawkUtils::HookSymbols(
        hModule,
        &hook,
        1
    );

    if (bHookSuccess)
    {
        return true;
    }

    Wh_Log(
        L"Failed to hook ImmersiveContextMenuHelper::CanApplyOwnerDrawToMenu in %s.",
        lpDll ? lpDll : L"explorer.exe"
    );
    return false;
}

#define LoadIntSetting(NAME) \
settings.NAME = Wh_GetIntSetting(L ## #NAME)

void LoadSettings()
{
    LoadIntSetting(explorer);
    /* Tray icons are always 64-bit */
#ifdef _WIN64
    LoadIntSetting(sound);
    LoadIntSetting(network);
    LoadIntSetting(defender);
    LoadIntSetting(nosettingsicon);
    LoadIntSetting(narrator);
#endif
}

#define HOOK(MODULE) \
HookICMH_CAODTM(L ## #MODULE L".dll", &ICMH_CAODTM_orig_ ## MODULE)

#define HOOK_SAFE(MODULE, MODULE_SAFE) \
HookICMH_CAODTM(L ## MODULE L".dll", &ICMH_CAODTM_orig_ ## MODULE_SAFE)

#define HOOK_SELF(NAME) \
HookICMH_CAODTM(NULL, &ICMH_CAODTM_orig_ ## NAME)

BOOL Wh_ModInit()
{
    LoadSettings();

    /* Explorer is always 64-bit */
#ifdef _WIN64
    WCHAR szProcessPath[MAX_PATH];
    GetModuleFileNameW(NULL, szProcessPath, MAX_PATH);
    bool bIsExplorer = (0 == wcsicmp(szProcessPath, L"C:\\Windows\\explorer.exe"));

    if (settings.nosettingsicon && bIsExplorer)
    {
        Wh_SetFunctionHook(
            (void *)SetMenuItemInfoW,
            (void *)SetMenuItemInfoW_hook,
            (void **)&SetMenuItemInfoW_orig
        );
    }
#endif

    if (settings.explorer
#ifdef _WIN64
    && 0 != wcsicmp(szProcessPath, L"C:\\Windows\\System32\\SecurityHealthSystray.exe")
#endif
    )
    {
        HOOK(shell32);
        HOOK(ExplorerFrame);
        
        /* Explorer itself is always 64-bit */
#ifdef _WIN64
        if (bIsExplorer)
        {
            HOOK_SELF(explorer);
            HOOK(twinui);
            HOOK_SAFE("twinui.pcshell", twinui_pcshell);
        }
#endif
    }

    /* Tray icons are always 64-bit */
#ifdef _WIN64
    if (bIsExplorer)
    {
        if (settings.sound)
        {
            HOOK(SndVolSSO);
        }

        if (settings.network)
        {
            HOOK(pnidui);
        }
    }

    if (settings.defender
    &&  0 == wcsicmp(szProcessPath, L"C:\\Windows\\System32\\SecurityHealthSystray.exe"))
    {
        HOOK(SecurityHealthSSO);
    }

    if (settings.narrator
    &&  0 == wcsicmp(szProcessPath, L"C:\\Windows\\System32\\Narrator.exe"))
    {
        HOOK_SELF(Narrator);
    }
#endif

    return TRUE;
}

BOOL Wh_ModSettingsChanged(BOOL *bReload)
{
    *bReload = TRUE;
    return TRUE;
}

}  // namespace EradicateImmersiveMenus
#undef ORIG
#undef LoadIntSetting
#undef HOOK
#undef HOOK_SAFE
#undef HOOK_SELF

// ============================================================
// ===== dwm-unextend (inline)
// ============================================================
namespace DwmUnextend {

// DWM Unextend Frames (Office/ribbon titlebar fix). Mirrors the DWM-frame
// hooks of the "DWM Unextend Frames" mod. classic-theme-transparency-fix
// already hooks DwmIsCompositionEnabled + IsCompositionActive, so we add only
// the frame/blur/attribute hooks here (no double-hook).
//
// The key: return DWM_E_COMPOSITIONDISABLED (NOT S_OK). Office 2007+ draws a
// custom glass caption (Office button + Quick Access toolbar) via
// DwmExtendFrameIntoClientArea. Under classic theme that extended region has
// nothing composited behind it and renders black/transparent. Failing the call
// makes Office fall back to a classic, opaque caption.
const HRESULT kCompositionDisabled = (HRESULT)0x80263001L;  // DWM_E_COMPOSITIONDISABLED
const DWORD   kDwmwaExtendedFrameBounds = 9;                // DWMWA_EXTENDED_FRAME_BOUNDS

typedef HRESULT (WINAPI *DwmExtendFrameIntoClientArea_t)(HWND, const MARGINS*);
DwmExtendFrameIntoClientArea_t DwmExtendFrameIntoClientArea_orig;
HRESULT WINAPI DwmExtendFrameIntoClientArea_hook(HWND hWnd, const MARGINS* pMarInset)
{
    return kCompositionDisabled;
}

typedef HRESULT (WINAPI *DwmEnableBlurBehindWindow_t)(HWND, const void*);
DwmEnableBlurBehindWindow_t DwmEnableBlurBehindWindow_orig;
HRESULT WINAPI DwmEnableBlurBehindWindow_hook(HWND hWnd, const void* pBlurBehind)
{
    return kCompositionDisabled;
}

typedef HRESULT (WINAPI *DwmSetWindowAttribute_t)(HWND, DWORD, LPCVOID, DWORD);
DwmSetWindowAttribute_t DwmSetWindowAttribute_orig;
HRESULT WINAPI DwmSetWindowAttribute_hook(HWND hWnd, DWORD dwAttribute, LPCVOID pvAttribute, DWORD cbAttribute)
{
    if (dwAttribute == kDwmwaExtendedFrameBounds)
    {
        return S_OK;
    }
    return DwmSetWindowAttribute_orig(hWnd, dwAttribute, pvAttribute, cbAttribute);
}

static void HookDwm(HMODULE mod, const char* name, void* hook, void** orig)
{
    FARPROC p = GetProcAddress(mod, name);
    if (p)
    {
        WindhawkUtils::Wh_SetFunctionHookT((void*)p, hook, orig);
    }
}

BOOL Wh_ModInit()
{
    HMODULE dwmapiModule = LoadLibraryExW(L"dwmapi.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!dwmapiModule)
    {
        return FALSE;
    }
    HookDwm(dwmapiModule, "DwmExtendFrameIntoClientArea",
            (void*)DwmExtendFrameIntoClientArea_hook, (void**)&DwmExtendFrameIntoClientArea_orig);
    HookDwm(dwmapiModule, "DwmEnableBlurBehindWindow",
            (void*)DwmEnableBlurBehindWindow_hook, (void**)&DwmEnableBlurBehindWindow_orig);
    HookDwm(dwmapiModule, "DwmSetWindowAttribute",
            (void*)DwmSetWindowAttribute_hook, (void**)&DwmSetWindowAttribute_orig);
    return TRUE;
}

}  // namespace DwmUnextend

// ============================================================
// ===== combined lifecycle
// ============================================================
BOOL Wh_ModInit(void) {
    g_inExplorer = (0 == _wcsicmp(CurrentExeName(), L"explorer.exe"));
    g_inSolidWorks = IsSolidWorks();

    if (g_inSolidWorks) {
        // SolidWorks: only the allowlisted sub-mods run; the others caused
        // Save As dropdown flicker, so they are skipped in this process.
        if (!MsgBoxFontFix::Wh_ModInit()) Wh_Log(L"MsgBoxFontFix::Wh_ModInit failed");
        return TRUE;
    }

    if (g_inExplorer) {
        if (!AeroTray::Wh_ModInit()) Wh_Log(L"AeroTray::Wh_ModInit failed");
        if (!ExplorerFrameClassic::Wh_ModInit()) Wh_Log(L"ExplorerFrameClassic::Wh_ModInit failed");
        if (!ClassicExplorerTreeview::Wh_ModInit()) Wh_Log(L"ClassicExplorerTreeview::Wh_ModInit failed");
        if (!ClassicThemeExplorerLite::Wh_ModInit()) Wh_Log(L"ClassicThemeExplorerLite::Wh_ModInit failed");
        if (!ClassicTaskbarButtonsLite::Wh_ModInit()) Wh_Log(L"ClassicTaskbarButtonsLite::Wh_ModInit failed");
    }

    if (!ClassicTaskdlgFix::Wh_ModInit()) Wh_Log(L"ClassicTaskdlgFix::Wh_ModInit failed");
    if (!ClassicThemeTransparencyFix::Wh_ModInit()) Wh_Log(L"ClassicThemeTransparencyFix::Wh_ModInit failed");
    if (!ClientedgeInApps::Wh_ModInit()) Wh_Log(L"ClientedgeInApps::Wh_ModInit failed");
    if (!MsgBoxFontFix::Wh_ModInit()) Wh_Log(L"MsgBoxFontFix::Wh_ModInit failed");
    if (!ModernizeFolderPicker::Wh_ModInit()) Wh_Log(L"ModernizeFolderPicker::Wh_ModInit failed");
    if (!ClassicFilePickerDialog::Wh_ModInit()) Wh_Log(L"ClassicFilePickerDialog::Wh_ModInit failed");

    if (!IsMaximizedExcluded()) {
        if (!ClassicMaximizedWindowsFix::Wh_ModInit()) Wh_Log(L"ClassicMaximizedWindowsFix::Wh_ModInit failed");
    }

    if (!IsEradicateExcluded()) {
        if (!EradicateImmersiveMenus::Wh_ModInit()) Wh_Log(L"EradicateImmersiveMenus::Wh_ModInit failed");
    }

    if (!IsBrowserExcluded()) {
        if (!DwmUnextend::Wh_ModInit()) Wh_Log(L"DwmUnextend::Wh_ModInit failed");
    }

    return TRUE;
}

void Wh_ModAfterInit(void) {
    if (g_inSolidWorks) {
        return;
    }
    if (g_inExplorer) ExplorerFrameClassic::Wh_ModAfterInit();
}

void Wh_ModUninit(void) {
    if (g_inSolidWorks) {
        return;
    }
    if (g_inExplorer) AeroTray::Wh_ModUninit();
    if (g_inExplorer) ExplorerFrameClassic::Wh_ModUninit();
    if (g_inExplorer) ClassicExplorerTreeview::Wh_ModUninit();
    if (!IsMaximizedExcluded()) ClassicMaximizedWindowsFix::Wh_ModUninit();
}

void Wh_ModSettingsChanged(BOOL* bReload) {
    *bReload = TRUE;
}
