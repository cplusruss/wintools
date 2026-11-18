#!/usr/bin/env python3
"""keydiag.py - keyboard repeat / chatter diagnostics via WH_KEYBOARD_LL."""

import ctypes
import ctypes.wintypes as wt
import time
from collections import deque

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

LLKHF_EXTENDED = 0x01
LLKHF_LOWER_IL_INJECTED = 0x02
LLKHF_INJECTED = 0x10

KEYEVENTF_KEYUP = 0x0002
VK_F24 = 0x87   # no shell or application binds it, so tapping it is inert

SPI_GETKEYBOARDDELAY = 0x0016
SPI_SETKEYBOARDDELAY = 0x0017
SPI_GETKEYBOARDSPEED = 0x000A
SPI_SETKEYBOARDSPEED = 0x000B
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

DELAY_MS = (250, 500, 750, 1000)
SPEED_MAX = 31


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    wt.LPARAM, ctypes.c_int, wt.WPARAM, ctypes.POINTER(KBDLLHOOKSTRUCT))

_user32.SetWindowsHookExW.restype = wt.HHOOK
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE,
                                      wt.DWORD]
_user32.UnhookWindowsHookEx.restype = wt.BOOL
_user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
_user32.CallNextHookEx.restype = wt.LPARAM
_user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM,
                                   ctypes.POINTER(KBDLLHOOKSTRUCT)]
_user32.GetKeyNameTextW.restype = ctypes.c_int
_user32.GetKeyNameTextW.argtypes = [wt.LONG, wt.LPWSTR, ctypes.c_int]
_user32.SystemParametersInfoW.restype = wt.BOOL
_user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p,
                                          wt.UINT]
# Without an explicit restype ctypes assumes c_int and truncates the 64-bit
# module handle, which makes SetWindowsHookExW fail with ERROR_MOD_NOT_FOUND.
_kernel32.GetModuleHandleW.restype = wt.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
_user32.keybd_event.restype = None
_user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wt.DWORD,
                                ctypes.c_size_t]


def tap_probe_key():
    _user32.keybd_event(VK_F24, 0, 0, 0)
    _user32.keybd_event(VK_F24, 0, KEYEVENTF_KEYUP, 0)


def spi_get_int(action):
    val = ctypes.c_int(0)
    if not _user32.SystemParametersInfoW(action, 0, ctypes.byref(val), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return val.value


def spi_set_int(action, value):
    if not _user32.SystemParametersInfoW(
            action, value, None, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE):
        raise ctypes.WinError(ctypes.get_last_error())


def keyboard_delay_index():
    return spi_get_int(SPI_GETKEYBOARDDELAY)


def keyboard_speed_index():
    return spi_get_int(SPI_GETKEYBOARDSPEED)


def keyboard_delay_ms():
    return DELAY_MS[min(keyboard_delay_index(), len(DELAY_MS) - 1)]


def speed_to_ms(index):
    # SPI_GETKEYBOARDSPEED is 0..31 mapping linearly onto ~2.5..30 chars/sec.
    return 1000.0 / (2.5 + (30.0 - 2.5) * index / SPEED_MAX)


def keyboard_repeat_ms():
    return speed_to_ms(keyboard_speed_index())


def set_keyboard_delay(index):
    spi_set_int(SPI_SETKEYBOARDDELAY, index)


def set_keyboard_speed(index):
    spi_set_int(SPI_SETKEYBOARDSPEED, index)


def key_name(vk, scan, extended):
    lparam = (scan << 16) | (0x01000000 if extended else 0)
    buf = ctypes.create_unicode_buffer(64)
    if _user32.GetKeyNameTextW(lparam, buf, 64) and buf.value.strip():
        return buf.value
    return f"VK {vk:02X}"


class KeyHook:
    """Global low-level keyboard hook.  The callback runs on the Qt main
    thread's message loop and must stay trivial - Windows silently drops a
    hook whose callback exceeds LowLevelHooksTimeout - so it only appends a
    tuple and the UI drains the queue on a timer."""

    def __init__(self):
        self.events = deque()
        self._handle = None
        self._proc = None  # a dropped reference here crashes the input thread

    def running(self):
        return self._handle is not None

    def start(self):
        if self._handle is not None:
            return
        self._proc = HOOKPROC(self._callback)
        self._handle = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc,
            _kernel32.GetModuleHandleW(None), 0)
        if not self._handle:
            self._handle = None
            self._proc = None
            raise ctypes.WinError(ctypes.get_last_error())

    def stop(self):
        if self._handle is None:
            return
        _user32.UnhookWindowsHookEx(self._handle)
        self._handle = None
        self._proc = None

    def drain(self):
        out = []
        while self.events:
            out.append(self.events.popleft())
        return out

    def prove_delivery(self, attempts=3, per_attempt=0.7):
        """Tap a key nothing reacts to and confirm it comes back.

        Windows silently drops a low-level hook whose callback overruns
        LowLevelHooksTimeout, and the dead handle still looks installed - so
        an unproven hook means an empty grid that reads as "your keyboard is
        fine".  A single tap can also be swallowed by a foreground or
        secure-desktop transition, hence the retries.  Never sleeps: the
        callback is only delivered while this thread retrieves messages.

        Returns the probe events seen (empty when delivery failed); either
        way the queue is left clean so probes are never counted.
        """
        for _ in range(attempts):
            self.drain()
            tap_probe_key()
            deadline = time.monotonic() + per_attempt
            while time.monotonic() < deadline:
                QApplication.processEvents()
                seen = [e for e in self.events if e[2] == VK_F24]
                if len(seen) >= 2:
                    self.drain()
                    return seen
        self.drain()
        return []

    def _callback(self, nCode, wParam, lParam):
        if nCode == 0:
            st = lParam.contents
            self.events.append((time.perf_counter(), int(wParam), st.vkCode,
                                st.scanCode, st.flags))
        return _user32.CallNextHookEx(None, nCode, wParam, lParam)


EVENT_COLS = ("#", "t ms", "key", "vk", "scan", "edge", "gap ms", "class")
KEY_COLS = ("key", "vk", "scan", "presses", "repeats", "chatter", "min gap ms")
MAX_ROWS = 2000
ANOMALIES = ("chatter", "injected", "repeat-fast")


def style_grid(t):
    t.setAlternatingRowColors(False)
    t.setShowGrid(True)
    t.setGridStyle(Qt.SolidLine)
    t.setStyleSheet(
        "QTableWidget { gridline-color: black; }"
        "QTableView::item { padding: 0px; }")
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(QFontMetrics(t.font()).height() + 2)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    return t


class KeyDiagPage(QWidget):
    """Classifies every keystroke the system sees:

    injected     - another process synthesised it (macro tool, RDP, KVM)
    chatter      - key released and re-pressed faster than a finger can
    repeat-fast  - held-key repeat arriving faster than the configured rate
    repeat       - held-key auto-repeat at the configured rate
    """

    def __init__(self, filterkeys_reader, parent=None):
        super().__init__(parent)
        self._read_fk = filterkeys_reader
        self.hook = KeyHook()
        self.keys = {}
        self.counts = dict.fromkeys(
            ("press", "repeat", "repeat-fast", "chatter", "injected",
             "release"), 0)
        self.seq = 0
        self._build_ui()
        self._refresh_settings()

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._drain)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_capture = QPushButton("Start capture")
        self.btn_capture.clicked.connect(self._toggle)
        row.addWidget(self.btn_capture)
        btn = QPushButton("Clear")
        btn.clicked.connect(self._clear)
        row.addWidget(btn)
        row.addWidget(QLabel("Chatter under"))
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 200)
        self.threshold.setValue(40)
        self.threshold.setSuffix(" ms")
        row.addWidget(self.threshold)
        self.anomalies_only = QCheckBox("Anomalies only")
        row.addWidget(self.anomalies_only)
        row.addStretch(1)
        outer.addLayout(row)

        self.settings = QLabel()
        outer.addWidget(self.settings)

        self.events = style_grid(QTableWidget(0, len(EVENT_COLS)))
        self.events.setHorizontalHeaderLabels(EVENT_COLS)
        outer.addWidget(self.events, 3)

        self.summary = style_grid(QTableWidget(0, len(KEY_COLS)))
        self.summary.setHorizontalHeaderLabels(KEY_COLS)
        outer.addWidget(self.summary, 2)

        self.status = QLabel()
        outer.addWidget(self.status)

        self.repro = QLineEdit()
        outer.addWidget(self.repro)

    # ---- settings readout ----
    def _refresh_settings(self):
        on, delay, repeat = self._read_fk()
        if on:
            self.expected_ms = float(repeat) if repeat else keyboard_repeat_ms()
            src = f"FilterKeys on   delay {delay} ms   repeat {repeat} ms"
        else:
            self.expected_ms = keyboard_repeat_ms()
            src = (f"FilterKeys off   delay {keyboard_delay_ms()} ms   "
                   f"repeat {keyboard_repeat_ms():.0f} ms")
        self.settings.setText(src)

    # ---- capture ----
    def _toggle(self):
        if self.hook.running():
            self.hook.stop()
            self.timer.stop()
            self.btn_capture.setText("Start capture")
        else:
            self._refresh_settings()
            try:
                self.hook.start()
            except OSError as e:
                self.status.setText(str(e))
                return
            self.btn_capture.setEnabled(False)
            delivered = self.hook.prove_delivery()
            self.btn_capture.setEnabled(True)
            if not delivered:
                self.hook.stop()
                self.status.setText(
                    "hook installed but no events were delivered")
                return
            self.timer.start()
            self.btn_capture.setText("Stop capture")
            self.repro.setFocus()
        self._update_status()

    def _clear(self):
        self.hook.drain()
        self.keys.clear()
        for k in self.counts:
            self.counts[k] = 0
        self.seq = 0
        self.events.setRowCount(0)
        self.summary.setRowCount(0)
        self._update_status()

    def _drain(self):
        rows = self.hook.drain()
        if not rows:
            return
        threshold = self.threshold.value()
        only = self.anomalies_only.isChecked()
        for t, msg, vk, scan, flags in rows:
            self.seq += 1
            down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
            kid = (vk, scan)
            st = self.keys.setdefault(kid, {
                "name": key_name(vk, scan, flags & LLKHF_EXTENDED),
                "vk": vk, "scan": scan,
                "last_t": None, "last_down": None, "presses": 0,
                "repeats": 0, "chatter": 0, "min_gap": None,
            })
            gap = None if st["last_t"] is None else (t - st["last_t"]) * 1000.0

            if flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED):
                cls = "injected"
            elif not down:
                cls = "release"
            elif st["last_down"] is True:
                cls = ("repeat-fast" if gap is not None
                       and gap < self.expected_ms * 0.5 else "repeat")
            elif st["last_down"] is False and gap is not None and gap < threshold:
                cls = "chatter"
            else:
                cls = "press"

            self.counts[cls] += 1
            if cls == "press":
                st["presses"] += 1
            elif cls in ("repeat", "repeat-fast"):
                st["repeats"] += 1
            elif cls == "chatter":
                st["chatter"] += 1
            if down and st["last_down"] is False and gap is not None:
                if st["min_gap"] is None or gap < st["min_gap"]:
                    st["min_gap"] = gap

            st["last_t"] = t
            st["last_down"] = down

            if not only or cls in ANOMALIES:
                self._add_event(t, st["name"], vk, scan, down, gap, cls)

        self.events.scrollToBottom()
        self._refresh_summary()
        self._update_status()

    def _add_event(self, t, name, vk, scan, down, gap, cls):
        r = self.events.rowCount()
        if r >= MAX_ROWS:
            self.events.removeRow(0)
            r -= 1
        self.events.insertRow(r)
        cells = (str(self.seq), f"{t * 1000:.1f}", name, f"{vk:02X}",
                 f"{scan:02X}", "down" if down else "up",
                 "" if gap is None else f"{gap:.1f}", cls)
        for c, text in enumerate(cells):
            self.events.setItem(r, c, QTableWidgetItem(text))

    def _refresh_summary(self):
        ordered = sorted(self.keys.values(),
                         key=lambda s: (-s["chatter"], -s["repeats"], s["name"]))
        self.summary.setRowCount(len(ordered))
        for r, st in enumerate(ordered):
            cells = (st["name"], f"{st['vk']:02X}", f"{st['scan']:02X}",
                     str(st["presses"]), str(st["repeats"]), str(st["chatter"]),
                     "" if st["min_gap"] is None else f"{st['min_gap']:.1f}")
            for c, text in enumerate(cells):
                self.summary.setItem(r, c, QTableWidgetItem(text))

    def _update_status(self):
        c = self.counts
        worst = max(self.keys.values(), key=lambda s: s["chatter"],
                    default=None)
        bits = [
            "capturing" if self.hook.running() else "stopped",
            f"press {c['press']}",
            f"repeat {c['repeat'] + c['repeat-fast']}",
            f"chatter {c['chatter']}",
            f"injected {c['injected']}",
        ]
        if worst is not None and worst["chatter"]:
            bits.append(f"worst {worst['name']} {worst['chatter']}")
        self.status.setText("   ".join(bits))

    # ---- finder integration ----
    def search_entries(self, tab_name):
        return [
            (f"{tab_name}  ->  Start capture", self.btn_capture, self),
            (f"{tab_name}  ->  Chatter threshold", self.threshold, self),
            (f"{tab_name}  ->  Anomalies only", self.anomalies_only, self),
        ]

    def closeEvent(self, ev):
        self.hook.stop()
        super().closeEvent(ev)
