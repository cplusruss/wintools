"""Synthetic test for the Startup tab (startup.py).

Run keys, the StartupApproved key and the Startup folder all point at scratch
locations (HKCU\\Software\\wintools-selftest-startup and a temp folder), so no
real startup entry is read or changed. Tasks and services are scanned
read-only against the real machine.
"""

import os
import shutil
import sys
import tempfile
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import win32com.client  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import clean  # noqa: E402
import startup  # noqa: E402

app = QApplication.instance() or QApplication([])

HKCU = winreg.HKEY_CURRENT_USER
BASE = r"Software\wintools-selftest-startup"
RUN = BASE + r"\Run"
APPROVED = BASE + r"\Approved"
FOLDER = tempfile.mkdtemp(prefix="wintools-startup-")
BACKUP = tempfile.mkdtemp(prefix="wintools-startup-bk-")
# not notepad.exe: classic Notepad is an optional feature and may be removed
EXE = os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe")


def teardown():
    try:
        clean.reg_delete_recursive(HKCU, BASE)
    except OSError:
        pass


teardown()
roots = startup.Roots(run=((HKCU, RUN, "Run", "Run (test)"),),
                      folders=((HKCU, FOLDER, "Folder (test)"),),
                      approved=APPROVED, services_record=BASE + r"\Services",
                      tasks=False, services=False)

with winreg.CreateKey(HKCU, RUN) as k:
    winreg.SetValueEx(k, "Notepad Test", 0, winreg.REG_SZ, f'"{EXE}" /A')
    winreg.SetValueEx(k, "Gone Test", 0, winreg.REG_SZ, r'"C:\nope\missing.exe" -x')
    winreg.SetValueEx(k, "Rundll Test", 0, winreg.REG_SZ,
                      r"rundll32.exe C:\nope\thing.dll,Start")
link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(
    os.path.join(FOLDER, "Note Link.lnk"))
link.TargetPath = EXE
link.Arguments = "/B"
link.Save()
Path(FOLDER, "desktop.ini").write_text("[.ShellClassInfo]\n")

try:
    # ---- helpers ----
    assert startup.target_of(f'"{EXE}" /A') == EXE
    assert startup.target_of(r"rundll32.exe C:\nope\thing.dll,Start") == r"C:\nope\thing.dll"
    assert startup.target_of("cmd.exe /c x").lower().endswith(r"system32\cmd.exe")
    assert startup.publisher(EXE).startswith("Microsoft")
    print("helpers ok")

    # ---- scan ----
    by = {e.name: e for e in startup.scan(roots)}
    assert set(by) == {"Notepad Test", "Gone Test", "Rundll Test", "Note Link"}, set(by)
    assert all(e.enabled for e in by.values())
    assert by["Gone Test"].missing and not by["Notepad Test"].missing
    assert by["Notepad Test"].microsoft
    assert by["Note Link"].kind == "folder" and by["Note Link"].target.lower() == EXE.lower()
    assert "/B" in by["Note Link"].command
    print("scan ok:", sorted(by))

    # ---- disable / enable the Task Manager way ----
    def approved(name):
        with winreg.OpenKey(HKCU, APPROVED + "\\" + ("Run" if name != "Note Link.lnk"
                                                      else "StartupFolder")) as k:
            return winreg.QueryValueEx(k, name)[0]

    for name, value in (("Notepad Test", "Notepad Test"), ("Note Link", "Note Link.lnk")):
        startup.set_enabled(by[name], False, roots)
        assert approved(value)[0] == 3 and len(approved(value)) == 12
        assert not {e.name: e for e in startup.scan(roots)}[name].enabled
        startup.set_enabled(by[name], True, roots)
        assert approved(value)[0] == 2
        assert {e.name: e for e in startup.scan(roots)}[name].enabled
    with winreg.OpenKey(HKCU, RUN) as k:   # the Run value itself is untouched
        assert winreg.QueryValueEx(k, "Notepad Test")[0] == f'"{EXE}" /A'
    print("enable/disable ok")

    # ---- page: hide Microsoft, filter, toggle by checkbox ----
    page = startup.StartupPage(roots=roots)
    page.reload()
    names = lambda: [page.tree.topLevelItem(i).text(0)  # noqa: E731
                     for i in range(page.tree.topLevelItemCount())]
    assert "Notepad Test" not in names() and "Gone Test" in names(), names()
    page.cb_hide_ms.setChecked(False)
    assert {"Notepad Test", "Note Link"} <= set(names())
    page.edt_filter.setText("gone")
    assert names() == ["Gone Test"], names()
    item = page.tree.topLevelItem(0)
    assert item.foreground(0).color().name() == "#b00000", "missing file not flagged"
    item.setCheckState(0, Qt.Unchecked)
    assert approved("Gone Test")[0] == 3
    assert "Disabled Gone Test" in page.status.text(), page.status.text()
    print("page ok:", page.status.text())

    # ---- delete with backup ----
    page.edt_filter.setText("")
    for i in range(page.tree.topLevelItemCount()):
        it = page.tree.topLevelItem(i)
        it.setSelected(it.text(0) in ("Gone Test", "Note Link"))
    startup.clean.REG_BACKUP_DIR = Path(BACKUP)
    assert page.delete_selected(confirm=False) == ""
    left = {e.name for e in startup.scan(roots)}
    assert left == {"Notepad Test", "Rundll Test"}, left
    saved = [f for d in os.listdir(BACKUP) for f in os.listdir(os.path.join(BACKUP, d))]
    assert "Note Link.lnk" in saved and any(f.endswith(".reg") for f in saved), saved
    try:
        approved("Gone Test")
        raise AssertionError("StartupApproved value left behind")
    except FileNotFoundError:
        pass
    print("delete ok:", saved)

    # ---- real tasks and services, read-only ----
    tasks = startup.scan_tasks()
    services = startup.scan_services()
    assert all(e.kind == "task" and e.key.startswith("\\") for e in tasks)
    assert services and all(e.kind == "service" for e in services)
    assert not startup.deletable(services[0])
    print(f"real scan ok: {len(tasks)} boot/logon tasks, {len(services)} services")
finally:
    teardown()
    shutil.rmtree(FOLDER, ignore_errors=True)
    shutil.rmtree(BACKUP, ignore_errors=True)

print("STATUS: SUCCESS")
