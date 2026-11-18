"""Contract test for the Classic rows in initcfg and the Capture Classic
button.

The row checks only inspect initcfg.STEPS. The button checks build the page
over stub rows and a stubbed capture, so nothing real is read or written, and
this file never runs a New PC apply on this machine.
"""

import os
import sys
import threading
import time
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

import initcfg  # noqa: E402
import tweaks  # noqa: E402
import winclassic  # noqa: E402

CLASSIC = ("defenderep", "explorerpatcher", "openshell", "windhawk",
           "taskbartweaker", "classicappearance")

# ---- the row order ----
keys = initcfg.NEWPC_KEYS
assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]
assert len(initcfg.STEPS) == len(set(initcfg.STEPS)), initcfg.STEPS
assert "darkmode" not in initcfg.STEPS and "darkmode" not in keys
assert keys[-6:] == CLASSIC, keys[-6:]
assert initcfg.STEPS[-7:] == (*CLASSIC, initcfg.RESTART), initcfg.STEPS[-7:]
assert initcfg.STEPS[-8] == "logonanimation"
assert initcfg.STEPS[0] == "blackdesktop"
assert initcfg.RECYCLE in initcfg.STEPS
assert initcfg.STEPS.index(initcfg.RECYCLE) == initcfg.STEPS.index("desktopicons") + 1
print("row order ok:", len(initcfg.STEPS), "rows")

# ---- every classic row resolves to a step object, and none is a Tweaks page tweak ----
by_tweak = {t.key for t in tweaks.TWEAKS}
assert not by_tweak & set(CLASSIC), by_tweak & set(CLASSIC)
assert [s.key for s in winclassic.STEPS] == list(CLASSIC)
page_tweaks = {t.key for _tab, sections in tweaks.tabs() for _s, tw in sections for t in tw}
assert not page_tweaks & set(CLASSIC)
missing = [k for k in keys if k not in by_tweak | set(CLASSIC)]
assert not missing, missing
print("steps resolve ok")

# ---- the Capture Classic button ----
app = QApplication([])
# the New PC / Capture Classic warning is covered by test_confirm_guards.py
mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes).start()
trace = []


class StubStep:
    section = "Classic"

    def __init__(self, key, gate=None):
        self.key, self.label, self.gate, self.applied = key, key.title(), gate, 0

    def state(self):
        trace.append(self.key)
        return None

    def apply(self, on):
        self.applied += 1
        if self.gate is not None:
            assert self.gate.wait(20), "gate never opened"
        return 0


def wait_for(cond, what):
    end = time.time() + 20
    while not cond():
        app.processEvents()
        assert time.time() < end, f"timed out waiting for {what}"
        time.sleep(0.01)


gate = threading.Event()
stub = StubStep("defenderep", gate)
other = StubStep("openshell")
reports, calls = [], []
with mock.patch.object(initcfg, "STEPS", ("defenderep", "openshell", initcfg.RESTART)), \
        mock.patch.object(winclassic, "STEPS", (stub, other)), \
        mock.patch.object(tweaks, "TWEAKS", []):
    page = initcfg.InitConfigPage(reports.append, lambda: calls.append("refresh"),
                                  lambda: calls.append("restart"))
    assert page.btn.text() == "New PC"
    assert page.btn_capture.text() == "Capture Classic"
    layout = page.btn.parentWidget().layout()
    bottom = [layout.itemAt(i).layout() for i in range(layout.count())
              if layout.itemAt(i).layout() is not None][0]
    order = [bottom.itemAt(i).widget() for i in range(bottom.count())]
    assert order == [page.btn, page.btn_capture, page.status], order
    assert page.btn_capture.isEnabled() and page.btn.isEnabled()
    assert page.grid.rowCount() == 3
    assert page.grid.item(0, 0).text() == "Defenderep" and page.grid.item(0, 1).text() == "Classic"
    assert page.grid.item(0, 2).text() == "n/a"

    # every refresh drops the cached answers before it reads the first row
    trace.clear()
    with mock.patch.object(winclassic, "clear_cache", lambda: trace.append("clear")):
        page.refresh_states()
    assert trace == ["clear", "defenderep", "openshell"], trace

    # Capture Classic reports the count, and is not a New PC run
    with mock.patch.object(winclassic, "capture", return_value=6) as cap:
        page.btn_capture.click()
        wait_for(lambda: page.status.text() == "Captured 6 components", "capture status")
        assert cap.call_count == 1
        wait_for(page.btn.isEnabled, "buttons back")
        assert page.btn_capture.isEnabled()
    assert reports[-1] == "Captured 6 components", reports
    assert not stub.applied and not other.applied

    # a failed capture shows the error and re-enables both buttons
    with mock.patch.object(winclassic, "capture",
                           side_effect=FileNotFoundError(r"missing C:\x\y")):
        page.btn_capture.click()
        wait_for(lambda: page.status.text() == r"Capture failed: missing C:\x\y", "error status")
        wait_for(page.btn.isEnabled, "buttons back")
        assert page.btn_capture.isEnabled()
    with mock.patch.object(winclassic, "capture", side_effect=ValueError("bad type LINK")):
        page.btn_capture.click()
        wait_for(lambda: page.status.text() == "Capture failed: ValueError: bad type LINK", "error status")
        wait_for(page.btn.isEnabled, "buttons back")

    # New PC in progress disables Capture Classic; it comes back afterwards
    page.grid.item(2, 0).setCheckState(Qt.Unchecked)
    with mock.patch.object(winclassic, "capture") as cap:
        page.btn.click()
        assert not page.btn.isEnabled() and not page.btn_capture.isEnabled()
        page.btn_capture.click()
        app.processEvents()
        assert not cap.called
        gate.set()
        wait_for(page.btn.isEnabled, "New PC run")
        assert page.btn_capture.isEnabled()
    assert stub.applied == 1 and other.applied == 1
    assert page.status.text().startswith("2 applied   0 failed"), page.status.text()

    # a capture in progress disables New PC
    started, release = threading.Event(), threading.Event()

    def slow_capture():
        started.set()
        assert release.wait(20)
        return 6

    with mock.patch.object(winclassic, "capture", slow_capture):
        page.btn_capture.click()
        wait_for(started.is_set, "capture start")
        assert not page.btn.isEnabled() and not page.btn_capture.isEnabled()
        release.set()
        wait_for(lambda: page.status.text() == "Captured 6 components", "capture done")
        wait_for(page.btn.isEnabled, "buttons back")
    page.shutdown()
print("Capture Classic button ok")

# ---- a capture from another PC or update is applied only once confirmed, for that run ----
REASONS = ["captured on OTHERPC, this is THISPC", "UBR 3958, capture is 4249"]
accepted, seen = [], []
classic = winclassic.Step("windhawk", "Windhawk", lambda: seen.append(list(accepted)),
                          lambda: None)
with mock.patch.object(initcfg, "STEPS", ("windhawk",)), \
        mock.patch.object(winclassic, "STEPS", (classic,)), \
        mock.patch.object(tweaks, "TWEAKS", []), \
        mock.patch.object(winclassic, "accept_mismatch", accepted.append):
    page = initcfg.InitConfigPage(lambda text: None, lambda: None, lambda: None)
    for answer, accepts in ((QMessageBox.Yes, True), (QMessageBox.No, False)):
        accepted.clear()
        seen.clear()
        with mock.patch.object(winclassic, "capture_mismatch", return_value=REASONS), \
                mock.patch.object(QMessageBox, "question", return_value=answer) as q:
            page.btn.click()
            wait_for(page.btn.isEnabled, "New PC run")
        assert q.call_count == 1 and all(r in q.call_args[0][2] for r in REASONS), q.call_args
        # Enter must mean No
        assert q.call_args[0][3:5] == (QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        during = [None, REASONS] if accepts else [None]
        assert seen == [during], seen
        assert accepted == [*during, None], accepted
    # nothing to confirm, or no capture to read: no question
    for mismatch in (mock.Mock(return_value=[]), mock.Mock(side_effect=OSError("missing"))):
        with mock.patch.object(winclassic, "capture_mismatch", mismatch), \
                mock.patch.object(QMessageBox, "question") as q:
            page.btn.click()
            wait_for(page.btn.isEnabled, "New PC run")
        assert mismatch.called and not q.called
    page.shutdown()

# rows that are not classic steps never read the capture
with mock.patch.object(initcfg, "STEPS", ("defenderep",)), \
        mock.patch.object(winclassic, "STEPS", (StubStep("defenderep"),)), \
        mock.patch.object(tweaks, "TWEAKS", []), \
        mock.patch.object(winclassic, "capture_mismatch") as mismatch:
    page = initcfg.InitConfigPage(lambda text: None, lambda: None, lambda: None)
    page.btn.click()
    wait_for(page.btn.isEnabled, "New PC run")
    assert not mismatch.called
    page.shutdown()
print("capture mismatch confirmation ok")
print("STATUS: SUCCESS")
