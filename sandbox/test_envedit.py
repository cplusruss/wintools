"""Synthetic test for the Environment tab (envedit.py).

Both scopes point at scratch keys under HKCU\\Software\\wintools-selftest-env and
snapshots go to a temp folder; the real Environment keys are compared before
and after, and the broadcast is stubbed.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import clean  # noqa: E402
import envedit  # noqa: E402

app = QApplication.instance() or QApplication([])
HKCU = winreg.HKEY_CURRENT_USER
BASE = r"Software\wintools-selftest-env"
SYS, USR = BASE + r"\System", BASE + r"\User"
SNAPS = Path(tempfile.mkdtemp(prefix="wintools-env-snaps-"))
roots = envedit.Roots(system=(HKCU, SYS), user=(HKCU, USR), snapshots=SNAPS)
WINDIR = os.environ["SystemRoot"]


def real_env():
    return envedit.load()


def values(key):
    with winreg.OpenKey(HKCU, key) as k:
        out, i = {}, 0
        while True:
            try:
                n, v, t = winreg.EnumValue(k, i)
            except OSError:
                return out
            out[n] = (v, t)
            i += 1


def teardown():
    try:
        clean.reg_delete_recursive(HKCU, BASE)
    except OSError:
        pass


broadcasts = []
envedit.broadcast = lambda: broadcasts.append(1) or True
before_real = real_env().as_json()
saved_environ = dict(os.environ)
teardown()
for key, vals in ((SYS, {"Path": (fr"{WINDIR}\system32;%SystemRoot%;C:\nope\missing", winreg.REG_EXPAND_SZ),
                         "ComSpec": (r"%SystemRoot%\system32\cmd.exe", winreg.REG_EXPAND_SZ),
                         "TOOL_HOME": (r"C:\nope\tool", winreg.REG_SZ)}),
                  (USR, {"Path": (fr"{WINDIR}\System32", winreg.REG_EXPAND_SZ),
                         "TEMP": (r"%USERPROFILE%\AppData\Local\Temp", winreg.REG_EXPAND_SZ)})):
    with winreg.CreateKey(HKCU, key) as k:
        for name, (v, t) in vals.items():
            winreg.SetValueEx(k, name, 0, t, v)

try:
    # ---- load, markers ----
    env = envedit.load(roots)
    assert env.system["path"].entries == [fr"{WINDIR}\system32", "%SystemRoot%", r"C:\nope\missing"]
    assert envedit.entry_state(r"C:\nope\missing", None) == "missing"
    assert envedit.entry_state(r"%SystemRoot%\system32", None) == ""
    assert envedit.entry_state(".COM", None) == ""
    print("load ok")

    page = envedit.EnvPage(roots=roots)
    page.reload()
    sys_tree, usr_tree = page.trees["system"], page.trees["user"]
    path_item = next(it for it in page._top(sys_tree) if it.text(0) == "Path")
    assert path_item.childCount() == 3 and "1 missing" in path_item.text(1), path_item.text(1)
    assert path_item.child(2).foreground(1).color().name() == "#b00000"
    assert not page.pending()
    assert len(envedit.snapshots(roots)) == 1, "first look takes a snapshot"
    page.reload()
    assert len(envedit.snapshots(roots)) == 1, "an unchanged environment is not snapshotted again"
    print("page ok:", page.status.text())

    # ---- edit: remove missing, reorder, add entry, add variable ----
    path_item = next(it for it in page._top(sys_tree) if it.text(0) == "Path")
    sys_tree.setFocus()
    sys_tree.clearSelection()
    path_item.setSelected(True)
    assert page.remove_missing() == 1
    path_item.child(1).setSelected(True)
    path_item.setSelected(False)
    page.move_entry(-1)
    assert [path_item.child(i).text(1) for i in range(2)] == ["%SystemRoot%", fr"{WINDIR}\system32"]
    sys_tree.clearSelection()
    path_item.child(1).setSelected(True)
    page.add_entry(r"C:\Tools\bin")
    page.add_variable("user", "NEW_VAR", r"%USERPROFILE%\x")
    labels = sorted(c.label for c in page.pending())
    assert labels == ["add user NEW_VAR", "change system Path"], labels

    # ---- save writes only the changes, keeps types ----
    assert page.save(confirm=False) == ""
    sv, uv = values(SYS), values(USR)
    assert sv["Path"] == (fr"%SystemRoot%;{WINDIR}\system32;C:\Tools\bin", winreg.REG_EXPAND_SZ), sv["Path"]
    assert sv["TOOL_HOME"] == (r"C:\nope\tool", winreg.REG_SZ), "untouched value changed"
    assert uv["NEW_VAR"] == (r"%USERPROFILE%\x", winreg.REG_EXPAND_SZ)
    page._refresh_thread.join(5)
    app.processEvents()
    assert broadcasts, "save did not refresh the environment"
    assert os.environ.get("NEW_VAR") == os.path.expandvars(r"%USERPROFILE%\x"), "process env not reloaded"
    snaps = [envedit.read_snapshot(p).as_json() for p in envedit.snapshots(roots)]
    assert env.as_json() in snaps, "pre-save state not in any snapshot"
    assert envedit.load(roots).as_json() in snaps, "saved state not snapshotted"
    assert not page.pending()
    print("save ok:", page.status.text())

    # ---- the broadcast runs off the UI thread: save returns before it ends ----
    gate = threading.Event()
    envedit.broadcast = lambda: gate.wait(10) and broadcasts.append(1) or True
    n = len(broadcasts)
    page.add_variable("user", "ASYNC_VAR", "x")
    t0 = time.perf_counter()
    assert page.save(confirm=False) == ""
    assert time.perf_counter() - t0 < 2, "save waited for the broadcast"
    assert page.status.text().startswith("Saved 1 change. Refreshing environment"), page.status.text()
    assert values(USR)["ASYNC_VAR"] == ("x", winreg.REG_SZ)
    gate.set()
    page._refresh_thread.join(5)
    app.processEvents()
    assert len(broadcasts) == n + 1
    assert page.status.text().startswith("Saved 1 change. Environment refreshed"), page.status.text()
    envedit.broadcast = lambda: broadcasts.append(1) or True
    print("async broadcast ok:", page.status.text())

    # ---- guards: empty system Path refused, critical removal needs a yes ----
    sys_tree.clearSelection()
    path_item = next(it for it in page._top(sys_tree) if it.text(0) == "Path")
    for i in range(path_item.childCount()):
        path_item.child(i).setSelected(True)
    page.delete_selected()
    assert page.save(confirm=False).startswith("Not saved: the system Path would be empty")
    assert values(SYS)["Path"][0].endswith(r"C:\Tools\bin"), "empty Path was written"
    page.reload()
    sys_tree.clearSelection()
    next(it for it in page._top(sys_tree) if it.text(0) == "ComSpec").setSelected(True)
    page.delete_selected()
    assert page.save(confirm=False) == "critical: ComSpec"
    assert "ComSpec" in values(SYS), "critical variable removed without a yes"
    print("guards ok")

    # ---- restore a snapshot ----
    first = envedit.snapshots(roots)[-1]          # oldest: the original state
    page.reload()
    assert page.restore_snapshot(str(first), confirm=False) == ""
    sv, uv = values(SYS), values(USR)
    assert sv["Path"][0] == fr"{WINDIR}\system32;%SystemRoot%;C:\nope\missing", sv["Path"]
    assert "NEW_VAR" not in uv
    print("restore ok:", page.status.text())

    # ---- the keys themselves are never deleted ----
    page.reload()
    for tree in page.trees.values():
        tree.clearSelection()
        for it in page._top(tree):
            if it.text(0) not in ("Path", "ComSpec"):
                it.setSelected(True)
        page.trees  # noqa: B018
    usr_tree.setFocus()
    page.delete_selected()
    page.save(confirm=False)
    assert winreg.OpenKey(HKCU, USR), "user key deleted"
    print("keys kept ok")
finally:
    teardown()
    shutil.rmtree(SNAPS, ignore_errors=True)
    os.environ.clear()
    os.environ.update(saved_environ)

assert real_env().as_json() == before_real, "the real Environment keys changed!"
print("real Environment untouched")
print("STATUS: SUCCESS")
