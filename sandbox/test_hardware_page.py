"""Contract test for hardware.py: the CPU-Z replica page, offscreen.

Every sub-tab builds from live data in the CPU-Z 2.15 layout (ref screenshots in
docs\\plans\\08_Hardware_Tab\\ref), labels are gray exactly while their boxes are
empty, boxes without a phase-1 source are empty strings, there are no tooltips,
the 1 s timer runs only while the page is shown, and a failing data source
replaces only the group box it feeds with its error text.
"""

import os
import re
import sys
import time
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QPalette  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QGroupBox, QLabel, QLineEdit, QTableWidget, QTabWidget,
    QToolButton, QWidget,
)

import hardware  # noqa: E402
import hwinfo  # noqa: E402
import smbios  # noqa: E402
import temps  # noqa: E402

app = QApplication([])
reg = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                     r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
REG_NAME = winreg.QueryValueEx(reg, "ProcessorNameString")[0].strip()
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rsmb_7950x3d_b650_creator.bin"
LEFT = {"manufacturer", "model", "bus_specs", "bios_brand", "bios_version", "bios_date",
        "part", "serial", "instructions"}


def labels(tab):
    return [(g.title(), [lbl.text() for lbl in g.findChildren(QLabel) if lbl.text()])
            for g in tab.findChildren(QGroupBox)]


def values(tab):
    return {k: b.text() for k, b in tab.boxes.items()}


def gray(lbl):
    return lbl.palette().color(QPalette.WindowText) == hardware.GRAY


def gray_labels(tab):
    return {lbl.text() for lbl, _ids in tab.labels if gray(lbl)}


def check_grays(tab):
    # a label is gray exactly while every box it heads is empty
    for lbl, boxes in tab.labels:
        empty = not any(b.text() for b in boxes)
        assert gray(lbl) == empty, (lbl.text(), [b.text() for b in boxes])


def check_alignment(tab):
    for key, box in tab.boxes.items():
        want = Qt.AlignLeft if key in LEFT else Qt.AlignHCenter
        assert box.alignment() & Qt.AlignHorizontal_Mask == want, (key, box.alignment())


# ---- lazy: nothing is read until the page is first shown ----
page = hardware.HardwarePage()
assert not page._built and not page._timer.isActive()
page.resize(900, 600)
page.show()
app.processEvents()
assert page._built
assert [page.subtabs.tabText(i) for i in range(page.subtabs.count())] == [
    "CPU", "Caches", "Mainboard", "Memory", "SPD", "Graphics", "Sensors", "About"]
print("tabs ok")

# ---- labels in CPU-Z order ----
assert labels(page.cpu) == [
    ("Processor", ["Name", "Code Name", "Max TDP", "Package", "Technology", "Core Voltage",
                   "Specification", "Family", "Model", "Stepping", "Ext. Family",
                   "Ext. Model", "Revision", "Instructions"]),
    ("Clocks (Core #0)", ["Core Speed", "Multiplier", "Bus Speed", "Rated FSB"]),
    ("Cache", ["L1 Data", "L1 Inst.", "Level 2", "Level 3"]),
], labels(page.cpu)
assert [lbl.text() for lbl in page.cpu.selection_frame.findChildren(QLabel)] == [
    "Selection", "Cores", "Threads"]
assert labels(page.caches) == [
    (title, ["Size", "Descriptor", "Count x Size"])
    for title in ("L1 D-Cache", "L1 I-Cache", "Level 2", "Level 3")], labels(page.caches)
assert labels(page.mainboard) == [
    ("Motherboard", ["Manufacturer", "Model", "Bus Specs.", "Chipset", "Rev.",
                     "Southbridge", "Rev.", "LPCIO"]),
    ("BIOS", ["Brand", "Version", "Date", "CPU Microcode"]),
    ("Graphic Interface", ["Bus", "Current Link Width", "Max. Supported",
                           "Current Link Speed", "Max. Supported"]),
], labels(page.mainboard)
assert labels(page.memory) == [
    ("General", ["Type", "Channel #", "Size", "DC Mode", "Uncore Frequency"]),
    ("Timings", ["DRAM Frequency", "FSB:DRAM", "CAS# Latency (CL)",
                 "RAS# to CAS# Delay (tRCD)", "RAS# Precharge (tRP)",
                 "Cycle Time (tRAS)", "Bank Cycle Time (tRC)", "Command Rate (CR)",
                 "DRAM Idle Timer", "Total CAS# (tRDRAM)", "Row To Column (tRCD)"]),
], labels(page.memory)
assert labels(page.spd) == [
    ("Memory Slot Selection", ["Module Size", "Max Bandwidth", "SPD Ext.", "Module Manuf.",
                               "Week/Year", "DRAM Manuf.", "Buffered", "Part Number",
                               "Correction", "Serial Number", "Registered"]),
    ("Timings Table", ["Frequency", "CAS# Latency", "RAS# to CAS#", "RAS# Precharge",
                       "tRAS", "tRC", "Command Rate", "Voltage"]),
], labels(page.spd)
assert labels(page.graphics) == [
    ("Display Device Selection", ["Perf Level"]),
    ("GPU", ["Name", "Board Manuf.", "Code Name", "Revision", "Technology", "TDP",
             "ROPs / TMUs", "Cores"]),
    ("Clocks", ["GFX Core", "Shader / SoC", "Memory"]),
    ("Memory", ["Size", "Type", "Vendor", "Bus Width"]),
], labels(page.graphics)
assert labels(page.about) == [("System", ["Windows", "DirectX", "CPUID"])], labels(page.about)
print("labels ok")

# ---- the shared bottom bar keeps only Tools; the socket frame lives on the CPU tab ----
bar = page.bottom_bar
assert [bar.itemAt(i).widget() for i in range(bar.count()) if bar.itemAt(i).widget()] == [
    page.tools]
assert not hasattr(page, "selection") and not hasattr(page, "cores_box")
assert page.cpu.selection.count() == 1 and page.cpu.selection.itemText(0) == "Socket #1"
assert page.cpu.cores_box.text() == str(len(hwinfo.topology().cores))
assert page.cpu.threads_box.text() == str(os.cpu_count())
assert page.cpu.cores_box.isReadOnly() and page.cpu.threads_box.isReadOnly()
print("bottom bar ok")

# ---- CPU tab values (this PC is the CPU-Z reference) ----
cpu = values(page.cpu)
assert cpu["spec"] == REG_NAME, cpu["spec"]
assert re.fullmatch(r"\d+\.\d\d MHz", cpu["core_speed"]), cpu["core_speed"]
for k in ("vid", "multiplier", "bus_speed", "rated_fsb"):
    assert cpu[k] == "", (k, cpu[k])
assert cpu["instructions"].startswith(("MMX", "SSE")) and "AVX512" in cpu["instructions"]
assert cpu["instructions"].endswith("SHA"), cpu["instructions"]
if "7950X3D" in REG_NAME:
    want = {"name": "AMD Ryzen 9 7950X3D", "code_name": "Raphael", "tdp": "120.0 W",
            "package": "Socket AM5 (LGA1718)", "technology": "5 nm", "family": "F",
            "model": "1", "stepping": "2", "ext_family": "19", "ext_model": "61",
            "revision": "RPL-B2", "l1d": "16 x 32 KBytes", "l1d_ways": "8-way",
            "l1i": "16 x 32 KBytes", "l1i_ways": "8-way", "l2": "16 x 1 MBytes",
            "l2_ways": "8-way", "l3": "96 MB + 32 MB", "l3_ways": "16-way"}
    for k, v in want.items():
        assert cpu[k] == v, (k, cpu[k], v)
assert page.cpu.logo.text() == ("AMD" if REG_NAME.startswith("AMD") else "Intel")
assert gray_labels(page.cpu) == {"Core Voltage", "Multiplier", "Bus Speed", "Rated FSB"}, \
    gray_labels(page.cpu)
# the ways box fits the widest text a mixed-slice cache produces
ways_box = page.cpu.boxes["l1d_ways"]
assert ways_box.minimumWidth() >= ways_box.fontMetrics().horizontalAdvance("12-way + 8-way") + 8
print("cpu ok:", {k: cpu[k] for k in ("name", "code_name", "core_speed", "l3")})

# ---- Caches tab ----
cc = values(page.caches)
topo = hwinfo.topology()
for key, (level, kind) in {"l1d": (1, "data"), "l1i": (1, "instruction"),
                           "l2": (2, "unified"), "l3": (3, "unified")}.items():
    info = hwinfo.cache_info(topo, level, kind)
    assert cc[f"{key}_size"] == info.size, (key, cc[f"{key}_size"], info)
    assert cc[f"{key}_descriptor"] == info.descriptor
    assert cc[f"{key}_count"] == info.summary
assert not gray_labels(page.caches)
print("caches ok")

# ---- Mainboard tab: CPU-Z splits Chipset / Southbridge / LPCIO into two boxes ----
mb = values(page.mainboard)
assert mb["lpcio_vendor"] == "" and mb["lpcio"] == ""
if "B650-CREATOR" in mb["model"]:
    assert (mb["manufacturer"], mb["model"], mb["model_rev"]) == (
        "ASUSTeK COMPUTER INC.", "ProArt B650-CREATOR", "Rev 1.xx"), mb
    assert (mb["bios_brand"], mb["bios_date"]) == ("American Megatrends Inc.", "07/17/2024")
    assert mb["bios_version"] == "2124 - AMD AGESA ComboAm5PI 1.2.0.0a", mb["bios_version"]
    assert mb["bus_specs"] == "PCI-Express 5.0 (32.0 GT/s)", mb["bus_specs"]
    assert (mb["chipset_vendor"], mb["chipset"], mb["chipset_rev"]) == ("AMD", "Ryzen SOC", "00")
    assert (mb["southbridge_vendor"], mb["southbridge"], mb["southbridge_rev"]) == (
        "AMD", "B650", "51"), mb
assert re.fullmatch(r"PCI-Express [1-6]\.0", mb["gi_bus"]), mb["gi_bus"]
assert re.fullmatch(r"x\d+", mb["gi_width"]) and re.fullmatch(r"x\d+", mb["gi_width_max"])
assert mb["gi_speed"].endswith(" GT/s") and mb["gi_speed_max"].endswith(" GT/s")
assert mb["microcode"] == hwinfo.microcode()
assert gray_labels(page.mainboard) == {"LPCIO"}, gray_labels(page.mainboard)
print("mainboard ok")

# ---- Memory tab: no Mem Controller Freq. row; Channel # counts DIMM channels ----
mem = values(page.memory)
assert set(mem) == {"type", "channels", "size", "dc_mode", "uncore", "dram_freq", "fsb_dram",
                    "cl", "trcd", "trp", "tras", "trc", "cr", "idle_timer", "trdram",
                    "row_to_col"}, set(mem)
assert mem["type"] == "DDR5" and mem["size"] == "128 GBytes", mem
assert mem["channels"] == "2 x 32-bit", mem["channels"]
assert mem["dram_freq"] == "1800.0 MHz", mem["dram_freq"]
for k, v in mem.items():
    if k not in ("type", "size", "channels", "dram_freq"):
        assert v == "", (k, v)
assert gray_labels(page.memory) == {
    "DC Mode", "Uncore Frequency", "FSB:DRAM", "CAS# Latency (CL)",
    "RAS# to CAS# Delay (tRCD)", "RAS# Precharge (tRP)", "Cycle Time (tRAS)",
    "Bank Cycle Time (tRC)", "Command Rate (CR)", "DRAM Idle Timer", "Total CAS# (tRDRAM)",
    "Row To Column (tRCD)"}, gray_labels(page.memory)
print("memory ok")

# ---- SPD tab: slot row, then left / right pairs; no Ranks ----
spd = page.spd
assert [spd.slot.itemText(i) for i in range(spd.slot.count())] == [
    "Slot #1", "Slot #2", "Slot #3", "Slot #4"]
s1 = values(spd)
assert set(s1) == {"type", "size", "bandwidth", "spd_ext", "manufacturer", "week_year",
                   "dram_manuf", "buffered", "part", "correction", "serial", "registered"}, set(s1)
assert s1["type"] == "DDR5 (UDIMM)" and s1["size"] == "32 GBytes", s1
assert s1["bandwidth"] == "DDR5-4800 (2400 MHz)", s1["bandwidth"]
assert s1["manufacturer"] == "Corsair" and s1["part"] == "CMK128GX5M4B5600C40", s1
assert s1["serial"] == "", "SMBIOS reports an all-zero serial"
for k in ("spd_ext", "week_year", "dram_manuf", "buffered", "correction", "registered"):
    assert s1[k] == "", (k, s1[k])
assert gray_labels(spd) == {"SPD Ext.", "Week/Year", "DRAM Manuf.", "Buffered", "Correction",
                            "Serial Number", "Registered", "Frequency", "CAS# Latency",
                            "RAS# to CAS#", "RAS# Precharge", "tRAS", "tRC", "Command Rate",
                            "Voltage"}, gray_labels(spd)
spd.slot.setCurrentIndex(3)
assert values(spd)["part"] == "CMK128GX5M4B5600C40"
# the timings table is read-only boxes under empty profile headers, not a grid
assert not spd.findChildren(QTableWidget)
assert [lbl.text() for lbl in spd.timing_labels] == [
    "Frequency", "CAS# Latency", "RAS# to CAS#", "RAS# Precharge", "tRAS", "tRC",
    "Command Rate", "Voltage"]
assert len(spd.timing_headers) == 4 and all(h.text() == "" for h in spd.timing_headers)
assert len(spd.timing_boxes) == 8 and all(len(row) == 4 for row in spd.timing_boxes)
assert all(b.isReadOnly() and b.text() == "" for row in spd.timing_boxes for b in row)
spd.slot.setCurrentIndex(0)

# fields from synthetic devices
def device(**kw):
    base = {"present": True, "size_mb": 16384, "memory_type": "DDR4", "speed": 3200,
            "configured_speed": 3200, "manufacturer": "Corsair", "part_number": "PART",
            "serial": "12345678", "device_locator": "DIMM 0", "bank_locator": "P0 CHANNEL A",
            "form_factor": 9, "type_detail": 0x4080}
    base.update(kw)
    return smbios.MemoryDevice(**base)


empty = hardware.spd_fields(None)
assert set(empty) == set(s1) and all(v == "" for v in empty.values()), empty
assert hardware.spd_fields(device(present=False, size_mb=None)) == empty
rdimm = hardware.spd_fields(device(type_detail=0x2080, memory_type="DDR5", speed=4800))
assert (rdimm["type"], rdimm["registered"], rdimm["buffered"]) == ("DDR5 (RDIMM)", "Yes", "Yes")
assert rdimm["bandwidth"] == "DDR5-4800 (2400 MHz)"
lr = hardware.spd_fields(device(type_detail=0x8080))
assert (lr["type"], lr["registered"], lr["buffered"]) == ("DDR4 (LRDIMM)", "", "Yes")
so = hardware.spd_fields(device(form_factor=0x0D))
assert (so["type"], so["registered"], so["buffered"], so["serial"]) == (
    "DDR4 (SO-DIMM)", "", "", "12345678")
assert hardware.spd_fields(device(form_factor=0x10))["type"] == "DDR4"
# unknown memory type: empty box, and no bandwidth text built on it
unk = hardware.spd_fields(device(memory_type=""))
assert unk["type"] == "" and unk["bandwidth"] == "" and unk["size"] == "16 GBytes", unk
# a present module of unknown size keeps its other fields
nosize = hardware.spd_fields(device(size_mb=None))
assert nosize["size"] == "" and nosize["part"] == "PART" and nosize["type"] == "DDR4 (UDIMM)"
assert hardware.spd_fields(device(serial="0"))["serial"] == ""
assert hardware.spd_fields(device(serial="00000000"))["serial"] == ""
assert hardware.spd_fields(device(manufacturer="029E"))["manufacturer"] == "Corsair"
assert hardware.spd_fields(device(manufacturer="80AD"))["manufacturer"] == "SK Hynix"
print("spd ok")

# ---- Graphics tab: Perf Level, ' *' on the primary adapter, CPU-Z rows ----
gfx = page.graphics
adapters = hwinfo.dxgi_adapters()
assert gfx.device.count() == len(adapters) >= 1
assert [gfx.device.itemText(i) for i in range(gfx.device.count())] == [
    a.name + (" *" if a.primary else "") for a in adapters]
assert any(gfx.device.itemText(i).endswith(" *") for i in range(gfx.device.count()))
assert gfx.perf_label.text() == "Perf Level"
assert [gfx.perf.itemText(i) for i in range(gfx.perf.count())] == ["Current"]
g = values(gfx)
assert set(g) == {"name", "board_manuf", "code_name", "revision", "technology", "tdp",
                  "rops_tmus", "cores", "clk_core", "clk_shader", "clk_memory", "mem_size",
                  "mem_type", "mem_vendor", "bus_width"}, set(g)
assert g["name"] == adapters[0].name, g["name"]
assert g["revision"] == f"{adapters[0].revision:02X}"
assert g["mem_vendor"] == "" and g["clk_shader"] == ""
if adapters[0].vendor == 0x10DE:
    assert page.graphics.logo.text() == "NVIDIA"
    assert re.fullmatch(r"\d+\.\d MHz", g["clk_core"]), g["clk_core"]
    assert re.fullmatch(r"\d+\.\d MHz", g["clk_memory"]), g["clk_memory"]
    assert re.fullmatch(r"\d+ bits", g["bus_width"]), g["bus_width"]
    assert re.fullmatch(r"\d+\.\d W", g["tdp"]), g["tdp"]
    assert g["board_manuf"] and g["technology"].endswith(" nm"), g
if adapters[0].device == 0x2204:
    want = {"board_manuf": "ASUSTeK Computer Inc.", "code_name": "GA102-300",
            "technology": "8 nm", "tdp": "350.0 W", "rops_tmus": "112 / 328",
            "cores": "10496", "mem_type": "GDDR6X", "mem_size": "24 GBytes",
            "bus_width": "384 bits"}
    for k, v in want.items():
        assert g[k] == v, (k, g[k], v)
assert gray_labels(gfx) == {"Shader / SoC", "Vendor"}, gray_labels(gfx)
gfx.device.setCurrentIndex(gfx.device.count() - 1)
assert values(gfx)["name"] == adapters[-1].name
gfx.device.setCurrentIndex(0)
print("graphics ok:", {k: g[k] for k in ("name", "code_name", "board_manuf", "tdp", "rops_tmus",
                                         "cores", "mem_type", "mem_size", "bus_width")})

# ---- About tab ----
ab = values(page.about)
assert ab["windows"] == hwinfo.windows_version(), ab
assert ab["directx"] == hwinfo.directx_version(), ab
assert ab["cpuid"] == "OK", ab
print("about ok")

# ---- gray labels and alignment hold on every sub-tab ----
for tab in (page.cpu, page.caches, page.mainboard, page.memory, page.spd, page.graphics,
            page.about):
    check_grays(tab)
    check_alignment(tab)
print("grays and alignment ok")

# ---- Sensors sub-tab is the existing TempsPage and polls only while visible ----
assert isinstance(page.sensors, temps.TempsPage)
assert page.subtabs.currentWidget() is page.cpu and not page.sensors._timer.isActive()
page.subtabs.setCurrentWidget(page.sensors)
app.processEvents()
assert page.sensors._timer.isActive()
page.subtabs.setCurrentWidget(page.cpu)
assert not page.sensors._timer.isActive()
print("sensors ok")

# ---- no tooltips anywhere ----
tips = [(type(w).__name__, w.toolTip()) for w in page.findChildren(QWidget) if w.toolTip()]
assert not tips, tips

# ---- every value box is read-only ----
for tab in (page.cpu, page.caches, page.mainboard, page.memory, page.spd,
            page.graphics, page.about):
    assert all(b.isReadOnly() for b in tab.findChildren(QLineEdit)), tab
print("no tooltips ok")

# ---- live refresh: the timer follows visibility; ticks update the core speed ----
assert page._timer.isActive() and page._timer.interval() == 1000
page.cpu.set_text("core_speed", "")
speed_label = next(lbl for lbl, boxes in page.cpu.labels
                   if boxes == [page.cpu.boxes["core_speed"]])
assert gray(speed_label)
time.sleep(0.2)
page._tick()
assert re.fullmatch(r"\d+\.\d\d MHz", page.cpu.boxes["core_speed"].text())
assert not gray(speed_label)
page.hide()
assert not page._timer.isActive()
page.show()
assert page._timer.isActive()
tabs = QTabWidget()
other = QWidget()
standalone = hardware.HardwarePage()
tabs.addTab(other, "other")
tabs.addTab(standalone, "Hardware")
tabs.show()
app.processEvents()
assert not standalone._built and not standalone._timer.isActive()
tabs.setCurrentIndex(1)
app.processEvents()
assert standalone._built and standalone._timer.isActive()

# the Clocks window follows the tab: hidden with it, restored on return
standalone.open_clocks()
window = standalone.clocks_window
assert window.isVisible()
tabs.setCurrentIndex(0)
app.processEvents()
assert not standalone._timer.isActive() and not window.isVisible()
tabs.setCurrentIndex(1)
app.processEvents()
assert standalone._timer.isActive() and window.isVisible(), "Clocks window not restored"
window.hide()                                           # closed by the user: stays closed
tabs.setCurrentIndex(0)
app.processEvents()
tabs.setCurrentIndex(1)
app.processEvents()
assert not window.isVisible()
standalone.shutdown()
print("timer ok")

# ---- core picked by the clocks group ----
time.sleep(0.2)
page._tick()
page.set_clock_core(3)
assert page.cpu.clock_box.title() == "Clocks (Core #3)"
assert re.fullmatch(r"\d+\.\d\d MHz", page.cpu.boxes["core_speed"].text())
page.set_clock_core(0)
try:
    page.set_clock_core(len(topo.cores))
    raise AssertionError("core past the last was accepted")
except IndexError:
    pass
assert page.cpu.clock_box.title() == "Clocks (Core #0)"

# ---- Tools > Clocks window ----
actions = page.tools.menu().actions()
assert [a.text() for a in actions] == ["Clocks"]
assert page.clocks_window is None
actions[0].trigger()
app.processEvents()
win = page.clocks_window
assert win is not None and win.isVisible() and not win.isModal()
grid = win.grid
assert isinstance(grid, QTableWidget)
assert grid.rowCount() == len(topo.cores), (grid.rowCount(), len(topo.cores))
assert [grid.horizontalHeaderItem(c).text() for c in range(grid.columnCount())] == [
    "Core", "Speed", "Multiplier", "Bus"]
assert [grid.item(r, 0).text() for r in range(grid.rowCount())] == [
    f"Core #{i}" for i in range(len(topo.cores))]
time.sleep(0.2)
page._tick()
for r in range(grid.rowCount()):
    assert re.fullmatch(r"\d+\.\d\d MHz", grid.item(r, 1).text()), grid.item(r, 1).text()
    assert grid.item(r, 2).text() == "" and grid.item(r, 3).text() == ""
assert not grid.alternatingRowColors() and grid.showGrid()
assert "gridline-color: black" in grid.styleSheet()
grid.setCurrentCell(3, 0)
assert page.clock_core == 3 and page.cpu.clock_box.title() == "Clocks (Core #3)"
grid.setCurrentCell(0, 1)
assert page.clock_core == 0 and page.cpu.clock_box.title() == "Clocks (Core #0)"
actions[0].trigger()
assert page.clocks_window is win, "a second Clocks window was opened"
print("clocks window ok")


# ---- a failing source replaces only the group box it feeds ----
def failed(tab, title):
    sec = tab.sections[title]
    assert not sec.box.isVisibleTo(tab) and sec.error.isVisibleTo(tab), title
    return sec.error.text()


def fine(tab, title):
    sec = tab.sections[title]
    assert sec.box.isVisibleTo(tab) and not sec.error.isVisibleTo(tab), title


class BrokenSmbios(hardware.Context):
    @property
    def smbios(self):
        raise smbios.SmbiosError("table unreadable")


bad = hardware.HardwarePage(BrokenSmbios())
bad.show()
app.processEvents()
for tab, title in ((bad.mainboard, "Motherboard"), (bad.mainboard, "BIOS"),
                   (bad.memory, "General"), (bad.memory, "Timings"),
                   (bad.spd, "Memory Slot Selection")):
    assert failed(tab, title) == "SMBIOS: table unreadable", (title, failed(tab, title))
fine(bad.mainboard, "Graphic Interface")
assert values(bad.mainboard)["gi_bus"].startswith("PCI-Express")
fine(bad.spd, "Timings Table")
for title in ("Processor", "Clocks (Core #0)", "Cache"):
    fine(bad.cpu, title)
assert bad.cpu.boxes["spec"].text() == REG_NAME, "CPU does not depend on SMBIOS here"
assert bad.graphics.device.count() >= 1
bad.shutdown()


class BrokenTopology(hardware.Context):
    @property
    def topology(self):
        raise hwinfo.HwError("glpi down")


bad = hardware.HardwarePage(BrokenTopology())
bad.show()
app.processEvents()
assert failed(bad.cpu, "Cache") == "Topology: glpi down"
fine(bad.cpu, "Processor")
assert failed(bad.caches, "Level 3") == "Topology: glpi down"
assert bad.cpu.cores_box.text() == "" and bad.cpu.selection.count() == 0
bad.open_clocks()
assert bad.clocks_window.grid is None
assert [lbl.text() for lbl in bad.clocks_window.findChildren(QLabel)] == ["Clocks: glpi down"]
bad.shutdown()
print("error display ok")

# ---- structures and devices that do not exist are empty boxes, never errors ----
full = smbios.parse(FIXTURE.read_bytes())
real_pci = hwinfo.pci_devices()


def open_page(**attrs):
    ctx = type("Ctx", (hardware.Context,), attrs)()
    p = hardware.HardwarePage(ctx)
    p.show()
    app.processEvents()
    return p


no_board = open_page(smbios=smbios.Table(full.version,
                                         [s for s in full.structures if s.type != 2]))
for title in ("Motherboard", "BIOS", "Graphic Interface"):
    fine(no_board.mainboard, title)
m = values(no_board.mainboard)
assert (m["manufacturer"], m["model"], m["model_rev"]) == ("", "", ""), m
assert m["bios_brand"] == "American Megatrends Inc." and m["chipset"] == "Ryzen SOC"
assert m["southbridge"] == "790E", "no board model to name the chipset from"
no_board.shutdown()

no_bios = open_page(smbios=smbios.Table(full.version,
                                        [s for s in full.structures if s.type != 0]))
assert values(no_bios.mainboard)["bios_brand"] == "" and values(no_bios.mainboard)["model"]
fine(no_bios.mainboard, "BIOS")
no_bios.shutdown()

no_host = open_page(pci=[d for d in real_pci if (d.base_class, d.sub_class) != (6, 0)])
m = values(no_host.mainboard)
assert (m["chipset_vendor"], m["chipset"], m["chipset_rev"]) == ("", "", "")
assert m["southbridge"] == "B650"
fine(no_host.mainboard, "Motherboard")
no_host.shutdown()

no_isa = open_page(pci=[d for d in real_pci if (d.base_class, d.sub_class) != (6, 1)])
m = values(no_isa.mainboard)
assert (m["southbridge_vendor"], m["southbridge"], m["southbridge_rev"]) == ("", "", "")
assert m["chipset"] == "Ryzen SOC"
no_isa.shutdown()

no_gpu_dev = open_page(pci=[d for d in real_pci if d.base_class != 3])
m = values(no_gpu_dev.mainboard)
assert all(m[k] == "" for k in ("gi_bus", "gi_width", "gi_width_max", "gi_speed",
                                "gi_speed_max")), m
fine(no_gpu_dev.mainboard, "Graphic Interface")
no_gpu_dev.shutdown()

# no Direct3D 12: DirectX is empty, the rest of About is fine
real_load = hwinfo._load_d3d12


def no_d3d12():
    raise OSError("d3d12.dll not found")


hwinfo._load_d3d12 = no_d3d12
try:
    about = open_page()
finally:
    hwinfo._load_d3d12 = real_load
fine(about.about, "System")
assert values(about.about)["directx"] == "" and values(about.about)["windows"]
assert gray_labels(about.about) == {"DirectX"}
about.shutdown()
print("absent structures ok")

# ---- bus specs: root port data, else the CPU's generation, else empty ----
port = next(d for d in real_pci if d.is_root_port)
with_port = open_page(pci=[port._replace(max_speed=4) if d is port else d for d in real_pci])
assert values(with_port.mainboard)["bus_specs"] == "PCI-Express 4.0 (16.0 GT/s)"
with_port.shutdown()


class UnknownCpu(hardware.Context):
    identity = hwinfo.Identity("AuthenticAMD", "AMD Mystery 1", 15, 9, 9, 0x99, 0x99)


unknown = hardware.HardwarePage(UnknownCpu())
unknown.show()
app.processEvents()
assert values(unknown.mainboard)["bus_specs"] == "", "no source for the generation"
mystery = values(unknown.cpu)
assert mystery["package"] == "AM5", mystery["package"]    # the SMBIOS socket designation
for k in ("name", "code_name", "tdp", "technology", "revision"):
    assert mystery[k] == "", (k, mystery[k])
assert mystery["spec"] == "AMD Mystery 1" and mystery["ext_family"] == "99"
unknown.shutdown()
known = hardware.cpu_processor(type("K", (hardware.Context,), {
    "identity": hwinfo.Identity("GenuineIntel", "Intel(R) Core(TM) Ultra 9 285K", 6, 0xC, 2,
                                6, 0xC6)})())
assert (known["name"], known["code_name"], known["package"], known["tdp"]) == (
    "Intel Core Ultra 9 285K", "Arrow Lake", "Socket LGA1851", "125.0 W"), known
for vendor, logo in (("GenuineIntel", "Intel"), ("AuthenticAMD", "AMD"), ("HygonGenuine", "")):
    tab = open_page(identity=hwinfo.Identity(vendor, "Brand", 15, 9, 9, 0x99, 0x99))
    assert tab.cpu.logo.text() == logo, (vendor, tab.cpu.logo.text())
    tab.shutdown()
print("bus specs / unknown cpu ok")

# ---- two sockets: the selection picks the package whose counts are shown ----
half = len(topo.cores) // 2
two = hwinfo.Topology(topo.cores, [
    hwinfo.Package(tuple(i for c in topo.cores[:half] for i in c.logical)),
    hwinfo.Package(tuple(i for c in topo.cores[half:] for i in c.logical))],
    topo.caches, topo.numa)
dual = open_page(topology=two)
sel = dual.cpu.selection
assert [sel.itemText(i) for i in range(sel.count())] == ["Socket #1", "Socket #2"]
sel.setCurrentIndex(1)
assert (dual.cpu.cores_box.text(), dual.cpu.threads_box.text()) == (
    str(len(topo.cores) - half), str(two.package_threads(1)))
dual.shutdown()
print("sockets ok")

# ---- per-adapter errors: only that adapter's boxes are replaced ----
if len(adapters) >= 2:
    flawed = next(i for i, a in enumerate(adapters) if not a.primary)
    broken = list(adapters)
    broken[flawed] = adapters[flawed]._replace(
        error="D3DKMTQueryAdapterInfo(test): 0xC0000001", bus=None, device_number=None,
        function=None)
    mixed = open_page(adapters=broken)
    mg = mixed.graphics
    mg.device.setCurrentIndex(flawed)
    assert "D3DKMT" in failed(mg, "GPU")
    assert not mg.sections["Clocks"].box.isVisibleTo(mg)
    assert not mg.sections["Memory"].box.isVisibleTo(mg)
    other = 1 - flawed
    mg.device.setCurrentIndex(other)
    for title in ("GPU", "Clocks", "Memory"):
        fine(mg, title)
    assert values(mg)["name"] == adapters[other].name
    fine(mixed.mainboard, "Graphic Interface")
    mixed.shutdown()

if adapters[0].vendor == 0x10DE:
    class NoSmiRow(hardware.Context):
        nvidia = {}

    class NoSmi(hardware.Context):
        @property
        def nvidia(self):
            raise hwinfo.HwError("nvidia-smi not found")

    for ctx_cls, prefix in ((NoSmiRow, "NVIDIA: nvidia-smi lists no GPU"),
                            (NoSmi, "NVIDIA: nvidia-smi not found")):
        broken = hardware.HardwarePage(ctx_cls())
        broken.show()
        app.processEvents()
        assert failed(broken.graphics, "GPU").startswith(prefix)
        broken.shutdown()
    print("nvidia errors ok")


# ---- memory fields from synthetic SMBIOS devices ----
def dimm(size, mtype, bank, dev="DIMM 0", conf=3600, **kw):
    fields = {"present": size != 0, "size_mb": size or None, "memory_type": mtype,
              "bank_locator": bank, "device_locator": dev, "configured_speed": conf,
              "manufacturer": "029E"}
    fields.update(kw)
    return device(**fields)


class MemCtx(hardware.Context):
    smbios = object()      # the patched memory_devices ignores its table


real_devices = smbios.memory_devices
try:
    for devs, want in (
            ([dimm(16384, "DDR4", "ChannelA-DIMM0"), dimm(16384, "DDR4", "ChannelB-DIMM0"),
              dimm(0, "DDR4", "ChannelA-DIMM1")], ("2 x 64-bit", "32 GBytes", "DDR4")),
            ([dimm(8192, "DDR4", "Controller0-ChannelA"),
              dimm(8192, "DDR4", "Controller1-ChannelA")], ("2 x 64-bit", "16 GBytes", "DDR4")),
            ([dimm(16384, "DDR4", "P0 CHANNEL A"), dimm(16384, "DDR4", "P0 CHANNEL A", "DIMM 1")],
             ("1 x 64-bit", "32 GBytes", "DDR4")),
            ([dimm(16384, "DDR5", "BANK 0")], ("", "16 GBytes", "DDR5")),
            ([dimm(16384, "DDR5", "P0 CHANNEL A", conf=None)], ("1 x 32-bit", "16 GBytes", "DDR5")),
            ([dimm(512, "DDR3", "CHANNEL 0"), dimm(1024, "DDR3", "CHANNEL 1")],
             ("2 x 64-bit", "1536 MBytes", "DDR3")),
            ([dimm(0, "DDR4", "ChannelA-DIMM0")], ("", "", "")),
            ([dimm(None, "DDR5", "P0 CHANNEL A", size_mb=None, present=True),
              dimm(32768, "DDR5", "P0 CHANNEL B")], ("2 x 32-bit", "", "DDR5")),
            ([dimm(8192, "", "CHANNEL A")], ("", "8 GBytes", ""))):
        smbios.memory_devices = lambda _t, devs=devs: devs
        fields = hardware.memory_general(MemCtx())
        assert set(fields) == {"type", "channels", "size", "dc_mode", "uncore"}, fields
        assert (fields["channels"], fields["size"], fields["type"]) == want, (fields, want)
        timings = hardware.memory_timings(MemCtx())
        live = [d for d in devs if d.present]
        speed = live[0].configured_speed if live else None
        assert timings["dram_freq"] == ("1800.0 MHz" if speed else ""), timings
        assert all(v == "" for k, v in timings.items() if k != "dram_freq")
finally:
    smbios.memory_devices = real_devices

# a present module of unknown size: its size box is empty, the module's other boxes are not
unknown_size = [device(size_mb=None, present=True), device()]
try:
    smbios.memory_devices = lambda _t: unknown_size
    sized = open_page(smbios=full)
finally:
    smbios.memory_devices = real_devices
sized.spd.slot.setCurrentIndex(0)
row = values(sized.spd)
assert row["size"] == "" and row["part"] == "PART" and row["type"] == "DDR4 (UDIMM)", row
sized.spd.slot.setCurrentIndex(1)
assert values(sized.spd)["size"] == "16 GBytes"
assert values(sized.memory)["size"] == "", "a module of unknown size makes the total unknown"
sized.shutdown()
print("memory fields ok")

# ---- shutdown stops everything ----
page.shutdown()
assert not page._timer.isActive() and not page.sensors._timer.isActive()
assert not page.clocks_window.isVisible()
assert isinstance(page.cpu.selection, QComboBox) and isinstance(page.tools, QToolButton)
print("STATUS: SUCCESS")
