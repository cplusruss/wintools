"""Verify icon extraction for live uninstall entries + the pythonw swap."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

import clean
import wintools

app = QApplication.instance() or QApplication([])

# --- pythonw swap in relaunch ---
import inspect
src = inspect.getsource(wintools.relaunch_elevated)
print("relaunch_elevated uses pythonw.exe:", "pythonw.exe" in src)
assert "pythonw.exe" in src

# --- _parse_display_icon ---
cases = [
    ('"C:\\foo.exe",2',           ('C:\\foo.exe', 2)),
    ('C:\\foo.exe,-100',          ('C:\\foo.exe', -100)),
    ('C:\\bar.ico',               ('C:\\bar.ico', 0)),
    ('"C:\\baz.dll"',             ('C:\\baz.dll', 0)),
    ('',                           ('', 0)),
]
for inp, expected in cases:
    got = clean._parse_display_icon(inp)
    print(f"  parse {inp!r:35s} -> {got}")
    assert got == expected, f"expected {expected}, got {got}"
print("_parse_display_icon OK")

# --- Extract icon from a guaranteed-present binary ---
cmd_exe = os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe")
pix = clean.extract_small_icon(cmd_exe)
print(f"cmd.exe icon: pix={pix}  is_null={pix is None or pix.isNull()}  size={pix.size() if pix else None}")
assert pix is not None and not pix.isNull(), "could not extract cmd.exe icon"
assert pix.width() == 16 and pix.height() == 16

# --- Enumerate live uninstall entries and try to extract icons for the first
#     30 that pass the default filter ---
ents = clean.enumerate_uninstall_entries()
visible = [e for e in ents if not e.system_component and not e.parent_key_name and e.display_name]
print(f"Visible entries: {len(visible)}")

ok = miss = 0
samples = []
for e in visible[:30]:
    fb = clean._extract_exe_from_command(e.uninstall_string or e.quiet_uninstall_string)
    if fb:
        fb = os.path.expandvars(fb)
    p = clean.extract_small_icon(e.display_icon, fb)
    if p is not None and not p.isNull():
        ok += 1
        samples.append((e.display_name, e.display_icon or fb, p.size()))
    else:
        miss += 1
print(f"Icons extracted: {ok}/30, missing: {miss}")
for name, src, sz in samples[:5]:
    print(f"  + {name[:40]:40s}  src={src!r:60.60s}  size={sz.width()}x{sz.height()}")
assert ok > 0, "expected at least one icon from a live entry"

# --- Verify UninstallPage uses the icons ---
SETTINGS = wintools.QSettings(
    os.path.join(os.environ["TEMP"], "wintools-selftest.ini"),
    wintools.QSettings.IniFormat)
SETTINGS.clear()
w = wintools.WintoolsWindow(SETTINGS)
un = dict(w.clean_pages)["Uninstall"]
# Force enumeration to complete synchronously enough by spinning the loop
from PyQt5.QtCore import QEventLoop, QTimer
loop = QEventLoop()
un._enum_worker.finished_all.connect(lambda *_: loop.quit())
QTimer.singleShot(30_000, loop.quit)
loop.exec_()
app.processEvents()

print(f"Uninstall tree items: {un.tree.topLevelItemCount()}")
icon_count = 0
for i in range(un.tree.topLevelItemCount()):
    it = un.tree.topLevelItem(i)
    if not it.icon(clean.UN_COL_NAME).isNull():
        icon_count += 1
print(f"Tree rows with icon set: {icon_count}")
assert icon_count > 0, "expected at least one row to have an icon"

# --- Banner color sanity ---
# (current process is not elevated in test runs)
central = w.centralWidget()
from PyQt5.QtWidgets import QFrame
banner = central.findChild(QFrame, "elevationBanner")
print(f"Banner found: {banner is not None}")
if banner is not None:
    ss = banner.styleSheet()
    print(f"Banner stylesheet snippet: {ss[:80]!r}")
    assert "#fff8b0" in ss
    print("Banner has yellow background.")

print()
print("STATUS: SUCCESS")
