"""Contract test for the warning that guards New PC, Capture Classic and Install.

Each button asks first with a Yes/No warning whose default is No; No starts
nothing. Pages are built over stub rows and stubbed workers, so nothing on
this machine is read for real or changed.
"""

import os
import sys
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

import initcfg  # noqa: E402
import installer  # noqa: E402
import tweaks  # noqa: E402
import winclassic  # noqa: E402

app = QApplication([])
YES_NO = (QMessageBox.Yes | QMessageBox.No, QMessageBox.No)


class Stub:
    section = "Classic"

    def __init__(self, key):
        self.key, self.label, self.applied = key, key.title(), 0

    def state(self):
        return None

    def apply(self, on):
        self.applied += 1
        return 0


def classic(key, label):
    return winclassic.Step(key, label, lambda: None, lambda: None)


# ---- New PC: warns with the step count, the classic rows and the restart ----
ep, ws, tw = classic("explorerpatcher", "ExplorerPatcher"), classic("windhawk", "Windhawk"), Stub("fileext")
with mock.patch.object(initcfg, "STEPS", ("fileext", "explorerpatcher", "windhawk", initcfg.RESTART)), \
        mock.patch.object(winclassic, "STEPS", (ep, ws)), \
        mock.patch.object(tweaks, "TWEAKS", [tw]), \
        mock.patch.object(winclassic, "capture_mismatch", return_value=[]):
    page = initcfg.InitConfigPage(lambda t: None, lambda: None, lambda: None)
    with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.No) as w, \
            mock.patch.object(initcfg, "NewPcWorker") as worker:
        page.btn.click()
    assert w.call_count == 1 and not worker.called and not tw.applied
    title, text = w.call_args[0][1:3]
    assert title == "New PC", title
    assert text.startswith("Apply 4 steps to this PC?"), text
    assert "ExplorerPatcher" in text and "Windhawk" in text and "Restart Explorer" in text, text
    assert w.call_args[0][3:5] == YES_NO, w.call_args
    assert page.btn.isEnabled() and page.status.text() == ""

    # Yes runs the plan
    with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes), \
            mock.patch.object(initcfg, "NewPcWorker") as worker:
        page.btn.click()
    assert worker.called
    page._worker = None
    page._set_busy(False)

    # no classic row checked: no classic labels in the warning
    for r, s in enumerate(initcfg.STEPS):
        if s in ("explorerpatcher", "windhawk"):
            page.grid.item(r, 0).setCheckState(0)
    with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.No) as w:
        page.btn.click()
    text = w.call_args[0][2]
    assert text.startswith("Apply 2 steps to this PC?") and "Windhawk" not in text, text

    # nothing checked: no warning, nothing runs
    for r in range(page.grid.rowCount()):
        page.grid.item(r, 0).setCheckState(0)
    with mock.patch.object(QMessageBox, "warning") as w:
        page.btn.click()
    assert not w.called
    page.shutdown()
print("New PC warning ok")

# ---- Capture Classic: warns with the capture it replaces ----
with mock.patch.object(initcfg, "STEPS", ("explorerpatcher",)), \
        mock.patch.object(winclassic, "STEPS", (ep,)), \
        mock.patch.object(tweaks, "TWEAKS", []):
    page = initcfg.InitConfigPage(lambda t: None, lambda: None, lambda: None)
    man = {"captured": "2026-10-14T09:00:00-05:00", "computer": "THISPC",
           "build": 22631, "ubr": 4249}
    with mock.patch.object(winclassic, "load_manifest", return_value=man), \
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.No) as w, \
            mock.patch.object(initcfg, "CaptureWorker") as cap:
        page.btn_capture.click()
    assert w.call_count == 1 and not cap.called
    title, text = w.call_args[0][1:3]
    assert title == "Capture Classic", title
    assert "2026-10-14T09:00:00-05:00" in text and "THISPC" in text and "22631.4249" in text, text
    assert w.call_args[0][3:5] == YES_NO
    assert page.btn_capture.isEnabled() and page.status.text() == ""

    # a capture written before manifests named the computer
    old = {k: v for k, v in man.items() if k != "computer"}
    with mock.patch.object(winclassic, "load_manifest", return_value=old), \
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.No) as w:
        page.btn_capture.click()
    text = w.call_args[0][2]
    assert "2026-10-14T09:00:00-05:00" in text and "22631.4249" in text, text

    # no capture yet: still asks, without a capture to name
    with mock.patch.object(winclassic, "load_manifest", side_effect=FileNotFoundError("manifest.json")), \
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes) as w, \
            mock.patch.object(initcfg, "CaptureWorker") as cap:
        page.btn_capture.click()
    assert w.call_count == 1 and cap.called
    assert "THISPC" not in w.call_args[0][2]
    page._capturer = None
    page.shutdown()
print("Capture Classic warning ok")

# ---- Install: warns with the packages it installs ----
with mock.patch.object(installer, "winget_version", return_value="v1.29"), \
        mock.patch.object(installer, "installed_versions",
                          return_value=[None] * len(installer.PACKAGES)), \
        mock.patch.object(tweaks.Tweak, "state", return_value=True):
    page = installer.InstallerPage(lambda t: None, lambda: None)
    checked = page.checked_rows()
    names = [page.grid.item(r, 0).text() for r in checked]
    assert names, "no package row checked"
    with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.No) as w, \
            mock.patch.object(installer, "prompt_password") as pw, \
            mock.patch.object(installer, "InstallWorker") as worker:
        page.btn_install.click()
    assert w.call_count == 1 and not worker.called and not pw.called
    title, text = w.call_args[0][1:3]
    assert title == "Install", title
    assert text.startswith(f"Install {len(names)} items on this PC?"), text
    assert all(n in text for n in names), text
    assert w.call_args[0][3:5] == YES_NO
    assert all(page.grid.item(r, 2).text() == "" for r in checked)
    assert page.btn_install.isEnabled()
print("Install warning ok")
print("STATUS: SUCCESS")
