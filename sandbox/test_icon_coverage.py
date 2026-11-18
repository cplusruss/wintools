"""Compare icon coverage before vs after the new fallback chain.

Old path: extract_small_icon(display_icon, fallback_exe).
New path: extract_icon_for_entry(e, use_generic_fallback=True).
"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

import clean
import wintools

app = QApplication.instance() or QApplication([])

ents = clean.enumerate_uninstall_entries()
visible = [e for e in ents if not e.system_component and not e.parent_key_name and e.display_name]
print(f"Visible entries: {len(visible)}")

# ---- Old behavior ----
old_ok = 0
for e in visible:
    fb = clean._extract_exe_from_command(e.uninstall_string or e.quiet_uninstall_string)
    if fb:
        fb = os.path.expandvars(fb)
    p = clean.extract_small_icon(e.display_icon, fb)
    if p is not None and not p.isNull():
        old_ok += 1
print(f"Old coverage (DisplayIcon + UninstallString fallback): {old_ok}/{len(visible)} = "
      f"{100*old_ok/len(visible):.1f}%")

# ---- New behavior, without generic fallback (real icons only) ----
new_real = 0
for e in visible:
    p = clean.extract_icon_for_entry(e, use_generic_fallback=False)
    if p is not None and not p.isNull():
        new_real += 1
print(f"New coverage (real icons only):                          {new_real}/{len(visible)} = "
      f"{100*new_real/len(visible):.1f}%")

# ---- New behavior with generic fallback ----
t0 = time.perf_counter()
new_with_fb = 0
generic_used = 0
generic_pix = clean._extract_icon_from_path(*clean.GENERIC_ICON_SOURCE)
generic_bytes = generic_pix.toImage().bits().asstring(16*16*4) if generic_pix is not None else b""
for e in visible:
    p = clean.extract_icon_for_entry(e, use_generic_fallback=True)
    if p is not None and not p.isNull():
        new_with_fb += 1
        # Cheap-ish check for 'is this the generic fallback' by comparing the
        # 16x16 ARGB image bits (might miss in edge cases but good enough for
        # eyeballing).
        if generic_bytes and p.toImage().bits().asstring(16*16*4) == generic_bytes:
            generic_used += 1
dt = time.perf_counter() - t0
print(f"New coverage (with generic fallback):                     {new_with_fb}/{len(visible)} = "
      f"{100*new_with_fb/len(visible):.1f}%")
print(f"  ... of which generic-fallback icon:                     {generic_used} entries")
print(f"  wall-clock for all extractions (no cache):              {dt:.2f}s")

# ---- Through the UI (which uses cache) ----
t0 = time.perf_counter()
SETTINGS = wintools.QSettings(
    os.path.join(os.environ["TEMP"], "wintools-selftest.ini"),
    wintools.QSettings.IniFormat)
SETTINGS.clear()
w = wintools.WintoolsWindow(SETTINGS)
un = dict(w.clean_pages)["Uninstall"]
from PyQt5.QtCore import QEventLoop, QTimer
loop = QEventLoop()
un._enum_worker.finished_all.connect(lambda *_: loop.quit())
QTimer.singleShot(30_000, loop.quit)
loop.exec_()
app.processEvents()
dt = time.perf_counter() - t0
print(f"UI populated in {dt:.2f}s with caching")
icon_count = 0
for i in range(un.tree.topLevelItemCount()):
    it = un.tree.topLevelItem(i)
    if not it.icon(clean.UN_COL_NAME).isNull():
        icon_count += 1
print(f"Tree rows with icon: {icon_count}/{un.tree.topLevelItemCount()} = "
      f"{100*icon_count/max(un.tree.topLevelItemCount(),1):.1f}%")
assert icon_count == un.tree.topLevelItemCount(), "every row should have an icon now"
print()
print("STATUS: SUCCESS")
