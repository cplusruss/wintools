#!/usr/bin/env python3
"""initcfg.py - the Initial Config tab: a per-step New PC checklist."""

import ctypes
import ctypes.wintypes as wt
import functools
import os
import uuid

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
import tweaks
import winclassic
from clean import recycle
from keydiag import style_grid

NEWPC_KEYS = (
    # Appearance
    "blackdesktop", "blacksignin", "visualfx", "noanimations",
    "mousemax", "screensaver", "desktopicons",
    # Always on
    "alwayson", "hibernate",
    # Taskbar
    "taskbarleft", "taskbarsearch", "taskview", "widgets", "chat",
    "stickers",
    # Start menu
    "startads", "bingsearch", "searchhighlights", "recommended",
    # Explorer
    "fileext", "openthispc", "syncads", "shortcutsuffix", "shortcutarrow",
    "storeopenwith", "classicmenu",
    # Telemetry / AI
    "telemetrysvc", "telemetrytasks", "enhanceprivacy", "cortana",
    "newsinterests", "copilot", "recall", "activityhistory",
    "inkpersonalization", "edgetelemetry", "edgediscover", "officetelemetry",
    "firefoxtelemetry", "chrometelemetry", "nvidiatelemetry", "vstelemetry",
    # Annoyances
    "lockscreenads", "scoobe", "windowstips", "suggestedcontent", "websearch",
    "logonanimation",
    # Classic
    "defenderep", "explorerpatcher", "openshell", "windhawk", "taskbartweaker",
    "classicappearance",
)

RECYCLE = "recycle"
RESTART = "restart"
ACTIONS = {RECYCLE: "Recycle Desktop Items", RESTART: "Restart Explorer"}
_after_icons = NEWPC_KEYS.index("desktopicons") + 1
STEPS = (*NEWPC_KEYS[:_after_icons], RECYCLE, *NEWPC_KEYS[_after_icons:],
         RESTART)

# same tints as wintools.TweakPage (importing it from here would be circular)
LIME = QColor(200, 240, 170)
PINK = QColor(255, 205, 213)
STATE_WORD = {True: "on", False: "off", None: "n/a"}
STATE_TINT = {True: LIME, False: PINK, None: None}

FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
FOLDERID_PUBLIC_DESKTOP = "{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        u = uuid.UUID(text)
        super().__init__(u.time_low, u.time_mid, u.time_hi_version,
                         (ctypes.c_ubyte * 8)(*u.bytes[8:]))


_shell32 = ctypes.WinDLL("shell32")
_shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT  # raises OSError on failure
_shell32.SHGetKnownFolderPath.argtypes = [
    ctypes.POINTER(GUID), wt.DWORD, wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_ole32 = ctypes.WinDLL("ole32")
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]


def known_folder(folder_id):
    out = ctypes.c_void_p()
    try:
        _shell32.SHGetKnownFolderPath(
            ctypes.byref(GUID(folder_id)), 0, None, ctypes.byref(out))
        return ctypes.wstring_at(out.value)
    finally:
        _ole32.CoTaskMemFree(out)


def desktop_dirs():
    return [known_folder(FOLDERID_DESKTOP),
            known_folder(FOLDERID_PUBLIC_DESKTOP)]


def desktop_items(dirs):
    return sorted(os.path.join(d, name) for d in dirs
                  for name in os.listdir(d) if name.lower() != "desktop.ini")


def _apply(tw):
    left = tw.apply(True)
    return f"{left} task(s) unchanged" if left else ""


def _recycle_step(paths):
    _recycled, failed = recycle(paths)
    return f"{len(failed)} not recycled: {failed[0][1]}" if failed else ""


class NewPcWorker(QThread):
    """steps: [(label, fn)]; fn returns "" or an error text, or raises OSError."""

    progress = pyqtSignal(int)

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.errors = []

    def run(self):
        for i, (label, fn) in enumerate(self.steps, 1):
            try:
                err = fn()
            except OSError as e:
                err = e.strerror or str(e)
            except Exception as e:  # one step's bug must not kill a half-applied run
                err = f"{type(e).__name__}: {e}"
            if err:
                self.errors.append(f"{label}: {err}")
            self.progress.emit(i)


class CaptureWorker(QThread):
    # result is the status line text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = ""

    def run(self):
        try:
            self.result = f"Captured {winclassic.capture()} components"
        except OSError as e:
            self.result = f"Capture failed: {e.strerror or e}"
        except Exception as e:  # a bug must show in the status line, not kill the thread
            self.result = f"Capture failed: {type(e).__name__}: {e}"


class InitConfigPage(QWidget):
    def __init__(self, report, refresh, restart_explorer, parent=None):
        super().__init__(parent)
        self._report = report
        self._refresh = refresh
        self._restart_explorer = restart_explorer
        self._worker = None
        self._capturer = None
        self._total = 0
        self._restart = False

        by_key = {t.key: t for t in (*tweaks.TWEAKS, *winclassic.STEPS)}
        self._steps = STEPS
        self._tweaks = {s: by_key[s] for s in STEPS if s not in ACTIONS}

        self.grid = style_grid(QTableWidget(len(STEPS), 3))
        self.grid.setHorizontalHeaderLabels(("Step", "Section", "State"))
        self.grid.horizontalHeader().setStretchLastSection(True)
        for r, step in enumerate(STEPS):
            tw = self._tweaks.get(step)
            first = QTableWidgetItem(tw.label if tw else ACTIONS[step])
            first.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                           | Qt.ItemIsUserCheckable)
            first.setCheckState(Qt.Checked)
            self.grid.setItem(r, 0, first)
            self.grid.setItem(r, 1, QTableWidgetItem(tw.section if tw else "Action"))
            self.grid.setItem(r, 2, QTableWidgetItem())

        self.btn = QPushButton("New PC")
        self.btn.clicked.connect(self._new_pc)
        self.btn_capture = QPushButton("Capture Classic")
        self.btn_capture.clicked.connect(self._capture)
        self.status = QLabel()
        # a long failure list must wrap, or it widens the whole window
        self.status.setWordWrap(True)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn)
        bottom.addWidget(self.btn_capture)
        bottom.addWidget(self.status, 1)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addWidget(self.grid, 1)
        v.addLayout(bottom)

        self.refresh_states()

    def refresh_states(self):
        winclassic.clear_cache()
        for r, step in enumerate(self._steps):
            tw = self._tweaks.get(step)
            tint = None
            if tw is not None:
                state = tw.state()
                text, tint = STATE_WORD[state], STATE_TINT[state]
            elif step == RECYCLE:
                n = len(desktop_items(desktop_dirs()))
                text = f"{n} item" + ("" if n == 1 else "s")
            else:
                text = ""
            self.grid.item(r, 2).setText(text)
            brush = QBrush(tint) if tint else QBrush()
            for c in range(3):
                self.grid.item(r, c).setBackground(brush)

    def checked_steps(self):
        return [s for r, s in enumerate(self._steps)
                if self.grid.item(r, 0).checkState() == Qt.Checked]

    def _set_busy(self, busy):
        self.btn.setEnabled(not busy)
        self.btn_capture.setEnabled(not busy)

    def _capture(self):
        try:
            man = winclassic.load_manifest()
            # older captures (e.g. the 2026-10-14 one) have no "computer" field
            where = ", ".join(filter(None, (man.get("computer"),
                                            f"{man['build']}.{man['ubr']}")))
            text = f"Replace the capture from {man['captured']} ({where})?"
        except (OSError, ValueError):  # no capture yet
            text = "Capture this PC's classic setup?"
        if QMessageBox.warning(self, "Capture Classic", text,
                               QMessageBox.Yes | QMessageBox.No,
                               QMessageBox.No) != QMessageBox.Yes:
            return
        self._set_busy(True)
        self.status.setText("Capturing")
        self._capturer = CaptureWorker(self)
        self._capturer.finished.connect(self._capture_done)
        self._capturer.start()

    def _capture_done(self):
        worker, self._capturer = self._capturer, None
        if worker is None:  # closed while the capture ran
            return
        self.status.setText(worker.result)
        self._report(worker.result)
        self.refresh_states()
        self._set_busy(False)

    def _new_pc(self):
        steps = self.checked_steps()
        if not steps:
            return
        listed = [self._tweaks[s].label for s in steps
                  if isinstance(self._tweaks.get(s), winclassic.Step)]
        if RESTART in steps:
            listed.append(ACTIONS[RESTART])
        text = f"Apply {len(steps)} steps to this PC?"
        if listed:
            text += "\n\n" + "\n".join(listed)
        if QMessageBox.warning(self, "New PC", text,
                               QMessageBox.Yes | QMessageBox.No,
                               QMessageBox.No) != QMessageBox.Yes:
            return
        paths = []
        if RECYCLE in steps:
            paths = desktop_items(desktop_dirs())
            if not paths or QMessageBox.question(
                    self, "New PC", f"Recycle {len(paths)} desktop items?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                steps.remove(RECYCLE)
        # a capture from another PC or another update fails the classic steps
        # unless confirmed here, for this run only
        winclassic.accept_mismatch(None)
        if any(isinstance(self._tweaks.get(s), winclassic.Step) for s in steps):
            try:
                reasons = winclassic.capture_mismatch()
            except (OSError, ValueError):  # the steps report a missing capture
                reasons = []
            if reasons and QMessageBox.question(
                    self, "New PC",
                    "The classic capture may not suit this PC:\n\n"
                    + "\n".join(reasons) + "\n\nApply it anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) == QMessageBox.Yes:
                winclassic.accept_mismatch(reasons)
        work = []
        for s in steps:
            if s == RECYCLE:
                work.append((ACTIONS[s], functools.partial(_recycle_step, paths)))
            elif s != RESTART:
                work.append((self._tweaks[s].label,
                             functools.partial(_apply, self._tweaks[s])))
        self._restart = RESTART in steps
        self._total = len(work) + self._restart
        if not self._total:
            return
        self._set_busy(True)
        self.status.setText(f"0 of {self._total}")
        self._worker = NewPcWorker(work, self)
        self._worker.progress.connect(self._progress)
        self._worker.finished.connect(self._finish)
        self._worker.start()

    def _progress(self, k):
        self.status.setText(f"{k} of {self._total}")

    def _finish(self):
        if self._worker is None:  # closed while the last step ran
            return
        winclassic.accept_mismatch(None)
        errors = list(self._worker.errors)
        # Explorer is the shell and this is its GUI thread's job, so it runs
        # only after the worker has stopped.
        if self._restart:
            try:
                self._restart_explorer()
            except OSError as e:
                errors.append(f"{ACTIONS[RESTART]}: {e.strerror or e}")
        text = "   ".join([f"{self._total - len(errors)} applied   "
                           f"{len(errors)} failed", *errors])
        self.status.setText(text)
        self._report(text)
        self._refresh()
        self._set_busy(False)

    def shutdown(self):
        worker, self._worker = self._worker, None
        if worker is not None and worker.isRunning():
            worker.progress.disconnect(self._progress)
            worker.finished.disconnect(self._finish)
            worker.wait()
        winclassic.accept_mismatch(None)
        capturer, self._capturer = self._capturer, None
        if capturer is not None and capturer.isRunning():
            capturer.finished.disconnect(self._capture_done)
            capturer.wait()
