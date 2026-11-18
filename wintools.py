#!/usr/bin/env python3
"""wintools.py - Windows 11 utility tabs: keyboard, tweaks, disk + registry cleanup."""

import ctypes
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from PyQt5.QtCore import QEvent, QPoint, QRect, QSettings, QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QKeySequence, QPalette
from PyQt5.QtWidgets import (
    QAction, QActionGroup, QApplication, QCheckBox, QDialog, QFileDialog,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QStyle,
    QStyleOptionTab, QStylePainter, QTabBar, QTabWidget, QToolBar,
    QVBoxLayout, QWidget,
)

import clean
import ctxmenu
import envedit
import gpu
import hardware
import initcfg
import installer
import keydiag
import startup
import tweaks
from filterkeys import (
    FKF_FILTERKEYSON, read_filterkeys, set_filterkeys, summary,
)

PRESETS = (
    ("Default", 250, 30),
    ("Fast", 200, 15),
    ("Very fast", 150, 10),
    ("Ultra fast", 100, 6),
    ("Extreme", 50, 3),
)

DELAY_RANGE = (0, 2000)
RATE_RANGE = (1, 500)

# (label, SPI_SETKEYBOARDDELAY index, SPI_SETKEYBOARDSPEED index)
WIN_PRESETS = (
    ("Windows default", 1, 31),
    ("Relaxed", 2, 20),
    ("No accidents", 3, 8),
)


ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "resource", "icons")

# (menu label, settings key, QTabWidget position)
TAB_POSITIONS = (
    ("&Top", "top", QTabWidget.North),
    ("&Left", "left", QTabWidget.West),
    ("&Right", "right", QTabWidget.East),
)
TAB_ICON_SIZES = (16, 24, 32, 48, 64)
TAB_STEP_KEYS = {Qt.Key_Plus: 1, Qt.Key_Minus: -1}   # with KeypadModifier

# finder search terms per tab, beyond the tab name itself (never displayed)
TAB_TERMS = {
    "Initial Config": ("new pc", "setup"),
    "Installer": ("install apps", "winget", "software"),
    "Repeat rate": ("keyboard repeat", "typematic", "filterkeys"),
    "Key diagnostics": ("keyboard test", "key chatter"),
    "System": (),
    "GPU": ("graphics", "video card", "nvidia"),
    "Hardware": ("cpu-z", "cpu", "processor", "mainboard", "motherboard", "memory", "spd",
                 "ram", "bios", "sensors", "temps", "temperatures", "clocks"),
    "Files": ("temp files", "junk", "disk cleanup"),
    "Registry": ("registry cleaner", "regedit"),
    "Orphan paths": ("broken paths", "missing paths"),
    "Uninstall": ("remove programs", "add remove programs",
                  "programs and features", "apps and features",
                  "installed apps"),
    "Startup": ("autorun", "autostart", "run at login"),
    "Environment": ("environment variables", "env vars", "path"),
    "Context Menu": ("right click menu", "shell menu", "explorer menu"),
    "Empty folders": ("empty dirs", "empty directories"),
    "Largest files": ("big files", "disk space"),
}


def icon(name):
    path = os.path.join(ICON_DIR, f"{name}.ico")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return QIcon(path)


class SideTabBar(QTabBar):
    """Main tab bar. On the left or right it keeps each label (icon + text)
    horizontal, like a sidebar; Qt's own side tabs rotate the text 90 degrees."""

    TURN = {QTabBar.RoundedWest: 90, QTabBar.TriangularWest: 90,
            QTabBar.RoundedEast: -90, QTabBar.TriangularEast: -90}

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        if self.shape() in self.TURN:
            size.transpose()
        return size

    def paintEvent(self, event):
        turn = self.TURN.get(self.shape())
        if turn is None:
            super().paintEvent(event)
            return
        painter = QStylePainter(self)
        opt = QStyleOptionTab()
        for i in range(self.count()):
            if not self.isTabVisible(i):
                continue
            self.initStyleOption(opt, i)
            painter.drawControl(QStyle.CE_TabBarTabShape, opt)
            painter.save()
            size = opt.rect.size()
            size.transpose()
            label = QRect(QPoint(), size)
            label.moveCenter(opt.rect.center())
            opt.rect = label
            center = self.tabRect(i).center()
            painter.translate(center)
            painter.rotate(turn)
            painter.translate(-center)
            painter.drawControl(QStyle.CE_TabBarTabLabel, opt)
            painter.restore()


def _slider_spin(lo, hi, val):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    b = QSpinBox()
    b.setRange(lo, hi)
    s.valueChanged.connect(b.setValue)
    b.valueChanged.connect(s.setValue)
    b.setValue(val)
    return s, b


# ====================================================================
#  ELEVATION
# ====================================================================

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_shell32.IsUserAnAdmin.restype = ctypes.c_int
_shell32.IsUserAnAdmin.argtypes = []
# ShellExecuteW returns a pointer-sized pseudo-HINSTANCE; the default c_int
# restype truncates it on x64 and can turn a success into a bogus code.
_shell32.ShellExecuteW.restype = ctypes.c_void_p
_shell32.ShellExecuteW.argtypes = [
    ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
    ctypes.c_wchar_p, ctypes.c_int,
]


# Without its own AppUserModelID the window is grouped under pythonw.exe and
# the taskbar shows Python's icon instead of the window icon.
APP_ID = "wintools.wintools"
_shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
_shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]


def set_app_id():
    try:
        _shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except OSError:  # cosmetic only
        pass


def is_admin():
    try:
        return bool(_shell32.IsUserAnAdmin())
    except OSError:
        return False


def settings_path():
    # <exe name>.ini beside the exe; beside the script when run from source
    app = sys.executable if getattr(sys, "frozen", False) else __file__
    return os.path.splitext(os.path.abspath(app))[0] + ".ini"


def _relaunch_args():
    if getattr(sys, "frozen", False):
        # Not __file__: the _MEI extraction dir dies with the first instance.
        return (sys.executable, subprocess.list2cmdline(sys.argv[1:]),
                os.path.dirname(os.path.abspath(sys.executable)))
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(exe):
        exe = sys.executable
    params = subprocess.list2cmdline(
        [os.path.abspath(sys.argv[0])] + sys.argv[1:])
    return exe, params, os.path.dirname(os.path.abspath(__file__))


def relaunch_elevated():
    """Re-run this script through pythonw.exe under UAC.  pythonw keeps the
    relaunch console-free; returns False when the user declines so the caller
    can carry on unelevated (HKCU tweaks still work)."""
    exe, params, cwd = _relaunch_args()
    rc = _shell32.ShellExecuteW(None, "runas", exe, params, cwd, 1)
    return (rc or 0) > 32


# ====================================================================
#  FUZZY FINDER
# ====================================================================

def fuzzy_score(query, target):
    if not query:
        return 0
    q = query.lower()
    t = target.lower()
    if q in t:
        return 1000 - t.index(q) - len(t) // 4
    i = 0
    score = 0
    last = -2
    for c in q:
        idx = t.find(c, i)
        if idx < 0:
            return -1
        if idx == last + 1:
            score += 6
        elif idx > 0 and not t[idx - 1].isalnum():
            score += 4
        score += 2
        i = idx + 1
        last = idx
    return score - len(t) // 8


class FinderWindow(QDialog):
    """Frameless floating fuzzy finder.  Shown ABOVE the main window and
    magnetically attached to its top edge: when the main window moves or
    resizes, the finder follows.

    Live preview: as the user navigates the list, the main window switches
    to the tab containing the setting and highlights it in bright green.
    Esc reverts the tab and removes the highlight; Enter or double-click
    keeps the tab and focuses the control.
    """
    HIGHLIGHT_COLOR = QColor(120, 255, 120)
    MAX_H = 250

    def __init__(self, parent_main):
        super().__init__(parent_main)
        self.parent_main = parent_main
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setMaximumHeight(self.MAX_H)
        self.setStyleSheet(
            "FinderWindow { background:#f0f0f0; border:1px solid #888; }")

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(3)

        self.input = QLineEdit()
        self.input.setMinimumHeight(30)
        self.input.setFocusPolicy(Qt.StrongFocus)
        v.addWidget(self.input)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        # NoFocus on the list means a mouse-click selects an item but does
        # NOT steal keyboard focus - the input stays focused so typed text
        # always lands in it, and up/down arrows always reach the input's
        # event filter (which forwards them to the list).
        self.list.setFocusPolicy(Qt.NoFocus)
        v.addWidget(self.list, 1)

        self.input.textChanged.connect(self._filter)
        self.input.installEventFilter(self)
        self.list.currentRowChanged.connect(self._on_row_changed)
        self.list.itemDoubleClicked.connect(lambda _: self._accept())

        self._search_index = []
        self._original_tab = None
        self._highlighted = None
        self._original_palette = None
        self._original_autofill = False

    def show_above(self, search_index):
        self._search_index = search_index
        self._original_tab = self.parent_main.tabs.currentIndex()
        self.input.clear()
        self._filter("")
        self._reposition()
        self.show()
        self.raise_()
        # On Windows, frameless Qt.Tool windows don't always receive keyboard
        # focus on show(); explicitly activate this window first *then* focus
        # the input.
        self.activateWindow()
        self.input.setFocus(Qt.OtherFocusReason)
        self.input.selectAll()

    def _reposition(self):
        m = self.parent_main.frameGeometry()
        my_h = self.MAX_H
        my_y = max(0, m.y() - my_h - 2)
        self.setGeometry(m.x(), my_y, m.width(), my_h)

    def _filter(self, q):
        self.list.blockSignals(True)
        self.list.clear()
        scored = []
        for label, widget, page in self._search_index:
            # widget None marks a whole-tab entry
            terms = (label, *TAB_TERMS[label]) if widget is None else (label,)
            s = max(fuzzy_score(q, t) for t in terms)
            if s >= 0:
                scored.append((s, label, widget, page))
        scored.sort(key=lambda x: -x[0])
        for s, label, widget, page in scored[:300]:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, (widget, page))
            self.list.addItem(it)
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._unhighlight()

    def _on_row_changed(self, row):
        if row < 0:
            self._unhighlight()
            return
        item = self.list.item(row)
        if not item:
            return
        widget, page = item.data(Qt.UserRole)
        self._unhighlight()
        self.parent_main.jump_to(widget, page)
        if widget is not None:
            self._highlight(widget)

    def _highlight(self, widget):
        self._highlighted = widget
        self._original_palette = QPalette(widget.palette())
        self._original_autofill = widget.autoFillBackground()
        pal = QPalette(self._original_palette)
        # backgroundRole() is what autoFillBackground paints (Window for a
        # QCheckBox, Button for a QSpinBox); Base is what the spin box's own
        # editable field paints.
        pal.setColor(widget.backgroundRole(), self.HIGHLIGHT_COLOR)
        pal.setColor(QPalette.Base, self.HIGHLIGHT_COLOR)
        widget.setPalette(pal)
        widget.setAutoFillBackground(True)

    def _unhighlight(self):
        if self._highlighted is not None and self._original_palette is not None:
            self._highlighted.setPalette(self._original_palette)
            self._highlighted.setAutoFillBackground(self._original_autofill)
        self._highlighted = None
        self._original_palette = None

    def _accept(self):
        item = self.list.currentItem()
        if not item:
            return self._cancel()
        widget, _page = item.data(Qt.UserRole)
        self._unhighlight()
        self.hide()
        if widget is None:
            return
        QTimer.singleShot(0, lambda w=widget: (
            w.setFocus(),
            w.selectAll() if hasattr(w, "selectAll") else None,
        ))

    def _cancel(self):
        self._unhighlight()
        if self._original_tab is not None:
            self.parent_main.tabs.setCurrentIndex(self._original_tab)
        self.hide()

    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                self.list.keyPressEvent(ev)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._accept()
                return True
            if k == Qt.Key_Escape:
                self._cancel()
                return True
        return super().eventFilter(obj, ev)

    def closeEvent(self, ev):
        self._cancel()
        super().closeEvent(ev)


# ====================================================================
#  PAGES
# ====================================================================

class RepeatRatePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load()
        self._load_windows()

    def _build_ui(self):
        page = QVBoxLayout(self)
        page.setContentsMargins(6, 6, 6, 6)
        page.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        page.addLayout(top)
        top.addWidget(self._build_windows_group(), 1)

        fk_box = QGroupBox("FilterKeys")
        top.addWidget(fk_box, 1)
        outer = QVBoxLayout(fk_box)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)

        self.delay_slider, self.delay = _slider_spin(*DELAY_RANGE, 250)
        self.rate_slider, self.rate = _slider_spin(*RATE_RANGE, 30)
        self.cps = QLabel()
        self.rate.valueChanged.connect(self._update_cps)
        self._update_cps(self.rate.value())

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        grid.addWidget(QLabel("Delay"), 0, 0)
        grid.addWidget(self.delay_slider, 0, 1)
        grid.addWidget(self.delay, 0, 2)
        grid.addWidget(QLabel("ms"), 0, 3)
        grid.addWidget(QLabel("Repeat"), 1, 0)
        grid.addWidget(self.rate_slider, 1, 1)
        grid.addWidget(self.rate, 1, 2)
        grid.addWidget(QLabel("ms"), 1, 3)
        grid.addWidget(self.cps, 1, 4)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        presets = QHBoxLayout()
        presets.setSpacing(4)
        for name, d, r in PRESETS:
            b = QPushButton(name)
            b.clicked.connect(lambda _, d=d, r=r: self._set(d, r))
            presets.addWidget(b)
        presets.addStretch(1)
        outer.addLayout(presets)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_apply = QPushButton("Apply")
        self.btn_save = QPushButton("Apply + save")
        self.btn_off = QPushButton("Off")
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(lambda: self._apply(False))
        self.btn_save.clicked.connect(lambda: self._apply(True))
        self.btn_off.clicked.connect(self._off)
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_off)
        row.addStretch(1)
        outer.addLayout(row)

        self.status = QLabel()
        outer.addWidget(self.status)
        outer.addStretch(1)

        gb = QGroupBox("Test")
        gl = QVBoxLayout(gb)
        gl.setContentsMargins(6, 4, 6, 4)
        gl.addWidget(QPlainTextEdit())
        page.addWidget(gb, 1)

    def _build_windows_group(self):
        """The native repeat, used whenever FilterKeys is off."""
        box = QGroupBox("Windows")
        grid = QGridLayout(box)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)

        self.win_delay = QSlider(Qt.Horizontal)
        self.win_delay.setRange(0, len(keydiag.DELAY_MS) - 1)
        self.win_delay.setPageStep(1)
        self.win_delay.setTickInterval(1)
        self.win_delay.setTickPosition(QSlider.TicksBelow)
        self.win_delay_lbl = QLabel()

        self.win_speed = QSlider(Qt.Horizontal)
        self.win_speed.setRange(0, keydiag.SPEED_MAX)
        self.win_speed_lbl = QLabel()

        # Driven explicitly rather than only from valueChanged: setValue() to
        # the value a slider already holds emits nothing, which would leave
        # the labels blank on load.
        self.win_delay.valueChanged.connect(self._update_win_labels)
        self.win_speed.valueChanged.connect(self._update_win_labels)
        self._update_win_labels()

        grid.addWidget(QLabel("Delay"), 0, 0)
        grid.addWidget(self.win_delay, 0, 1)
        grid.addWidget(self.win_delay_lbl, 0, 2)
        grid.addWidget(QLabel("Repeat"), 1, 0)
        grid.addWidget(self.win_speed, 1, 1)
        grid.addWidget(self.win_speed_lbl, 1, 2)
        grid.setColumnStretch(1, 1)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_win_apply = QPushButton("Apply")
        self.btn_win_apply.clicked.connect(self._apply_windows)
        row.addWidget(self.btn_win_apply)
        for name, d, s in WIN_PRESETS:
            b = QPushButton(name)
            b.clicked.connect(lambda _, d=d, s=s: self._set_windows(d, s))
            row.addWidget(b)
        row.addStretch(1)
        grid.addLayout(row, 2, 0, 1, 3)

        self.win_status = QLabel()
        grid.addWidget(self.win_status, 3, 0, 1, 3)
        grid.setRowStretch(4, 1)
        return box

    def _update_win_labels(self, _=None):
        ms = keydiag.speed_to_ms(self.win_speed.value())
        self.win_delay_lbl.setText(
            f"{keydiag.DELAY_MS[self.win_delay.value()]} ms")
        self.win_speed_lbl.setText(f"{ms:.0f} ms   {1000 / ms:.1f} /s")

    def _set_windows(self, delay_index, speed_index):
        self.win_delay.setValue(delay_index)
        self.win_speed.setValue(speed_index)
        self._update_win_labels()

    def _load_windows(self):
        try:
            delay, speed = (keydiag.keyboard_delay_index(),
                            keydiag.keyboard_speed_index())
        except OSError as e:
            self.win_status.setText(str(e))
            return
        self._set_windows(min(delay, len(keydiag.DELAY_MS) - 1), speed)
        self.win_status.setText(
            f"{keydiag.DELAY_MS[delay]} ms   "
            f"{keydiag.speed_to_ms(speed):.0f} ms")

    def _apply_windows(self):
        delay, speed = self.win_delay.value(), self.win_speed.value()
        try:
            keydiag.set_keyboard_delay(delay)
            keydiag.set_keyboard_speed(speed)
        except OSError as e:
            self.win_status.setText(str(e))
            return
        self.win_status.setText(
            f"{keydiag.DELAY_MS[delay]} ms   "
            f"{keydiag.speed_to_ms(speed):.0f} ms   saved")

    def _update_cps(self, ms):
        self.cps.setText(f"{1000 / ms:.1f} /s")

    def _set(self, delay, rate):
        self.delay.setValue(delay)
        self.rate.setValue(rate)

    def _load(self):
        try:
            fk = read_filterkeys()
        except OSError as e:
            self.status.setText(str(e))
            return
        if fk.dwFlags & FKF_FILTERKEYSON:
            self._set(fk.iDelayMSec, fk.iRepeatMSec)
            self.status.setText(
                f"On   delay {fk.iDelayMSec} ms   repeat {fk.iRepeatMSec} ms"
            )
        else:
            self.status.setText("Off")

    def _apply(self, persist):
        delay, rate = self.delay.value(), self.rate.value()
        try:
            set_filterkeys(True, delay, rate, persist)
        except OSError as e:
            self.status.setText(str(e))
            return
        saved = "   saved" if persist else ""
        self.status.setText(f"On   delay {delay} ms   repeat {rate} ms{saved}")

    def _off(self):
        try:
            set_filterkeys(False, 0, 0, True)
        except OSError as e:
            self.status.setText(str(e))
            return
        self._set(250, 30)
        self.status.setText("Off   saved")

    def search_entries(self, tab_name):
        return [
            (f"{tab_name}  ->  Windows  ->  Delay", self.win_delay, self),
            (f"{tab_name}  ->  Windows  ->  Repeat", self.win_speed, self),
            (f"{tab_name}  ->  FilterKeys  ->  Delay", self.delay, self),
            (f"{tab_name}  ->  FilterKeys  ->  Repeat", self.rate, self),
        ]


def _section_label(text):
    lbl = QLabel(text)
    f = QFont(lbl.font())
    f.setUnderline(True)
    f.setBold(True)
    lbl.setFont(f)
    return lbl


def _vsep():
    sep = QFrame()
    sep.setFixedWidth(3)
    sep.setStyleSheet("background:#7a7a7a;")
    sep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    return sep


class TweakPage(QScrollArea):
    """Four dense columns of sections; one checkbox per tweak, tinted by
    live state (lime = on, pink = off, no tint = not applicable)."""

    N_COLS = 4
    PINK = QColor(255, 205, 213)
    LIME = QColor(200, 240, 170)

    def __init__(self, tab_name, sections, report):
        super().__init__()
        self.tab_name = tab_name
        self.report = report
        self.boxes = {}

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        outer.addLayout(row, 1)

        total = sum(len(t) for _, t in sections)
        target = max(1.0, total / self.N_COLS)
        columns = [QVBoxLayout() for _ in range(self.N_COLS)]
        for lay in columns:
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(1)

        ci, load = 0, 0.0
        for name, items in sections:
            if load >= target and ci < self.N_COLS - 1:
                ci += 1
                load = 0.0
            lay = columns[ci]
            lay.addWidget(_section_label(name))
            for tw in items:
                cb = QCheckBox(tw.label)
                cb.clicked.connect(lambda on, t=tw: self._apply(t, on))
                lay.addWidget(cb)
                self.boxes[tw.key] = (cb, tw, name)
            lay.addSpacing(6)
            load += len(items) + 1

        for i, lay in enumerate(columns):
            lay.addStretch(1)
            row.addLayout(lay, 1)
            if i < self.N_COLS - 1:
                row.addWidget(_vsep())

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        btn = QPushButton("Remove Copilot AppX")
        btn.clicked.connect(self._remove_copilot_appx)
        actions.addWidget(btn)
        actions.addStretch(1)
        outer.addLayout(actions)

        self.setWidget(body)
        self.setWidgetResizable(True)
        self.refresh()

    def _sync(self, cb, tw):
        state = tw.state()
        cb.blockSignals(True)
        cb.setEnabled(state is not None)
        cb.setChecked(bool(state))
        cb.blockSignals(False)
        if state is None:
            cb.setAutoFillBackground(False)
        else:
            pal = cb.palette()
            pal.setColor(cb.backgroundRole(), self.LIME if state else self.PINK)
            cb.setPalette(pal)
            cb.setAutoFillBackground(True)

    def refresh(self):
        for cb, tw, _sec in self.boxes.values():
            self._sync(cb, tw)

    def _apply(self, tw, on):
        try:
            failed = tw.apply(on)
        except OSError as e:
            self.boxes[tw.key][0].setChecked(not on)
            self.report(f"{tw.label}: {e.strerror or e}")
            return
        cb = self.boxes[tw.key][0]
        self._sync(cb, tw)
        state = tw.state()
        tail = f"   {failed} task(s) unchanged" if failed else ""
        self.report(f"{tw.label}: {'on' if state else 'off'}{tail}")

    def search_entries(self, tab_name):
        return [(f"{tab_name}  ->  {sec}  ->  {tw.label}", cb, self)
                for cb, tw, sec in self.boxes.values()]

    def enabled_count(self):
        return sum(1 for cb, _t, _s in self.boxes.values() if cb.isChecked())

    def _remove_copilot_appx(self):
        if QMessageBox.question(
                self, "Remove Copilot AppX",
                "Uninstall the Copilot AppX packages? This is one-way and "
                "runs elevated (UAC).") != QMessageBox.Yes:
            return
        launched = tweaks.remove_copilot_appx()
        self.report("Copilot AppX removal started (elevated)" if launched
                    else "Copilot AppX removal cancelled")


# ====================================================================
#  MAIN WINDOW
# ====================================================================

class WintoolsWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        geo = settings.value("geometry")
        if geo is None or not self.restoreGeometry(geo):
            self.resize(1180, 700)

        sections = [sec for _tab, secs in tweaks.tabs() for sec in secs]
        self.gpu_page = gpu.GpuPage(self)
        self.pages = [
            ("Repeat rate", RepeatRatePage(self)),
            ("Key diagnostics", keydiag.KeyDiagPage(summary, self)),
            ("System", TweakPage("System", sections, self._report)),
            ("GPU", self.gpu_page),
        ]
        # Action pages from clean: no persistent settings, so they stay out
        # of self.pages and the finder index.
        self._clean_config = clean.load_config()
        self.clean_pages = [
            ("Files", clean.FilesPage(
                self._clean_config, self._save_clean_config, self)),
            ("Registry", clean.RegistryPage(self)),
            ("Orphan paths", clean.OrphanPathsPage(self)),
            ("Uninstall", clean.UninstallPage(self)),
            ("Empty folders", clean.EmptyFoldersPage(self)),
            ("Largest files", clean.LargestFilesPage(self)),
        ]

        self.hardware_page = hardware.HardwarePage(parent=self)
        self.initcfg_page = initcfg.InitConfigPage(
            self._report, self.refresh_all, self.restart_explorer, self)
        self.installer_page = installer.InstallerPage(
            self._report, self.refresh_all, self)

        self.tabs = QTabWidget()
        self.tabs.setTabBar(SideTabBar())
        tab_pages = [("Initial Config", self.initcfg_page),
                     ("Installer", self.installer_page), *self.pages,
                     ("Hardware", self.hardware_page), *self.clean_pages[:4],
                     ("Startup", startup.StartupPage(self)),
                     ("Environment", envedit.EnvPage(self)),
                     ("Context Menu", ctxmenu.ContextMenuPage(self)),
                     *self.clean_pages[4:]]
        icons = ("initcfg", "installer", "repeat", "keydiag", "system", "gpu",
                 "hardware", "files", "registry", "orphans", "uninstall",
                 "startup", "envedit", "ctxmenu", "empty", "largest")
        for (name, page), key in zip(tab_pages, icons, strict=True):
            i = self.tabs.addTab(page, icon(f"tab_{key}"), name)
            # the name lives in tab data, so the label can be blanked (icons only)
            self.tabs.tabBar().setTabData(i, name)
        self.tabs.setCurrentIndex(
            min(settings.value("tab_index", 0, type=int), self.tabs.count() - 1))
        self.tabs.currentChanged.connect(self._update_title)
        self._update_title(self.tabs.currentIndex())
        self.setCentralWidget(self.tabs)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._apply_tab_layout()
        state = settings.value("window_state")
        if state is not None:
            self.restoreState(state)

        self.lbl_count = QLabel()
        self.lbl_mode = QLabel("admin" if is_admin() else "not admin")
        for lbl in (self.lbl_count, self.lbl_mode):
            lbl.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            self.statusBar().addPermanentWidget(lbl)

        self.search_index = [(name, None, page) for name, page in tab_pages]
        for name, page in self.pages:
            self.search_index.extend(page.search_entries(name))
        self._finder = None

        self._show_counts()

    def _update_title(self, index):
        self.setWindowTitle(f"wintools - {self.tabs.tabBar().tabData(index)}")

    # ---- menus / toolbar ----
    def _action(self, text, icon_name, slot, *keys):
        act = QAction(icon(icon_name), text, self)
        act.triggered.connect(slot)
        act.setShortcuts([QKeySequence(k) for k in keys])
        return act

    def _build_actions(self):
        self.act_import = self._action(
            "&Import XML...", "act_import", self.import_config, "Ctrl+O")
        self.act_export = self._action(
            "&Export XML...", "act_export", self.export_config, "Ctrl+S")
        self.act_find = self._action(
            "&Find...", "act_find", self.open_finder,
            "Ctrl+F", "Ctrl+K", "Ctrl+Space")
        self.act_refresh = self._action(
            "&Refresh", "act_refresh", self.refresh_all, "F5", "Ctrl+R")
        self.act_explorer = self._action(
            "Restart E&xplorer", "act_explorer", self.restart_explorer)
        # an app-wide filter, not a shortcut: text fields claim printable keys
        # before shortcuts, and keypad +/- must never reach them
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if (ev.type() == QEvent.KeyPress and ev.modifiers() & Qt.KeypadModifier
                and ev.key() in TAB_STEP_KEYS and isinstance(obj, QWidget)
                and obj.window() is self):
            self._step_tab(TAB_STEP_KEYS[ev.key()])
            return True
        return super().eventFilter(obj, ev)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addAction(self.act_import)
        m.addAction(self.act_export)
        m.addSeparator()
        m.addAction("E&xit", self.close).setShortcut("Ctrl+Q")

        m = mb.addMenu("&Tools")
        m.addAction(self.act_find)
        m.addAction(self.act_refresh)
        m.addSeparator()
        m.addAction(self.act_explorer)

        m = mb.addMenu("&View")
        pos = self.settings.value("tab_position", "top")
        px = self.settings.value("tab_icon_size", 16, type=int)
        self.grp_tab_pos = QActionGroup(self)
        sub = m.addMenu("Tab &Position")
        for label, key, _where in TAB_POSITIONS:
            a = sub.addAction(label)
            a.setCheckable(True)
            a.setData(key)
            a.setChecked(key == pos)
            self.grp_tab_pos.addAction(a)
        self.grp_tab_icon = QActionGroup(self)
        sub = m.addMenu("Tab &Icon Size")
        for size in TAB_ICON_SIZES:
            a = sub.addAction(f"{size} px")
            a.setCheckable(True)
            a.setData(size)
            a.setChecked(size == px)
            self.grp_tab_icon.addAction(a)
        # a stale or hand-edited setting falls back to the first choice
        for grp in (self.grp_tab_pos, self.grp_tab_icon):
            if grp.checkedAction() is None:
                grp.actions()[0].setChecked(True)
            grp.triggered.connect(self._apply_tab_layout)
        self.act_tab_text = m.addAction("Show Tab &Text")
        self.act_tab_text.setCheckable(True)
        self.act_tab_text.setChecked(
            self.settings.value("tab_show_text", True, type=bool))
        self.act_tab_text.toggled.connect(self._apply_tab_layout)
        m.addSeparator()
        self._view_menu = m

    def _build_toolbar(self):
        tb = QToolBar("Toolbar")
        tb.setObjectName("toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(24, 24))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.addAction(self.act_refresh)
        tb.addAction(self.act_find)
        tb.addSeparator()
        tb.addAction(self.act_import)
        tb.addAction(self.act_export)
        tb.addSeparator()
        tb.addAction(self.act_explorer)
        self.addToolBar(tb)
        self._view_menu.addAction(tb.toggleViewAction())

    def _apply_tab_layout(self, *_):
        key = self.grp_tab_pos.checkedAction().data()
        px = self.grp_tab_icon.checkedAction().data()
        show = self.act_tab_text.isChecked()
        self.tabs.setTabPosition(
            next(w for _l, k, w in TAB_POSITIONS if k == key))
        self.tabs.setIconSize(QSize(px, px))
        bar = self.tabs.tabBar()
        for i in range(self.tabs.count()):
            self.tabs.setTabText(i, bar.tabData(i) if show else "")
        self.settings.setValue("tab_position", key)
        self.settings.setValue("tab_icon_size", px)
        self.settings.setValue("tab_show_text", show)

    def _step_tab(self, step):
        self.tabs.setCurrentIndex(
            (self.tabs.currentIndex() + step) % self.tabs.count())

    # ---- finder ----
    def open_finder(self):
        if self._finder is None:
            self._finder = FinderWindow(self)
        if self._finder.isVisible():
            self._finder.input.selectAll()
            self._finder.input.setFocus()
            return
        self._finder.show_above(self.search_index)

    def jump_to(self, widget, page):
        idx = self.tabs.indexOf(page)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)
        if widget is not None and isinstance(page, QScrollArea):
            QTimer.singleShot(
                0, lambda: page.ensureWidgetVisible(widget, 30, 30))

    def closeEvent(self, ev):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("tab_index", self.tabs.currentIndex())
        # A tab child never gets its own close event, so the global hook has
        # to be torn down from here.
        for _name, page in self.pages:
            if isinstance(page, keydiag.KeyDiagPage):
                page.hook.stop()
        for _name, page in self.clean_pages:
            page.shutdown()
        self.hardware_page.shutdown()
        self.initcfg_page.shutdown()
        self.installer_page.shutdown()
        super().closeEvent(ev)

    def moveEvent(self, ev):
        super().moveEvent(ev)
        if self._finder is not None and self._finder.isVisible():
            self._finder._reposition()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._finder is not None and self._finder.isVisible():
            self._finder._reposition()

    # ---- actions ----
    def refresh_all(self):
        for _name, page in self.pages:
            if isinstance(page, (TweakPage, gpu.GpuPage)):
                page.refresh()
        self.initcfg_page.refresh_states()
        self.installer_page.refresh_states()
        self._show_counts()

    def restart_explorer(self):
        subprocess.run(["taskkill", "/f", "/im", "explorer.exe"],
                       creationflags=tweaks.CREATE_NO_WINDOW,
                       capture_output=True, check=False)
        subprocess.Popen(["explorer.exe"],
                         creationflags=tweaks.CREATE_NO_WINDOW)
        self.statusBar().showMessage("Explorer restarted")

    def export_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export configuration", "wintools.xml", "XML files (*.xml)")
        if not path:
            return
        try:
            n = tweaks.export_config(path, [
                gpu.profile_element(p) for p in self.gpu_page.profiles()])
        except OSError as e:
            self.statusBar().showMessage(f"Export failed: {e}", 5000)
            return
        self.statusBar().showMessage(f"Exported {n} settings to {path}")

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import configuration", "", "XML files (*.xml)")
        if not path:
            return
        if QMessageBox.question(
                self, "Import configuration",
                f"Apply saved settings from\n{path}?") != QMessageBox.Yes:
            return
        try:
            applied, skipped, failed = tweaks.import_config(path)
            g_applied, g_skipped = self.gpu_page.apply_profiles(
                gpu.profiles_from_root(ET.parse(path).getroot()))
        except (OSError, ET.ParseError) as e:
            self.statusBar().showMessage(f"Import failed: {e}", 5000)
            return
        applied += g_applied
        skipped += g_skipped
        self.refresh_all()
        msg = f"Imported {applied} settings"
        if skipped:
            msg += f"   {skipped} unknown"
        if failed:
            msg += f"   {failed} failed"
        self.statusBar().showMessage(msg)

    def _save_clean_config(self):
        try:
            clean.save_config(self._clean_config)
        except OSError as e:
            self.statusBar().showMessage(f"Config save failed: {e}", 5000)

    def _report(self, msg):
        self.statusBar().showMessage(msg)
        self._show_counts()

    def _show_counts(self):
        on = sum(p.enabled_count() for _n, p in self.pages
                 if isinstance(p, TweakPage))
        self.lbl_count.setText(f"{on} of {len(tweaks.TWEAKS)} enabled")


def _isolate_children():
    # Children inherit the bootloader's _PYI_* vars naming this instance's
    # _MEI dir; a restarted Explorer becomes the shell and would hand them to
    # every later launch of the exe, which then dies on the deleted dir.
    if getattr(sys, "frozen", False):
        os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"


def main():
    if sys.argv[1:2] == ["--ctxmenu-dump"]:
        ctxmenu.dump_main(sys.argv[2:])
        return
    _isolate_children()
    if "--no-elevate" in sys.argv:
        sys.argv.remove("--no-elevate")
    elif not is_admin() and relaunch_elevated():
        return

    set_app_id()  # before the first window exists
    app = QApplication(sys.argv)

    # <ICON_INJECT_START>
    # Force Qt to be fully ready before any other operations
    app.processEvents()

    # Icon setup after processing events
    try:
        import os
        from PyQt5.QtGui import QIcon
        icon_path = os.path.join(os.path.dirname(__file__), "wintools.ico")
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            app.setWindowIcon(app_icon)
    except Exception as e:
        print(f"Icon setup failed: {e}")
    # <ICON_INJECT_END>
    app.setStyle("Windows")
    app.setFont(QFont("Tahoma", 8))
    win = WintoolsWindow(QSettings(settings_path(), QSettings.IniFormat))
    # <ICON_INJECT_START>
    # Set window icon too
    try:
        if hasattr(app, 'windowIcon') and not app.windowIcon().isNull():
            win.setWindowIcon(app.windowIcon())
    except Exception:
        pass
    # <ICON_INJECT_END>
    win.show()
    smoke_ms = os.environ.get("WINTOOLS_SMOKE_MS")
    if smoke_ms:
        QTimer.singleShot(int(smoke_ms), app.quit)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
