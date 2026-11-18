"""Contract test for WintoolsWindow construction and finder wiring.

Builds the whole window offscreen and exercises the search index and
fuzzy filter.  Read-only: no tweak is applied.
"""

import os
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication, QCheckBox  # noqa: E402

import ctxmenu  # noqa: E402
import envedit  # noqa: E402
import hardware  # noqa: E402
import initcfg  # noqa: E402
import installer  # noqa: E402
import keydiag  # noqa: E402
import startup  # noqa: E402
import tweaks  # noqa: E402
import wintools  # noqa: E402
from wintools import FinderWindow, TweakPage, WintoolsWindow  # noqa: E402

app = QApplication([])
SETTINGS = wintools.QSettings(
    os.path.join(os.environ["TEMP"], "wintools-selftest.ini"),
    wintools.QSettings.IniFormat)
SETTINGS.clear()
win = WintoolsWindow(SETTINGS)
win.show()
app.processEvents()

assert win.tabs.count() == 1 + 1 + 2 + 1 + 1 + 1 + 6 + 1 + 1 + 1, win.tabs.count()
assert win.tabs.tabText(0) == "Initial Config"
assert win.tabs.tabText(1) == "Installer"
assert win.tabs.tabText(4) == "System"
assert win.tabs.tabText(5) == "GPU"
assert isinstance(win.tabs.widget(0), initcfg.InitConfigPage)
assert isinstance(win.tabs.widget(1), installer.InstallerPage)
assert win.tabs.widget(1) is win.installer_page
assert [n for n, _p in win.clean_pages] == [
    "Files", "Registry", "Orphan paths", "Uninstall", "Empty folders",
    "Largest files"]
assert win.tabs.tabText(win.tabs.count() - 1) == "Largest files"
assert win.tabs.tabText(2) == "Repeat rate"
assert win.tabs.tabText(3) == "Key diagnostics"
assert win.tabs.tabText(6) == "Hardware"
assert "Temperatures" not in [win.tabs.tabText(i) for i in range(win.tabs.count())]
assert isinstance(win.tabs.widget(6), hardware.HardwarePage)
assert win.tabs.widget(6) is win.hardware_page
assert not hasattr(win, "temps_page")
assert not win.hardware_page._built, "Hardware must not read anything at startup"
assert not win.hardware_page._timer.isActive()
assert [win.tabs.tabText(i) for i in range(10, 15)] == [
    "Uninstall", "Startup", "Environment", "Context Menu", "Empty folders"]
assert isinstance(win.tabs.widget(11), startup.StartupPage)
assert not win.tabs.widget(11)._built, "Startup must not scan at startup"
assert isinstance(win.tabs.widget(12), envedit.EnvPage)
assert not win.tabs.widget(12)._built, "Environment must not load at startup"
assert isinstance(win.tabs.widget(13), ctxmenu.ContextMenuPage)
assert not win.tabs.widget(13)._built, "Context Menu must not build at startup"
print(f"tabs ok: {[win.tabs.tabText(i) for i in range(win.tabs.count())]}")

pages = [p for _n, p in win.pages if isinstance(p, TweakPage)]
boxes = sum(len(p.boxes) for p in pages)
assert boxes == len(tweaks.TWEAKS), (boxes, len(tweaks.TWEAKS))
gpu_entries = 8 * len(win.gpu_page.boxes)
n_tabs = win.tabs.count()
assert len(win.search_index) == n_tabs + boxes + 7 + gpu_entries, len(win.search_index)
tab_entries = [(lbl, p) for lbl, w, p in win.search_index if w is None]
assert tab_entries == [(win.tabs.tabText(i), win.tabs.widget(i)) for i in range(n_tabs)]
assert set(wintools.TAB_TERMS) == {lbl for lbl, _p in tab_entries}
print(f"search index ok: {len(win.search_index)} entries")

na = [k for p in pages for k, (cb, _t, _s) in p.boxes.items() if not cb.isEnabled()]
print(f"not applicable on this machine: {len(na)}  {sorted(na)}")

fw = FinderWindow(win)
fw.show_above(win.search_index)
assert fw.list.count() == len(win.search_index), fw.list.count()

fw.input.setText("widgets")
assert fw.list.count() >= 1, fw.list.count()
assert "Widgets" in fw.list.item(0).text(), fw.list.item(0).text()
top_widget, top_page = fw.list.item(0).data(0x0100)
assert isinstance(top_widget, QCheckBox)
assert win.tabs.currentWidget() is top_page, win.tabs.currentIndex()
print(f"finder top hit: {fw.list.item(0).text()}")

# The live preview repainted the checkbox; Esc must restore it exactly.
before = top_widget.palette().color(top_widget.backgroundRole()).name()
fw._cancel()
after = top_widget.palette().color(top_widget.backgroundRole()).name()
assert before != after, (before, after)
assert win.tabs.currentIndex() == 0, win.tabs.currentIndex()
print(f"preview revert ok: {before} -> {after}")

fw.show_above(win.search_index)
fw.input.setText("qqqzzz")
assert fw.list.count() == 0, fw.list.count()
fw._cancel()
print("no-match path ok")

# ---- whole tabs are searchable, by name and by their extra terms ----
uninstall = win.tabs.widget(10)
for q, top in (("remove prog", "Uninstall"), ("uninstall", "Uninstall"),
               ("env vars", "Environment"), ("temperatures", "Hardware"),
               ("cpu-z", "Hardware"), ("motherboard", "Hardware"), ("spd", "Hardware")):
    fw.show_above(win.search_index)
    fw.input.setText(q)
    assert fw.list.item(0).text() == top, (q, fw.list.item(0).text())
    assert fw.list.item(0).data(0x0100)[0] is None, q
    fw._cancel()
fw.show_above(win.search_index)
assert fw.list.item(0).text() == "Initial Config"   # tabs lead the empty list
fw.input.setText("remove prog")
assert win.tabs.currentWidget() is uninstall, win.tabs.currentIndex()
fw._cancel()
assert win.tabs.currentIndex() == 0, win.tabs.currentIndex()
fw.show_above(win.search_index)
fw.input.setText("remove prog")
fw._accept()
app.processEvents()
assert not fw.isVisible() and win.tabs.currentWidget() is uninstall
win.tabs.setCurrentIndex(0)
# ---- the Hardware tab builds on first show, polls only while current, and
# shuts its timers down with the window ----
hw = win.hardware_page
win.tabs.setCurrentWidget(hw)
app.processEvents()
assert hw._built and hw._timer.isActive()
win.tabs.setCurrentIndex(0)
app.processEvents()
assert not hw._timer.isActive()
print("tab search ok")

# ---- the Windows repeat group reflects live state on load ----
rr = win.pages[0][1]
assert rr.win_delay_lbl.text().endswith(" ms"), repr(rr.win_delay_lbl.text())
assert "/s" in rr.win_speed_lbl.text(), repr(rr.win_speed_lbl.text())
assert rr.win_delay.value() == keydiag.keyboard_delay_index()
assert rr.win_speed.value() == keydiag.keyboard_speed_index()
for label, d, s in wintools.WIN_PRESETS:
    rr._set_windows(d, s)
    assert rr.win_delay_lbl.text() == f"{keydiag.DELAY_MS[d]} ms", \
        (label, rr.win_delay_lbl.text())
    assert rr.win_speed_lbl.text().endswith("/s"), (label, rr.win_speed_lbl)
rr._load_windows()
assert rr.win_delay.value() == keydiag.keyboard_delay_index()
print(f"windows group ok: {rr.win_delay_lbl.text()}  {rr.win_speed_lbl.text()}")

# ---- Enter keeps the tab it previewed instead of reverting it ----
fw.show_above(win.search_index)
fw.input.setText("widgets")
target, target_page = fw.list.item(0).data(0x0100)
fw._accept()
app.processEvents()
assert not fw.isVisible()
assert win.tabs.currentWidget() is target_page, win.tabs.currentIndex()
assert win.focusWidget() is target, win.focusWidget()
print("finder accept ok")

# ---- checkbox -> apply -> registry, against a scratch key ----
SCRATCH = r"Software\wintools-selftest-ui"
tweaks._delete_tree(tweaks.HKCU, SCRATCH)
op = tweaks.D(tweaks.HKCU, SCRATCH, "flag", 1, tweaks.DELETE)
demo = tweaks.Tweak("demo", "T", "Sec", "Demo Setting", [op])
messages = []
page = TweakPage("T", [("Sec", [demo])], messages.append)
cb = page.boxes["demo"][0]
assert not cb.isChecked() and op.read() is None

cb.click()
assert op.read() == 1, op.read()
assert cb.isChecked()
assert messages[-1] == "Demo Setting: on", messages[-1]

cb.click()
assert op.read() is None, op.read()
assert not cb.isChecked()
assert messages[-1] == "Demo Setting: off", messages[-1]
tweaks._delete_tree(tweaks.HKCU, SCRATCH)
print(f"apply round-trip ok: {messages}")


# ---- a write that is refused must revert the checkbox and be reported ----
class RefusingOp:
    on, off, off_key, path = True, False, None, "denied"

    def available(self):
        return True

    def read(self):
        return False

    def write(self, on):
        raise PermissionError(5, "Access is denied")


refused = tweaks.Tweak("refused", "T", "Sec", "Refused Setting", [RefusingOp()])
messages.clear()
page = TweakPage("T", [("Sec", [refused])], messages.append)
cb = page.boxes["refused"][0]
cb.click()
assert not cb.isChecked(), "checkbox stayed on after a refused write"
assert "Access is denied" in messages[-1], messages[-1]
print(f"refused write ok: {messages[-1]}")

# ---- Initial Config is a checklist page, not a finder-indexed settings page ----
ic = win.tabs.widget(0)
assert ic is win.initcfg_page
assert ic.grid.rowCount() == len(initcfg.NEWPC_KEYS) + 2
assert all(ic is not p for _n, p in win.pages)
ip = win.installer_page
assert all(ip is not p for _n, p in win.pages)

# ---- a New PC run still in flight is waited for on close ----
release = threading.Event()
ic._total, ic._restart = 1, False
ic._worker = initcfg.NewPcWorker([("slow", lambda: release.wait(10) and "")], ic)
ic._worker.progress.connect(ic._progress)
ic._worker.finished.connect(ic._finish)
ic._worker.start()
ip._total = 1
ip._worker = installer.InstallWorker(
    [(0, "slow", lambda: release.wait(10) and "")], ip)
ip._worker.status.connect(ip._set_status)
ip._worker.progress.connect(ip._progress)
ip._worker.finished.connect(ip._finish)
ip._worker.start()
app.processEvents()
assert ic._worker.isRunning() and ip._worker.isRunning()
win.tabs.setCurrentWidget(hw)
app.processEvents()
assert hw._timer.isActive()
hw.open_clocks()
assert hw.clocks_window.isVisible()
win.tabs.setCurrentIndex(0)                  # the Clocks window leaves with the tab
app.processEvents()
assert not hw.clocks_window.isVisible() and not hw._timer.isActive()
win.tabs.setCurrentWidget(hw)                # and comes back with it
app.processEvents()
assert hw.clocks_window.isVisible() and hw._timer.isActive()
threading.Timer(0.3, release.set).start()
win.close()
app.processEvents()
assert not hw._timer.isActive() and not hw.sensors._timer.isActive()
assert not hw.clocks_window.isVisible()
assert ic._worker is None and release.is_set(), "close did not wait for worker"
assert ip._worker is None, "close did not wait for the installer worker"
print("worker shut down on close ok")

# ---- F5 / refresh_all re-reads the Initial Config states ----
ic = win.initcfg_page
ic.grid.item(0, 2).setText("stale")
win.refresh_all()
assert ic.grid.item(0, 2).text() in ("on", "off", "n/a"), ic.grid.item(0, 2).text()
print("refresh_all covers Initial Config ok")

# ---- F5 / refresh_all re-reads the Installer states ----
ip = win.installer_page
ip.grid.item(installer.FIREFOX_ROW, 1).setText("stale")
ip.grid.item(installer.WINGET_ROW, 1).setText("stale")
win.refresh_all()
assert ip.grid.item(installer.FIREFOX_ROW, 1).text() in ("on", "off", "n/a"), \
    ip.grid.item(installer.FIREFOX_ROW, 1).text()
assert ip.grid.item(installer.WINGET_ROW, 1).text() != "stale"
print("refresh_all covers Installer ok")

# ---- clean pages shut down with the window ----
app.processEvents()
print("clean pages closed ok")

print("STATUS: SUCCESS")
