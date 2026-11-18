// ==WindhawkMod==
// @id              cplusruss-w11-shell
// @name            cplusruss W11 Shell
// @description     Experimental classic-style Windows 11 shell tweaks: restyle toast notifications classic-gray (via XAML Diagnostics), plus a Ctrl+Shift+MiddleClick UI element inspector.
// @version         0.3.2
// @author          rlemburg
// @include         explorer.exe
// @include         ShellExperienceHost.exe
// @architecture    x86-64
// @compilerOptions -DWINVER=0x0A00 -lole32 -loleaut32 -lruntimeobject -lshcore -luser32 -ldwmapi -Wl,--export-all-symbols
// ==/WindhawkMod==

// ==WindhawkModReadme==
/*
# cplusruss W11 Shell

A container mod for experimental classic-style shell tweaks.

## Feature: Classic toasts (XAML Diagnostics TAP)

Win11 toast notifications are XAML, hosted in their own `CoreWindow` on a separate
UI thread (in `explorer.exe` on 23H2), so a normal hook can't reach their tree.
This uses the same mechanism as Ramen Software's Notification Center Styler --
stripped to the bone: it injects a XAML Diagnostics TAP (`InitializeXamlDiagnosticsEx`)
and watches the visual tree process-wide/cross-thread. When the toast's background
border (`ToastBackgroundBorder2`) is added, it sets a flat classic-gray look
directly on the live element (which runs on the toast's own thread, so it's safe).

The full style-rule/theme engine is intentionally NOT ported -- only the TAP
plumbing + a hardcoded classic recolor.

## Feature: Element inspector

A worker thread polls for **Ctrl+Shift+MiddleClick** and dumps the UI element
under the cursor (via UI Automation) to the clipboard + a log file.
*/
// ==/WindhawkModReadme==

// ==WindhawkModSettings==
/*
- toasts: true
  $name: Restyle toast notifications
  $description: Master switch for the toast styler (XAML Diagnostics TAP). Turn off to run only the inspector.
- fireTest: false
  $name: "Fire a test toast (button)"
  $description: Toggle on and Save to fire a styled test toast. Toggle off then on again to re-fire.
- bgColor: D4D0C8
  $name: Background color (RRGGBB)
  $description: Classic 3D face is D4D0C8; Win95 silver is C0C0C0.
- squareCorners: true
  $name: Square corners
  $description: Squares the XAML corners AND the toast window itself via DWM (Win11 rounds top-level windows regardless of XAML, so the window must be squared too).
- flatBorder: true
  $name: Flat border
  $description: Solid border in Border color. Takes precedence -- when ON it shows regardless of the 3D raised setting. Turn OFF to use the 3D raised bevel instead.
- borderColor: 808080
  $name: Border color (RRGGBB)
  $description: Used by the flat border.
- removeShadow: true
  $name: Remove drop shadow
- border3d: false
  $name: 3D raised border
  $description: Two-tone bevel (highlight top-left, shadow bottom-right) across the toast's two background borders. Applies ONLY when Flat border is OFF.
- highlightColor: FFFFFF
  $name: 3D highlight color (RRGGBB)
- shadowColor: "404040"
  $name: 3D shadow color (RRGGBB)
- bevel: 2
  $name: 3D bevel width (px)
- iconSize: 40
  $name: App icon size (px)
- headingFont: Arial
  $name: Heading font family
- headingSize: 14
  $name: Heading font size (px; classic point sizes render ~1.33x larger)
- headingBold: true
  $name: Heading bold
- bodyFont: Tahoma
  $name: Body font family
- bodySize: 8
  $name: Body font size (px)
- senderFont: Tahoma
  $name: Sender (app name) font family
- senderSize: 14
  $name: Sender font size (px)
- senderBold: false
  $name: Sender bold
- inspector: true
  $name: Element inspector (Ctrl+Shift+MiddleClick)
  $description: Dumps the UI element under the cursor to the clipboard + log file.
- inspectorLog: auto
  $name: Inspector log path
  $description: File to append captures to. "auto" = %TEMP%\cplusruss-w11-shell-inspect.log
*/
// ==/WindhawkModSettings==

#include <windhawk_api.h>
#include <windhawk_utils.h>

// winbase.h (via windhawk_api.h) defines GetCurrentTime() as a macro that
// collides with the C++/WinRT XAML GetCurrentTime method. Undef before winrt.
#undef GetCurrentTime

#include <Unknwn.h>
#include <combaseapi.h>
#include <ocidl.h>
#include <uiautomation.h>
#include <xamlom.h>

#include <winrt/base.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.UI.h>
#include <winrt/Windows.UI.Core.h>
#include <dwmapi.h>
#include <winrt/Windows.UI.Text.h>
#include <winrt/Windows.UI.Xaml.h>
#include <winrt/Windows.UI.Xaml.Controls.h>
#include <winrt/Windows.UI.Xaml.Media.h>
#include <winrt/Windows.Data.Xml.Dom.h>
#include <winrt/Windows.UI.Notifications.h>

#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <string_view>

namespace wf = winrt::Windows::Foundation;
namespace wux = winrt::Windows::UI::Xaml;

// ============================================================================
// Feature: Classic toasts -- minimal XAML Diagnostics TAP
//
// Ported (stripped) from ramensoftware Notification Center Styler. The TAP gives
// a process-wide, cross-thread view of the XAML tree, which is how we reach the
// toast living on its own CoreWindow thread.
// ============================================================================

// --- Settings ---------------------------------------------------------------
struct ToastCfg {
    uint32_t bg = 0xD4D0C8;
    uint32_t border = 0x808080;
    bool squareCorners = true;
    bool flatBorder = true;
    bool removeShadow = true;
    bool border3d = false;
    uint32_t hi = 0xFFFFFF;
    uint32_t sh = 0x404040;
    int bevel = 2;
    double iconSize = 40;
    std::wstring headingFont = L"Arial";
    double headingSize = 14;
    bool headingBold = true;
    std::wstring bodyFont = L"Tahoma";
    double bodySize = 8;
    std::wstring senderFont = L"Tahoma";
    double senderSize = 14;
    bool senderBold = false;
};
ToastCfg g_toastCfg;

static uint32_t ParseHexColor(PCWSTR s, uint32_t fallback) {
    if (!s || !*s) return fallback;
    if (*s == L'#') s++;
    wchar_t* end = nullptr;
    unsigned long v = wcstoul(s, &end, 16);
    if (end == s) return fallback;
    return static_cast<uint32_t>(v & 0xFFFFFF);
}

static void LoadToastCfg() {
    PCWSTR bg = Wh_GetStringSetting(L"bgColor");
    g_toastCfg.bg = ParseHexColor(bg, 0xD4D0C8);
    Wh_FreeStringSetting(bg);
    PCWSTR bc = Wh_GetStringSetting(L"borderColor");
    g_toastCfg.border = ParseHexColor(bc, 0x808080);
    Wh_FreeStringSetting(bc);
    g_toastCfg.squareCorners = Wh_GetIntSetting(L"squareCorners") != 0;
    g_toastCfg.flatBorder = Wh_GetIntSetting(L"flatBorder") != 0;
    g_toastCfg.removeShadow = Wh_GetIntSetting(L"removeShadow") != 0;
    g_toastCfg.border3d = Wh_GetIntSetting(L"border3d") != 0;
    PCWSTR hc = Wh_GetStringSetting(L"highlightColor");
    g_toastCfg.hi = ParseHexColor(hc, 0xFFFFFF);
    Wh_FreeStringSetting(hc);
    PCWSTR sc = Wh_GetStringSetting(L"shadowColor");
    g_toastCfg.sh = ParseHexColor(sc, 0x404040);
    Wh_FreeStringSetting(sc);
    g_toastCfg.bevel = Wh_GetIntSetting(L"bevel");
    if (g_toastCfg.bevel < 1) g_toastCfg.bevel = 2;
    g_toastCfg.iconSize = static_cast<double>(Wh_GetIntSetting(L"iconSize"));
    if (g_toastCfg.iconSize < 1) g_toastCfg.iconSize = 40;
    PCWSTR hf = Wh_GetStringSetting(L"headingFont");
    g_toastCfg.headingFont = (hf && *hf) ? std::wstring(hf) : L"Arial";
    Wh_FreeStringSetting(hf);
    g_toastCfg.headingSize = static_cast<double>(Wh_GetIntSetting(L"headingSize"));
    if (g_toastCfg.headingSize < 1) g_toastCfg.headingSize = 14;
    g_toastCfg.headingBold = Wh_GetIntSetting(L"headingBold") != 0;
    PCWSTR bf = Wh_GetStringSetting(L"bodyFont");
    g_toastCfg.bodyFont = (bf && *bf) ? std::wstring(bf) : L"Tahoma";
    Wh_FreeStringSetting(bf);
    g_toastCfg.bodySize = static_cast<double>(Wh_GetIntSetting(L"bodySize"));
    if (g_toastCfg.bodySize < 1) g_toastCfg.bodySize = 8;
    PCWSTR sf = Wh_GetStringSetting(L"senderFont");
    g_toastCfg.senderFont = (sf && *sf) ? std::wstring(sf) : L"Tahoma";
    Wh_FreeStringSetting(sf);
    g_toastCfg.senderSize = static_cast<double>(Wh_GetIntSetting(L"senderSize"));
    if (g_toastCfg.senderSize < 1) g_toastCfg.senderSize = 14;
    g_toastCfg.senderBold = Wh_GetIntSetting(L"senderBold") != 0;
}

static winrt::Windows::UI::Color MakeColor(uint32_t rgb) {
    return winrt::Windows::UI::Color{
        0xFF,
        static_cast<uint8_t>((rgb >> 16) & 0xFF),
        static_cast<uint8_t>((rgb >> 8) & 0xFF),
        static_cast<uint8_t>(rgb & 0xFF),
    };
}

// ICoreWindowInterop -- to recover the toast CoreWindow's HWND for the DWM call.
// (No __declspec(uuid): Windhawk's MinGW clang doesn't support __uuidof, so we
// QueryInterface with the explicit IID off the CoreWindow's raw ABI pointer.)
struct ICoreWindowInterop : ::IUnknown {
    virtual HRESULT __stdcall get_WindowHandle(HWND* hwnd) = 0;
    virtual HRESULT __stdcall put_MessageHandled(unsigned char value) = 0;
};
static const GUID IID_ICoreWindowInterop =
    {0x45D64A29, 0xA63E, 0x4CB6, {0xB4, 0x98, 0x57, 0x81, 0xD2, 0x98, 0xCB, 0x4F}};
#ifndef DWMWA_WINDOW_CORNER_PREFERENCE
#define DWMWA_WINDOW_CORNER_PREFERENCE 33
#endif

// Square the toast's WINDOW corners. Win11's DWM rounds top-level window corners
// regardless of XAML CornerRadius -- so squaring the XAML borders alone can't do it.
// We set DWMWCP_DONOTROUND on the toast HWND. This runs on the toast's own UI thread
// (ApplyCustomizations does), so CoreWindow::GetForCurrentThread() is the toast window.
static void SquareToastWindow() {
    auto cw = winrt::Windows::UI::Core::CoreWindow::GetForCurrentThread();
    if (!cw) return;
    auto unk = reinterpret_cast<::IUnknown*>(winrt::get_abi(cw));
    if (!unk) return;
    ICoreWindowInterop* interop = nullptr;
    if (FAILED(unk->QueryInterface(IID_ICoreWindowInterop, reinterpret_cast<void**>(&interop))) || !interop)
        return;
    HWND hwnd = nullptr;
    HRESULT hr = interop->get_WindowHandle(&hwnd);
    interop->Release();
    if (FAILED(hr) || !hwnd) return;
    DWORD pref = 1;  // DWMWCP_DONOTROUND
    DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, &pref, sizeof(pref));
}

static void ApplyBgBorder(wux::Controls::Border border, bool isBorder2) {
    if (g_toastCfg.squareCorners) { border.CornerRadius(wux::CornerRadius{0, 0, 0, 0}); SquareToastWindow(); }
    border.Background(wux::Media::SolidColorBrush(MakeColor(g_toastCfg.bg)));
    // Border styles are now precedence-clear (no silent override): a flat border in
    // borderColor takes precedence and applies regardless of the 3D toggle; the 3D
    // raised bevel applies only when the flat border is off; neither -> no border.
    if (g_toastCfg.flatBorder) {
        border.BorderThickness(wux::Thickness{1, 1, 2, 2});
        border.BorderBrush(wux::Media::SolidColorBrush(MakeColor(g_toastCfg.border)));
    } else if (g_toastCfg.border3d) {
        double w = static_cast<double>(g_toastCfg.bevel);
        if (isBorder2) {
            border.BorderThickness(wux::Thickness{w, w, 0, 0});
            border.BorderBrush(wux::Media::SolidColorBrush(MakeColor(g_toastCfg.hi)));
        } else {
            border.BorderThickness(wux::Thickness{0, 0, w, w});
            border.BorderBrush(wux::Media::SolidColorBrush(MakeColor(g_toastCfg.sh)));
        }
    } else {
        border.BorderThickness(wux::Thickness{0, 0, 0, 0});
    }
}

static void ApplyFont(wux::Controls::TextBlock tb, std::wstring const& family,
                      double size, bool bold) {
    if (!family.empty()) tb.FontFamily(wux::Media::FontFamily(winrt::hstring{family}));
    if (size > 0) tb.FontSize(size);
    tb.FontWeight(bold ? winrt::Windows::UI::Text::FontWeights::Bold()
                       : winrt::Windows::UI::Text::FontWeights::Normal());
}

// DIAG: append a line to %TEMP%\cplusruss-w11-shell-toasttree.log (reliable file I/O;
// the Windhawk Wh_Log isn't always captured). Used to dump the live toast subtree so
// the REAL visible-border element is identifiable.
static void AppendToastTree(const wchar_t* text) {
    wchar_t path[MAX_PATH];
    DWORD n = GetTempPathW(MAX_PATH, path);
    if (!n || n >= MAX_PATH) return;
    wcscat_s(path, MAX_PATH, L"cplusruss-w11-shell-toasttree.log");
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    WriteFile(h, text, static_cast<DWORD>(wcslen(text) * sizeof(wchar_t)), &written, nullptr);
    CloseHandle(h);
}

// DIAG: recurse the visual tree, logging each node's runtime class + Name + size +
// whether it's a Border. winrt::get_class_name names even unnamed/visual-only elements.
static void DumpToastSubtree(wux::DependencyObject node, int depth) {
    if (!node || depth > 40) return;
    std::wstring line(static_cast<size_t>(depth) * 2, L' ');
    try { line += std::wstring(winrt::get_class_name(node)); } catch (...) { line += L"?"; }
    if (auto fe = node.try_as<wux::FrameworkElement>()) {
        auto nm = fe.Name();
        line += L"  name=";
        line += (nm.empty() ? std::wstring(L"-") : std::wstring(nm));
        line += L"  " + std::to_wstring(static_cast<int>(fe.ActualWidth())) +
                L"x" + std::to_wstring(static_cast<int>(fe.ActualHeight()));
    }
    if (node.try_as<wux::Controls::Border>()) line += L"  [Border]";
    line += L"\n";
    AppendToastTree(line.c_str());
    int cnt = wux::Media::VisualTreeHelper::GetChildrenCount(node);
    for (int i = 0; i < cnt; i++)
        DumpToastSubtree(wux::Media::VisualTreeHelper::GetChild(node, i), depth + 1);
}

// Called on the element's own UI thread (so direct WinRT mutation is safe).
void ApplyCustomizations(InstanceHandle, wux::FrameworkElement element, PCWSTR) {
    auto nameHs = element.Name();
    std::wstring_view name{nameHs};
    if (name.empty()) return;

    // Gray background on both concentric background borders; a real two-tone
    // raised bevel split between them -- Border2 paints the highlight (top+left),
    // Border the shadow (bottom+right) -- which a single XAML Border can't do.
    if (name == L"ToastBackgroundBorder2" || name == L"ToastBackgroundBorder") {
        if (auto border = element.try_as<wux::Controls::Border>()) {
            bool is2 = (name == L"ToastBackgroundBorder2");
            ApplyBgBorder(border, is2);
            // On Add the toast banner is still composing, so the first pass can be
            // missed until the user interacts -- re-apply once it finishes loading.
            border.Loaded([is2](winrt::Windows::Foundation::IInspectable const& s,
                                wux::RoutedEventArgs const&) {
                if (auto b = s.try_as<wux::Controls::Border>()) ApplyBgBorder(b, is2);
            });
            Wh_Log(L"[W11Shell] styler: styled %s", nameHs.c_str());
        }
    }

    // Peek/overlay borders shown during the entrance, plus the acrylic highlight --
    // gray them too so the toast looks styled the instant it appears, not only after
    // the entrance settles or on hover.
    if (name == L"ToastBorder" || name == L"ToastPeekRegionBorder" ||
        name == L"ToastAcrylicHightlightBorder") {
        if (auto b = element.try_as<wux::Controls::Border>()) {
            if (g_toastCfg.squareCorners) { b.CornerRadius(wux::CornerRadius{0, 0, 0, 0}); SquareToastWindow(); }
            b.Background(wux::Media::SolidColorBrush(MakeColor(g_toastCfg.bg)));
            // The visible card EDGE on modern FlexibleToastView toasts is ToastBorder,
            // not the inner ToastBackgroundBorder (which sits behind it) -- so the flat
            // border has to go here to actually be seen. (The 3D bevel still relies on
            // the inner Border2/Border two-tone split.)
            if (name == L"ToastBorder") {
                if (g_toastCfg.flatBorder) {
                    b.BorderThickness(wux::Thickness{1, 1, 2, 2});
                    b.BorderBrush(wux::Media::SolidColorBrush(MakeColor(g_toastCfg.border)));
                } else if (!g_toastCfg.border3d) {
                    b.BorderThickness(wux::Thickness{0, 0, 0, 0});
                }
            }
            Wh_Log(L"[W11Shell] styler: styled overlay %s", nameHs.c_str());
        }
    }

    // Priority/urgent toasts show a content Grid as the visible backdrop instead
    // of ToastBackgroundBorder2 -- gray those (and square them if they're Borders).
    if (name == L"ToastContentGrid" || name == L"ToastContentView2" ||
        name == L"ToastContentView" || name == L"ToastContentExpandedGrid" ||
        name == L"ToastGrid" || name == L"ToastGrid2" ||
        name == L"UrgentToastContentCollapsedGrid") {
        auto brush = wux::Media::SolidColorBrush(MakeColor(g_toastCfg.bg));
        if (g_toastCfg.squareCorners) SquareToastWindow();
        if (auto b = element.try_as<wux::Controls::Border>()) {
            if (g_toastCfg.squareCorners) b.CornerRadius(wux::CornerRadius{0, 0, 0, 0});
            b.Background(brush);
        } else if (auto panel = element.try_as<wux::Controls::Panel>()) {
            panel.Background(brush);
        }
        Wh_Log(L"[W11Shell] styler: bg grid %s", nameHs.c_str());
    }

    // Enlarge the app logo (it's a tiny 12x12 by default). The toast tree carries
    // both templates, so target both logo element names.
    if (name == L"AppLogo2" || name == L"AppLogo" ||
        name == L"UrgentToastTitleBarAppLogoBorder") {
        double s = g_toastCfg.iconSize;
        element.Width(s);
        element.Height(s);
        element.MinWidth(s);
        element.MinHeight(s);
        // The attribution row is a fixed-height cell, so open up the parent too.
        if (auto parent = wux::Media::VisualTreeHelper::GetParent(element)) {
            if (auto p = parent.try_as<wux::FrameworkElement>()) {
                p.MinHeight(s);
                p.MinWidth(s);
            }
        }
        Wh_Log(L"[W11Shell] styler: resized icon %s -> %d", nameHs.c_str(),
               static_cast<int>(s));
    }

    // Grow the top attribution row so the larger icon + sender name fit.
    if (name == L"ToastTitleBar" || name == L"UrgentToastContentCollapsedTitleBar") {
        element.MinHeight(g_toastCfg.iconSize + 12);
        Wh_Log(L"[W11Shell] styler: grew title bar %s", nameHs.c_str());
    }

    // Fonts: heading (the toast title) and body (message + sender name).
    if (name == L"Title2") {
        if (auto tb = element.try_as<wux::Controls::TextBlock>()) {
            ApplyFont(tb, g_toastCfg.headingFont, g_toastCfg.headingSize, g_toastCfg.headingBold);
            Wh_Log(L"[W11Shell] styler: heading font on %s", nameHs.c_str());
        }
    }
    if (name == L"MessageText2") {
        if (auto tb = element.try_as<wux::Controls::TextBlock>()) {
            ApplyFont(tb, g_toastCfg.bodyFont, g_toastCfg.bodySize, false);
            Wh_Log(L"[W11Shell] styler: body font on %s", nameHs.c_str());
        }
    }
    // Sender (app name) line at the top, next to the icon -- its own font setting.
    if (name == L"SenderName" || name == L"UrgentToastTitleBarSenderName") {
        if (auto tb = element.try_as<wux::Controls::TextBlock>()) {
            ApplyFont(tb, g_toastCfg.senderFont, g_toastCfg.senderSize, g_toastCfg.senderBold);
            Wh_Log(L"[W11Shell] styler: sender font on %s", nameHs.c_str());
        }
    }

    if (g_toastCfg.removeShadow &&
        (name == L"NormalToastView" || name == L"PriorityToastView")) {
        if (auto ui = element.try_as<wux::UIElement>()) ui.Shadow(nullptr);
    }

    // DIAG (temporary): dump the WHOLE composed toast subtree to a file so the real
    // visible-border element is identifiable. Triggered off ToastBackgroundBorder2
    // (reliably present per Notification Center Styler), walking UP to the top
    // ancestor first so the dump is rooted at the toast's outermost element. Fires on
    // Loaded (tree fully composed by then).
    if (name == L"ToastBackgroundBorder2" || name == L"ToastBackgroundBorder") {
        element.Loaded([](winrt::Windows::Foundation::IInspectable const& s,
                          wux::RoutedEventArgs const&) {
            auto node = s.try_as<wux::DependencyObject>();
            if (!node) return;
            wux::DependencyObject root = node;
            for (int i = 0; i < 40; i++) {
                auto p = wux::Media::VisualTreeHelper::GetParent(root);
                if (!p) break;
                root = p;
            }
            AppendToastTree(L"\n===== TOAST TREE =====\n");
            DumpToastSubtree(root, 0);
        });
    }
}

static HMODULE GetCurrentModuleHandle() {
    HMODULE module;
    if (!GetModuleHandleEx(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                               GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           L"", &module)) {
        return nullptr;
    }
    return module;
}

// --- VisualTreeWatcher (IVisualTreeServiceCallback2) -------------------------
class VisualTreeWatcher : public winrt::implements<VisualTreeWatcher, IVisualTreeServiceCallback2, winrt::non_agile> {
public:
    VisualTreeWatcher(winrt::com_ptr<IUnknown> site);
    VisualTreeWatcher(const VisualTreeWatcher&) = delete;
    VisualTreeWatcher& operator=(const VisualTreeWatcher&) = delete;
    ~VisualTreeWatcher();
    void UnadviseVisualTreeChange();

private:
    HRESULT STDMETHODCALLTYPE OnVisualTreeChange(ParentChildRelation relation, VisualElement element, VisualMutationType mutationType) override;
    HRESULT STDMETHODCALLTYPE OnElementStateChanged(InstanceHandle element, VisualElementState elementState, LPCWSTR context) noexcept override;

    wf::IInspectable FromHandle(InstanceHandle handle) {
        wf::IInspectable obj;
        winrt::check_hresult(m_XamlDiagnostics->GetIInspectableFromHandle(
            handle, reinterpret_cast<::IInspectable**>(winrt::put_abi(obj))));
        return obj;
    }

    winrt::com_ptr<IXamlDiagnostics> m_XamlDiagnostics = nullptr;
};

VisualTreeWatcher::VisualTreeWatcher(winrt::com_ptr<IUnknown> site)
    : m_XamlDiagnostics(site.as<IXamlDiagnostics>()) {
    // Advising from a fresh thread; doing it inline can hang the app.
    HANDLE thread = CreateThread(
        nullptr, 0,
        [](LPVOID lpParam) -> DWORD {
            auto watcher = reinterpret_cast<VisualTreeWatcher*>(lpParam);
            HRESULT hr = watcher->m_XamlDiagnostics.as<IVisualTreeService3>()->AdviseVisualTreeChange(watcher);
            watcher->Release();
            if (FAILED(hr)) Wh_Log(L"[W11Shell] styler: Advise error %08X", hr);
            return 0;
        },
        this, 0, nullptr);
    if (thread) {
        AddRef();
        CloseHandle(thread);
    }
}

VisualTreeWatcher::~VisualTreeWatcher() {}

void VisualTreeWatcher::UnadviseVisualTreeChange() {
    HRESULT hr = m_XamlDiagnostics.as<IVisualTreeService3>()->UnadviseVisualTreeChange(this);
    if (FAILED(hr)) Wh_Log(L"[W11Shell] styler: Unadvise error %08X", hr);
}

HRESULT VisualTreeWatcher::OnVisualTreeChange(ParentChildRelation, VisualElement element, VisualMutationType mutationType) try {
    if (mutationType == Add) {
        const auto inspectable = FromHandle(element.Handle);
        if (auto fe = inspectable.try_as<wux::FrameworkElement>()) {
            ApplyCustomizations(element.Handle, fe, element.Type);
        }
    }
    return S_OK;
} catch (...) {
    Wh_Log(L"[W11Shell] styler: OnVisualTreeChange error %08X", winrt::to_hresult());
    return S_OK;
}

HRESULT VisualTreeWatcher::OnElementStateChanged(InstanceHandle, VisualElementState, LPCWSTR) noexcept {
    return S_OK;
}

// --- TAP COM server ---------------------------------------------------------
winrt::com_ptr<VisualTreeWatcher> g_visualTreeWatcher;

// {7E3F1A92-4C6B-4E2A-9F1D-2B5C8A0E7D34} -- unique to this mod.
static constexpr CLSID CLSID_WindhawkTAP = {
    0x7e3f1a92, 0x4c6b, 0x4e2a, {0x9f, 0x1d, 0x2b, 0x5c, 0x8a, 0x0e, 0x7d, 0x34}};

class WindhawkTAP : public winrt::implements<WindhawkTAP, IObjectWithSite, winrt::non_agile> {
public:
    HRESULT STDMETHODCALLTYPE SetSite(IUnknown* pUnkSite) override;
    HRESULT STDMETHODCALLTYPE GetSite(REFIID riid, void** ppvSite) noexcept override;

private:
    winrt::com_ptr<IUnknown> site;
};

HRESULT WindhawkTAP::SetSite(IUnknown* pUnkSite) try {
    if (g_visualTreeWatcher) {
        g_visualTreeWatcher->UnadviseVisualTreeChange();
        g_visualTreeWatcher = nullptr;
    }
    site.copy_from(pUnkSite);
    if (site) {
        FreeLibrary(GetCurrentModuleHandle());  // balance InitializeXamlDiagnosticsEx
        g_visualTreeWatcher = winrt::make_self<VisualTreeWatcher>(site);
    }
    return S_OK;
} catch (...) {
    HRESULT hr = winrt::to_hresult();
    Wh_Log(L"[W11Shell] styler: SetSite error %08X", hr);
    return hr;
}

HRESULT WindhawkTAP::GetSite(REFIID riid, void** ppvSite) noexcept {
    return site.as(riid, ppvSite);
}

template <class T>
struct SimpleFactory : winrt::implements<SimpleFactory<T>, IClassFactory, winrt::non_agile> {
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* pUnkOuter, REFIID riid, void** ppvObject) override try {
        if (!pUnkOuter) {
            *ppvObject = nullptr;
            return winrt::make<T>().as(riid, ppvObject);
        }
        return CLASS_E_NOAGGREGATION;
    } catch (...) {
        return winrt::to_hresult();
    }
    HRESULT STDMETHODCALLTYPE LockServer(BOOL) noexcept override { return S_OK; }
};

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdll-attribute-on-redeclaration"
__declspec(dllexport) _Use_decl_annotations_ STDAPI
    DllGetClassObject(REFCLSID rclsid, REFIID riid, LPVOID* ppv) try {
    if (rclsid == CLSID_WindhawkTAP) {
        *ppv = nullptr;
        return winrt::make<SimpleFactory<WindhawkTAP>>().as(riid, ppv);
    }
    return CLASS_E_CLASSNOTAVAILABLE;
} catch (...) {
    return winrt::to_hresult();
}

__declspec(dllexport) _Use_decl_annotations_ STDAPI DllCanUnloadNow(void) {
    return winrt::get_module_lock() ? S_FALSE : S_OK;
}
#pragma clang diagnostic pop

using PFN_INITIALIZE_XAML_DIAGNOSTICS_EX = decltype(&InitializeXamlDiagnosticsEx);

static HRESULT InjectWindhawkTAP() noexcept {
    HMODULE module = GetCurrentModuleHandle();
    if (!module) return HRESULT_FROM_WIN32(GetLastError());

    WCHAR location[MAX_PATH];
    switch (GetModuleFileName(module, location, ARRAYSIZE(location))) {
        case 0:
        case ARRAYSIZE(location):
            return HRESULT_FROM_WIN32(GetLastError());
    }

    const HMODULE wux_dll = LoadLibraryEx(L"Windows.UI.Xaml.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!wux_dll) return HRESULT_FROM_WIN32(GetLastError());

    const auto ixde = reinterpret_cast<PFN_INITIALIZE_XAML_DIAGNOSTICS_EX>(
        GetProcAddress(wux_dll, "InitializeXamlDiagnosticsEx"));
    if (!ixde) return HRESULT_FROM_WIN32(GetLastError());

    // Only a few connection slots are ever needed; a fresh process connects on
    // #1. (The original 10000 here, multiplied by the retry below, hammered XAML
    // hard enough to wedge ShellExperienceHost / the notification center.)
    HRESULT hr = E_FAIL;
    for (int i = 0; i < 16; i++) {
        WCHAR connectionName[256];
        wsprintf(connectionName, L"VisualDiagConnection%d", i + 1);
        hr = ixde(connectionName, GetCurrentProcessId(), L"", location, CLSID_WindhawkTAP, nullptr);
        if (hr != HRESULT_FROM_WIN32(ERROR_NOT_FOUND)) break;
    }
    return hr;
}

std::atomic<bool> g_toastInitialized;

// A freshly-respawned ShellExperienceHost has no connectable XAML core yet, so
// InitializeXamlDiagnosticsEx returns ERROR_NOT_FOUND (0x80070490). Retry until
// XAML is up.
static DWORD WINAPI TapRetryThread(LPVOID) {
    for (int i = 0; i < 15 && g_toastInitialized.load(); i++) {
        HRESULT hr = InjectWindhawkTAP();
        if (hr != HRESULT_FROM_WIN32(ERROR_NOT_FOUND)) {
            if (SUCCEEDED(hr)) Wh_Log(L"[W11Shell] styler: TAP injected (try %d)", i + 1);
            else Wh_Log(L"[W11Shell] styler: TAP inject hr=%08X (try %d)", hr, i + 1);
            return 0;
        }
        Sleep(3000);
    }
    Wh_Log(L"[W11Shell] styler: TAP not connected (gave up)");
    return 0;
}

static void ToastStylerInit() {
    LoadToastCfg();
    if (Wh_GetIntSetting(L"toasts") == 0) return;  // master off -> inspector only
    if (g_toastInitialized.exchange(true)) return;
    HANDLE t = CreateThread(nullptr, 0, TapRetryThread, nullptr, 0, nullptr);
    if (t) CloseHandle(t);
}

static void ToastStylerUninit() {
    if (g_visualTreeWatcher) {
        g_visualTreeWatcher->UnadviseVisualTreeChange();
        g_visualTreeWatcher = nullptr;
    }
    g_toastInitialized = false;
}

// ============================================================================
// Feature: Element inspector (Ctrl+Shift+MiddleClick)
// ============================================================================
namespace inspector {

using winrt::com_ptr;

static std::atomic<bool> g_running{false};
static HANDLE g_thread = nullptr;
static std::wstring g_logPath;

static std::wstring BstrTake(BSTR b) {
    std::wstring s = b ? std::wstring(b, SysStringLen(b)) : L"";
    if (b) SysFreeString(b);
    return s;
}

static void AppendNode(IUIAutomationTreeWalker* walker, IUIAutomationElement* el,
                       int depth, std::wstring& out, int& count) {
    if (!el || count >= 600 || depth > 16) return;
    count++;

    BSTR cls = nullptr, name = nullptr, aid = nullptr;
    el->get_CurrentClassName(&cls);
    el->get_CurrentName(&name);
    el->get_CurrentAutomationId(&aid);
    CONTROLTYPEID ct = 0;
    el->get_CurrentControlType(&ct);
    RECT r{};
    el->get_CurrentBoundingRectangle(&r);

    out += std::wstring(static_cast<size_t>(depth) * 2, L' ');
    out += L"ct=" + std::to_wstring(static_cast<int>(ct)) + L" \"" + BstrTake(name) +
           L"\" Class=" + BstrTake(cls) + L" AutoId=" + BstrTake(aid) + L" [" +
           std::to_wstring(r.left) + L"," + std::to_wstring(r.top) + L" " +
           std::to_wstring(r.right - r.left) + L"x" + std::to_wstring(r.bottom - r.top) + L"]\n";

    com_ptr<IUIAutomationElement> child;
    if (SUCCEEDED(walker->GetFirstChildElement(el, child.put())) && child) {
        com_ptr<IUIAutomationElement> cur = child;
        while (cur) {
            AppendNode(walker, cur.get(), depth + 1, out, count);
            com_ptr<IUIAutomationElement> next;
            walker->GetNextSiblingElement(cur.get(), next.put());
            cur = next;
        }
    }
}

static com_ptr<IUIAutomationElement> FindDumpRoot(IUIAutomationTreeWalker* walker,
                                                  com_ptr<IUIAutomationElement> el) {
    com_ptr<IUIAutomationElement> cur = el, best, top = el;
    while (cur) {
        BSTR cls = nullptr, aid = nullptr;
        cur->get_CurrentClassName(&cls);
        cur->get_CurrentAutomationId(&aid);
        std::wstring sig = BstrTake(cls) + L" " + BstrTake(aid);
        if (sig.find(L"Toast") != std::wstring::npos) best = cur;
        top = cur;
        com_ptr<IUIAutomationElement> parent;
        walker->GetParentElement(cur.get(), parent.put());
        cur = parent;
    }
    return best ? best : top;
}

static void SetClipboard(const std::wstring& text) {
    if (!OpenClipboard(nullptr)) return;
    EmptyClipboard();
    size_t bytes = (text.size() + 1) * sizeof(wchar_t);
    if (HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE, bytes)) {
        if (void* p = GlobalLock(h)) {
            memcpy(p, text.c_str(), bytes);
            GlobalUnlock(h);
            SetClipboardData(CF_UNICODETEXT, h);
        } else {
            GlobalFree(h);
        }
    }
    CloseClipboard();
}

static void WriteLogFile(const std::wstring& text) {
    if (g_logPath.empty()) return;
    HANDLE h = CreateFileW(g_logPath.c_str(), FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    int n = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()),
                                nullptr, 0, nullptr, nullptr);
    if (n > 0) {
        std::string utf8(static_cast<size_t>(n), '\0');
        WideCharToMultiByte(CP_UTF8, 0, text.c_str(), static_cast<int>(text.size()),
                            utf8.data(), n, nullptr, nullptr);
        DWORD wr = 0;
        WriteFile(h, utf8.data(), static_cast<DWORD>(utf8.size()), &wr, nullptr);
        WriteFile(h, "\r\n", 2, &wr, nullptr);
    }
    CloseHandle(h);
}

static void Capture(IUIAutomation* uia, IUIAutomationTreeWalker* walker) {
    POINT pt{};
    GetCursorPos(&pt);
    com_ptr<IUIAutomationElement> el;
    if (FAILED(uia->ElementFromPoint(pt, el.put())) || !el) {
        Wh_Log(L"[W11Shell] inspector: no element at %d,%d", pt.x, pt.y);
        return;
    }
    com_ptr<IUIAutomationElement> root = FindDumpRoot(walker, el);
    std::wstring out = L"=== capture @ " + std::to_wstring(pt.x) + L"," +
                       std::to_wstring(pt.y) + L" ===\n";
    int count = 0;
    AppendNode(walker, root.get(), 0, out, count);
    SetClipboard(out);
    WriteLogFile(out);
    Wh_Log(L"[W11Shell] inspector: captured %d nodes at %d,%d", count, pt.x, pt.y);
}

static DWORD WINAPI ThreadProc(LPVOID) {
    HRESULT hrCo = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    com_ptr<IUIAutomation> uia;
    HRESULT hr = CoCreateInstance(__uuidof(CUIAutomation), nullptr, CLSCTX_INPROC_SERVER,
                                  __uuidof(IUIAutomation), uia.put_void());
    if (FAILED(hr) || !uia) {
        Wh_Log(L"[W11Shell] inspector: CUIAutomation create failed (hr=0x%08X)", hr);
        if (SUCCEEDED(hrCo)) CoUninitialize();
        return 0;
    }
    com_ptr<IUIAutomationTreeWalker> walker;
    uia->get_RawViewWalker(walker.put());
    if (!walker) {
        Wh_Log(L"[W11Shell] inspector: no RawViewWalker");
        if (SUCCEEDED(hrCo)) CoUninitialize();
        return 0;
    }
    Wh_Log(L"[W11Shell] inspector: ready (Ctrl+Shift+MiddleClick)");

    bool armed = true;
    while (g_running.load()) {
        Sleep(30);
        bool chord = (GetAsyncKeyState(VK_CONTROL) & 0x8000) &&
                     (GetAsyncKeyState(VK_SHIFT) & 0x8000) &&
                     (GetAsyncKeyState(VK_MBUTTON) & 0x8000);
        if (chord && armed) {
            armed = false;
            Capture(uia.get(), walker.get());
        }
        if (!(GetAsyncKeyState(VK_MBUTTON) & 0x8000)) armed = true;
    }
    if (SUCCEEDED(hrCo)) CoUninitialize();
    return 0;
}

static void Start() {
    if (Wh_GetIntSetting(L"inspector") == 0) return;
    PCWSTR p = Wh_GetStringSetting(L"inspectorLog");
    g_logPath = p ? std::wstring(p) : L"";
    Wh_FreeStringSetting(p);
    if (g_logPath.empty() || g_logPath == L"auto") {
        wchar_t tmp[MAX_PATH];
        DWORD n = GetTempPathW(MAX_PATH, tmp);
        g_logPath = (n > 0 && n < MAX_PATH)
                        ? std::wstring(tmp) + L"cplusruss-w11-shell-inspect.log"
                        : L"";
    }
    g_running = true;
    g_thread = CreateThread(nullptr, 0, ThreadProc, nullptr, 0, nullptr);
    Wh_Log(L"[W11Shell] inspector: started; log=%s", g_logPath.c_str());
}

static void Stop() {
    g_running = false;
    if (g_thread) {
        WaitForSingleObject(g_thread, 2000);
        CloseHandle(g_thread);
        g_thread = nullptr;
    }
}

}  // namespace inspector

// --- "Fire a test toast" button (toggle the fireTest setting) ---------------
static bool IsProcessExe(PCWSTR exe) {
    WCHAR path[MAX_PATH];
    if (!GetModuleFileNameW(nullptr, path, ARRAYSIZE(path))) return false;
    PCWSTR base = wcsrchr(path, L'\\');
    return _wcsicmp(base ? base + 1 : path, exe) == 0;
}

static void FireTestToast() {
    try {
        using namespace winrt::Windows::UI::Notifications;
        winrt::Windows::Data::Xml::Dom::XmlDocument xml;
        xml.LoadXml(
            LR"(<toast><visual><binding template="ToastGeneric">)"
            LR"(<text>cplusruss W11 Shell</text>)"
            LR"(<text>Windhawk test toast</text></binding></visual></toast>)");
        ToastNotification toast(xml);
        toast.Tag(winrt::hstring{std::to_wstring(GetTickCount())});
        ToastNotificationManager::CreateToastNotifier(
            L"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe")
            .Show(toast);
        Wh_Log(L"[W11Shell] fired test toast");
    } catch (...) {
        Wh_Log(L"[W11Shell] FireTestToast error %08X", winrt::to_hresult());
    }
}

// --- Windhawk lifecycle -----------------------------------------------------
BOOL Wh_ModInit(void) {
    ToastStylerInit();
    inspector::Start();
    return TRUE;
}

void Wh_ModSettingsChanged(void) {
    LoadToastCfg();  // applies to toasts shown after this point
    inspector::Stop();
    inspector::Start();
    // "Fire a test toast" button: fire once, from explorer only (settings-changed
    // runs in every injected process, so guard to avoid duplicate toasts).
    if (Wh_GetIntSetting(L"fireTest") && IsProcessExe(L"explorer.exe")) {
        FireTestToast();
    }
}

void Wh_ModUninit(void) {
    ToastStylerUninit();
    inspector::Stop();
    Wh_Log(L"[W11Shell] unloaded");
}
