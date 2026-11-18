#!/usr/bin/env python3
"""hardware.py - the Hardware tab for wintools: a CPU-Z replica (CPU, Caches,
Mainboard, Memory, SPD, Graphics, About) built from what Windows exposes
without a driver, plus the Sensors page and a live Clocks window.

A data source that should work and does not replaces only the group box it
feeds with `<source>: <error>`.  A structure or device that does not exist, and
a field no source covers, is an empty box."""

import functools
import re
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QMenu, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

import cpudb
import hwinfo
import smbios
import temps
from keydiag import style_grid

CLOCK_MS = 1000
SPD_TABLE_ROWS = ("Frequency", "CAS# Latency", "RAS# to CAS#", "RAS# Precharge", "tRAS",
                  "tRC", "Command Rate", "Voltage")
SPD_PROFILES = 4
CHANNEL_RE = re.compile(r"(?:CONTROLLER\s*(\d+)[-\s]*)?CHANNEL\s*([A-Z0-9]+)", re.I)
CPU_LOGOS = {"AuthenticAMD": "AMD", "GenuineIntel": "Intel"}
GPU_LOGOS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}
GRAY = QColor(128, 128, 128)
NAVY = QColor(0, 0, 128)
# CPU-Z centers its value boxes except these text fields
LEFT_ALIGNED = frozenset({"manufacturer", "model", "bus_specs", "bios_brand", "bios_version",
                          "bios_date", "part", "serial", "instructions"})


class SourceError(Exception):
    # Message form `<source>: <error>`; shown in place of the group box it feeds.

    def __init__(self, source, err):
        super().__init__(f"{source}: {err}")


def _call(source, fn, *args):
    try:
        return fn(*args)
    except (OSError, ValueError) as e:
        raise SourceError(source, e) from e


def _get(ctx, source, attr):
    try:
        return getattr(ctx, attr)
    except (OSError, ValueError) as e:
        raise SourceError(source, e) from e


class Context:
    # The heavy readers: each runs once, and only when a sub-tab asks.

    @functools.cached_property
    def identity(self):
        return hwinfo.identity()

    @functools.cached_property
    def topology(self):
        return hwinfo.topology()

    @functools.cached_property
    def smbios(self):
        return smbios.load()

    @functools.cached_property
    def pci(self):
        return hwinfo.pci_devices()

    @functools.cached_property
    def adapters(self):
        return hwinfo.dxgi_adapters()

    @functools.cached_property
    def nvidia(self):
        return hwinfo.nvidia_infos()


def _gbytes(mb):
    return f"{mb // 1024} GBytes" if mb % 1024 == 0 else f"{mb} MBytes"


def _val1(value, unit):
    return "" if value is None else f"{value:.1f} {unit}"


def _cpu_info(ctx):
    ident = _get(ctx, "CPUID", "identity")
    return cpudb.lookup(ident.vendor, ident.ext_family, ident.ext_model, ident.stepping,
                        ident.brand)


# ====================================================================
#  COLLECTORS: one dict of field id -> text per group box
# ====================================================================

CACHE_LEVELS = (("l1d", 1, "data"), ("l1i", 1, "instruction"),
                ("l2", 2, "unified"), ("l3", 3, "unified"))


def _cache(topo, level, kind):
    if not any(c.level == level and c.kind == kind for c in topo.caches):
        return None
    return _call("Topology", hwinfo.cache_info, topo, level, kind)


def cpu_processor(ctx):
    ident = _get(ctx, "CPUID", "identity")
    info = _cpu_info(ctx)
    if info is not None and info.package:
        package = info.package
    else:
        sockets = _call("SMBIOS", smbios.processors, _get(ctx, "SMBIOS", "smbios"))
        package = sockets[0].socket if sockets else ""
    return {
        "name": info.name if info else "", "code_name": info.code_name if info else "",
        "tdp": info.tdp if info else "", "package": package,
        "technology": info.technology if info else "", "vid": "",
        "spec": ident.brand, "family": hwinfo.hex_id(ident.family),
        "model": hwinfo.hex_id(ident.model), "stepping": hwinfo.hex_id(ident.stepping),
        "ext_family": hwinfo.hex_id(ident.ext_family),
        "ext_model": hwinfo.hex_id(ident.ext_model),
        "revision": info.revision if info else "",
        "instructions": _call("CPUID", hwinfo.instructions),
    }


def cpu_clocks(_ctx):
    return dict.fromkeys(("core_speed", "multiplier", "bus_speed", "rated_fsb"), "")


def cpu_cache(ctx):
    topo = _get(ctx, "Topology", "topology")
    out = {}
    for key, level, kind in CACHE_LEVELS:
        cache = _cache(topo, level, kind)
        out[key] = cache.summary if cache else ""
        out[f"{key}_ways"] = cache.ways if cache else ""
    return out


def cache_fields(ctx, key):
    level, kind = next((lv, kd) for k, lv, kd in CACHE_LEVELS if k == key)
    cache = _cache(_get(ctx, "Topology", "topology"), level, kind)
    return {f"{key}_size": cache.size if cache else "",
            f"{key}_descriptor": cache.descriptor if cache else "",
            f"{key}_count": cache.summary if cache else ""}


def mainboard_board(ctx):
    board = _call("SMBIOS", smbios.baseboard, _get(ctx, "SMBIOS", "smbios"))
    devs = _get(ctx, "PCI", "pci")
    model = board.product if board else ""
    gen = hwinfo.max_root_port_speed(devs)
    if gen is None:
        info = _cpu_info(ctx)
        gen = info.pcie_gen if info else None
    out = {
        "manufacturer": board.manufacturer if board else "", "model": model,
        "model_rev": board.version if board else "",
        "bus_specs": hwinfo.pcie_bus_text(gen, rate=True) if gen else "",
        "lpcio_vendor": "", "lpcio": "",
    }
    for prefix, bridge in (("chipset", hwinfo.host_bridge(devs)),
                           ("southbridge", hwinfo.isa_bridge(devs))):
        if bridge is None:
            vendor, name, rev = "", "", ""
        else:
            vendor, name = cpudb.chipset(bridge.vendor, bridge.device, model)
            rev = f"{bridge.revision:02X}"
        out.update({f"{prefix}_vendor": vendor, prefix: name, f"{prefix}_rev": rev})
    return out


def mainboard_bios(ctx):
    tbl = _get(ctx, "SMBIOS", "smbios")
    bios = _call("SMBIOS", smbios.bios, tbl)
    agesa = _call("SMBIOS", smbios.agesa, tbl)
    version = bios.version if bios else ""
    if agesa:
        version = f"{version} - AMD AGESA {agesa}" if version else f"AMD AGESA {agesa}"
    return {"bios_brand": bios.vendor if bios else "", "bios_version": version,
            "bios_date": bios.date if bios else "",
            "microcode": _call("Registry", hwinfo.microcode)}


def mainboard_gi(ctx):
    out = dict.fromkeys(("gi_bus", "gi_width", "gi_width_max", "gi_speed", "gi_speed_max"), "")
    adapters = _get(ctx, "DXGI", "adapters")
    primary = next((a for a in adapters if a.primary), adapters[0] if adapters else None)
    if primary is None:
        return out
    if primary.error:
        raise SourceError("DXGI", primary.error)
    link = hwinfo.pci_device_at(_get(ctx, "PCI", "pci"), primary.bus, primary.device_number,
                                primary.function)
    if link is None:
        return out
    if link.max_speed:
        out["gi_bus"] = hwinfo.pcie_bus_text(link.max_speed)
        out["gi_speed_max"] = hwinfo.link_speed_text(link.max_speed)
    if link.current_speed:
        out["gi_speed"] = hwinfo.link_speed_text(link.current_speed)
    if link.max_width:
        out["gi_width_max"] = hwinfo.link_width_text(link.max_width)
    if link.current_width:
        out["gi_width"] = hwinfo.link_width_text(link.current_width)
    return out


def _channels(populated):
    # None when a populated slot's locators name no channel.
    found = set()
    for d in populated:
        m = CHANNEL_RE.search(d.bank_locator) or CHANNEL_RE.search(d.device_locator)
        if m is None:
            return None
        found.add((m[1] or "", m[2].upper()))
    return len(found)


def _populated(ctx):
    devices = _call("SMBIOS", smbios.memory_devices, _get(ctx, "SMBIOS", "smbios"))
    return [d for d in devices if d.present]


def memory_general(ctx):
    populated = _populated(ctx)
    types = sorted({d.memory_type for d in populated if d.memory_type})
    channels = _channels(populated) if populated else None
    if channels is None or len(types) != 1 or any(not d.memory_type for d in populated):
        channel_text = ""
    elif types == ["DDR5"]:
        channel_text = f"{channels} x 32-bit"
    else:
        channel_text = f"{channels} x 64-bit"
    # a module of unknown size makes the total unknown
    known = populated and all(d.size_mb is not None for d in populated)
    return {"type": "/".join(types), "channels": channel_text,
            "size": _gbytes(sum(d.size_mb for d in populated)) if known else "",
            "dc_mode": "", "uncore": ""}


def memory_timings(ctx):
    populated = _populated(ctx)
    speed = populated[0].configured_speed if populated else None
    out = dict.fromkeys(("fsb_dram", "cl", "trcd", "trp", "tras", "trc", "cr", "idle_timer",
                         "trdram", "row_to_col"), "")
    out["dram_freq"] = _val1(speed / 2, "MHz") if speed else ""
    return out


SPD_KEYS = ("type", "size", "bandwidth", "spd_ext", "manufacturer", "week_year", "dram_manuf",
            "buffered", "part", "correction", "serial", "registered")


def spd_fields(device):
    out = dict.fromkeys(SPD_KEYS, "")
    if device is None or not device.present:
        return out
    if device.memory_type:
        out["type"] = (f"{device.memory_type} ({device.module_kind})" if device.module_kind
                       else device.memory_type)
        if device.speed:
            out["bandwidth"] = (f"{device.memory_type}-{device.speed} "
                                f"({device.speed / 2:g} MHz)")
    if device.size_mb is not None:
        out["size"] = _gbytes(device.size_mb)
    out.update(manufacturer=cpudb.jedec_name(device.manufacturer), part=device.part_number,
               buffered="Yes" if device.buffered else "",
               registered="Yes" if device.registered else "")
    if device.serial.strip("0 "):          # firmware fills unserialised modules with zeros
        out["serial"] = device.serial
    return out


GRAPHICS_KEYS = ("name", "board_manuf", "code_name", "revision", "technology", "tdp",
                 "rops_tmus", "cores", "clk_core", "clk_shader", "clk_memory", "mem_size",
                 "mem_type", "mem_vendor", "bus_width")


def graphics_fields(adapter, ctx):
    out = dict.fromkeys(GRAPHICS_KEYS, "")
    if adapter is None:
        return out
    if adapter.error:
        raise SourceError("DXGI", adapter.error)
    out.update(name=adapter.name, revision=f"{adapter.revision:02X}",
               board_manuf=cpudb.board_vendor(adapter.subsystem & 0xFFFF),
               mem_size=_gbytes(adapter.vram >> 20))
    if adapter.vendor != 0x10DE:
        return out
    nv = _get(ctx, "NVIDIA", "nvidia").get((adapter.bus, adapter.device_number,
                                            adapter.function))
    if nv is None:
        raise SourceError("NVIDIA", f"nvidia-smi lists no GPU for {adapter.name} at "
                          f"{adapter.bus:02X}:{adapter.device_number:02X}")
    known = cpudb.nvidia_gpu(adapter.device)
    if known:
        out.update(code_name=known.code_name, technology=known.technology,
                   mem_type=known.memory_type,
                   cores="" if known.cores is None else str(known.cores))
        if known.rops is not None and known.tmus is not None:
            out["rops_tmus"] = f"{known.rops} / {known.tmus}"
    out.update(tdp=_val1(nv.tdp_w, "W"), clk_core=_val1(nv.core_mhz, "MHz"),
               clk_memory=_val1(nv.memory_mhz, "MHz"),
               bus_width=f"{nv.bus_width} bits" if nv.bus_width else "")
    if nv.memory_mib:
        out["mem_size"] = _gbytes(int(nv.memory_mib))
    return out


def about_fields(_ctx):
    return {"windows": _call("Windows", hwinfo.windows_version),
            "directx": _call("DirectX", hwinfo.directx_version),
            "cpuid": _call("CPUID", hwinfo.thunk_status)}


# ====================================================================
#  WIDGETS
# ====================================================================

def _value_box(width=None, left=False):
    box = QLineEdit()
    box.setReadOnly(True)
    box.setAlignment((Qt.AlignLeft if left else Qt.AlignHCenter) | Qt.AlignVCenter)
    pal = box.palette()
    pal.setColor(QPalette.Base, Qt.white)
    pal.setColor(QPalette.Text, NAVY)
    box.setPalette(pal)
    if width:
        box.setFixedWidth(width)
    return box


def _label(text):
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return lbl


def _shade(label, boxes):
    # CPU-Z greys a label while the box it heads is empty
    pal = label.palette()
    pal.setColor(QPalette.WindowText, Qt.black if any(b.text() for b in boxes) else GRAY)
    label.setPalette(pal)


def _logo_frame():
    frame = QFrame()
    frame.setFrameStyle(QFrame.Panel | QFrame.Sunken)
    frame.setFixedSize(120, 70)
    logo = QLabel("", frame)
    logo.setAlignment(Qt.AlignCenter)
    logo.setFont(QFont("Tahoma", 16, QFont.Bold))
    QVBoxLayout(frame).addWidget(logo)
    return frame, logo


class Section:
    # A group box that can be swapped for its error text.

    def __init__(self, title, box, stack, error, ids, collect):
        self.title, self.box, self.stack, self.error = title, box, stack, error
        self.ids, self.collect = ids, collect

    def ok(self):
        self.stack.show()
        self.stack.setCurrentIndex(0)

    def fail(self, message):
        self.error.setText(message)
        self.stack.show()
        self.stack.setCurrentIndex(1)

    def hide(self):
        self.stack.hide()


class FieldTab(QWidget):
    # A row is a tuple of cells (id, label[, box width]); a cell without a width
    # stretches, one with an empty label is a box alone under the previous label.

    def __init__(self):
        super().__init__()
        self.boxes = {}
        self.labels = []        # [label, [boxes it heads]]
        self.sections = {}
        self._heading = None

    def _cell(self, key, text, width=None):
        box = self.boxes[key] = _value_box(width, key in LEFT_ALIGNED)
        label = None
        if text:
            label = _label(text)
            self._heading = [label, [box]]
            self.labels.append(self._heading)
        elif self._heading is not None:
            self._heading[1].append(box)
        return label, box

    def _wrap(self, title, box, before, collect=None):
        stack = QStackedWidget()
        stack.addWidget(box)
        error = QLabel()
        error.setWordWrap(True)
        error.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        error.setTextInteractionFlags(Qt.TextSelectableByMouse)
        stack.addWidget(error)
        self.sections[title] = Section(title, box, stack, error,
                                       [k for k in self.boxes if k not in before], collect)
        return stack

    def group(self, title, rows, collect=None):
        before = set(self.boxes)
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(2)
        fm = self.fontMetrics()
        first = max([fm.horizontalAdvance(row[0][1]) + 6 for row in rows if row[0][1]],
                    default=0)
        for row in rows:
            self._heading = None
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            for n, (key, text, *width) in enumerate(row):
                label, b = self._cell(key, text, width[0] if width else None)
                if label is not None:
                    if n == 0:
                        label.setMinimumWidth(first)
                    h.addWidget(label)
                h.addWidget(b, 0 if width else 1)
            if all(len(cell) == 3 for cell in row):
                h.addStretch(1)
            v.addLayout(h)
        return self._wrap(title, box, before, collect)

    def grid_group(self, title, cells, collect=None, columns=(1, 1)):
        # cells: (row, column pair, id, label); the pairs sit side by side
        before = set(self.boxes)
        box = QGroupBox(title)
        grid = QGridLayout(box)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setSpacing(2)
        for row, pair, key, text in cells:
            self._heading = None
            label, b = self._cell(key, text)
            grid.addWidget(label, row, 2 * pair)
            grid.addWidget(b, row, 2 * pair + 1)
        for pair, stretch in enumerate(columns):
            grid.setColumnStretch(2 * pair + 1, stretch)
        return self._wrap(title, box, before, collect)

    def fill_section(self, sec, values):
        if values.keys() != set(sec.ids):
            raise KeyError(f"{sec.title}: fields differ: missing "
                           f"{sorted(set(sec.ids) - values.keys())}, "
                           f"extra {sorted(values.keys() - set(sec.ids))}")
        for key, text in values.items():
            self.boxes[key].setText(text)
            self.boxes[key].setCursorPosition(0)
        sec.ok()
        self.refresh_labels()

    def refresh_labels(self):
        for label, boxes in self.labels:
            _shade(label, boxes)

    def set_text(self, key, text):
        self.boxes[key].setText(text)
        self.boxes[key].setCursorPosition(0)
        self.refresh_labels()

    def load(self, ctx):
        for sec in self.sections.values():
            if sec.collect is None:
                continue
            try:
                values = sec.collect(ctx)
            except (SourceError, OSError, ValueError) as e:
                sec.fail(str(e))
                continue
            self.fill_section(sec, values)
        self.refresh_labels()

    def page_layout(self, *items):
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        for item in items:
            (v.addLayout if isinstance(item, QLayout) else v.addWidget)(item)
        v.addStretch(1)


class CpuTab(FieldTab):
    def __init__(self):
        super().__init__()
        processor = self.group("Processor", (
            (("name", "Name"),),
            (("code_name", "Code Name"), ("tdp", "Max TDP")),
            (("package", "Package"),),
            (("technology", "Technology"), ("vid", "Core Voltage")),
            (("spec", "Specification"),),
            (("family", "Family", 36), ("model", "Model", 36), ("stepping", "Stepping", 36)),
            (("ext_family", "Ext. Family", 36), ("ext_model", "Ext. Model", 36),
             ("revision", "Revision", 80)),
            (("instructions", "Instructions"),)), cpu_processor)
        frame, self.logo = _logo_frame()
        top = QHBoxLayout()
        top.addWidget(processor, 1)
        top.addWidget(frame, 0, Qt.AlignTop)
        clocks = self.group("Clocks (Core #0)", (
            (("core_speed", "Core Speed"),), (("multiplier", "Multiplier"),),
            (("bus_speed", "Bus Speed"),), (("rated_fsb", "Rated FSB"),)), cpu_clocks)
        self.clock_box = self.sections["Clocks (Core #0)"].box
        # wide enough for the widest text a cache with differing slices produces
        ways = self.fontMetrics().horizontalAdvance("12-way + 8-way") + 16
        cache = self.group("Cache", tuple(
            ((key, label), (f"{key}_ways", "", ways)) for key, label in (
                ("l1d", "L1 Data"), ("l1i", "L1 Inst."), ("l2", "Level 2"),
                ("l3", "Level 3"))), cpu_cache)
        bottom = QHBoxLayout()
        bottom.addWidget(clocks, 1)
        bottom.addWidget(cache, 1)

        self.selection = QComboBox()
        self.cores_box, self.threads_box = _value_box(40), _value_box(40)
        self.selection_frame = QFrame()
        self.selection_frame.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        sel = QHBoxLayout(self.selection_frame)
        sel.setContentsMargins(6, 4, 6, 4)
        sel.setSpacing(6)
        for widget in (QLabel("Selection"), self.selection, QLabel("Cores"), self.cores_box,
                       QLabel("Threads"), self.threads_box):
            sel.addWidget(widget)
        sel.addStretch(1)
        self._topo = None
        self.selection.currentIndexChanged.connect(self._show_counts)
        self.page_layout(top, bottom, self.selection_frame)

    def set_clock_title(self, n):
        self.clock_box.setTitle(f"Clocks (Core #{n})")

    def load(self, ctx):
        super().load(ctx)
        try:
            self.logo.setText(CPU_LOGOS.get(_get(ctx, "CPUID", "identity").vendor, ""))
            self._topo = _get(ctx, "Topology", "topology")
        except SourceError:
            return                                  # the groups above carry the error
        self.selection.addItems([f"Socket #{n}" for n in range(1, len(self._topo.packages) + 1)])

    def _show_counts(self, index):
        if self._topo is None or index < 0:
            self.cores_box.setText("")
            self.threads_box.setText("")
            return
        self.cores_box.setText(str(self._topo.package_cores(index)))
        self.threads_box.setText(str(self._topo.package_threads(index)))


class CachesTab(FieldTab):
    def __init__(self):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(4)
        for n, (key, title) in enumerate((("l1d", "L1 D-Cache"), ("l1i", "L1 I-Cache"),
                                          ("l2", "Level 2"), ("l3", "Level 3"))):
            grid.addWidget(self.group(title, (
                ((f"{key}_size", "Size"),), ((f"{key}_descriptor", "Descriptor"),),
                ((f"{key}_count", "Count x Size"),)),
                functools.partial(cache_fields, key=key)), n // 2, n % 2)
        grid.setRowStretch(2, 1)


class MainboardTab(FieldTab):
    def __init__(self):
        super().__init__()
        board = self.group("Motherboard", (
            (("manufacturer", "Manufacturer"),),
            (("model", "Model"), ("model_rev", "", 110)),
            (("bus_specs", "Bus Specs."),),
            (("chipset_vendor", "Chipset", 70), ("chipset", ""), ("chipset_rev", "Rev.", 36)),
            (("southbridge_vendor", "Southbridge", 70), ("southbridge", ""),
             ("southbridge_rev", "Rev.", 36)),
            (("lpcio_vendor", "LPCIO", 70), ("lpcio", ""))), mainboard_board)
        bios = self.group("BIOS", (
            (("bios_brand", "Brand"),), (("bios_version", "Version"),),
            (("bios_date", "Date"), ("microcode", "CPU Microcode", 110))), mainboard_bios)
        gi = self.group("Graphic Interface", (
            (("gi_bus", "Bus"),),
            (("gi_width", "Current Link Width"), ("gi_width_max", "Max. Supported")),
            (("gi_speed", "Current Link Speed"), ("gi_speed_max", "Max. Supported"))),
            mainboard_gi)
        self.page_layout(board, bios, gi)


class MemoryTab(FieldTab):
    def __init__(self):
        super().__init__()
        general = self.grid_group("General", (
            (0, 0, "type", "Type"), (0, 1, "channels", "Channel #"),
            (1, 0, "size", "Size"), (1, 1, "dc_mode", "DC Mode"),
            (2, 1, "uncore", "Uncore Frequency")), memory_general, columns=(1, 2))
        timings = self.group("Timings", tuple(((key, label),) for key, label in (
            ("dram_freq", "DRAM Frequency"), ("fsb_dram", "FSB:DRAM"),
            ("cl", "CAS# Latency (CL)"), ("trcd", "RAS# to CAS# Delay (tRCD)"),
            ("trp", "RAS# Precharge (tRP)"), ("tras", "Cycle Time (tRAS)"),
            ("trc", "Bank Cycle Time (tRC)"), ("cr", "Command Rate (CR)"),
            ("idle_timer", "DRAM Idle Timer"), ("trdram", "Total CAS# (tRDRAM)"),
            ("row_to_col", "Row To Column (tRCD)"))), memory_timings)
        self.page_layout(general, timings)


class SpdTab(FieldTab):
    def __init__(self):
        super().__init__()
        self._rows = []
        before = set(self.boxes)
        box = QGroupBox("Memory Slot Selection")
        grid = QGridLayout(box)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setSpacing(2)
        self.slot = QComboBox()
        self._heading = None
        _, kind = self._cell("type", "", 110)
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.slot)
        top.addWidget(kind)
        top.addStretch(1)
        grid.addLayout(top, 0, 0, 1, 2)
        for row, pair, key, text in ((0, 1, "size", "Module Size"),
                                     (1, 0, "bandwidth", "Max Bandwidth"),
                                     (1, 1, "spd_ext", "SPD Ext."),
                                     (2, 0, "manufacturer", "Module Manuf."),
                                     (2, 1, "week_year", "Week/Year"),
                                     (3, 0, "dram_manuf", "DRAM Manuf."),
                                     (3, 1, "buffered", "Buffered"),
                                     (4, 0, "part", "Part Number"),
                                     (4, 1, "correction", "Correction"),
                                     (5, 0, "serial", "Serial Number"),
                                     (5, 1, "registered", "Registered")):
            self._heading = None
            label, b = self._cell(key, text)
            grid.addWidget(label, row, 2 * pair)
            grid.addWidget(b, row, 2 * pair + 1)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(3, 2)
        slots = self._wrap("Memory Slot Selection", box, before)
        self.slot.currentIndexChanged.connect(self._show_slot)

        # CPU-Z draws the timings table as read-only boxes under the profile names
        tbox = QGroupBox("Timings Table")
        tg = QGridLayout(tbox)
        tg.setContentsMargins(6, 4, 6, 4)
        tg.setSpacing(2)
        self.timing_headers, self.timing_labels, self.timing_boxes = [], [], []
        for c in range(SPD_PROFILES):
            head = QLabel("")
            head.setAlignment(Qt.AlignCenter)
            tg.addWidget(head, 0, c + 1)
            self.timing_headers.append(head)
        for r, name in enumerate(SPD_TABLE_ROWS):
            label = _label(name)
            tg.addWidget(label, r + 1, 0)
            self.timing_labels.append(label)
            row_boxes = []
            for c in range(SPD_PROFILES):
                b = _value_box()
                tg.addWidget(b, r + 1, c + 1)
                row_boxes.append(b)
            self.timing_boxes.append(row_boxes)
            self.labels.append([label, row_boxes])
        for c in range(1, SPD_PROFILES + 1):
            tg.setColumnStretch(c, 1)
        timings = self._wrap("Timings Table", tbox, set(self.boxes))
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addWidget(slots)
        v.addWidget(timings)
        v.addStretch(1)

    def load(self, ctx):
        sec = self.sections["Memory Slot Selection"]
        try:
            devices = _call("SMBIOS", smbios.memory_devices, _get(ctx, "SMBIOS", "smbios"))
        except (SourceError, OSError, ValueError) as e:
            sec.fail(str(e))
            return
        self._rows = [spd_fields(d) for d in devices]
        self.slot.blockSignals(True)
        self.slot.clear()
        self.slot.addItems([f"Slot #{n}" for n in range(1, len(devices) + 1)])
        self.slot.blockSignals(False)
        self._show_slot(0)
        self.refresh_labels()

    def _show_slot(self, index):
        self.fill_section(self.sections["Memory Slot Selection"],
                          self._rows[index] if 0 <= index < len(self._rows)
                          else spd_fields(None))


class GraphicsTab(FieldTab):
    def __init__(self):
        super().__init__()
        self._rows = []
        self._logos = []
        self.device, self.perf = QComboBox(), QComboBox()
        self.perf.addItem("Current")
        self.perf_label = QLabel("Perf Level")
        selection = QGroupBox("Display Device Selection")
        sel = QHBoxLayout(selection)
        sel.setContentsMargins(6, 4, 6, 4)
        sel.addWidget(self.device, 1)
        sel.addWidget(self.perf_label)
        sel.addWidget(self.perf)
        picker = QStackedWidget()
        picker.addWidget(selection)
        error = QLabel()
        error.setWordWrap(True)
        error.setTextInteractionFlags(Qt.TextSelectableByMouse)
        picker.addWidget(error)
        self.sections["Display Device Selection"] = Section(
            "Display Device Selection", selection, picker, error, [], None)
        gpu = self.group("GPU", (
            (("name", "Name"),), (("board_manuf", "Board Manuf."),),
            (("code_name", "Code Name"), ("revision", "Revision", 36)),
            (("technology", "Technology"), ("tdp", "TDP")),
            (("rops_tmus", "ROPs / TMUs"), ("cores", "Cores"))))
        self.logo_frame, self.logo = _logo_frame()
        middle = QHBoxLayout()
        middle.addWidget(gpu, 1)
        middle.addWidget(self.logo_frame, 0, Qt.AlignTop)
        clocks = self.group("Clocks", (
            (("clk_core", "GFX Core"),), (("clk_shader", "Shader / SoC"),),
            (("clk_memory", "Memory"),)))
        memory = self.group("Memory", (
            (("mem_size", "Size"),), (("mem_type", "Type"),), (("mem_vendor", "Vendor"),),
            (("bus_width", "Bus Width"),)))
        lower = QHBoxLayout()
        lower.addWidget(clocks, 1)
        lower.addWidget(memory, 1)
        self.device.currentIndexChanged.connect(self._show_device)
        self.page_layout(picker, middle, lower)

    def load(self, ctx):
        picker = self.sections["Display Device Selection"]
        try:
            adapters = _get(ctx, "DXGI", "adapters")
        except SourceError as e:
            picker.fail(str(e))
            for title in ("GPU", "Clocks", "Memory"):
                self.sections[title].hide()
            self.logo_frame.hide()
            return
        self._rows, self._logos = [], []
        for a in adapters:
            try:
                self._rows.append(graphics_fields(a, ctx))
            except (SourceError, OSError, ValueError) as e:
                self._rows.append(str(e))
            self._logos.append(GPU_LOGOS.get(a.vendor, ""))
        self.device.blockSignals(True)
        self.device.clear()
        self.device.addItems([a.name + (" *" if a.primary else "") for a in adapters])
        self.device.blockSignals(False)
        self._show_device(0)

    def _show_device(self, index):
        valid = 0 <= index < len(self._rows)
        row = self._rows[index] if valid else graphics_fields(None, None)
        gpu, clocks, memory = (self.sections[t] for t in ("GPU", "Clocks", "Memory"))
        self.logo.setText(self._logos[index] if valid else "")
        if isinstance(row, str):
            gpu.fail(row)
            clocks.hide()
            memory.hide()
            self.logo.setText("")
            return
        for sec in (gpu, clocks, memory):
            self.fill_section(sec, {k: row[k] for k in sec.ids})


class AboutTab(FieldTab):
    def __init__(self):
        super().__init__()
        self.page_layout(self.group("System", (
            (("windows", "Windows"),), (("directx", "DirectX"),), (("cpuid", "CPUID"),)),
            about_fields))


# ====================================================================
#  CLOCKS WINDOW AND PAGE
# ====================================================================

class ClocksWindow(QWidget):
    # Multiplier and Bus have no driver-free source and stay empty.

    COLUMNS = ("Core", "Speed", "Multiplier", "Bus")
    core_picked = pyqtSignal(int)

    def __init__(self, core_count, error, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Clocks")
        self.grid = None
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        if error:
            v.addWidget(QLabel(error))
            return
        self.grid = style_grid(QTableWidget(core_count, len(self.COLUMNS)))
        self.grid.setHorizontalHeaderLabels(self.COLUMNS)
        self.grid.horizontalHeader().setStretchLastSection(True)
        for row in range(core_count):
            for col in range(len(self.COLUMNS)):
                text = f"Core #{row}" if col == 0 else ""
                item = QTableWidgetItem(text)
                if col:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.grid.setItem(row, col, item)
        self.grid.currentCellChanged.connect(self._cell_changed)
        v.addWidget(self.grid)
        self.resize(320, min(90 + 18 * core_count, 700))

    def _cell_changed(self, row, _col, _prev_row, _prev_col):
        if row >= 0:
            self.core_picked.emit(row)

    def show_values(self, mhz_per_core):
        for row, mhz in enumerate(mhz_per_core):
            self.grid.item(row, 1).setText(hwinfo.mhz_text(mhz))


class HardwarePage(QWidget):
    # Nothing is read until the page is first shown; the one-second clock timer
    # runs only while it is visible, and the Clocks window goes and comes back
    # with the page.

    def __init__(self, ctx=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx if ctx is not None else Context()
        self._built = False
        self.clocks = None
        self.clocks_window = None
        self._restore_clocks = False
        self.clock_core = 0
        self._topo = None
        self._clock_error = ""
        self._timer = QTimer(self)
        self._timer.setInterval(CLOCK_MS)
        self._timer.timeout.connect(self._tick)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

    # ---- build ----
    def _make(self, cls):
        tab = cls()
        tab.load(self.ctx)
        return tab

    def _build(self):
        self.subtabs = QTabWidget()
        self.cpu = self._make(CpuTab)
        self.caches = self._make(CachesTab)
        self.mainboard = self._make(MainboardTab)
        self.memory = self._make(MemoryTab)
        self.spd = self._make(SpdTab)
        self.graphics = self._make(GraphicsTab)
        self.sensors = temps.TempsPage()
        self.about = self._make(AboutTab)
        for name, tab in (("CPU", self.cpu), ("Caches", self.caches),
                          ("Mainboard", self.mainboard), ("Memory", self.memory),
                          ("SPD", self.spd), ("Graphics", self.graphics),
                          ("Sensors", self.sensors), ("About", self.about)):
            self.subtabs.addTab(tab, name)

        self.tools = QToolButton()
        self.tools.setText("Tools")
        self.tools.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.tools)
        menu.addAction("Clocks", self.open_clocks)
        self.tools.setMenu(menu)
        self.bottom_bar = QHBoxLayout()
        self.bottom_bar.addStretch(1)
        self.bottom_bar.addWidget(self.tools)
        layout = self.layout()
        layout.addWidget(self.subtabs, 1)
        layout.addLayout(self.bottom_bar)

        self._start_clocks()
        self._built = True
        self._tick()

    def _start_clocks(self):
        try:
            self._topo = self.ctx.topology
            self.clocks = hwinfo.CoreClocks(self._topo)
            time.sleep(0.1)     # a rate needs two collections; the first _tick is the second
        except OSError as e:
            if self.clocks is not None:
                self.clocks.close()
            self.clocks = None
            self._clock_error = f"Clocks: {e}"

    # ---- live refresh ----
    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._built:
            self._build()
        self._timer.start()
        if self._restore_clocks:
            self._restore_clocks = False
            self.clocks_window.show()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._timer.stop()
        window = self.clocks_window
        self._restore_clocks = window is not None and window.isVisible()
        if self._restore_clocks:
            window.hide()

    def _tick(self):
        if self.clocks is None:
            self.cpu.set_text("core_speed", self._clock_error)
            return
        try:
            self.clocks.sample()
            self._show_clocks()
        except OSError as e:
            self.cpu.set_text("core_speed", f"Clocks: {e}")

    def _show_clocks(self):
        per_core = self.clocks.per_core(self._topo)
        self.cpu.set_text("core_speed", hwinfo.mhz_text(per_core[self.clock_core]))
        window = self.clocks_window
        if window is not None and window.grid is not None and window.isVisible():
            window.show_values(per_core)

    def set_clock_core(self, n):
        if self._topo is None:
            raise hwinfo.HwError(self._clock_error or "no topology")
        if not 0 <= n < len(self._topo.cores):
            raise IndexError(f"core {n}: this CPU has {len(self._topo.cores)}")
        self.clock_core = n
        self.cpu.set_clock_title(n)
        if self.clocks is not None and self.clocks.last is not None:
            self._show_clocks()

    def open_clocks(self):
        if self.clocks_window is None:
            count = len(self._topo.cores) if self._topo is not None else 0
            self.clocks_window = ClocksWindow(count, self._clock_error, self)
            self.clocks_window.core_picked.connect(self.set_clock_core)
        self.clocks_window.show()
        self.clocks_window.raise_()
        if self.clocks is not None and self.clocks.last is not None:
            self._show_clocks()

    def shutdown(self):
        self._timer.stop()
        if self.clocks_window is not None:
            self.clocks_window.close()
        if self.clocks is not None:
            self.clocks.close()
            self.clocks = None
        if self._built:
            self.sensors.shutdown()
