"""Contract test for clean.UninstallRunWorker.

The fixture's uninstaller mimics Inno/NSIS: it starts a detached copy that
deletes the uninstall key two seconds later, then exits at once. finished_all
must not fire until that copy is done, or the page refreshes too early.
"""
import os
import sys
import tempfile
import winreg

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

from clean import (UninstallRunWorker, enumerate_uninstall_entries,
                   reg_delete_recursive, reg_key_info)

PARENT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
TAG = "__clean_test_relaunch__"
KEY = PARENT + "\\" + TAG
HIVE = winreg.HKEY_CURRENT_USER

try:
    reg_delete_recursive(HIVE, KEY)
except OSError:
    pass

tmp = tempfile.mkdtemp(prefix="clean-relaunch-")
second_stage = os.path.join(tmp, "stage2.py")
with open(second_stage, "w") as f:
    f.write(
        "import time, winreg\n"
        "time.sleep(2)\n"
        f"winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r'{KEY}')\n")
cmd = f'start "" /b "{sys.executable}" "{second_stage}"'

winreg.CreateKey(HIVE, KEY)
with winreg.OpenKey(HIVE, KEY, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "Clean Test - Relaunch")
    winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, cmd)

entry = next(e for e in enumerate_uninstall_entries() if e.sub_name == TAG)

app = QApplication.instance() or QApplication([])
worker = UninstallRunWorker([entry], use_quiet=False)
result = []
loop = QEventLoop()
worker.finished_all.connect(lambda ok, fail: (
    result.append((ok, fail, reg_key_info(HIVE, KEY))), loop.quit()))
worker.start()
QTimer.singleShot(30_000, loop.quit)
loop.exec_()
worker.wait(5000)

try:
    assert result, "run worker did not finish in 30s"
    ok, fail, key_info = result[0]
    print(f"  ok={ok} fail={fail} key_after_finish={key_info}")
    assert (ok, fail) == (1, 0), (ok, fail)
    assert key_info is None, "finished_all fired before the relaunched uninstaller exited"
finally:
    try:
        reg_delete_recursive(HIVE, KEY)
    except OSError:
        pass
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("STATUS: SUCCESS")
