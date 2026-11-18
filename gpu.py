#!/usr/bin/env python3
"""gpu.py - NVIDIA GPU settings through nvidia-smi for wintools."""

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from io import BytesIO

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

import tweaks

SMI = "nvidia-smi"
TASK_NAME = "wintools GPU settings"
PROFILE_DIR = os.path.join(os.environ["ProgramData"], "wintools")
PROFILE_PATH = os.path.join(PROFILE_DIR, "gpu.xml")
BOOT_CMD = os.path.join(PROFILE_DIR, "gpu-boot.cmd")

COMPUTE_MODES = {"Default": 0, "Prohibited": 2, "Exclusive_Process": 3}
DRIVER_MODELS = {"WDDM": 0, "TCC": 1, "MCDM": 2}

LIVE_FIELDS = ("pci.bus_id", "temperature.gpu", "power.draw", "clocks.gr",
               "clocks.mem", "fan.speed", "pstate",
               "clocks_event_reasons.active")

# clocks_event_reasons.active bitmask
REASONS = (
    (0x001, "idle"), (0x002, "app clocks"), (0x004, "power cap"),
    (0x008, "HW slowdown"), (0x010, "sync boost"), (0x020, "thermal"),
    (0x040, "HW thermal"), (0x080, "power brake"), (0x100, "display clocks"),
)


class SmiError(OSError):
    pass


def run(args):
    r = subprocess.run([SMI, *args], capture_output=True, text=True,
                       creationflags=tweaks.CREATE_NO_WINDOW, check=False)
    if r.returncode:
        raise SmiError((r.stdout + r.stderr).strip() or f"exit {r.returncode}")
    return r.stdout


def _num(text):
    # Laptop/mobile GPUs report locked controls (power, target temp) as N/A.
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        raise SmiError(f"GPU settings not supported here "
                       f"(nvidia-smi reports {text!r})") from None


def _text(gpu, path):
    el = gpu.find(path)
    if el is None or el.text is None:
        raise SmiError(f"nvidia-smi XML missing {path}")
    return el.text.strip()


def parse_gpus(xml_text):
    """nvidia-smi -q -x output -> list of setting dicts, in index order."""
    out = []
    for i, g in enumerate(ET.fromstring(xml_text).findall("gpu")):
        sup = g.find("supported_clocks")
        mem = sorted({int(_num(e.find("value").text))
                      for e in sup.findall("supported_mem_clock")})
        gr = sorted({int(_num(e.text))
                     for e in sup.iter("supported_graphics_clock")})
        pw = "gpu_power_readings/"
        out.append({
            "index": i,
            "bus": g.get("id"),
            "name": _text(g, "product_name"),
            "power_limit": int(_num(_text(g, pw + "requested_power_limit"))),
            "power_default": int(_num(_text(g, pw + "default_power_limit"))),
            "power_min": int(_num(_text(g, pw + "min_power_limit"))),
            "power_max": int(_num(_text(g, pw + "max_power_limit"))),
            "target_temp": int(_num(_text(
                g, "temperature/gpu_target_temperature"))),
            "target_min": int(_num(_text(
                g, "supported_gpu_target_temp/gpu_target_temp_min"))),
            "target_max": int(_num(_text(
                g, "supported_gpu_target_temp/gpu_target_temp_max"))),
            "compute_mode": _text(g, "compute_mode"),
            "accounting": _text(g, "accounting_mode") == "Enabled",
            "dm_current": _text(g, "driver_model/current_dm"),
            "dm_pending": _text(g, "driver_model/pending_dm"),
            "mem_clocks": mem,
            "gpu_clocks": gr,
        })
    return out


def read_gpus():
    return parse_gpus(run(["-q", "-x"]))


def reasons_text(mask):
    return ", ".join(name for bit, name in REASONS if mask & bit)


def read_live():
    """{bus_id: readout string} from one lightweight query."""
    csv = run([f"--query-gpu={','.join(LIVE_FIELDS)}",
               "--format=csv,noheader,nounits"])
    out = {}
    for line in csv.strip().splitlines():
        bus, temp, draw, gr, mem, fan, pstate, mask = \
            [f.strip() for f in line.split(",")]
        out[bus] = (f"{temp} °C   {float(draw):.0f} W   {gr} / {mem} MHz   "
                    f"fan {fan} %   {pstate}   {reasons_text(int(mask, 16))}")
    return out


# --------------------------------------------------------------------
#  profile: the settings wintools writes, per GPU (keyed by PCI bus id)
# --------------------------------------------------------------------

def profile_commands(p):
    """Profile dict -> list of nvidia-smi arg lists, in apply order.
    target_temp None leaves it alone; a lock of None resets it."""
    i = ["-i", p["bus"]]
    cmds = [i + ["-pl", str(p["power_limit"])]]
    if p["target_temp"] is not None:
        cmds.append(i + ["-gtt", str(p["target_temp"])])
    cmds.append(i + ["-lgc", "%d,%d" % p["gpu_lock"]] if p["gpu_lock"]
                else i + ["-rgc"])
    cmds.append(i + ["-lmc", "%d,%d" % p["mem_lock"]] if p["mem_lock"]
                else i + ["-rmc"])
    cmds.append(i + ["-cc", "1" if p["cuda_clocks"] else "0"])
    cmds.append(i + ["-c", str(COMPUTE_MODES[p["compute_mode"]])])
    cmds.append(i + ["-am", "1" if p["accounting"] else "0"])
    return cmds


def apply_profile(p):
    """Run every command; returns [(switch, error text), ...] for failures."""
    failed = []
    for args in profile_commands(p):
        try:
            run(args)
        except SmiError as e:
            failed.append((args[2], str(e).splitlines()[0]))
    return failed


def _pair(v):
    return "%d,%d" % v if v else ""


def _unpair(s):
    return tuple(int(x) for x in s.split(",")) if s else None


def profile_element(p):
    return ET.Element("gpu", {
        "bus": p["bus"],
        "power_limit": str(p["power_limit"]),
        "target_temp": "" if p["target_temp"] is None else str(p["target_temp"]),
        "gpu_lock": _pair(p["gpu_lock"]),
        "mem_lock": _pair(p["mem_lock"]),
        "cuda_clocks": "1" if p["cuda_clocks"] else "0",
        "compute_mode": p["compute_mode"],
        "accounting": "1" if p["accounting"] else "0",
    })


def profiles_from_root(root):
    out = []
    for el in root.findall("gpu"):
        t = el.get("target_temp")
        out.append({
            "bus": el.get("bus"),
            "power_limit": int(el.get("power_limit")),
            "target_temp": int(t) if t else None,
            "gpu_lock": _unpair(el.get("gpu_lock")),
            "mem_lock": _unpair(el.get("mem_lock")),
            "cuda_clocks": el.get("cuda_clocks") == "1",
            "compute_mode": el.get("compute_mode"),
            "accounting": el.get("accounting") == "1",
        })
    return out


def save_profiles(profiles):
    root = ET.Element("wintools-gpu", version="1")
    root.extend(profile_element(p) for p in profiles)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    buf = BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(PROFILE_PATH, "wb") as f:
        f.write(buf.getvalue())


def load_profiles():
    """{bus: profile} from the saved file; empty before the first Apply."""
    if not os.path.exists(PROFILE_PATH):
        return {}
    return {p["bus"]: p for p in profiles_from_root(ET.parse(PROFILE_PATH).getroot())}


# --------------------------------------------------------------------
#  apply at boot: SYSTEM task running a generated .cmd
# --------------------------------------------------------------------

def boot_script(profiles, smi_path):
    lines = ["@echo off"]
    for p in profiles:
        for args in profile_commands(p):
            lines.append(subprocess.list2cmdline([smi_path, *args]))
    return "\r\n".join(lines) + "\r\n"


def write_boot_script(profiles):
    smi = shutil.which(SMI)
    if smi is None:
        raise SmiError("nvidia-smi not found")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with open(BOOT_CMD, "w", encoding="ascii", newline="") as f:
        f.write(boot_script(profiles, smi))


def boot_enabled():
    return tweaks._schtasks(["/Query", "/TN", TASK_NAME]).returncode == 0


def enable_boot(profiles):
    write_boot_script(profiles)
    r = tweaks._schtasks([
        "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONSTART",
        "/DELAY", "0000:30", "/RU", "SYSTEM", "/RL", "HIGHEST",
        "/TR", f'cmd.exe /c "{BOOT_CMD}"'])
    if r.returncode:
        raise OSError((r.stdout + r.stderr).strip())


def disable_boot():
    r = tweaks._schtasks(["/Delete", "/F", "/TN", TASK_NAME])
    if r.returncode:
        raise OSError((r.stdout + r.stderr).strip())


# --------------------------------------------------------------------
#  page
# --------------------------------------------------------------------

class GpuBox(QGroupBox):
    def __init__(self, gpu, apply_cb, dm_cb):
        super().__init__(f"GPU {gpu['index']}   {gpu['name']}   {gpu['bus'][-7:]}")
        self.bus = gpu["bus"]
        grid = QGridLayout(self)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)

        self.power = QSpinBox()
        self.power.setRange(gpu["power_min"], gpu["power_max"])
        self.power_lbl = QLabel(
            f"{gpu['power_default']} W default   "
            f"{gpu['power_min']}–{gpu['power_max']} W")

        self.temp_on = QCheckBox("Target temp")
        self.temp = QSpinBox()
        self.temp.setRange(gpu["target_min"], gpu["target_max"])
        self.temp_lbl = QLabel()

        g_lo, g_hi = gpu["gpu_clocks"][0], gpu["gpu_clocks"][-1]
        self.glock_on = QCheckBox("GPU clock lock")
        self.glock_lo, self.glock_hi = QSpinBox(), QSpinBox()
        for s in (self.glock_lo, self.glock_hi):
            s.setRange(g_lo, g_hi)
            s.setSingleStep(15)
        self.glock_lo.setValue(g_lo)
        self.glock_hi.setValue(g_hi)

        self.mlock_on = QCheckBox("Mem clock lock")
        self.mlock_lo, self.mlock_hi = QComboBox(), QComboBox()
        for c in (self.mlock_lo, self.mlock_hi):
            c.addItems([str(m) for m in gpu["mem_clocks"]])
        self.mlock_hi.setCurrentIndex(self.mlock_hi.count() - 1)

        self.cuda = QCheckBox("CUDA clock override")
        self.compute = QComboBox()
        self.compute.addItems(list(COMPUTE_MODES))
        self.accounting = QCheckBox("Accounting")

        self.dm = QComboBox()
        self.dm.addItems(list(DRIVER_MODELS))
        self.dm_btn = QPushButton("Set")
        self.dm_btn.clicked.connect(lambda: dm_cb(self))
        self.dm_lbl = QLabel()

        r = 0
        grid.addWidget(QLabel("Power limit"), r, 0)
        grid.addWidget(self.power, r, 1)
        grid.addWidget(QLabel("W"), r, 2)
        grid.addWidget(self.power_lbl, r, 3, 1, 2)
        r += 1
        grid.addWidget(self.temp_on, r, 0)
        grid.addWidget(self.temp, r, 1)
        grid.addWidget(QLabel("°C"), r, 2)
        grid.addWidget(self.temp_lbl, r, 3, 1, 2)
        r += 1
        grid.addWidget(self.glock_on, r, 0)
        grid.addWidget(self.glock_lo, r, 1)
        grid.addWidget(QLabel("–"), r, 2)
        grid.addWidget(self.glock_hi, r, 3)
        grid.addWidget(QLabel("MHz"), r, 4)
        r += 1
        grid.addWidget(self.mlock_on, r, 0)
        grid.addWidget(self.mlock_lo, r, 1)
        grid.addWidget(QLabel("–"), r, 2)
        grid.addWidget(self.mlock_hi, r, 3)
        grid.addWidget(QLabel("MHz"), r, 4)
        r += 1
        grid.addWidget(self.cuda, r, 0, 1, 2)
        r += 1
        grid.addWidget(QLabel("Compute mode"), r, 0)
        grid.addWidget(self.compute, r, 1, 1, 3)
        r += 1
        grid.addWidget(self.accounting, r, 0, 1, 2)
        r += 1
        grid.addWidget(QLabel("Driver model"), r, 0)
        grid.addWidget(self.dm, r, 1)
        grid.addWidget(self.dm_btn, r, 3)
        grid.addWidget(self.dm_lbl, r, 4)
        r += 1
        self.live = QLabel()
        grid.addWidget(self.live, r, 0, 1, 5)
        r += 1
        btn = QPushButton("Apply")
        btn.clicked.connect(lambda: apply_cb([self]))
        grid.addWidget(btn, r, 0)
        grid.setColumnStretch(5, 1)
        grid.setRowStretch(r + 1, 1)

    def load(self, gpu, saved):
        """Live values where nvidia-smi reports them; clock locks and the
        CUDA override are write-only, so they come from the saved profile."""
        self.power.setValue(gpu["power_limit"])
        self.temp.setValue(gpu["target_temp"])
        self.temp_lbl.setText(f"{gpu['target_temp']} °C")
        self.compute.setCurrentText(gpu["compute_mode"])
        self.accounting.setChecked(gpu["accounting"])
        self.dm.setCurrentText(gpu["dm_pending"])
        self.dm_lbl.setText(gpu["dm_current"] if gpu["dm_current"] == gpu["dm_pending"]
                            else f"{gpu['dm_current']} -> {gpu['dm_pending']} at reboot")
        if saved is not None:
            self._set_saved(saved)

    def set_profile(self, p):
        """Put an imported profile into the controls."""
        self.power.setValue(p["power_limit"])
        if p["target_temp"] is not None:
            self.temp.setValue(p["target_temp"])
        self.compute.setCurrentText(p["compute_mode"])
        self.accounting.setChecked(p["accounting"])
        self._set_saved(p)

    def _set_saved(self, p):
        self.temp_on.setChecked(p["target_temp"] is not None)
        self.glock_on.setChecked(p["gpu_lock"] is not None)
        if p["gpu_lock"]:
            self.glock_lo.setValue(p["gpu_lock"][0])
            self.glock_hi.setValue(p["gpu_lock"][1])
        self.mlock_on.setChecked(p["mem_lock"] is not None)
        if p["mem_lock"]:
            self.mlock_lo.setCurrentText(str(p["mem_lock"][0]))
            self.mlock_hi.setCurrentText(str(p["mem_lock"][1]))
        self.cuda.setChecked(p["cuda_clocks"])

    def profile(self):
        return {
            "bus": self.bus,
            "power_limit": self.power.value(),
            "target_temp": self.temp.value() if self.temp_on.isChecked() else None,
            "gpu_lock": ((self.glock_lo.value(), self.glock_hi.value())
                         if self.glock_on.isChecked() else None),
            "mem_lock": ((int(self.mlock_lo.currentText()),
                          int(self.mlock_hi.currentText()))
                         if self.mlock_on.isChecked() else None),
            "cuda_clocks": self.cuda.isChecked(),
            "compute_mode": self.compute.currentText(),
            "accounting": self.accounting.isChecked(),
        }


class GpuPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.boxes = []
        page = QVBoxLayout(self)
        page.setContentsMargins(6, 6, 6, 6)
        page.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(4)
        b = QPushButton("Refresh")
        b.clicked.connect(self.refresh)
        top.addWidget(b)
        b = QPushButton("Apply all")
        b.clicked.connect(lambda: self._apply(self.boxes))
        top.addWidget(b)
        self.boot = QCheckBox("Apply at boot")
        self.boot.clicked.connect(self._toggle_boot)
        top.addWidget(self.boot)
        b = QPushButton("Restart driver")
        b.clicked.connect(self._restart_driver)
        top.addWidget(b)
        top.addStretch(1)
        page.addLayout(top)

        self.row = QHBoxLayout()
        self.row.setSpacing(6)
        page.addLayout(self.row)
        self.status = QLabel()
        page.addWidget(self.status)
        page.addStretch(1)

        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build(self):
        try:
            gpus = read_gpus()
        except (OSError, ET.ParseError) as e:
            self.status.setText(str(e))
            return
        for g in gpus:
            box = GpuBox(g, self._apply, self._set_driver_model)
            self.row.addWidget(box)
            self.boxes.append(box)
        self.row.addStretch(1)
        self._load(gpus)

    def _load(self, gpus):
        saved = load_profiles()
        for box, g in zip(self.boxes, gpus):
            box.load(g, saved.get(g["bus"]))
        self._sync_boot()
        self._tick()

    def _sync_boot(self):
        self.boot.setChecked(boot_enabled())

    def refresh(self):
        if not self.boxes:
            return
        try:
            self._load(read_gpus())
        except (OSError, ET.ParseError) as e:
            self.status.setText(str(e))
            return
        self.status.setText("")

    def showEvent(self, ev):
        super().showEvent(ev)
        self._tick()

    def _tick(self):
        if not self.boxes or not self.isVisible():
            return
        try:
            live = read_live()
        except OSError as e:
            self.status.setText(str(e))
            return
        for box in self.boxes:
            box.live.setText(live.get(box.bus, ""))

    def profiles(self):
        return [b.profile() for b in self.boxes]

    def _save(self):
        save_profiles(self.profiles())
        if boot_enabled():
            write_boot_script(self.profiles())

    def _apply(self, boxes):
        msgs = []
        for box in boxes:
            failed = apply_profile(box.profile())
            head = box.title().split("   ")[0]
            msgs.append(f"{head}: " + ("ok" if not failed else "   ".join(
                f"{sw} {err}" for sw, err in failed)))
        try:
            self._save()
        except OSError as e:
            msgs.append(f"save: {e}")
        self.refresh()
        self.status.setText("   |   ".join(msgs))

    def apply_profiles(self, profiles):
        """Import path: load matching profiles into the UI, then apply.
        Returns (applied, skipped)."""
        by_bus = {b.bus: b for b in self.boxes}
        hit = []
        for p in profiles:
            box = by_bus.get(p["bus"])
            if box is not None:
                box.set_profile(p)
                hit.append(box)
        if hit:
            self._apply(hit)
        return len(hit), len(profiles) - len(hit)

    def _toggle_boot(self, on):
        try:
            if on:
                save_profiles(self.profiles())
                enable_boot(self.profiles())
            else:
                disable_boot()
        except OSError as e:
            self.status.setText(f"Apply at boot: {e}")
        else:
            self.status.setText(f"Apply at boot: {'on' if on else 'off'}")
        self._sync_boot()

    def _set_driver_model(self, box):
        dm = box.dm.currentText()
        try:
            run(["-i", box.bus, "-dm", str(DRIVER_MODELS[dm])])
        except SmiError as e:
            self.status.setText(f"Driver model: {str(e).splitlines()[0]}")
            return
        self.refresh()
        self.status.setText(f"Driver model {dm}: pending reboot")

    def _restart_driver(self):
        if QMessageBox.question(
                self, "Restart driver",
                "Restart the NVIDIA display driver?") != QMessageBox.Yes:
            return
        try:
            run(["-r"])
        except SmiError as e:
            self.status.setText(f"Restart driver: {str(e).splitlines()[0]}")
            return
        self.refresh()
        self.status.setText("Driver restarted")

    def search_entries(self, tab_name):
        out = []
        for b in self.boxes:
            head = f"{tab_name}  ->  {b.title().split('   ')[0]}"
            out += [
                (f"{head}  ->  Power limit", b.power, self),
                (f"{head}  ->  Target temp", b.temp, self),
                (f"{head}  ->  GPU clock lock", b.glock_lo, self),
                (f"{head}  ->  Mem clock lock", b.mlock_lo, self),
                (f"{head}  ->  CUDA clock override", b.cuda, self),
                (f"{head}  ->  Compute mode", b.compute, self),
                (f"{head}  ->  Accounting", b.accounting, self),
                (f"{head}  ->  Driver model", b.dm, self),
            ]
        return out
