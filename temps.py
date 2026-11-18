#!/usr/bin/env python3
"""temps.py - live temperature readings for wintools: GPUs through nvidia-smi,
drives through the storage temperature IOCTL."""

import ctypes
import ctypes.wintypes as wt
import shutil

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import gpu
from keydiag import style_grid

COLS = ("Device", "Sensor", "°C", "Min °C", "Max °C", "Source")
POLL_MS = 2000
MAX_DRIVES = 32

IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
STORAGE_DEVICE_PROPERTY = 0
STORAGE_DEVICE_TEMPERATURE_PROPERTY = 52
ERROR_FILE_NOT_FOUND = 2
# The drive answers but carries no temperature sensor (card readers, some
# USB bridges): invalid function, not supported, invalid parameter.
NO_SENSOR = (1, 50, 87)

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wt.HANDLE
_k32.CreateFileW.argtypes = [
    wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD,
    wt.HANDLE,
]
_k32.DeviceIoControl.restype = wt.BOOL
_k32.DeviceIoControl.argtypes = [
    wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
    wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
]
_k32.CloseHandle.argtypes = [wt.HANDLE]
INVALID_HANDLE = wt.HANDLE(-1).value


def _winerror(what):
    err = ctypes.get_last_error()
    return OSError(0, ctypes.FormatError(err).strip(), what, err)


def _query(h, prop, what):
    inb = (ctypes.c_uint32 * 3)(prop, 0, 0)
    out = ctypes.create_string_buffer(4096)
    got = wt.DWORD()
    if not _k32.DeviceIoControl(h, IOCTL_STORAGE_QUERY_PROPERTY, inb,
                                ctypes.sizeof(inb), out, len(out),
                                ctypes.byref(got), None):
        raise _winerror(what)
    return out.raw[:got.value]


def _u(buf, off, n, signed=False):
    return int.from_bytes(buf[off:off + n], "little", signed=signed)


def _cstr(buf, off):
    if not off:
        return ""
    return buf[off:buf.index(b"\0", off)].decode("ascii", "replace").strip()


def parse_device_name(buf):
    """STORAGE_DEVICE_DESCRIPTOR -> 'vendor product'."""
    vendor, product = _cstr(buf, _u(buf, 12, 4)), _cstr(buf, _u(buf, 16, 4))
    return " ".join(s for s in (vendor, product) if s)


def parse_temperatures(buf):
    """STORAGE_TEMPERATURE_DATA_DESCRIPTOR -> [(index, deg C)]."""
    return [(_u(buf, 24 + 16 * i, 2), _u(buf, 26 + 16 * i, 2, signed=True))
            for i in range(_u(buf, 12, 2))]


def drive_temps():
    rows = []
    for n in range(MAX_DRIVES):
        what = rf"\\.\PhysicalDrive{n}"
        # zero access: the property queries need no read rights or elevation
        h = _k32.CreateFileW(what, 0, 3, None, 3, 0, None)
        if h == INVALID_HANDLE:
            if ctypes.get_last_error() == ERROR_FILE_NOT_FOUND:
                continue
            raise _winerror(what)
        try:
            name = parse_device_name(_query(h, STORAGE_DEVICE_PROPERTY, what))
            try:
                temps = parse_temperatures(
                    _query(h, STORAGE_DEVICE_TEMPERATURE_PROPERTY, what))
            except OSError as e:
                if e.winerror in NO_SENSOR:
                    continue
                raise
        finally:
            _k32.CloseHandle(h)
        for idx, deg in temps:
            sensor = "Drive" if len(temps) == 1 else f"Sensor {idx}"
            rows.append((f"Disk {n}  {name}", sensor, float(deg), "drive"))
    return rows


def gpu_temps():
    if shutil.which(gpu.SMI) is None:
        return []
    rows = []
    out = gpu.run(["--query-gpu=index,name,temperature.gpu",
                   "--format=csv,noheader,nounits"])
    for line in out.strip().splitlines():
        idx, name, deg = (f.strip() for f in line.split(","))
        rows.append((f"GPU {idx}  {name}", "Core", float(deg), "nvidia-smi"))
    return rows


SOURCES = (("nvidia-smi", gpu_temps), ("drive", drive_temps))


def read_all():
    """-> ([(device, sensor, deg C, source)], [error strings])"""
    rows, errors = [], []
    for name, fn in SOURCES:
        try:
            rows.extend(fn())
        except (OSError, ValueError) as e:
            errors.append(f"{name}: {e}")
    return rows, errors


class TempWorker(QThread):
    done = pyqtSignal(list, list)

    def run(self):
        self.done.emit(*read_all())


class TempsPage(QWidget):
    """Polls every source while the tab is visible; min / max are per session."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = style_grid(QTableWidget(0, len(COLS)))
        self.grid.setHorizontalHeaderLabels(COLS)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.status = QLabel()
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addWidget(self.grid, 1)
        v.addWidget(self.status)

        self._rows = {}
        self._minmax = {}
        self._worker = TempWorker(self)
        self._worker.done.connect(self._show)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)

    def poll(self):
        if not self._worker.isRunning():
            self._worker.start()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.poll()
        self._timer.start()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._timer.stop()

    def shutdown(self):
        self._timer.stop()
        self._worker.wait()

    def _show(self, rows, errors):
        keys = [(dev, sensor, src) for dev, sensor, _deg, src in rows]
        if keys != list(self._rows):
            self.grid.setRowCount(len(keys))
            self._rows = {k: i for i, k in enumerate(keys)}
            for i, (dev, sensor, src) in enumerate(keys):
                for c, text in ((0, dev), (1, sensor), (5, src)):
                    self.grid.setItem(i, c, QTableWidgetItem(text))
        for dev, sensor, deg, src in rows:
            key = (dev, sensor, src)
            lo, hi = self._minmax.get(key, (deg, deg))
            self._minmax[key] = lo, hi = min(lo, deg), max(hi, deg)
            for c, val in ((2, deg), (3, lo), (4, hi)):
                item = QTableWidgetItem(f"{val:.1f}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.grid.setItem(self._rows[key], c, item)
        self.status.setText("   ".join([f"{len(rows)} sensors", *errors]))
