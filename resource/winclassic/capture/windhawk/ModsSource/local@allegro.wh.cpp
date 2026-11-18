// ==WindhawkMod==
// @id              allegro
// @name            Allegro
// @description     Allegro Visibility-pane / dock tweaks, split into explicit per-version chunks (25.1 = full set; 17.4 = labels/docks/chrome, no pane-appearance changes). Shared inspector + diagnostics. Applies to PCB Editor (allegro.exe) and the Allegro Free Viewer (allegro_free_viewer.exe).
// @version         0.81.0
// @author          rlemburg
// @include         allegro.exe
// @include         allegro_free_viewer.exe
// @architecture    x86-64
// ==/WindhawkMod==

// ==WindhawkModReadme==
/*
# Allegro

Hooks Allegro / OrCAD PCB Editor 25.1 (`allegro.exe`, a custom Qt5 build):

- **Blank header labels (default on):** captures `ColorVisibilityPane` (via
  `QObject::setObjectName`) and blanks its texts by intercepting `QLabel::setText`
  AND `QAbstractButton::setText` (the "Conductors" toggle is a checkbox, not a
  label): "Global visibility", "Quickviews", "View", "Conductors" -> empty, while
  the widget keeps its place. "Global visibility"/"Quickviews" match by text;
  "View"/"Conductors" are ambiguous (no parent linkage at setText time) so each is
  blanked as the first of its kind created after the pane is captured.

- **Hide pane scrollbars (default on):** a pane-scoped stylesheet collapses the
  Visibility pane's scrollbars (`QScrollBar` width/height 0) so they never show.

- **Remove row striping (default on):** the Visibility-pane stripes are per-row
  brushes from the model (`UIFQTableModel::data`, Qt::BackgroundRole), NOT
  alternatingRowColors. Two dead ends were tried: detouring `data()` CRASHED
  allegro.exe (CFG-guarded internal function); a `QTableView::item{background}`
  rule cannot win because the base style fills the model brush OVER the QSS
  background. The working approach: a pane-scoped
  `QTableView{alternate-background-color:white}` overrides the palette AlternateBase
  the model derives its stripe brush from, so the brush handed to the painter is
  the pane gray rgb(212,208,200) = no visible stripe and the grid blends with the
  pane (no white box), while selection/hover (more-specific QSS rules) are
  untouched. `setAlternatingRowColors(false)` is also forced app-wide as a backstop.

- **Inspector (default off, opt-in):** enable `inspect`, then **Ctrl+Shift+Middle-click**
  any control to append its RTTI class, objectName (captured safely from setObjectName,
  not a getter), pointer, full parent chain AND child subtree to `inspect.log` and the
  Windows clipboard; or **Ctrl+Alt+Middle-click** to dump the whole top-level window's
  widget tree the same way (so you can paste "I clicked X -- here's the inspection"
  straight into a chat as context). The window-level press and the leaf widget's press
  from one physical click accumulate into the same clipboard buffer. Runs on the GUI
  thread via `QApplication::notify` and uses only crash-safe primitives (no by-value Qt
  getters, no CRT printf). Used to identify a control precisely so a targeted tweak can
  be written without hunting.

- **Two version chunks (17.4 vs 25.1):** the feature logic is split into two explicit
  sections -- `namespace v251` (the full tweak set) and `namespace v174` (a subset:
  pane label/text blanking, Find/Options/Command dock + command-input styling, and
  window chrome -- but NO Visibility-pane *appearance* changes, since 17.4's pane
  already renders the way we want). Windhawk injects into every `allegro.exe` AND
  `allegro_free_viewer.exe` by name (the Free Viewer is the same Qt5 UI, view-only);
  the exe path picks the chunk (`SPB_25...` => 25.1, anything else => 17.4). The
  inspector and all diagnostics are SHARED and run identically in both. The chunk is
  chosen once per process in `Wh_ModInit`; takes effect on the next allegro restart.

Tested against SPB_25.1 (`cdsQt5Core.dll` / `cdsQt5Widgets.dll`, MSVC x64); 17.2/17.4
ship the same Qt5 classes/ABI. Verify the 17.4 chunk on first 17.x run.
*/
// ==/WindhawkModReadme==

// ==WindhawkModSettings==
/*
- floatToolbar: true
  $name: Let the "_" toolbar float freely (don't force docking)
  $description: >-
    Sets the special "_" toolbar to NoToolBarArea so dragging it floats it instead of
    snapping into a dock. Matched by its window title "_". Takes effect on the next
    allegro restart (applied when the toolbar's title is set at construction).
- panelBorder: true
  $name: Draw a border around the Visibility / Find / Options / Command panels
  $description: >-
    Draws a thin gray border around each panel's content so they don't blend into the
    surrounding gray. The border is applied to each dock's content scroll area. Takes
    effect on the next allegro restart (applied when each dock is built).
- inspect: false
  $name: Inspector -- middle-click a control/window to dump it (diagnostic)
  $description: >-
    When on, Ctrl+Shift+Middle-click any control to dump it (class, objectName, pointer,
    its full parent chain, AND its child subtree), or Ctrl+Alt+Middle-click to dump the
    whole top-level window's widget tree. Each dump is appended to
    C:\Dropbox\Common\cfg\windhawk\allegro\inspect.log AND copied to the Windows clipboard
    (paste it straight into a chat as context). Off by default; the notify hook is only
    installed when this is on, so leaving it off keeps the mod exactly as before. Toggling
    this needs a recompile + allegro restart to take effect.
- probeVisPane: false
  $name: Log capture/blank actions (diagnostic)
  $description: >-
    Logs [vispane] lines when the pane/labels/scrollbars are captured or changed.
    Off by default; turn on only to debug.
- dumpTree: false
  $name: Dump the pane widget tree once (diagnostic)
  $description: >-
    The first time the Visibility pane is shown, walk its entire child-widget tree
    and log every node ([tree] lines): class, objectName, geometry, and any
    item-view's model class. Read-only. Used to identify exactly what each element
    is. Turn off once the structure is known.
- logNames: false
  $name: Log pane object names (diagnostic)
  $description: >-
    Logs [names] lines for pane-ish objectNames (find/options/command/pane/dock)
    as they are set, with the widget's class. Used to find the exact Find/Options/
    Command pane names so their horizontal scrollbar can be targeted.
- probeBrush: false
  $name: Probe grid cell background brushes (diagnostic)
  $description: >-
    Logs [brush] lines for the first few Visibility-grid cells: the offset, style
    and RGB of any per-row background brush. Read-only. Used to pin down the stripe
    brush so it can be cleared precisely. Turn off once known.
*/
// ==/WindhawkModSettings==

#include <windhawk_api.h>
#include <cstdint>
#include <cstring>

// --- Minimal Qt5 QString ABI (stable across Qt 5.x) -----------------------
// QString holds one pointer to a heap QArrayData<ushort>; the NUL-terminated
// UTF-16 data lives at (char*)d + d->offset, d->size code units.
struct QArrayDataX {
    int       ref;     // 0
    int       size;    // 4  length in UTF-16 code units
    unsigned  alloc;   // 8
    ptrdiff_t offset;  // 16 (8-aligned on x64)
};
struct QtString { QArrayDataX* d; };   // a "const QString&" is a QtString*

static const unsigned short* QtStr_data(const QtString* s, int* outLen) {
    if (!s || !s->d) { *outLen = 0; return nullptr; }
    *outLen = s->d->size;
    return (const unsigned short*)((const char*)s->d + s->d->offset);
}
// Case-insensitive substring search (needleLower must be lowercase ASCII).
static bool ContainsCI(const wchar_t* hay, const wchar_t* needleLower) {
    for (; *hay; ++hay) {
        const wchar_t* h = hay; const wchar_t* n = needleLower;
        while (*n && *h) {
            wchar_t hc = (*h >= L'A' && *h <= L'Z') ? (wchar_t)(*h + 32) : *h;
            if (hc != *n) break;
            ++h; ++n;
        }
        if (!*n) return true;
    }
    return false;
}
struct QtModelIndex { int r; int c; uintptr_t i; const void* m; }; // model @ +16

// MSVC RTTI class name (".?AV<class>@@") from a polymorphic object, guarded so a
// non-RTTI / bad pointer yields nullptr instead of crashing.
static const char* RttiClassName(const void* obj) {
    if (!obj || IsBadReadPtr(obj, sizeof(void*))) return nullptr;
    void** vt = *(void***)obj;
    if (!vt || IsBadReadPtr((void*)(vt - 1), sizeof(void*))) return nullptr;
    const void* col = vt[-1];                                 // CompleteObjectLocator
    if (!col || IsBadReadPtr((void*)col, 24)) return nullptr;
    const int* c = (const int*)col;
    if (c[0] != 1) return nullptr;                            // x64 COL signature
    uintptr_t base = (uintptr_t)col - (unsigned)c[5];          // image base (RVA of COL)
    const char* td = (const char*)(base + (unsigned)c[3]);     // TypeDescriptor (RVA)
    if (IsBadReadPtr((void*)(td + 16), 8)) return nullptr;
    return td + 16;                                           // TypeDescriptor.name
}

// --- Settings -------------------------------------------------------------
// Feature tweaks -- permanently ON (no per-feature switch, by design).
bool g_noStripes      = true;   // remove Visibility-pane row striping
bool g_blankLabels    = true;   // blank pane header labels + Conductors/Masks text
bool g_hideScrollbars = true;   // hide Visibility-pane scrollbars
bool g_noHScroll      = true;   // hide horizontal scrollbar on Find/Options/Command docks
bool g_stdCheckboxes  = true;   // pin Visibility-grid checkbox indicators to 16px (stop scaling)
bool g_comboShrink    = true;   // drop the pane combos' content-based minimum width
bool g_styleCmd       = true;   // CommandBar input: Consolas 10pt, black text (font only)
bool g_hideCmdPrompt  = true;   // hide the "Command >" prompt QLineEdit
bool g_floatToolbar   = true;   // "_" toolbar: NoToolBarArea so it floats (no forced docking)
bool g_panelBorder    = true;   // border around the Visibility/Find/Options/Command panels (user setting)
// Per-version split: the feature logic lives in two explicit chunks -- namespace v251
// (the full tweak set) and namespace v174 (a subset). The exe path picks the chunk in
// Wh_ModInit (SPB_25... => 25.1, anything else => 17.4). The inspector + diagnostics are
// SHARED and run identically regardless of version. VerImpl is the dispatch table: each
// chunk supplies its setObjectName handler + whether it removes the grid row stripes.
enum Ver { VER_174, VER_251 };
Ver g_ver = VER_251;            // detected per-process in Wh_ModInit
struct VerImpl {
    void (*onSetObjectName)(void* self, const wchar_t* name);  // per-version objectName policy
    bool removeStripes;                                        // 25.1 removes row stripes; 17.4 keeps native
    bool blankLabels;                                          // blank+hide header labels (Global visibility / View / Class-Subclass)
    bool relabelLayers;                                        // 25.1 only: relabel Soldermask_Top -> Sm Top (17.4 keeps full names)
    bool blankSecondary;                                       // 25.1 only: also blank Quickviews + Conductors/Masks
};
const VerImpl* g_impl = nullptr;  // selected in Wh_ModInit before any hook fires
// Exposed in Windhawk settings -- inspector + diagnostics/logging only.
bool g_inspect        = false;  // Inspector: Ctrl+Shift+Middle (control) / Ctrl+Alt+Middle (window) dumps to inspect.log
bool g_probeVisPane   = false;  // DIAGNOSTIC: log [vispane] capture/blank actions
bool g_dumpTree       = false;  // DIAGNOSTIC: one-shot widget-tree dump on pane show
bool g_logNames       = false;  // DIAGNOSTIC: log pane-ish objectNames as they're set
bool g_probeBrush     = false;  // DIAGNOSTIC: log grid cells' backgroundBrush (offset+color)
void* g_filmDomainTable = nullptr;  // 17.4: the Film Domain Setting datagrid, forced un-striped via the setAltRows hook

// --- Resolved Qt entry points ---------------------------------------------
typedef void* (__cdecl* QStringCtor_t)(void* self);   // ??0QString@@QEAA@XZ (default ctor)
typedef void  (__cdecl* QStringDtor_t)(void* self);   // ??1QString@@QEAA@XZ
typedef void* (__cdecl* FromUtf16_t)(void* ret, const unsigned short* s, int size); // QString::fromUtf16 (RVO)
typedef void  (__cdecl* SetStyleSheet_t)(void* self, const QtString* sheet);          // QWidget::setStyleSheet
typedef void  (__cdecl* SetObjectName_t)(void* self, const QtString* name);
typedef void  (__cdecl* LabelSetText_t)(void* self, const QtString* text);
typedef void* (__cdecl* Parent_t)(void* self);        // QObject::parent() -> QObject*
typedef void  (__cdecl* SetAltRows_t)(void* self, bool enable);
// Introspection (diagnostic tree dump)
typedef void*      (__cdecl* ChildrenGetter_t)(void* self);            // QObject::children -> const QObjectList&
typedef void*      (__cdecl* QStrGetter_t)(void* ret, void* self);     // objectName/text -> QString (RVO)
typedef bool       (__cdecl* Inherits_t)(void* self, const char* cls); // QObject::inherits
typedef const int* (__cdecl* GeomGetter_t)(void* self);                // QWidget::geometry -> const QRect&
typedef void*      (__cdecl* ModelGetter_t)(void* self);               // QAbstractItemView::model
typedef void       (__cdecl* ItemPaint_t)(void* self, void* painter, const void* opt, const QtModelIndex* idx);
typedef void       (__cdecl* SetVisible_t)(void* self, bool visible);  // QWidget::setVisible (CALL, not hook)
typedef bool       (__cdecl* Notify_t)(void* self, void* receiver, void* event); // QApplication::notify
typedef void       (__cdecl* SetWidth_t)(void* self, int w); // QWidget::setMinimumWidth / setMaximumWidth
typedef void       (__cdecl* SetAllowedAreas_t)(void* self, int areas); // QToolBar::setAllowedAreas
typedef void       (__cdecl* SetGrid2_t)(void* self, int a, int b); // QGridLayout::setColumnStretch
typedef void       (__cdecl* SetSizePolicy2_t)(void* self, int h, int v); // QWidget::setSizePolicy
typedef void*      (__cdecl* Layout_t)(void* self);                 // QWidget::layout -> QLayout*
typedef void       (__cdecl* SetMargins4_t)(void* self, int l, int t, int r, int b); // QLayout::setContentsMargins

QStringCtor_t   pQString_ctor  = nullptr;
QStringDtor_t   pQString_dtor  = nullptr;
FromUtf16_t     pFromUtf16     = nullptr;
SetStyleSheet_t pSetStyleSheet = nullptr;
Parent_t        pParent        = nullptr;

SetObjectName_t QObject_setObjectName_orig    = nullptr;
LabelSetText_t  QLabel_setText_orig           = nullptr;
LabelSetText_t  QAbstractButton_setText_orig  = nullptr;
LabelSetText_t  QWidget_setWindowTitle_orig   = nullptr;
SetAltRows_t    QAIV_setAltRows_orig          = nullptr;

ChildrenGetter_t pChildren   = nullptr;
QStrGetter_t     pObjectName = nullptr;
Inherits_t       pInherits   = nullptr;
GeomGetter_t     pGeometry   = nullptr;
QStrGetter_t     pLabelText  = nullptr;
QStrGetter_t     pButtonText = nullptr;
ModelGetter_t    pAIVModel   = nullptr;
SetVisible_t     pSetVisible = nullptr;
SetWidth_t       pSetMinWidth = nullptr;
SetWidth_t       pSetMaxWidth = nullptr;
SetWidth_t       pSetMinHeight = nullptr;  // QWidget::setMinimumHeight (grow a dialog/table vertically)
SetWidth_t       pSetHSpacing = nullptr;   // QGridLayout::setHorizontalSpacing
SetGrid2_t       pSetColStretch = nullptr; // QGridLayout::setColumnStretch
SetSizePolicy2_t pSetSizePolicy2 = nullptr;
Layout_t         pWidgetLayout    = nullptr;
SetMargins4_t    pSetContentsMargins = nullptr;
SetAllowedAreas_t pSetAllowedAreas = nullptr;
ItemPaint_t      QStyledItemDelegate_paint_orig = nullptr;
Notify_t         QApplication_notify_orig       = nullptr;

// Inspector extras -- widget palette colors + property reads. ALL return refs /
// ints / bools (no by-value Qt copies), so they're crash-safe here unlike the
// QString/geometry getters. palette()->color(role)->red/green/blue gives any
// palette color; backgroundRole tells which role a widget paints its bg from.
typedef const void* (__cdecl* QWidgetPalette_t)(void* self);                 // QWidget::palette -> const QPalette&
typedef const void* (__cdecl* QPaletteColor_t)(const void* self, int role);  // QPalette::color(ColorRole) -> const QColor&
typedef int         (__cdecl* QColorChan_t)(const void* self);               // QColor::red/green/blue -> int
typedef int         (__cdecl* QWidgetRole_t)(void* self);                     // QWidget::backgroundRole -> ColorRole
typedef bool        (__cdecl* QWidgetBool_t)(void* self);                     // QWidget::isVisible/isEnabled/autoFillBackground

QWidgetPalette_t pQWidget_palette   = nullptr;
QPaletteColor_t  pQPalette_color    = nullptr;
QColorChan_t     pQColor_red        = nullptr;
QColorChan_t     pQColor_green      = nullptr;
QColorChan_t     pQColor_blue       = nullptr;
QWidgetRole_t    pQWidget_bgRole    = nullptr;
QWidgetBool_t    pQWidget_isVisible = nullptr;
QWidgetBool_t    pQWidget_isEnabled = nullptr;
QWidgetBool_t    pQWidget_autoFill  = nullptr;

// Palette WRITE -- to flatten 3D shade roles QSS can't reach. Value-type ABI:
// construct QPalette/QColor into stack buffers; every call takes this+args by ptr.
typedef void* (__cdecl* QPaletteCopy_t)(void* self, const void* other);              // QPalette(const QPalette&)
typedef void  (__cdecl* QPaletteDtor_t)(void* self);                                 // ~QPalette
typedef void  (__cdecl* QPaletteSetColor_t)(void* self, int role, const void* col);  // setColor(ColorRole, const QColor&)
typedef void* (__cdecl* QColorCtor_t)(void* self, int r, int g, int b, int a);       // QColor(int,int,int,int)
typedef void  (__cdecl* QWidgetSetPalette_t)(void* self, const void* pal);           // QWidget::setPalette

QPaletteCopy_t      pQPalette_copy      = nullptr;
QPaletteDtor_t      pQPalette_dtor      = nullptr;
QPaletteSetColor_t  pQPalette_setColor  = nullptr;
QColorCtor_t        pQColor_ctor        = nullptr;
QWidgetSetPalette_t pQWidget_setPalette = nullptr;

// --- Paint-recolor: gray CVPLayerGrid's hardcoded-white fills -------------------
// 17.4's CVPLayerGrid (in allegro.exe, paintEvent NOT exported -> not hookable) fills
// its no-button "N/A" cells and section dividers WHITE in its own paint, ignoring
// palette + QSS. We can't hook that paint, but we CAN hook the exported QPainter::
// fillRect overloads it calls. While the grid (or one of its QFrame dividers) is
// painting -- flagged by g_gridPainting, set around the paint event in the notify
// hook -- every fillRect is forced to the pane gray. The child swatches/labels paint
// in their OWN widgets (g_gridPainting==0 then), so their real colors are untouched.
void* g_layerGrid   = nullptr;   // captured CVPLayerGrid (17.4)
int   g_gridPainting = 0;        // >0 while the grid/its divider frames paint
long  g_gridFillN    = 0;        // diag: count of fills recolored during grid paint
bool  g_gridPaintLogged = false; // diag: log the first grid paint's fill count once

// Dock title bars (SPBFoldDockTitle) paint their grip/separator blocks in a hardcoded
// AAA8A4 (170,168,164) -- also not in the palette. While a title bar paints
// (g_titlePainting set in the notify hook), recolor ONLY that AAA8A4 fill to black
// (color-MATCH, unlike the grid where every fill -> gray). All other title fills (the
// gray bg etc.) pass through. Applies to every dock's title bar for a uniform look.
bool  g_blackDockSep = true;     // recolor dock-title AAA8A4 separators to black
int   g_titlePainting = 0;       // >0 while a dock title bar paints

typedef void (__cdecl* FillRectRC_t)(void*, const void*, const void*);        // fillRect(QRect&, QColor&)
typedef void (__cdecl* FillRectRB_t)(void*, const void*, const void*);        // fillRect(QRect&, QBrush&)
typedef void (__cdecl* FillRectIC_t)(void*, int,int,int,int, const void*);    // fillRect(x,y,w,h, QColor&)
typedef void (__cdecl* FillRectIB_t)(void*, int,int,int,int, const void*);    // fillRect(x,y,w,h, QBrush&)
typedef const void* (__cdecl* QBrushColor_t)(const void*);                    // QBrush::color() -> const QColor&
typedef void (__cdecl* SetPenC_t)(void*, const void*);                        // QPainter::setPen(const QColor&)
typedef void (__cdecl* SetPenP_t)(void*, const void*);                        // QPainter::setPen(const QPen&)
FillRectRC_t pFillRect_RC_orig = nullptr;
FillRectRB_t pFillRect_RB_orig = nullptr;
FillRectIC_t pFillRect_IC_orig = nullptr;
FillRectIB_t pFillRect_IB_orig = nullptr;
QBrushColor_t pQBrush_color    = nullptr;
SetPenC_t    pSetPenC_orig     = nullptr;
SetPenP_t    pSetPenP_orig     = nullptr;

// The substitute gray QColor (grid) + black QColor (title separators), built once.
static const void* GridGrayColor() {
    static char buf[24];
    static bool init = false;
    if (!init) { if (!pQColor_ctor) return nullptr; pQColor_ctor(buf, 212, 208, 200, 255); init = true; }
    g_gridFillN++;   // diag: one intended recolor
    return buf;
}
static const void* SepBlackColor() {
    static char buf[24];
    static bool init = false;
    if (!init) { if (!pQColor_ctor) return nullptr; pQColor_ctor(buf, 0, 0, 0, 255); init = true; }
    return buf;
}
// Is this QColor the title-bar separator gray AAA8A4 (170,168,164)? Tight tolerance so
// it never catches the face gray (212,208,200) or the shade grays.
static bool IsSepColor(const void* color) {
    if (!color || !pQColor_red || !pQColor_green || !pQColor_blue) return false;
    int r = pQColor_red(color), g = pQColor_green(color), b = pQColor_blue(color);
    return r >= 162 && r <= 178 && g >= 160 && g <= 176 && b >= 156 && b <= 172;
}
// diag: log the first few fill colors seen while a title bar paints, so the actual
// separator color is confirmed from the Windhawk log (no screen needed).
static void TitleDiag(const void* color) {
    if (!pQColor_red) return;
    static int n = 0;
    if (n < 8) { Wh_Log(L"[title] fill rgb(%d,%d,%d)", pQColor_red(color), pQColor_green(color), pQColor_blue(color)); n++; }
}
// QBrush fills are redirected to the QColor overload with the substitute color (a solid
// fill), so we never have to construct a QBrush.
void __cdecl FillRect_RC_hook(void* self, const void* rect, const void* color) {
    const void* g;
    if (g_gridPainting > 0 && (g = GridGrayColor())) color = g;
    else if (g_titlePainting > 0 && color) { TitleDiag(color); if (IsSepColor(color) && (g = SepBlackColor())) color = g; }
    pFillRect_RC_orig(self, rect, color);
}
void __cdecl FillRect_RB_hook(void* self, const void* rect, const void* brush) {
    const void* g;
    if (g_gridPainting > 0 && pFillRect_RC_orig && (g = GridGrayColor())) { pFillRect_RC_orig(self, rect, g); return; }
    if (g_titlePainting > 0 && brush && pQBrush_color && pFillRect_RC_orig) {
        const void* bc = pQBrush_color(brush);
        if (bc) { TitleDiag(bc); if (IsSepColor(bc) && (g = SepBlackColor())) { pFillRect_RC_orig(self, rect, g); return; } }
    }
    pFillRect_RB_orig(self, rect, brush);
}
void __cdecl FillRect_IC_hook(void* self, int x, int y, int w, int h, const void* color) {
    const void* g;
    if (g_gridPainting > 0 && (g = GridGrayColor())) color = g;
    else if (g_titlePainting > 0 && color) { TitleDiag(color); if (IsSepColor(color) && (g = SepBlackColor())) color = g; }
    pFillRect_IC_orig(self, x, y, w, h, color);
}
void __cdecl FillRect_IB_hook(void* self, int x, int y, int w, int h, const void* brush) {
    const void* g;
    if (g_gridPainting > 0 && pFillRect_IC_orig && (g = GridGrayColor())) { pFillRect_IC_orig(self, x, y, w, h, g); return; }
    if (g_titlePainting > 0 && brush && pQBrush_color && pFillRect_IC_orig) {
        const void* bc = pQBrush_color(brush);
        if (bc) { TitleDiag(bc); if (IsSepColor(bc) && (g = SepBlackColor())) { pFillRect_IC_orig(self, x, y, w, h, g); return; } }
    }
    pFillRect_IB_orig(self, x, y, w, h, brush);
}
// The AAA8A4 title separator is a PEN draw (drawLine), not a fill -- so recolor the
// pen. setPen(QColor): match AAA8A4 -> black. setPen(QPen): can't read its color
// safely (by-value getter), so force black while a title bar paints -- the title's
// only pen draws are its black text (stays black) + this separator (-> black). The
// _/[]/x buttons are child widgets (g_titlePainting==0 then), unaffected.
static void TitlePenDiag(const void* color, bool isQPen) {
    static int n = 0;
    if (n >= 12) return;
    n++;
    if (isQPen) Wh_Log(L"[title] setPen(QPen) -> forced black");
    else if (pQColor_red) Wh_Log(L"[title] setPen rgb(%d,%d,%d)%s",
        pQColor_red(color), pQColor_green(color), pQColor_blue(color), IsSepColor(color) ? L" MATCH" : L"");
}
void __cdecl SetPen_C_hook(void* self, const void* color) {
    const void* g;
    if (g_titlePainting > 0 && color) {
        TitlePenDiag(color, false);
        if (IsSepColor(color) && (g = SepBlackColor())) { pSetPenC_orig(self, g); return; }
    }
    pSetPenC_orig(self, color);
}
void __cdecl SetPen_P_hook(void* self, const void* pen) {
    const void* g;
    if (g_titlePainting > 0 && pSetPenC_orig && (g = SepBlackColor())) {
        TitlePenDiag(nullptr, true);
        pSetPenC_orig(self, g);   // force black (QPen color read is the crash-prone by-value getter)
        return;
    }
    pSetPenP_orig(self, pen);
}

// --- Turn off alternatingRowColors ----------------------------------------
void __cdecl QAIV_setAlternatingRowColors_hook(void* self, bool enable) {
    // 25.1 removes stripes app-wide; 17.4 keeps native striping EXCEPT the specifically
    // captured Film Domain Setting datagrid (g_filmDomainTable), forced off even on re-populate.
    bool remove = (self && self == g_filmDomainTable) || (g_impl && g_impl->removeStripes && g_noStripes);
    QAIV_setAltRows_orig(self, remove ? false : enable);
}

// --- Visibility-pane: capture pane, blank labels, hide scrollbars ----------
void* g_visPane        = nullptr;   // QObject* of ColorVisibilityPane
void* g_lblGlobalVis   = nullptr;
void* g_lblQuickviews  = nullptr;
void* g_lblView        = nullptr;
void* g_lblConductors  = nullptr;

// True if w is the Vis pane or a descendant (walks parent() on valid QObjects).
static bool IsUnderVisPane(void* w) {
    if (!g_visPane || !pParent) return false;
    void* p = w;
    for (int i = 0; i < 24 && p; i++) { if (p == g_visPane) return true; p = pParent(p); }
    return false;
}

// --- DIAGNOSTIC: one-shot widget-tree dump (RTTI class + structure only) ---
// Deliberately minimal + heavily guarded: NO by-value-QString getters
// (objectName/text), NO geometry/inherits calls -- the richer walk crashed
// inside one of those. RttiClassName both names the node AND validates it is a
// real polymorphic object before we traverse children, so a bad pointer (e.g.
// from a wrong list layout) is logged as "?" and never dereferenced further.
int g_dumpCount = 0;
static void DumpTree(void* obj, int depth) {
    if (!obj || depth > 30 || g_dumpCount > 3000) return;
    if (IsBadReadPtr(obj, sizeof(void*))) return;
    const char* cls = RttiClassName(obj);             // null => not a valid object
    g_dumpCount++;
    Wh_Log(L"[tree] d=%d %S obj=%p", depth, cls ? cls : "?", obj);
    if (!cls || !pChildren) return;

    void* listRef = pChildren(obj);                   // const QObjectList& (ref, no RVO)
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return;
    char* d = *(char**)listRef;                        // QListData::Data*
    if (!d || IsBadReadPtr(d, 16)) return;
    int begin = *(int*)(d + 8);
    int end   = *(int*)(d + 12);
    int n = end - begin;
    if (n <= 0 || n > 4000) return;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return;
    for (int i = 0; i < n; i++) DumpTree(arr[begin + i], depth + 1);
}

// DIAGNOSTIC (read-only): for the first several UIFQTableModel cells, scan the
// QStyleOptionViewItem's backgroundBrush region and log offset + brush style +
// color. QStyleOptionViewItem::backgroundBrush is ~+176 in Qt5 x64; a QBrush is
// {QBrushData* d}; QBrushData = {int ref; int style; QColor color;...}; QColor at
// d+8 = {int spec; ushort alpha,red,green,blue}. Tells us the exact stripe brush
// (offset + gray color) so a precise, crash-free clear can be written next.
int g_brushProbeN = 0;
static void ProbeBrushes(const void* opt, const QtModelIndex* idx) {
    if (!g_probeBrush || !idx || g_brushProbeN >= 16) return;
    const char* mc = RttiClassName(idx->m);
    if (!mc || strcmp(mc, ".?AVUIFQTableModel@@") != 0) return;
    const char* base = (const char*)opt;
    if (IsBadReadPtr((void*)base, 224)) { g_brushProbeN++; return; }
    for (int off = 152; off <= 200; off += 8) {
        const void* d = *(const void* const*)(base + off);
        if (!d || IsBadReadPtr((void*)d, 24)) continue;
        int ref   = *(const int*)d;
        int style = *(const int*)((const char*)d + 4);
        if (ref < -1 || ref > 1000000 || style <= 0 || style > 24) continue;  // skip NoBrush/junk
        const unsigned short* argb = (const unsigned short*)((const char*)d + 12);
        Wh_Log(L"[brush] r=%d c=%d opt+%d style=%d rgb=(%d,%d,%d)",
               idx->r, idx->c, off, style, argb[1] / 257, argb[2] / 257, argb[3] / 257);
    }
    g_brushProbeN++;
}

// Trigger the one-shot dump from the grid's delegate paint (GUI thread, after
// the pane + view are fully built; scoped to the pane's UIFQTableModel grid).
// Paint hooks proved safe in earlier builds; only the data() detour crashed.
bool g_dumped = false;
void __cdecl QStyledItemDelegate_paint_hook(void* self, void* painter, const void* opt, const QtModelIndex* idx) {
    if (g_dumpTree && !g_dumped && g_visPane && idx) {
        const char* mc = RttiClassName(idx->m);
        if (mc && strcmp(mc, ".?AVUIFQTableModel@@") == 0) {
            g_dumped = true;
            g_dumpCount = 0;
            Wh_Log(L"[tree] ===== ColorVisibilityPane tree dump =====");
            DumpTree(g_visPane, 0);
            Wh_Log(L"[tree] ===== end dump: %d nodes =====", g_dumpCount);
        }
    }
    ProbeBrushes(opt, idx);
    QStyledItemDelegate_paint_orig(self, painter, opt, idx);
}

// Set the widget's text to an empty QString via its original setText path
// (QLabel::setText or QAbstractButton::setText -- same ABI).
static void BlankText(void* self, LabelSetText_t orig) {
    if (!pQString_ctor || !pQString_dtor || !orig) return;
    char qs[sizeof(void*) * 2] = {0};
    pQString_ctor(qs);
    orig(self, (const QtString*)qs);
    pQString_dtor(qs);
}

// Set the widget's text to a specific string via its original setText path (build
// the QString with fromUtf16, like ApplyPaneStyle). Used to RELABEL pane texts.
static void SetTextTo(void* self, LabelSetText_t orig, const wchar_t* s) {
    if (!pFromUtf16 || !pQString_dtor || !orig) return;
    char qs[sizeof(void*) * 2] = {0};
    pFromUtf16(qs, (const unsigned short*)s, -1);
    orig(self, (const QtString*)qs);
    pQString_dtor(qs);
}

// Layer-name relabel: short replacement for a Vis-pane label text, or nullptr.
// (User request: "Soldermask_Top" -> "Sm Top", "Soldermask_Bottom" -> "Sm Bot".)
static const wchar_t* PaneTextReplacement(const wchar_t* t) {
    // Layer-select mode re-populates the labels using a SPACE separator ("Soldermask
    // Top") instead of the underscore ("Soldermask_Top") -> match both, else the
    // relabel reverts when that mode is toggled. Whole-text (exact) match, so the
    // subclass paths "Board Geometry/Soldermask_Top" stay untouched.
    if (_wcsicmp(t, L"Soldermask_Top")    == 0 || _wcsicmp(t, L"Soldermask Top")    == 0) return L"Sm Top";
    if (_wcsicmp(t, L"Soldermask_Bottom") == 0 || _wcsicmp(t, L"Soldermask Bottom") == 0) return L"Sm Bot";
    return nullptr;
}

// Outer border around the four panels (Visibility / Find / Options / Command) so
// they don't blend into the surrounding gray. The SPBFoldableDock / CVPane widgets
// themselves do NOT paint a QSS border (custom paint / no styled background -- the
// v0.59 ID-selector borders never showed). But every dock wraps its content in a
// QScrollArea, which IS a QFrame and ALWAYS honors a QSS border. So this sheet is
// set on the DOCK widget (VisibilityBar/FindBar/OptionsBar/CommandBar) and the
// QScrollArea rule cascades DOWN to the dock's content scroll area. Combo popups
// use QComboBoxListView and the command log uses QTextBrowser (both
// QAbstractScrollArea, NOT QScrollArea), so only the dock's outer scroll area
// matches -- no stray inner borders.
#define PANEL_BORDER_CSS \
    L"QScrollArea{border:1px solid rgb(128,128,128);} "

// Border-only sheet, set on a DOCK widget that otherwise carries no stylesheet
// (VisibilityBar in both versions; FindBar in 17.4). Borders its inner QScrollArea.
static void ApplyPanelBorder(void* w) {
    if (!g_panelBorder) return;
    if (!w || !pFromUtf16 || !pSetStyleSheet || !pQString_dtor) return;
    static const wchar_t kCss[] = PANEL_BORDER_CSS;
    char qs[sizeof(void*) * 2] = {0};
    pFromUtf16(qs, (const unsigned short*)kCss, -1);
    pSetStyleSheet(w, (const QtString*)qs);
    pQString_dtor(qs);
}

// Apply a pane-scoped stylesheet (one sheet -- setStyleSheet replaces, so the
// active tweaks are concatenated). Scrollbar collapse + the item-background
// override that covers the model's per-row stripe brushes. The stripe rule is
// plain QTableView::item (no pseudo-state), so the global sheet's more-specific
// ::item:selected / :hover rules still win -> selection & hover stay intact.
static void ApplyPaneStyle(void* paneWidget) {
    if (!paneWidget || !pFromUtf16 || !pSetStyleSheet || !pQString_dtor) return;
    wchar_t css[1024]; css[0] = L'\0';
    if (g_hideScrollbars)
        lstrcatW(css, L"QScrollBar:vertical{width:0px;max-width:0px;} "
                      L"QScrollBar:horizontal{height:0px;max-height:0px;} ");
    if (g_stdCheckboxes)
        // DEFERRED: the grid checkboxes are real AQCheckBox widgets that CVPLayerGrid
        // stretches to the row height (the row height is driven by the tall
        // CVPColorButton color swatches). A scoped `max-height:16px` here only
        // compressed the row spacing without shrinking the boxes, so it was reverted.
        // Sizing them down needs shrinking the row height (which shrinks the swatches
        // too) or fighting the custom layout -- left for later. This bare indicator
        // rule is a no-op on these custom-painted boxes but is harmless.
        lstrcatW(css, L"QAbstractItemView::indicator{width:16px;height:16px;} "
                      L"QCheckBox::indicator{width:16px;height:16px;} ");
    if (g_noStripes)
        // The stripe is a per-row model brush, which the base style paints OVER
        // any ::item background -- so a ::item rule cannot win. The model derives
        // that brush from the palette AlternateBase (the QSS
        // alternate-background-color); override base + alternate to the Windows
        // face gray rgb(212,208,200) so every row matches the pane and no stripe
        // shows. (::item kept as backup.)
        // The grid view is a descendant of CVPane but NOT a QTableView, so the
        // QTableView selector never reached it. The universal selector sets the
        // palette AlternateBase on every descendant (incl. the grid view), which
        // is where a custom model usually reads its per-row stripe brush from.
        lstrcatW(css, L"QTableView{background-color:rgb(212,208,200);alternate-background-color:rgb(212,208,200);} "
                      L"QTableView::item{background-color:rgb(212,208,200);} "
                      L"*{alternate-background-color:rgb(212,208,200);} ");
    if (g_comboShrink)
        // The two pane combos default to AdjustToContentsOnFirstShow, so their
        // minimum width = the widest item string, which blocks narrowing the pane.
        // AdjustToMinimumContentsLengthWithIcon (with the default minimumContents-
        // Length 0) drops that content-based minimum so the combo can shrink; the
        // popup still sizes to the items, so the list text stays readable. (QSS
        // type selectors match subclasses too, so a custom combo subclass is hit.)
        lstrcatW(css, L"QComboBox{qproperty-sizeAdjustPolicy:AdjustToMinimumContentsLengthWithIcon;} ");
    // "Enable layer select mode" checkbox (AQCheckBox #CVPLayerSelectBox) renders
    // centered with padding on both sides; zero its box padding/margin (and force
    // left text) so the indicator + text sit at the left edge of the pane.
    lstrcatW(css, L"#CVPLayerSelectBox{padding:0px;margin:0px;text-align:left;} "
                  L"#CVPLayerSelectBox::indicator{width:16px;height:16px;} ");
    // NOTE: the panel border is NOT applied here -- this sheet is set on CVPane, which
    // sits BELOW the dock's QScrollArea, so it can't reach it. The Visibility border is
    // applied on the VisibilityBar dock instead (see the VisibilityBar match below).
    if (!css[0]) return;
    char qs[sizeof(void*) * 2] = {0};
    pFromUtf16(qs, (const unsigned short*)css, -1);
    pSetStyleSheet(paneWidget, (const QtString*)qs);
    pQString_dtor(qs);
    if (g_probeVisPane) Wh_Log(L"[vispane] pane style applied (scroll=%d stripes=%d) pane=%p",
                               (int)g_hideScrollbars, (int)g_noStripes, paneWidget);
}

// Destripe 17.4's Visibility pane to CLASSIC GRAY (212,208,200). The QSS handles the
// row backgrounds + the model stripe (AlternateBase). What QSS/palette CANNOT reach
// is Cadence's hardcoded paint: CVPLayerGrid fills its no-button "N/A" cells (e.g.
// Anti/Bnd/Etch on a soldermask row) and its section dividers in WHITE in its own
// paintEvent (compiled into allegro.exe -- not hookable directly). Those whites are
// recolored to gray by the QPainter::fillRect hook gated on g_gridPainting (see the
// notify hook). So: QSS makes the rows gray, the paint hook makes the hardcoded
// whites gray -> uniform classic gray. (25.1 stays gray via ApplyPaneStyle.)
static void ApplyDestripe(void* paneWidget) {
    if (!paneWidget || !pFromUtf16 || !pSetStyleSheet || !pQString_dtor) return;
    const wchar_t* css =
        L"#CVPLayerGrid{background-color:rgb(212,208,200);} "
        L"#CVPLayerGrid QLabel{background-color:rgb(212,208,200);} "
        L"#CVPLayerGrid QFrame{background-color:rgb(212,208,200); border:none;} "
        L"*{alternate-background-color:rgb(212,208,200);} ";
    char qs[sizeof(void*) * 2] = {0};
    pFromUtf16(qs, (const unsigned short*)css, -1);
    pSetStyleSheet(paneWidget, (const QtString*)qs);
    pQString_dtor(qs);
    if (g_probeVisPane) Wh_Log(L"[vispane] 17.4 destripe (gray) applied pane=%p", paneWidget);
}

// CVPLayerGrid's own etched separators are drawn from the palette 3D shade roles,
// which QSS can't set. Flatten all five to the pane's base color so any such line
// blends. The pane is now WHITE (see ApplyDestripe), so flatten to white -- a white
// etched line on a white grid is invisible.
static void FlattenShades(void* widget) {
    if (!widget || !pQWidget_palette || !pQPalette_copy || !pQPalette_setColor ||
        !pQColor_ctor || !pQWidget_setPalette || !pQPalette_dtor) return;
    const void* cur = pQWidget_palette(widget);
    if (!cur || IsBadReadPtr(cur, sizeof(void*))) return;
    char pal[64] = {0};
    pQPalette_copy(pal, cur);
    char col[24] = {0};
    pQColor_ctor(col, 212, 208, 200, 255);  // classic gray (17.4 pane base)
    pQPalette_setColor(pal, 2,  col);        // Light
    pQPalette_setColor(pal, 3,  col);        // Midlight
    pQPalette_setColor(pal, 5,  col);        // Mid
    pQPalette_setColor(pal, 4,  col);        // Dark
    pQPalette_setColor(pal, 11, col);        // Shadow
    pQWidget_setPalette(widget, pal);
    pQPalette_dtor(pal);
    if (g_probeVisPane) Wh_Log(L"[vispane] flattened shades (white) on %p", widget);
}

// Hide BOTH scrollbars on a pane (Find / Options), via a pane-scoped stylesheet
// so it cascades to the pane's descendant scroll areas.
static void ApplyDockScrollHide(void* paneWidget) {
    if (!paneWidget || !pFromUtf16 || !pSetStyleSheet || !pQString_dtor) return;
    wchar_t css[256];
    lstrcpyW(css, L"QScrollBar:vertical{width:0px;max-width:0px;} "
                  L"QScrollBar:horizontal{height:0px;max-height:0px;} ");
    if (g_panelBorder) lstrcatW(css, PANEL_BORDER_CSS);  // outer panel border (dock's QScrollArea)
    char qs[sizeof(void*) * 2] = {0};
    pFromUtf16(qs, (const unsigned short*)css, -1);
    pSetStyleSheet(paneWidget, (const QtString*)qs);
    pQString_dtor(qs);
}

// 17.4 Find dock: never show a HORIZONTAL scrollbar (25.1 hides both on its Find via
// ApplyDockScrollHide; here we suppress only horizontal so a vertical scrollbar can
// still appear for tall content) + the optional panel border. ONE sheet, set on the
// FindBar dock -> cascades to its content QScrollArea. The vertical scrollbar is left
// intact intentionally (only the horizontal one was complained about).
static void ApplyFindHScrollHide(void* dock) {
    if (!dock || !pFromUtf16 || !pSetStyleSheet || !pQString_dtor) return;
    wchar_t css[256]; css[0] = L'\0';
    if (g_noHScroll)   lstrcatW(css, L"QScrollBar:horizontal{height:0px;max-height:0px;} ");
    if (g_panelBorder) lstrcatW(css, PANEL_BORDER_CSS);
    if (!css[0]) return;
    char qs[sizeof(void*) * 2] = {0};
    pFromUtf16(qs, (const unsigned short*)css, -1);
    pSetStyleSheet(dock, (const QtString*)qs);
    pQString_dtor(qs);
}

// CommandBar: H-scroll hide + set the command input font (QLineEdit/QComboBox and
// the combo's popup) to Consolas 10pt, black text on the default background. One
// sheet (setStyleSheet replaces). The "Command >" prompt is hidden separately by text.
static void ApplyCommandStyle(void* paneWidget) {
    if (!paneWidget || !pFromUtf16 || !pSetStyleSheet || !pQString_dtor) return;
    wchar_t css[512]; css[0] = L'\0';
    if (g_noHScroll)
        lstrcatW(css, L"QScrollBar:horizontal{height:0px;max-height:0px;} ");
    if (g_styleCmd)
        // Font only: Consolas 10pt, black text on the default field background.
        // (The earlier black-bg / white-text styling was reverted per request.)
        lstrcatW(css, L"QLineEdit,QComboBox,QComboBox QLineEdit,QComboBox QAbstractItemView"
                      L"{color:black;font-family:\"Consolas\";font-size:10pt;} ");
    // Command OUTPUT log: Cascadia Code font. 25.1's output is a CommandTextBrowser;
    // 17.4's is a plain QTextBrowser (verified via inspector). QSS type selectors match
    // subclasses, so the QTextBrowser base selector covers BOTH (scoped to this dock).
    lstrcatW(css, L"QTextBrowser{font-family:\"Cascadia Code\";} ");
    // Outer panel border on the CommandBar dock's content QScrollArea (user setting).
    if (g_panelBorder) lstrcatW(css, PANEL_BORDER_CSS);
    if (!css[0]) return;
    char qs[sizeof(void*) * 2] = {0};
    pFromUtf16(qs, (const unsigned short*)css, -1);
    pSetStyleSheet(paneWidget, (const QtString*)qs);
    pQString_dtor(qs);
}

// Classify a setText argument as one of the Visibility-pane texts we blank.
// 0 = none. "View" is a QLabel directly under CVPane (one-shot is fine).
// "Conductors"/"Masks" are AQCheckBox group labels created late and RE-SET on
// every grid refresh -> blank them every time the pane exists, not just once, or
// they reappear after a repopulate.
static int ClassifyPaneText(void* self, const wchar_t* t) {
    if (ContainsCI(t, L"global visibility")) return 1;
    if (ContainsCI(t, L"quickview"))         return 2;
    if (_wcsicmp(t, L"View") == 0 && (IsUnderVisPane(self) || (g_visPane && !g_lblView))) return 3;
    if ((_wcsicmp(t, L"Conductors") == 0 || _wcsicmp(t, L"Masks") == 0) && g_visPane) return 4;  // blank on EVERY set
    // The "Class/Subclass (user selected)" label: a rich-text QLabel with no objectName,
    // matched by its distinctive "Class/Subclass" text. The g_visPane requirement was DROPPED
    // (v0.49.0): in 17.4 this label's text is sometimes set BEFORE the pane is captured, so
    // requiring g_visPane intermittently missed it (the label reappeared). "class/subclass"
    // with the SLASH is distinctive enough alone (the Options "class and subclass" has no
    // slash, so no false match). Hidden, not blanked.
    if (ContainsCI(t, L"class/subclass")) return 5;
    // The Options pane "Active Class and Subclass" label (no slash) -- blank its text on
    // request. Distinct from the Vis-pane "Class/Subclass" (cls 5, has a slash), so the
    // "and" form matches ONLY the Options label and never the slash label.
    if (ContainsCI(t, L"class and subclass")) return 6;
    return 0;
}

// Shared body for QLabel::setText and QAbstractButton::setText.
// DIAGNOSTIC (temporary): append a label's setText text to text_probe.log so the
// EXACT "Soldermask..." string (normal vs layer-select mode) can be read back,
// instead of guessing the separator/format. Remove once the relabel match is fixed.
static void ProbeText(const wchar_t* s) {
    if (!s) return;
    char u8[1100];
    int nn = WideCharToMultiByte(CP_UTF8, 0, s, -1, u8, (int)sizeof(u8) - 2, nullptr, nullptr);
    if (nn <= 0) return;
    if (u8[nn - 1] == '\0') nn--;
    u8[nn++] = '\r'; u8[nn++] = '\n';
    HANDLE h = CreateFileW(L"C:\\Dropbox\\Common\\cfg\\windhawk\\allegro\\text_probe.log",
                           FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) { DWORD wr; WriteFile(h, u8, (DWORD)nn, &wr, nullptr); CloseHandle(h); }
}

static void HandlePaneSetText(void* self, const QtString* text, LabelSetText_t orig) {
    // Pane text editing is VERSION-SPECIFIC. blankLabels gates it entirely; what gets
    // touched is further controlled per-version by g_impl->relabelLayers (Soldermask
    // relabel) and g_impl->blankSecondary (Quickviews + Conductors/Masks). 17.4 blanks
    // only Global visibility / View / Class-Subclass; 25.1 does the full set.
    if (!g_impl || !g_impl->blankLabels) { orig(self, text); return; }
    // Match on the RAW (untruncated) QString text: the rich-text "Class/Subclass"
    // label's setText arg is HTML and can be long, which overflowed a fixed buffer.
    int len = 0;
    const unsigned short* u = (self && text) ? QtStr_data(text, &len) : nullptr;
    const wchar_t* raw = (len > 0) ? (const wchar_t*)u : nullptr;
    if (raw && g_impl->relabelLayers && ContainsCI(raw, L"soldermask")) ProbeText(raw);  // DIAG (25.1 relabel only)

    // Layer-name relabel (e.g. "Soldermask_Top" -> "Sm Top"): rewrite via the
    // original setText. Scoped to "after the Vis pane is captured" (g_visPane) --
    // IsUnderVisPane is unreliable here, since a label may not be parented yet when
    // its text is first set (same reason the Conductors match uses g_visPane).
    if (raw && g_visPane && g_impl->relabelLayers) {
        const wchar_t* repl = PaneTextReplacement(raw);
        if (repl) { SetTextTo(self, orig, repl); return; }
    }

    int cls = raw ? ClassifyPaneText(self, raw) : 0;
    // 17.4 removes only Global visibility (1), View (3) and Class/Subclass (5). The
    // secondary labels Quickviews (2) and Conductors/Masks (4) are blanked only by 25.1.
    if (!g_impl->blankSecondary && (cls == 2 || cls == 4)) cls = 0;

    // cls 5 (the Class/Subclass label) is rich text -> don't blank it; pass the
    // text through and hide the whole widget below.
    if (g_blankLabels && cls && cls != 5) BlankText(self, orig);
    else                                  orig(self, text);

    switch (cls) {
        case 1: g_lblGlobalVis  = self; break;
        case 2: g_lblQuickviews = self; break;
        case 3: g_lblView       = self; break;
        case 4: g_lblConductors = self; break;
    }

    // The 3 header labels (1/2/3) are QLabels in a QGridLayout: blanking leaves
    // their column width, so HIDE them -> the column collapses and the controls to
    // their right stretch into the freed space. (Conductors=4 is a checkbox: keep
    // the widget, only its text was blanked.)
    if (g_blankLabels && (cls == 1 || cls == 2 || cls == 3) && pSetVisible)
        pSetVisible(self, false);
    // The Class/Subclass label: hide it outright (re-hidden on every set in case
    // it is repopulated/shown again).
    if (cls == 5 && pSetVisible)
        pSetVisible(self, false);

    if (g_probeVisPane && cls)
        Wh_Log(L"[vispane] %s widget=%p cls=%d",
               (g_blankLabels ? L"blanked" : L"saw"), self, cls);
}

void __cdecl QLabel_setText_hook(void* self, const QtString* text) {
    HandlePaneSetText(self, text, QLabel_setText_orig);
}
void __cdecl QAbstractButton_setText_hook(void* self, const QtString* text) {
    HandlePaneSetText(self, text, QAbstractButton_setText_orig);
}

// The special "_" toolbar (an SPBToolBar with no objectName) docks when dragged.
// Match it by its window title "_" and set NoToolBarArea so it floats freely instead
// of being forced into a dock. Filtered to *ToolBar classes so a stray "_" title on
// some other widget is ignored.
void __cdecl QWidget_setWindowTitle_hook(void* self, const QtString* title) {
    QWidget_setWindowTitle_orig(self, title);
    // Float-toolbar is SHARED (both chunks keep it); floatToolbar is a user setting.
    if (!g_floatToolbar || !pSetAllowedAreas || !self || !title) return;
    int len = 0;
    const unsigned short* u = QtStr_data(title, &len);
    if (!u || len <= 0) return;
    const wchar_t* t = (const wchar_t*)u;
    if (_wcsicmp(t, L"_") != 0) return;
    const char* cls = RttiClassName(self);
    if (cls && strstr(cls, "ToolBar")) pSetAllowedAreas(self, 0);  // Qt::NoToolBarArea
}

// (object -> objectName) table, filled HERE from the hooked setObjectName -- it
// reads the QString argument directly (QtStr_data + lstrcpynW), never a getter, so
// it is crash-safe in this CFG exe. The Inspector looks names up from this table
// instead of calling the fatal objectName() getter.
struct NameReg { void* obj; wchar_t name[64]; };
NameReg g_nameReg[1024];
int     g_nameRegN = 0;
static void RegisterName(void* obj, const wchar_t* name) {
    if (!obj || !name || !name[0]) return;
    for (int i = 0; i < g_nameRegN; i++)
        if (g_nameReg[i].obj == obj) { lstrcpynW(g_nameReg[i].name, name, 64); return; }
    if (g_nameRegN < 1024) { g_nameReg[g_nameRegN].obj = obj; lstrcpynW(g_nameReg[g_nameRegN].name, name, 64); g_nameRegN++; }
}
static const wchar_t* LookupName(void* obj) {
    for (int i = 0; i < g_nameRegN; i++) if (g_nameReg[i].obj == obj) return g_nameReg[i].name;
    return L"";
}

// Find-pane "By Saved Query" combo: it has no objectName, so it's captured via its
// named ancestor group ("Design Object Find Filter") -- walk that subtree and pin
// each UIFQComboBox to a FIXED 216px width (min==max). Expanding made it overflow and
// clip; 216 fits inside the 230px group. The combo may not exist yet when the group
// is named, so the walk is retried on later setObjectName calls until found.
void* g_findFilterGroup = nullptr;
bool  g_findCombosDone  = false;
int   g_findComboTries  = 0;
static int PinFindCombos(void* obj, int depth) {           // returns # combos set
    if (!obj || depth > 12 || IsBadReadPtr(obj, sizeof(void*))) return 0;
    const char* cls = RttiClassName(obj);
    if (!cls) return 0;
    if (strstr(cls, "UIFQComboBox")) {                          // the find-pane combo
        if (pSetMinWidth && pSetMaxWidth) { pSetMinWidth(obj, 216); pSetMaxWidth(obj, 216); }
        return 1;                                               // don't descend into combo internals
    }
    if (!pChildren) return 0;
    void* listRef = pChildren(obj);
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return 0;
    char* d = *(char**)listRef;
    if (!d || IsBadReadPtr(d, 16)) return 0;
    int begin = *(int*)(d + 8), end = *(int*)(d + 12), n = end - begin;
    if (n <= 0 || n > 4000) return 0;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return 0;
    int set = 0;
    for (int i = 0; i < n; i++) set += PinFindCombos(arr[begin + i], depth + 1);
    return set;
}

// Vis-pane grid spacing: CVPLayerGrid (no objectName) arranges its columns with a
// QGridLayout whose horizontal spacing is too wide. Walk g_visPane to find
// CVPLayerGrid, then its QGridLayout child, and tighten horizontalSpacing to 2px.
// Retried on each setObjectName until found (the grid is built after the pane).
bool g_gridSpacingDone  = false;
int  g_gridSpacingTries = 0;
static bool TightenGridSpacing(void* obj, int depth) {
    if (!obj || depth > 16 || IsBadReadPtr(obj, sizeof(void*)) || !pChildren) return false;
    const char* cls = RttiClassName(obj);
    if (!cls) return false;
    void* listRef = pChildren(obj);
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return false;
    char* d = *(char**)listRef;
    if (!d || IsBadReadPtr(d, 16)) return false;
    int begin = *(int*)(d + 8), end = *(int*)(d + 12), n = end - begin;
    if (n <= 0 || n > 4000) return false;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return false;
    if (strstr(cls, "CVPLayerGrid")) {                          // found the grid
        for (int i = 0; i < n; i++) {                           // its QGridLayout is a child
            const char* c = RttiClassName(arr[begin + i]);
            if (c && strstr(c, "GridLayout")) {
                void* lay = arr[begin + i];
                if (pSetHSpacing) pSetHSpacing(lay, 2);          // tight inter-column gap
                // The columns stretch to FILL the pane (that's why shrinking spacing
                // spread them out). Zero every real column's stretch so each is sized
                // to its content, and put a stretch on a far-right empty column so the
                // slack collects there -> the checkbox columns pack to the left.
                if (pSetColStretch) {
                    for (int s = 0; s < 40; s++) pSetColStretch(lay, s, 0);
                    pSetColStretch(lay, 50, 1);
                }
                return true;
            }
        }
        return false;
    }
    for (int i = 0; i < n; i++) if (TightenGridSpacing(arr[begin + i], depth + 1)) return true;
    return false;
}

// "Command >" prompt (17.4): it is a bare QLineEdit DIRECT child of SPBCommandWindow
// "CommmandPane" [sic, 3 m's] with NO objectName, so it can't be matched directly. We
// capture the pane and hide any QLineEdit among its IMMEDIATE children. The real command
// input is a QLineEdit nested INSIDE an editable QComboBox (depth 2, not a direct child),
// so this never touches the input. Retried per setObjectName until found (the prompt may
// be built after the pane's name is set). 25.1 hides its named SPBCommandPrompt instead.
void* g_cmdPane        = nullptr;
bool  g_cmdPromptDone  = false;
int   g_cmdPromptTries = 0;
static bool HideCommandPrompt(void* pane) {
    if (!pane || !pChildren || !pSetVisible) return false;
    void* listRef = pChildren(pane);
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return false;
    char* d = *(char**)listRef;
    if (!d || IsBadReadPtr(d, 16)) return false;
    int begin = *(int*)(d + 8), end = *(int*)(d + 12), n = end - begin;
    if (n <= 0 || n > 4000) return false;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return false;
    bool hid = false;
    for (int i = 0; i < n; i++) {
        const char* cls = RttiClassName(arr[begin + i]);   // exact-direct-child only
        if (cls && strstr(cls, "QLineEdit")) { pSetVisible(arr[begin + i], false); hid = true; }
    }
    return hid;
}

// Options pane (17.4): the "Active Class and Subclass" combos don't fill the pane, leaving
// empty padding to their right. Walk the captured OptionsBar subtree: give every combo an
// Expanding width policy, and zero the "scrollPanel" content panel's layout margins so the
// combos run to the right edge. A combo returns without descending (its popup internals are
// QComboBox*-named and must not be touched). Scoped to OptionsBar so the Find pane is untouched.
void* g_optionsBar   = nullptr;
bool  g_optFillDone  = false;
int   g_optFillTries = 0;
static int FillOptionsPane(void* node, int depth) {        // returns # combos expanded
    if (!node || depth > 16 || IsBadReadPtr(node, sizeof(void*))) return 0;
    const char* cls = RttiClassName(node);
    if (!cls) return 0;
    if (strstr(cls, "ComboBox")) {                          // a UIFQComboBox -> fill width
        if (pSetSizePolicy2) pSetSizePolicy2(node, 7, 0);   // Expanding (H) / Fixed (V)
        return 1;                                           // don't descend into popup internals
    }
    if (pWidgetLayout && pSetContentsMargins) {             // the content panel -> drop margins
        const wchar_t* nm = LookupName(node);
        if (nm && _wcsicmp(nm, L"scrollPanel") == 0) {
            void* lay = pWidgetLayout(node);
            if (lay) pSetContentsMargins(lay, 0, 0, 0, 0);
        }
    }
    if (!pChildren) return 0;
    void* listRef = pChildren(node);
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return 0;
    char* d = *(char**)listRef;
    if (!d || IsBadReadPtr(d, 16)) return 0;
    int begin = *(int*)(d + 8), end = *(int*)(d + 12), n = end - begin;
    if (n <= 0 || n > 4000) return 0;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return 0;
    int count = 0;
    for (int i = 0; i < n; i++) count += FillOptionsPane(arr[begin + i], depth + 1);
    return count;
}

// Artwork "Available films" (17.4): the groupbox widens (min 450) but its INTERNAL
// UIFGridLayout leaves the UIFQTreeWidget narrow (empty space to the tree's right inside the
// groupbox). Walk the captured groupbox for the tree and pin ITS minimum width too so it
// fills the widened groupbox. (UIFGridLayout ignores sizePolicy -> minimumWidth is the lever.)
void* g_availFilmsGroup = nullptr;
bool  g_availTreeDone   = false;
int   g_availTreeTries  = 0;
static bool WidenAvailTree(void* node, int depth) {
    if (!node || depth > 10 || IsBadReadPtr(node, sizeof(void*))) return false;
    const char* cls = RttiClassName(node);
    if (!cls) return false;
    if (strstr(cls, "TreeWidget")) { if (pSetMinWidth) pSetMinWidth(node, 580); return true; }
    if (!pChildren) return false;
    void* listRef = pChildren(node);
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return false;
    char* d = *(char**)listRef;
    if (!d || IsBadReadPtr(d, 16)) return false;
    int begin = *(int*)(d + 8), end = *(int*)(d + 12), n = end - begin;
    if (n <= 0 || n > 4000) return false;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return false;
    for (int i = 0; i < n; i++) if (WidenAvailTree(arr[begin + i], depth + 1)) return true;
    return false;
}

// Film Domain Setting dialog (17.4): its datagrid (UIFQTableView) shows striped rows. Walk the
// captured dialog for the table, remember it (g_filmDomainTable) so the shared
// setAlternatingRowColors hook keeps forcing stripes off even if the app re-enables on populate,
// and turn them off once now. (17.4 keeps native stripes generally; this destripes just this table.)
void* g_filmDomainDlg   = nullptr;
bool  g_filmDomainDone  = false;
int   g_filmDomainTries = 0;
static bool FindFilmDomainTable(void* node, int depth) {
    if (!node || depth > 12 || IsBadReadPtr(node, sizeof(void*))) return false;
    const char* cls = RttiClassName(node);
    if (!cls) return false;
    if (strstr(cls, "TableView")) {                         // UIFQTableView -> the datagrid
        g_filmDomainTable = node;
        if (QAIV_setAltRows_orig) QAIV_setAltRows_orig(node, false);   // case: plain alternatingRowColors
        // case: per-row MODEL brush (like the Visibility grid) -- setAltRows can't remove that.
        // Override the palette so base == alternate (white) so the model's stripe brush blends in
        // (the model derives its stripe from AlternateBase; selection/hover rules are more specific
        // and still win). This is the same trick ApplyPaneStyle uses for the Visibility grid.
        if (pFromUtf16 && pSetStyleSheet && pQString_dtor) {
            static const wchar_t kCss[] =
                L"QTableView{background-color:white;alternate-background-color:white;} "
                L"QTableView::item{background-color:white;} "
                L"*{alternate-background-color:white;}";
            char qs[sizeof(void*) * 2] = {0};
            pFromUtf16(qs, (const unsigned short*)kCss, -1);
            pSetStyleSheet(node, (const QtString*)qs);
            pQString_dtor(qs);
        }
        return true;
    }
    if (!pChildren) return false;
    void* listRef = pChildren(node);
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return false;
    char* d = *(char**)listRef;
    if (!d || IsBadReadPtr(d, 16)) return false;
    int begin = *(int*)(d + 8), end = *(int*)(d + 12), n = end - begin;
    if (n <= 0 || n > 4000) return false;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return false;
    for (int i = 0; i < n; i++) if (FindFilmDomainTable(arr[begin + i], depth + 1)) return true;
    return false;
}

// DXF In Edit/View Layers dialog (17.4): open it ~2x taller with the layer datagrid taking
// the added height. The reliable lever is the TABLE's minimumHeight -- exactly like Available
// films' tree min-WIDTH sizes that dialog wide; Cadence's UIFGridLayout ignores sizePolicy, so
// pinning a min is the only thing that grows a child. Walk the captured dialog for the
// UIFQTableView and pin its height (which pushes the whole dialog taller).
void* g_dxfDlg   = nullptr;
bool  g_dxfDone  = false;
int   g_dxfTries = 0;
static bool FindDxfTable(void* node, int depth) {
    if (!node || depth > 12 || IsBadReadPtr(node, sizeof(void*))) return false;
    const char* cls = RttiClassName(node);
    if (!cls) return false;
    if (strstr(cls, "TableView")) {                     // UIFQTableView -> the layer datagrid
        if (pSetMinHeight) pSetMinHeight(node, 450);    // grow the grid -> grows the dialog
        return true;
    }
    if (!pChildren) return false;
    void* listRef = pChildren(node);
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return false;
    char* d = *(char**)listRef;
    if (!d || IsBadReadPtr(d, 16)) return false;
    int begin = *(int*)(d + 8), end = *(int*)(d + 12), n = end - begin;
    if (n <= 0 || n > 4000) return false;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return false;
    for (int i = 0; i < n; i++) if (FindDxfTable(arr[begin + i], depth + 1)) return true;
    return false;
}

// ===========================================================================
// VERSION CHUNK: Allegro 25.1 -- the FULL tweak set
// ===========================================================================
// This is the per-version setObjectName policy for 25.1: pane capture + full pane
// styling (stripes / scrollbars / combo shrink / checkbox indicator), the layer-grid
// spacing, the "Enable layer select mode" anchor, plus the version-agnostic chrome /
// dock / command tweaks. (Label/text blanking, the "_"-toolbar float, the inspector
// and ALL diagnostics are SHARED -- see HandlePaneSetText, QWidget_setWindowTitle_hook
// and the inspector section -- and apply to both versions.)
namespace v251 {
void OnSetObjectName(void* self, const wchar_t* w) {
    // Find-pane combo width (see PinFindCombos): capture the named filter group,
    // then walk it for the (unnamed) combo on each setObjectName until found.
    if (pSetMinWidth && pSetMaxWidth) {
        if (_wcsicmp(w, L"Design Object Find Filter") == 0) g_findFilterGroup = self;
        if (g_findFilterGroup && !g_findCombosDone && g_findComboTries < 128) {
            g_findComboTries++;
            if (PinFindCombos(g_findFilterGroup, 0) > 0) g_findCombosDone = true;
        }
    }

    // Vis-pane grid: tighten CVPLayerGrid's QGridLayout horizontal spacing once the
    // pane (g_visPane) is captured and the grid exists (retried until found).
    if (pSetHSpacing && g_visPane && !g_gridSpacingDone && g_gridSpacingTries < 128) {
        g_gridSpacingTries++;
        if (TightenGridSpacing(g_visPane, 0)) g_gridSpacingDone = true;
    }

    // Find-pane groupboxes "Design Object Find Filter" / "Find By Name": pin to a
    // fixed 230px width (min == max) to remove the slack/padding around them.
    if (pSetMinWidth && pSetMaxWidth &&
        (_wcsicmp(w, L"Design Object Find Filter") == 0 || _wcsicmp(w, L"Find By Name") == 0)) {
        pSetMinWidth(self, 230);
        pSetMaxWidth(self, 230);
    }

    // "Enable layer select mode" checkbox (AQCheckBox CVPLayerSelectBox): make it
    // Expanding so it fills the pane width and its indicator+text anchor LEFT (the
    // CSS text-align didn't move it -- the widget was narrow and centered by the
    // layout). Indicator size is pinned in ApplyPaneStyle.
    if (pSetSizePolicy2 && _wcsicmp(w, L"CVPLayerSelectBox") == 0) pSetSizePolicy2(self, 7, 0);

    // Native item-view checkbox fix REMOVED (mirrors the 17.4 chunk, v0.46.0): `image:none`
    // now leaves tree/list (UIFQTreeWidget) checkboxes BLANK in 25.1 too -- its item-views no
    // longer draw a native indicator under the current theming -- so Cadence's own indicators
    // are left alone (which renders the checkboxes). Confirmed blank by the user in 25.1.

    // "Command >" prompt: a QLineEdit named "SPBCommandPrompt" to the LEFT of the
    // real command input -- hide it. Matched by objectName (its text is set before
    // our hooks, so the old text match never caught it); setVisible(false) sticks.
    if (g_hideCmdPrompt && pSetVisible && _wcsicmp(w, L"SPBCommandPrompt") == 0) { pSetVisible(self, false); return; }

    // Cadence "cadence" logo: a QLabel named "LogoWidget" in the menu bar -- hide
    // it (replace with nothing). setVisible(false) sets the explicit-hide flag so
    // it stays hidden when its parent is later shown (same lever as the header
    // labels / the "Command >" prompt; calling setVisible on a captured widget is
    // safe here -- only the GLOBAL setVisible hook crashed).
    if (pSetVisible && _wcsicmp(w, L"LogoWidget") == 0) { pSetVisible(self, false); return; }

    // Visibility pane: full treatment (scrollbars + stripes + color).
    if (ContainsCI(w, L"colorvisibilitypane")) {
        g_visPane = self;
        if (g_probeVisPane) Wh_Log(L"[vispane] captured ColorVisibilityPane = %p", self);
        ApplyPaneStyle(self);
        return;
    }

    // Find / Options docks (SPBFoldableDock, names from the [names] dump): hide
    // BOTH scrollbars. Exact names so the *BarWindow wrappers aren't matched.
    if (g_noHScroll && (_wcsicmp(w, L"OptionsBar") == 0 || _wcsicmp(w, L"FindBar") == 0)) {
        ApplyDockScrollHide(self);
        Wh_Log(L"[scroll] hid scrollbars on \"%s\" (%p)", w, self);
    }
    // CommandBar: H-scroll hide + command input font (Consolas 10pt, black text).
    else if (_wcsicmp(w, L"CommandBar") == 0) {
        ApplyCommandStyle(self);
        Wh_Log(L"[cmd] styled CommandBar (hscroll=%d styleCmd=%d) (%p)",
               (int)g_noHScroll, (int)g_styleCmd, self);
    }
    // VisibilityBar dock: the vis pane's own sheet (on CVPane) can't reach the dock's
    // QScrollArea, so border it from the dock here. No other sheet on this dock.
    else if (_wcsicmp(w, L"VisibilityBar") == 0) {
        ApplyPanelBorder(self);
    }
}
}  // namespace v251

// ===========================================================================
// VERSION CHUNK: Allegro 17.4 -- subset (NO Visibility-pane appearance tweaks)
// ===========================================================================
// 17.4's Visibility pane already renders the way we want, so this chunk does NOT
// touch pane appearance: no row-stripe removal (see QAIV_setAlternatingRowColors_hook),
// no pane scrollbar hide, no combo shrink, no grid spacing, no layer-select-box anchor
// -- i.e. it does NOT call ApplyPaneStyle. It KEEPS the version-agnostic tweaks: the
// Find/Options/Command dock + command-input styling, the "Command >" prompt hide, the
// find combo / group-box widths, native item-view checkboxes, and the cadence-logo
// hide. It still CAPTURES the pane (g_visPane) so the SHARED label/text blanking
// (HandlePaneSetText) stays scoped to it. (Label/text blanking, the "_"-toolbar float,
// the inspector + diagnostics are SHARED and apply here too.)
namespace v174 {
void OnSetObjectName(void* self, const wchar_t* w) {
    // Full-width Visibility controls: the "Global visibility" On/Off/Last buttons
    // (CVPGlobalVisOn/Off/Restore) + the View dropdown (CVPViewDropdown) -- give them an
    // Expanding horizontal size policy so they fill the pane width. (In 25.1 this falls
    // out of hiding the header labels; 17.4 keeps the labels, so we stretch the controls
    // directly + zero the pane layout margins on capture, below.)
    if (pSetSizePolicy2 &&
        (_wcsicmp(w, L"CVPGlobalVisOn")      == 0 || _wcsicmp(w, L"CVPGlobalVisOff") == 0 ||
         _wcsicmp(w, L"CVPGlobalVisRestore") == 0 || _wcsicmp(w, L"CVPViewDropdown") == 0)) {
        pSetSizePolicy2(self, 7, 0);   // Expanding (H) / Fixed (V)
    }

    // Artwork Control Form: widen "Available films" to a 600px MINIMUM, AND widen the
    // UIFQTreeWidget INSIDE it -- the groupbox got wider but its internal UIFGridLayout left
    // the tree narrow (empty space to its right), so the film list never showed more. Capture
    // the groupbox and walk it for the tree to pin the tree's min width too (retried until
    // found). NOTE: true resize-following still does NOT work here (custom UIFGridLayout
    // ignores sizePolicy; pinning "Film options" Fixed broke its fields) -- static mins only.
    if (_wcsicmp(w, L"Available films") == 0) {
        if (pSetMinWidth) pSetMinWidth(self, 600);
        g_availFilmsGroup = self;
        g_availTreeDone = false; g_availTreeTries = 0;   // the Artwork dialog is RECREATED on each
                                                         // open -> reset so the NEW tree is re-widened
                                                         // (the tree's min is what sizes the dialog wide)
    }
    if (g_availFilmsGroup && !g_availTreeDone && g_availTreeTries < 128) {
        g_availTreeTries++;
        if (WidenAvailTree(g_availFilmsGroup, 0)) g_availTreeDone = true;
    }

    // Film Domain Setting datagrid: kill its striped rows (capture the dialog, then walk for
    // the UIFQTableView; retried until found). See FindFilmDomainTable.
    if (_wcsicmp(w, L"Window_Film Domain Setting") == 0) {
        g_filmDomainDlg = self;
        g_filmDomainDone = false; g_filmDomainTries = 0;   // recreated each open -> re-destripe the NEW table
    }
    if (g_filmDomainDlg && !g_filmDomainDone && g_filmDomainTries < 128) {
        g_filmDomainTries++;
        if (FindFilmDomainTable(g_filmDomainDlg, 0)) g_filmDomainDone = true;
    }

    // DXF In Edit/View Layers dialog: open it ~2x taller and let the layer datagrid grow into
    // the added height. Match the dialog robustly -- any "DXF In Edit..." objectName on a
    // *Dialog class (the exact form is Window_DXF In Edit/View Layers); floor the window height
    // as a fallback, then retry-walk for the datagrid to pin its height (the real lever). The
    // dialog is recreated each open, so reset the done-flag (same REOPEN gotcha as Film Domain).
    if (pSetMinHeight && ContainsCI(w, L"dxf in edit")) {
        const char* dcls = RttiClassName(self);
        if (dcls && strstr(dcls, "Dialog")) {
            g_dxfDlg = self;
            g_dxfDone = false; g_dxfTries = 0;
            pSetMinHeight(self, 700);   // window floor ~2x the native ~353 (covers a missed walk)
        }
    }
    if (pSetMinHeight && g_dxfDlg && !g_dxfDone && g_dxfTries < 128) {
        g_dxfTries++;
        if (FindDxfTable(g_dxfDlg, 0)) g_dxfDone = true;
    }

    // "Command >" prompt hide (17.4): capture SPBCommandWindow "CommmandPane", then hide
    // the bare QLineEdit among its direct children (retried until found). The real input
    // is a QLineEdit inside a QComboBox, so it is never hit. See HideCommandPrompt.
    if (g_hideCmdPrompt && _wcsicmp(w, L"CommmandPane") == 0) g_cmdPane = self;
    if (g_hideCmdPrompt && g_cmdPane && !g_cmdPromptDone && g_cmdPromptTries < 128) {
        g_cmdPromptTries++;
        if (HideCommandPrompt(g_cmdPane)) g_cmdPromptDone = true;
    }

    // Options pane: expand the Active Class/Subclass combos to the pane's right edge +
    // drop the content panel's margins (retried until the combos exist under the captured
    // OptionsBar). See FillOptionsPane.
    if (g_optionsBar && !g_optFillDone && g_optFillTries < 128) {
        g_optFillTries++;
        if (FillOptionsPane(g_optionsBar, 0) > 0) g_optFillDone = true;
    }

    // Find groupboxes: give "Design Object Find Filter" + "Find By Name" a MINIMUM width of
    // 280px (a bit wider) but NO maximum -- a min==max pin is what locked the Find panel to a
    // fixed width and stopped it resizing, so min-only keeps the 280 baseline while letting
    // the panel be dragged wider (arbitrary width). 25.1 still pins them to a fixed 230px.
    if (pSetMinWidth &&
        (_wcsicmp(w, L"Design Object Find Filter") == 0 || _wcsicmp(w, L"Find By Name") == 0)) {
        pSetMinWidth(self, 280);
    }

    // Native item-view checkbox fix is deliberately NOT applied in 17.4. `image:none`
    // restores the NATIVE indicator in 25.1, but under 17.4's older theme there is no
    // native item-view indicator to draw, so it left tree/list (UIFQTreeWidget) checkboxes
    // BLANK -- the opposite of intended. 17.4 leaves item-view indicators to Cadence's own
    // theme. (If they STILL render blank, the cause is the classic-theme @include=* mods
    // re-theming allegro -- exclude allegro.exe from those mods, not here.)

    // Cadence "cadence" logo hide (kept -- window chrome).
    if (pSetVisible && _wcsicmp(w, L"LogoWidget") == 0) { pSetVisible(self, false); return; }

    // Visibility pane: capture + zero the layout's contents margins so the On/Off/Last
    // row, the View dropdown and the (kept) labels sit edge-to-edge with no outer
    // padding. 17.4 keeps the rest of the pane native, but DOES destripe the rows
    // (user request -- 17.4's native pane now shows the per-row model-brush stripe).
    // (The outer border is applied on the VisibilityBar dock below, not on CVPane.)
    if (ContainsCI(w, L"colorvisibilitypane")) {
        g_visPane = self;
        if (pWidgetLayout && pSetContentsMargins) {
            void* lay = pWidgetLayout(self);
            if (lay) pSetContentsMargins(lay, 0, 0, 0, 0);
        }
        if (g_noStripes) ApplyDestripe(self);  // remove the row stripes only
        if (g_probeVisPane) Wh_Log(L"[vispane] captured ColorVisibilityPane = %p (17.4: destripe only)", self);
        return;
    }

    // CVPLayerGrid: the layer list draws two-tone etched row-separator lines from
    // the palette shade roles -- flatten ALL of them to face gray so the lines go.
    if (_wcsicmp(w, L"CVPLayerGrid") == 0) {
        g_layerGrid = self;                       // for the paint-recolor hook (gray N/A cells + dividers)
        if (g_noStripes) FlattenShades(self);
        return;
    }

    // VisibilityBar dock (17.4): otherwise native, just border its content QScrollArea.
    if (_wcsicmp(w, L"VisibilityBar") == 0) { ApplyPanelBorder(self); return; }
    // Find dock (17.4): suppress the horizontal scrollbar (parity with 25.1's Find) +
    // border. The combo/group-box width tweaks are still left native.
    if (_wcsicmp(w, L"FindBar") == 0)       { ApplyFindHScrollHide(self); return; }

    // Options dock: capture it (for the combo-fill retry above) + hide scrollbars.
    if (_wcsicmp(w, L"OptionsBar") == 0) {
        g_optionsBar = self;
        if (g_noHScroll) {
            ApplyDockScrollHide(self);
            Wh_Log(L"[scroll] hid scrollbars on \"%s\" (%p)", w, self);
        }
    }
    // CommandBar: H-scroll hide + command input/output font (kept -- docks & command).
    else if (_wcsicmp(w, L"CommandBar") == 0) {
        ApplyCommandStyle(self);
        Wh_Log(L"[cmd] styled CommandBar (hscroll=%d styleCmd=%d) (%p)",
               (int)g_noHScroll, (int)g_styleCmd, self);
    }
}
}  // namespace v174

// --- Dispatch table: the active chunk is selected in Wh_ModInit ------------
const VerImpl IMPL_251 = { &v251::OnSetObjectName, true,  true, true,  true  };  // 25.1: full set
const VerImpl IMPL_174 = { &v174::OnSetObjectName, true,  true, false, false }; // 17.4: blank only Global visibility/View/Class-Subclass; REMOVE stripes (destripe-only sheet); keep layer names, Quickviews, Conductors/Masks

// --- Shared setObjectName hook: name registry + diagnostics + dispatch -----
// The hook itself is SHARED (Windhawk allows one hook per symbol). It keeps the name
// registry filled (the inspector needs it, regardless of version), runs the shared
// [names] diagnostic, then dispatches the version-specific work to the active chunk.
void __cdecl QObject_setObjectName_hook(void* self, const QtString* name) {
    QObject_setObjectName_orig(self, name);
    if (!name) return;
    int len = 0;
    const unsigned short* u = QtStr_data(name, &len);
    if (!u || len <= 0) return;
    const wchar_t* w = (const wchar_t*)u;
    RegisterName(self, w);   // keep the registry filled for the inspector (both versions)

    // Diagnostic: log pane-ish object names (shared; off by default, runs the same in
    // both chunks). Placed before dispatch so it logs even names a chunk acts on.
    if (g_logNames &&
        (ContainsCI(w, L"find") || ContainsCI(w, L"option") || ContainsCI(w, L"command") ||
         ContainsCI(w, L"console") || ContainsCI(w, L"pane") || ContainsCI(w, L"dock") ||
         ContainsCI(w, L"bar"))) {
        const char* cls = RttiClassName(self);
        Wh_Log(L"[names] \"%s\" cls=%S self=%p", w, cls ? cls : "?", self);
    }

    // Version-specific feature work -> the active chunk (v251 or v174).
    if (g_impl && g_impl->onSetObjectName) g_impl->onSetObjectName(self, w);
}

// --- Inspector: Ctrl+Shift+Click a control --------------------------------
// Dumps the clicked widget + its parent chain (and, optionally, its child
// subtree) to inspect.log, on the GUI thread via the central QApplication::
// notify entry. CRASH-HARDENED for this CFG exe: it does NOT call the by-value Qt
// getters (objectName/text/geometry) or the CRT wide-printf -- both proved fatal
// here (the same lesson as DumpTree). It uses ONLY proven-safe primitives:
// RttiClassName + pParent + the guarded QObjectList walk (pure memory reads
// already used safely here), manual string/number formatting, and Win32 file I/O.
// objectName comes from the registry filled by the setObjectName hook (above),
// never from a getter. The notify hook is installed only when g_inspect is on.
static const wchar_t* kInspectPath =
    L"C:\\Dropbox\\Common\\cfg\\windhawk\\allegro\\inspect.log";

// Manual formatters -- the CRT wide-printf is not trusted in this exe.
static void UDecW(unsigned v, wchar_t* out) {
    wchar_t tmp[12]; int n = 0;
    if (v == 0) tmp[n++] = L'0';
    while (v) { tmp[n++] = (wchar_t)(L'0' + (v % 10)); v /= 10; }
    int k = 0; while (n) out[k++] = tmp[--n]; out[k] = L'\0';
}
static void HexPtrW(const void* p, wchar_t* out) {        // "0x" + 16 hex + NUL
    static const wchar_t* H = L"0123456789abcdef";
    unsigned long long v = (unsigned long long)p;
    out[0] = L'0'; out[1] = L'x';
    for (int i = 0; i < 16; i++) out[2 + i] = H[(v >> ((15 - i) * 4)) & 0xF];
    out[18] = L'\0';
}
static void AsciiToW(const char* s, wchar_t* out, int cap) {   // RTTI name is ASCII
    int i = 0;
    if (s) for (; s[i] && i < cap - 1; i++) out[i] = (wchar_t)(unsigned char)s[i];
    out[i] = L'\0';
}

// --- Inspector clipboard accumulator --------------------------------------
// In addition to inspect.log, the full dump of one physical click is accumulated
// here and pushed to the Windows clipboard at the end of RunInspect, so the user
// can paste "I clicked X -- here's the inspection" straight into a chat as context.
// CF_UNICODETEXT; runs on the GUI thread (notify), which is fine for the clipboard.
static wchar_t g_inspClip[32768];
static int     g_inspClipLen = 0;
static void ClipReset() { g_inspClip[0] = L'\0'; g_inspClipLen = 0; }
static void ClipAppend(const wchar_t* line) {
    if (!line) return;
    int n   = lstrlenW(line);
    int cap = (int)(sizeof(g_inspClip) / sizeof(wchar_t));
    if (g_inspClipLen + n + 3 >= cap) return;          // full -- drop the overflow line
    lstrcpyW(g_inspClip + g_inspClipLen, line);
    g_inspClipLen += n;
    g_inspClip[g_inspClipLen++] = L'\r';
    g_inspClip[g_inspClipLen++] = L'\n';
    g_inspClip[g_inspClipLen]   = L'\0';
}
static void SetClipboardTextW(const wchar_t* text) {
    if (!text || !text[0]) return;
    size_t bytes = ((size_t)lstrlenW(text) + 1) * sizeof(wchar_t);
    HGLOBAL hMem = GlobalAlloc(GMEM_MOVEABLE, bytes);
    if (!hMem) return;
    void* p = GlobalLock(hMem);
    if (!p) { GlobalFree(hMem); return; }
    memcpy(p, text, bytes);
    GlobalUnlock(hMem);
    // OpenClipboard MUST get a real HWND owned by this (GUI) thread. With a NULL
    // handle, EmptyClipboard sets the clipboard owner to NULL, which makes the
    // following SetClipboardData FAIL (documented). We run on the GUI thread (via
    // QApplication::notify), so GetActiveWindow() returns this thread's active
    // window; GetForegroundWindow() is a fallback.
    HWND hwnd = GetActiveWindow();
    if (!hwnd) hwnd = GetForegroundWindow();
    bool ok = false;
    if (OpenClipboard(hwnd)) {
        EmptyClipboard();
        if (SetClipboardData(CF_UNICODETEXT, hMem)) { hMem = nullptr; ok = true; }  // clipboard owns it now
        CloseClipboard();
    }
    if (hMem) GlobalFree(hMem);                          // open/set failed -> we still own it
    if (!ok) Wh_Log(L"[inspect] clipboard copy FAILED (hwnd=%p err=%lu)", hwnd, GetLastError());
}

// Mirror one finished line to the Windhawk log AND append (UTF-8 + CRLF) to
// inspect.log so it can be read back directly. No printf.
static void InspectWrite(const wchar_t* line) {
    ClipAppend(line);   // also accumulate for the clipboard copy (see RunInspect)
    // File ONLY (no Wh_Log mirror) -- keeps the Windhawk log uncluttered; the full
    // dump goes to inspect.log, which is read back directly. RunInspect logs a
    // single confirmation line per click.
    char u8[1100];
    int n = WideCharToMultiByte(CP_UTF8, 0, line, -1, u8, (int)sizeof(u8) - 2, nullptr, nullptr);
    if (n <= 0) return;
    if (u8[n - 1] == '\0') n--;
    u8[n++] = '\r'; u8[n++] = '\n';
    HANDLE h = CreateFileW(kInspectPath, FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) { DWORD wr; WriteFile(h, u8, (DWORD)n, &wr, nullptr); CloseHandle(h); }
}

// QPalette::ColorRole names (the ones worth showing).
static const wchar_t* RoleName(int role) {
    switch (role) {
        case 0:  return L"WindowText";
        case 1:  return L"Button";
        case 2:  return L"Light";
        case 3:  return L"Midlight";
        case 4:  return L"Dark";
        case 5:  return L"Mid";
        case 6:  return L"Text";
        case 8:  return L"ButtonText";
        case 9:  return L"Base";
        case 10: return L"Window";
        case 11: return L"Shadow";
        case 12: return L"Highlight";
        case 16: return L"AlternateBase";
        default: return L"role?";
    }
}

// Read a widget's palette color for a role via the ref chain (crash-safe).
static bool WidgetPaletteColor(void* widget, int role, int* r, int* g, int* b) {
    if (!pQWidget_palette || !pQPalette_color || !pQColor_red || !pQColor_green || !pQColor_blue)
        return false;
    const void* pal = pQWidget_palette(widget);
    if (!pal || IsBadReadPtr(pal, sizeof(void*))) return false;
    const void* col = pQPalette_color(pal, role);
    if (!col || IsBadReadPtr(col, sizeof(void*))) return false;
    *r = pQColor_red(col); *g = pQColor_green(col); *b = pQColor_blue(col);
    return true;
}

static void AppendRoleColor(wchar_t* line, void* w, int role) {
    int r, g, b;
    lstrcatW(line, L" ");  lstrcatW(line, RoleName(role));  lstrcatW(line, L"=");
    if (WidgetPaletteColor(w, role, &r, &g, &b)) {
        wchar_t n[12];
        lstrcatW(line, L"rgb(");
        UDecW((unsigned)r, n); lstrcatW(line, n); lstrcatW(line, L",");
        UDecW((unsigned)g, n); lstrcatW(line, n); lstrcatW(line, L",");
        UDecW((unsigned)b, n); lstrcatW(line, n); lstrcatW(line, L")");
    } else {
        lstrcatW(line, L"?");
    }
}

// Extra per-widget info (only if obj is a QWidget): bg role + flags, then the
// key palette colors. This is the "as much pertinent info as possible" dump --
// esp. Base / AlternateBase / Window, which drive striping & backgrounds.
static void DumpWidgetExtra(void* obj) {
    if (!obj || !pInherits || !pInherits(obj, "QWidget")) return;

    wchar_t f[256]; f[0] = L'\0';
    lstrcatW(f, L"      [widget]");
    if (pQWidget_bgRole)    { lstrcatW(f, L" bgRole=");   lstrcatW(f, RoleName(pQWidget_bgRole(obj))); }
    if (pQWidget_isVisible) { lstrcatW(f, L" vis=");      lstrcatW(f, pQWidget_isVisible(obj) ? L"1" : L"0"); }
    if (pQWidget_isEnabled) { lstrcatW(f, L" enabled=");  lstrcatW(f, pQWidget_isEnabled(obj) ? L"1" : L"0"); }
    if (pQWidget_autoFill)  { lstrcatW(f, L" autoFill="); lstrcatW(f, pQWidget_autoFill(obj) ? L"1" : L"0"); }
    InspectWrite(f);

    if (pQWidget_palette && pQPalette_color) {
        wchar_t c[512]; c[0] = L'\0';
        lstrcatW(c, L"      [palette]");
        AppendRoleColor(c, obj, 10);  // Window
        AppendRoleColor(c, obj, 9);   // Base
        AppendRoleColor(c, obj, 16);  // AlternateBase
        AppendRoleColor(c, obj, 1);   // Button
        AppendRoleColor(c, obj, 6);   // Text
        InspectWrite(c);
        // 3D shade roles -- where custom row/grid separator lines usually come from.
        wchar_t s[512]; s[0] = L'\0';
        lstrcatW(s, L"      [shades]");
        AppendRoleColor(s, obj, 2);   // Light
        AppendRoleColor(s, obj, 3);   // Midlight
        AppendRoleColor(s, obj, 5);   // Mid
        AppendRoleColor(s, obj, 4);   // Dark
        AppendRoleColor(s, obj, 11);  // Shadow
        InspectWrite(s);
    }
}

// One node: tag, RTTI class, registered objectName, pointer. Pure reads only.
static void DumpOne(void* obj, const wchar_t* tag) {
    wchar_t line[512]; line[0] = L'\0';
    wchar_t cw[256];   AsciiToW(RttiClassName(obj), cw, 256);
    wchar_t pw[20];    HexPtrW(obj, pw);
    const wchar_t* nm = LookupName(obj);
    lstrcatW(line, L"  ");      lstrcatW(line, tag);
    lstrcatW(line, L" cls=");   lstrcatW(line, cw[0] ? cw : L"?");
    lstrcatW(line, L" name=");  lstrcatW(line, nm[0] ? nm : L"?");
    lstrcatW(line, L" ptr=");   lstrcatW(line, pw);
    InspectWrite(line);
    DumpWidgetExtra(obj);   // palette colors + flags (QWidgets only)
}

// Bulk child walk -- RTTI class + pointer ONLY (same getter-free traversal as
// DumpTree); names are shown where the registry has them.
int g_inspCount = 0;
static void DumpSubtree(void* obj, int depth) {
    if (!obj || depth > 40 || g_inspCount > 8000 || IsBadReadPtr(obj, sizeof(void*))) return;  // caps raised for full-window dumps
    const char* cls = RttiClassName(obj);
    g_inspCount++;
    wchar_t line[512]; line[0] = L'\0';
    wchar_t dw[12];  UDecW((unsigned)depth, dw);
    wchar_t cw[256]; AsciiToW(cls, cw, 256);
    wchar_t pw[20];  HexPtrW(obj, pw);
    const wchar_t* nm = LookupName(obj);
    lstrcatW(line, L"  child d="); lstrcatW(line, dw);
    lstrcatW(line, L" ");          lstrcatW(line, cw[0] ? cw : L"?");
    if (nm[0]) { lstrcatW(line, L" name="); lstrcatW(line, nm); }
    lstrcatW(line, L" ptr=");      lstrcatW(line, pw);
    InspectWrite(line);
    if (!cls || !pChildren) return;
    void* listRef = pChildren(obj);
    if (!listRef || IsBadReadPtr(listRef, sizeof(void*))) return;
    char* d = *(char**)listRef;
    if (!d || IsBadReadPtr(d, 16)) return;
    int begin = *(int*)(d + 8), end = *(int*)(d + 12), n = end - begin;
    if (n <= 0 || n > 4000) return;
    void** arr = (void**)(d + 16);
    if (IsBadReadPtr(arr, (size_t)(begin + n) * sizeof(void*))) return;
    for (int i = 0; i < n; i++) DumpSubtree(arr[begin + i], depth + 1);
}

static void* g_lastInspObj     = nullptr;
static DWORD g_lastInspTick    = 0;
static DWORD g_lastAnyInspTick = 0;   // last time ANY inspect ran (clipboard session boundary)
// fullWindow=false (Ctrl+Shift+Middle): dump the control under the cursor -- its
// class/name/ptr, full ancestor chain AND child subtree. fullWindow=true
// (Ctrl+Alt+Middle): also walk up to the top-level window and dump its ENTIRE tree.
static void RunInspect(void* receiver, bool fullWindow) {
    DWORD now = GetTickCount();
    // De-dup the SAME receiver only -- so the window-level press and the leaf
    // widget's following press (different pointers) both get through, while a
    // jittery double-fire on one object is suppressed.
    if (receiver == g_lastInspObj && (now - g_lastInspTick) < 400) return;
    // A new physical click (a gap since ANY inspect) starts a fresh clipboard
    // buffer; the window-level + leaf blocks of ONE click accumulate into the same
    // buffer so the clipboard mirrors what inspect.log gets for that click.
    if (now - g_lastAnyInspTick > 400) ClipReset();
    g_lastAnyInspTick = now;
    g_lastInspObj = receiver; g_lastInspTick = now;
    // One concise confirmation line to the Windhawk log; full detail -> inspect.log + clipboard.
    { const char* rc = RttiClassName(receiver);
      Wh_Log(L"[inspect] %s %S name='%s' -> inspect.log + clipboard",
             fullWindow ? L"window" : L"control", rc ? rc : "?", LookupName(receiver)); }
    { wchar_t line[64], pw[20]; HexPtrW(receiver, pw); line[0] = L'\0';
      lstrcatW(line, L"===== INSPECT receiver="); lstrcatW(line, pw); lstrcatW(line, L" =====");
      InspectWrite(line); }
    DumpOne(receiver, L"TARGET     ");
    void* p = pParent ? pParent(receiver) : nullptr;
    for (int i = 0; i < 24 && p && !IsBadReadPtr(p, sizeof(void*)); i++) {
        wchar_t tag[24]; tag[0] = L'\0'; wchar_t iw[12]; UDecW((unsigned)i, iw);
        lstrcatW(tag, L"ancestor["); lstrcatW(tag, iw); lstrcatW(tag, L"]");
        DumpOne(p, tag);
        p = pParent(p);
    }
    if (!fullWindow) {
        // Control dump (Ctrl+Shift+Middle): the clicked widget's descendant subtree
        // (class+ptr only -- by-value getters crashed across a deep walk; depth/count capped).
        g_inspCount = 0;
        InspectWrite(L"  --- child subtree (class+ptr only) ---");
        DumpSubtree(receiver, 0);
    } else {
        // Window dump (Ctrl+Alt+Middle): walk up to the top-level window/dialog (the
        // highest ancestor below an SPBMainWindow, else the topmost widget) and dump its
        // ENTIRE subtree, so the whole window skeleton can be handed over for layout edits.
        void* root = receiver;
        void* q = pParent ? pParent(receiver) : nullptr;
        for (int i = 0; i < 40 && q && !IsBadReadPtr(q, sizeof(void*)); i++) {
            const char* cls = RttiClassName(q);
            if (cls && strstr(cls, "SPBMainWindow")) break;   // stop below the main window
            root = q; q = pParent(q);
        }
        g_inspCount = 0;
        InspectWrite(L"  --- FULL WINDOW TREE (class + name + ptr) ---");
        DumpSubtree(root, 0);
    }
    InspectWrite(L"===== end inspect =====");
    SetClipboardTextW(g_inspClip);   // mirror the whole click's dump to the clipboard
}

// Central GUI-thread event entry. On a Ctrl+modifier MIDDLE-button press, dump the
// receiver; everything else passes straight through. QEvent::t is at +16 on x64
// (vptr, QEventPrivate* d, then ushort t); MouseButtonPress == 2. The button +
// modifiers are read with GetAsyncKeyState (crash-safe, same primitive as before) --
// VK_MBUTTON is down at press time, so the gesture is distinguished from an ordinary
// left/right click. We dump EVERY qualifying press receiver (the per-receiver de-dup in
// RunInspect lets the window-level press and any following leaf-widget press both appear),
// so one click reveals the full dispatch sequence -- pick the real control from the blocks.
bool __cdecl QApplication_notify_hook(void* self, void* receiver, void* event) {
    if (g_inspect && receiver && event && !IsBadReadPtr(event, 24)) {
        unsigned short t = *(unsigned short*)((char*)event + 16);
        if (t == 2 &&
            (GetAsyncKeyState(VK_MBUTTON) & 0x8000) &&
            (GetAsyncKeyState(VK_CONTROL) & 0x8000)) {
            if (GetAsyncKeyState(VK_MENU) & 0x8000)
                RunInspect(receiver, true);        // Ctrl+Alt+Middle   -> full window
            else if (GetAsyncKeyState(VK_SHIFT) & 0x8000)
                RunInspect(receiver, false);       // Ctrl+Shift+Middle -> control
        }
    }

    // Paint-recolor: set a flag around the paint of widgets whose hardcoded fills the
    // fillRect hooks rewrite. QEvent::Paint == 12. (a) CVPLayerGrid + its QFrame
    // dividers -> every fill to gray (g_gridPainting). (b) any SPBFoldDockTitle -> its
    // AAA8A4 separator blocks to black (g_titlePainting). Child widgets paint in their
    // own events (flags clear), so their real colors are preserved.
    if (receiver && event && !IsBadReadPtr(event, 24)) {
        unsigned short t = *(unsigned short*)((char*)event + 16);
        if (t == 12) {
            if (g_layerGrid) {
                bool grid = (receiver == g_layerGrid);
                bool frame = false;
                if (!grid && pParent && pParent(receiver) == g_layerGrid) {
                    const char* cls = RttiClassName(receiver);
                    frame = cls && strstr(cls, "QFrame");
                }
                if (grid || frame) {
                    g_gridPainting++;
                    bool r = QApplication_notify_orig(self, receiver, event);
                    if (g_gridPainting > 0) g_gridPainting--;
                    if (grid && !g_gridPaintLogged) {   // diag: did fillRect recolor fire?
                        g_gridPaintLogged = true;
                        Wh_Log(L"[paint] first grid paint done: %ld fills recolored", g_gridFillN);
                    }
                    return r;
                }
            }
            if (g_blackDockSep) {
                const char* cls = RttiClassName(receiver);
                if (cls && strstr(cls, "SPBFoldDockTitle")) {
                    g_titlePainting++;
                    bool r = QApplication_notify_orig(self, receiver, event);
                    if (g_titlePainting > 0) g_titlePainting--;
                    return r;
                }
            }
        }
    }
    return QApplication_notify_orig(self, receiver, event);
}

// --- Settings -------------------------------------------------------------
static void LoadSettings() {
    // Only the inspector + diagnostics + the cross-version gate are user-toggled;
    // feature tweaks are permanently on (their g_* flags stay true, never loaded).
    g_floatToolbar   = Wh_GetIntSetting(L"floatToolbar")   != 0;
    g_panelBorder    = Wh_GetIntSetting(L"panelBorder")    != 0;
    g_inspect        = Wh_GetIntSetting(L"inspect")        != 0;
    g_probeVisPane   = Wh_GetIntSetting(L"probeVisPane")   != 0;
    g_dumpTree       = Wh_GetIntSetting(L"dumpTree")       != 0;
    g_logNames       = Wh_GetIntSetting(L"logNames")       != 0;
    g_probeBrush     = Wh_GetIntSetting(L"probeBrush")     != 0;
}

BOOL Wh_ModInit() {
    Wh_Log(L"Init: Allegro");
    LoadSettings();

    // Which Allegro is this process? The exe path picks the version chunk: SPB_25...
    // => the 25.1 chunk (full tweak set); anything else (17.4 / 17.2) => the 17.4 chunk
    // (subset). Windhawk injects into allegro.exe AND allegro_free_viewer.exe by name,
    // so both reach their target. The inspector + diagnostics are SHARED. Chunk is
    // path-based, so the Free Viewer under SPB_17.4 correctly gets the 17.4 chunk.
    wchar_t exePath[MAX_PATH]; exePath[0] = L'\0';
    GetModuleFileNameW(nullptr, exePath, MAX_PATH);
    g_ver  = ContainsCI(exePath, L"spb_25") ? VER_251 : VER_174;
    g_impl = (g_ver == VER_251) ? &IMPL_251 : &IMPL_174;
    Wh_Log(L"[ver] exe=%s -> %s chunk", exePath, (g_ver == VER_251) ? L"25.1" : L"17.4");

    HMODULE hCore = GetModuleHandleW(L"cdsQt5Core.dll");
    if (!hCore) hCore = LoadLibraryW(L"cdsQt5Core.dll");
    if (!hCore) { Wh_Log(L"cdsQt5Core.dll not found"); return FALSE; }
    HMODULE hWidgets = GetModuleHandleW(L"cdsQt5Widgets.dll");
    if (!hWidgets) hWidgets = LoadLibraryW(L"cdsQt5Widgets.dll");

    pQString_ctor  = (QStringCtor_t)GetProcAddress(hCore, "??0QString@@QEAA@XZ");
    pQString_dtor  = (QStringDtor_t)GetProcAddress(hCore, "??1QString@@QEAA@XZ");
    pFromUtf16     = (FromUtf16_t)GetProcAddress(hCore, "?fromUtf16@QString@@SA?AV1@PEBGH@Z");
    pParent        = (Parent_t)GetProcAddress(hCore, "?parent@QObject@@QEBAPEAV1@XZ");
    pChildren      = (ChildrenGetter_t)GetProcAddress(hCore, "?children@QObject@@QEBAAEBV?$QList@PEAVQObject@@@@XZ");
    pObjectName    = (QStrGetter_t)GetProcAddress(hCore, "?objectName@QObject@@QEBA?AVQString@@XZ");
    pInherits      = (Inherits_t)GetProcAddress(hCore, "?inherits@QObject@@QEBA_NPEBD@Z");
    if (hWidgets) {
        pSetStyleSheet = (SetStyleSheet_t)GetProcAddress(hWidgets, "?setStyleSheet@QWidget@@QEAAXAEBVQString@@@Z");
        pGeometry      = (GeomGetter_t)GetProcAddress(hWidgets, "?geometry@QWidget@@QEBAAEBVQRect@@XZ");
        pLabelText     = (QStrGetter_t)GetProcAddress(hWidgets, "?text@QLabel@@QEBA?AVQString@@XZ");
        pButtonText    = (QStrGetter_t)GetProcAddress(hWidgets, "?text@QAbstractButton@@QEBA?AVQString@@XZ");
        pAIVModel      = (ModelGetter_t)GetProcAddress(hWidgets, "?model@QAbstractItemView@@QEBAPEAVQAbstractItemModel@@XZ");
        pSetVisible    = (SetVisible_t)GetProcAddress(hWidgets, "?setVisible@QWidget@@UEAAX_N@Z");
        pSetMinWidth   = (SetWidth_t)GetProcAddress(hWidgets, "?setMinimumWidth@QWidget@@QEAAXH@Z");
        pSetMaxWidth   = (SetWidth_t)GetProcAddress(hWidgets, "?setMaximumWidth@QWidget@@QEAAXH@Z");
        pSetMinHeight  = (SetWidth_t)GetProcAddress(hWidgets, "?setMinimumHeight@QWidget@@QEAAXH@Z");
        pSetHSpacing   = (SetWidth_t)GetProcAddress(hWidgets, "?setHorizontalSpacing@QGridLayout@@QEAAXH@Z");
        pSetColStretch = (SetGrid2_t)GetProcAddress(hWidgets, "?setColumnStretch@QGridLayout@@QEAAXHH@Z");
        pSetSizePolicy2= (SetSizePolicy2_t)GetProcAddress(hWidgets, "?setSizePolicy@QWidget@@QEAAXW4Policy@QSizePolicy@@0@Z");
        pWidgetLayout  = (Layout_t)GetProcAddress(hWidgets, "?layout@QWidget@@QEBAPEAVQLayout@@XZ");
        pSetContentsMargins = (SetMargins4_t)GetProcAddress(hWidgets, "?setContentsMargins@QLayout@@QEAAXHHHH@Z");
        pSetAllowedAreas = (SetAllowedAreas_t)GetProcAddress(hWidgets, "?setAllowedAreas@QToolBar@@QEAAXV?$QFlags@W4ToolBarArea@Qt@@@@@Z");
        // Inspector extras (QWidget side -- palette accessor + property reads).
        pQWidget_palette   = (QWidgetPalette_t)GetProcAddress(hWidgets, "?palette@QWidget@@QEBAAEBVQPalette@@XZ");
        pQWidget_bgRole    = (QWidgetRole_t)GetProcAddress(hWidgets, "?backgroundRole@QWidget@@QEBA?AW4ColorRole@QPalette@@XZ");
        pQWidget_isVisible = (QWidgetBool_t)GetProcAddress(hWidgets, "?isVisible@QWidget@@QEBA_NXZ");
        pQWidget_isEnabled = (QWidgetBool_t)GetProcAddress(hWidgets, "?isEnabled@QWidget@@QEBA_NXZ");
        pQWidget_autoFill  = (QWidgetBool_t)GetProcAddress(hWidgets, "?autoFillBackground@QWidget@@QEBA_NXZ");
        pQWidget_setPalette = (QWidgetSetPalette_t)GetProcAddress(hWidgets, "?setPalette@QWidget@@QEAAXAEBVQPalette@@@Z");
    }

    // QPalette / QColor live in QtGui (cdsQt5Gui.dll) -- inspector palette colors
    // (read) + the shade-flatten write path.
    HMODULE hGui = GetModuleHandleW(L"cdsQt5Gui.dll");
    if (!hGui) hGui = LoadLibraryW(L"cdsQt5Gui.dll");
    if (hGui) {
        pQPalette_color    = (QPaletteColor_t)GetProcAddress(hGui, "?color@QPalette@@QEBAAEBVQColor@@W4ColorRole@1@@Z");
        pQColor_red        = (QColorChan_t)GetProcAddress(hGui, "?red@QColor@@QEBAHXZ");
        pQColor_green      = (QColorChan_t)GetProcAddress(hGui, "?green@QColor@@QEBAHXZ");
        pQColor_blue       = (QColorChan_t)GetProcAddress(hGui, "?blue@QColor@@QEBAHXZ");
        pQPalette_copy     = (QPaletteCopy_t)GetProcAddress(hGui, "??0QPalette@@QEAA@AEBV0@@Z");
        pQPalette_dtor     = (QPaletteDtor_t)GetProcAddress(hGui, "??1QPalette@@QEAA@XZ");
        pQPalette_setColor = (QPaletteSetColor_t)GetProcAddress(hGui, "?setColor@QPalette@@QEAAXW4ColorRole@1@AEBVQColor@@@Z");
        pQColor_ctor       = (QColorCtor_t)GetProcAddress(hGui, "??0QColor@@QEAA@HHHH@Z");

        // Paint-recolor hooks (17.4): gray CVPLayerGrid's hardcoded-white N/A cells +
        // dividers. Global QPainter::fillRect hooks, but they only act while
        // g_gridPainting>0 (set in the notify hook around the grid's paint) -- every
        // other fillRect in the app is an untouched passthrough.
        if (g_noStripes) {
            void* p;
            p = (void*)GetProcAddress(hGui, "?fillRect@QPainter@@QEAAXAEBVQRect@@AEBVQColor@@@Z");
            if (p) Wh_SetFunctionHook(p, (void*)FillRect_RC_hook, (void**)&pFillRect_RC_orig);
            p = (void*)GetProcAddress(hGui, "?fillRect@QPainter@@QEAAXAEBVQRect@@AEBVQBrush@@@Z");
            if (p) Wh_SetFunctionHook(p, (void*)FillRect_RB_hook, (void**)&pFillRect_RB_orig);
            p = (void*)GetProcAddress(hGui, "?fillRect@QPainter@@QEAAXHHHHAEBVQColor@@@Z");
            if (p) Wh_SetFunctionHook(p, (void*)FillRect_IC_hook, (void**)&pFillRect_IC_orig);
            p = (void*)GetProcAddress(hGui, "?fillRect@QPainter@@QEAAXHHHHAEBVQBrush@@@Z");
            if (p) Wh_SetFunctionHook(p, (void*)FillRect_IB_hook, (void**)&pFillRect_IB_orig);
            // QBrush::color() -- to read a brush fill's color for the title separator match.
            pQBrush_color = (QBrushColor_t)GetProcAddress(hGui, "?color@QBrush@@QEBAAEBVQColor@@XZ");
            // setPen hooks -- the AAA8A4 dock-title separator is a pen draw, not a fill.
            p = (void*)GetProcAddress(hGui, "?setPen@QPainter@@QEAAXAEBVQColor@@@Z");
            if (p) Wh_SetFunctionHook(p, (void*)SetPen_C_hook, (void**)&pSetPenC_orig);
            p = (void*)GetProcAddress(hGui, "?setPen@QPainter@@QEAAXAEBVQPen@@@Z");
            if (p) Wh_SetFunctionHook(p, (void*)SetPen_P_hook, (void**)&pSetPenP_orig);
            Wh_Log(L"[paint] fillRect hooks RC=%p RB=%p IC=%p IB=%p",
                   (void*)pFillRect_RC_orig, (void*)pFillRect_RB_orig,
                   (void*)pFillRect_IC_orig, (void*)pFillRect_IB_orig);
        }
    }

    // Capture the pane via setObjectName (Core).
    void* pSetObjName = (void*)GetProcAddress(hCore, "?setObjectName@QObject@@QEAAXAEBVQString@@@Z");
    if (pSetObjName && Wh_SetFunctionHook(pSetObjName, (void*)QObject_setObjectName_hook, (void**)&QObject_setObjectName_orig))
        Wh_Log(L"[vispane] setObjectName hooked");
    else
        Wh_Log(L"[vispane] setObjectName hook FAILED (sym=%p)", pSetObjName);

    if (hWidgets) {
        // Blank header labels via QLabel::setText.
        void* pLblSetText = (void*)GetProcAddress(hWidgets, "?setText@QLabel@@QEAAXAEBVQString@@@Z");
        if (pLblSetText && Wh_SetFunctionHook(pLblSetText, (void*)QLabel_setText_hook, (void**)&QLabel_setText_orig))
            Wh_Log(L"[vispane] QLabel::setText hooked (blankLabels=%d, ctor=%p)", (int)g_blankLabels, (void*)pQString_ctor);
        else
            Wh_Log(L"[vispane] QLabel::setText hook FAILED (sym=%p)", pLblSetText);

        // Blank checkbox/button text (e.g. "Conductors") via QAbstractButton::setText.
        void* pBtnSetText = (void*)GetProcAddress(hWidgets, "?setText@QAbstractButton@@QEAAXAEBVQString@@@Z");
        if (pBtnSetText && Wh_SetFunctionHook(pBtnSetText, (void*)QAbstractButton_setText_hook, (void**)&QAbstractButton_setText_orig))
            Wh_Log(L"[vispane] QAbstractButton::setText hooked");
        else
            Wh_Log(L"[vispane] QAbstractButton::setText hook FAILED (sym=%p)", pBtnSetText);

        // "_" toolbar float: catch its title via QWidget::setWindowTitle.
        void* pSetWinTitle = (void*)GetProcAddress(hWidgets, "?setWindowTitle@QWidget@@QEAAXAEBVQString@@@Z");
        if (pSetWinTitle && Wh_SetFunctionHook(pSetWinTitle, (void*)QWidget_setWindowTitle_hook, (void**)&QWidget_setWindowTitle_orig))
            Wh_Log(L"[toolbar] QWidget::setWindowTitle hooked (floatToolbar=%d)", (int)g_floatToolbar);
        else
            Wh_Log(L"[toolbar] setWindowTitle hook FAILED (sym=%p)", pSetWinTitle);

        // Turn off alternatingRowColors app-wide.
        void* pSetAlt = (void*)GetProcAddress(hWidgets, "?setAlternatingRowColors@QAbstractItemView@@QEAAX_N@Z");
        if (pSetAlt && Wh_SetFunctionHook(pSetAlt, (void*)QAIV_setAlternatingRowColors_hook, (void**)&QAIV_setAltRows_orig))
            Wh_Log(L"setAlternatingRowColors hooked (noStripes=%d)", (int)g_noStripes);
        else
            Wh_Log(L"setAlternatingRowColors hook FAILED (sym=%p)", pSetAlt);

        // DIAGNOSTIC: trigger the one-shot tree dump from the grid's delegate paint.
        void* pPaint = (void*)GetProcAddress(hWidgets, "?paint@QStyledItemDelegate@@UEBAXPEAVQPainter@@AEBVQStyleOptionViewItem@@AEBVQModelIndex@@@Z");
        if (pPaint && Wh_SetFunctionHook(pPaint, (void*)QStyledItemDelegate_paint_hook, (void**)&QStyledItemDelegate_paint_orig))
            Wh_Log(L"[tree] QStyledItemDelegate::paint hooked (dumpTree=%d); children=%p objectName=%p inherits=%p geometry=%p",
                   (int)g_dumpTree, (void*)pChildren, (void*)pObjectName, (void*)pInherits, (void*)pGeometry);
        else
            Wh_Log(L"[tree] QStyledItemDelegate::paint hook FAILED (sym=%p)", pPaint);

        // notify hook: needed by the inspector (Ctrl+Shift+Click) AND by the paint-
        // recolor (it sets g_gridPainting around the layer grid's paint). Install if
        // either is active.
        if (g_inspect || g_noStripes) {
            void* pNotify = (void*)GetProcAddress(hWidgets, "?notify@QApplication@@UEAA_NPEAVQObject@@PEAVQEvent@@@Z");
            if (pNotify && Wh_SetFunctionHook(pNotify, (void*)QApplication_notify_hook, (void**)&QApplication_notify_orig))
                Wh_Log(L"[inspect] QApplication::notify hooked (inspect=%d noStripes=%d)", (int)g_inspect, (int)g_noStripes);
            else
                Wh_Log(L"[inspect] notify hook FAILED (sym=%p)", pNotify);
        }
    } else {
        Wh_Log(L"cdsQt5Widgets.dll not loaded; label/scrollbar/striping hooks inactive");
    }

    return TRUE;
}

void Wh_ModSettingsChanged() {
    Wh_Log(L"Settings changed");
    LoadSettings();
}

void Wh_ModUninit() {
    Wh_Log(L"Uninit");
    // Windhawk auto-reverts all installed function hooks on unload.
}
