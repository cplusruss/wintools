"""Synthetic test for the Uninstall tab logic in clean.py.

Creates fake uninstall entries under HKCU\\Software\\Microsoft\\Windows\\
CurrentVersion\\Uninstall\\__clean_test__* and verifies that:
  - enumerate_uninstall_entries picks them up
  - validity flag distinguishes a missing-exe entry from a real-msiexec entry
  - UninstallRemoveWorker deletes them cleanly with backup files written
"""
import os
import sys
import tempfile
import winreg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clean import (
    enumerate_uninstall_entries, reg_delete_recursive, reg_key_info,
    UninstallRemoveWorker, REG_BACKUP_DIR, _extract_exe_from_command,
    _check_uninstaller_validity, UninstallEntry,
)

UNINSTALL_PARENT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
HIVE = winreg.HKEY_CURRENT_USER
TAGS = ["__clean_test_valid_msi__", "__clean_test_invalid_missing__",
        "__clean_test_valid_real__"]


def mk_uninstall(sub, values: dict):
    key_path = UNINSTALL_PARENT + "\\" + sub
    winreg.CreateKey(HIVE, key_path)
    with winreg.OpenKey(HIVE, key_path, 0, winreg.KEY_SET_VALUE) as k:
        for name, value in values.items():
            if isinstance(value, int):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


# Tear down any leftovers from a prior run.
for tag in TAGS:
    try:
        reg_delete_recursive(HIVE, UNINSTALL_PARENT + "\\" + tag)
    except OSError:
        pass

# 1) Valid (MSI): UninstallString uses msiexec.
mk_uninstall(TAGS[0], {
    "DisplayName": "Clean Test - Fake MSI",
    "DisplayVersion": "1.0.0",
    "Publisher": "TestCo",
    "UninstallString": 'MsiExec.exe /X{00000000-0000-0000-0000-000000000000}',
    "WindowsInstaller": 1,
    "EstimatedSize": 1024,
})

# 2) Invalid: UninstallString points to a non-existent .exe.
bogus = r"C:\definitely\does\not\exist\nope_uninst.exe"
mk_uninstall(TAGS[1], {
    "DisplayName": "Clean Test - Orphaned Uninstaller",
    "DisplayVersion": "0.0.1",
    "Publisher": "TestCo",
    "UninstallString": f'"{bogus}" /S',
    "EstimatedSize": 512,
})

# 3) Valid (real exe): UninstallString points to a real Windows binary.
real_exe = os.environ.get("ComSpec", os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe"))
assert os.path.isfile(real_exe), f"test prerequisite missing: {real_exe}"
mk_uninstall(TAGS[2], {
    "DisplayName": "Clean Test - cmd.exe as Uninstaller",
    "DisplayVersion": "1.0",
    "Publisher": "TestCo",
    "UninstallString": f'"{real_exe}"',
    "EstimatedSize": 256,
})

# Sanity: _extract_exe_from_command + _check_uninstaller_validity on those strings.
print("=== Unit-level checks ===")
for raw in [
    'MsiExec.exe /X{00000000-0000-0000-0000-000000000000}',
    f'"{bogus}" /S',
    f'"{real_exe}"',
]:
    print(f"  parse {raw!r:80s} -> {_extract_exe_from_command(raw)!r}")

print()
print("=== Enumeration check ===")
ents = enumerate_uninstall_entries()
test_ents = {e.sub_name: e for e in ents if e.sub_name in TAGS}
assert set(test_ents.keys()) == set(TAGS), f"missing: {set(TAGS) - set(test_ents.keys())}"
for tag in TAGS:
    e = test_ents[tag]
    label = "yes" if e.is_valid else f"NO ({e.invalid_reason})"
    print(f"  {tag:42s}  is_valid={label}")

assert test_ents[TAGS[0]].is_valid, "MSI fixture should be valid"
assert not test_ents[TAGS[1]].is_valid, "Missing-exe fixture should be INvalid"
assert "missing" in test_ents[TAGS[1]].invalid_reason
assert test_ents[TAGS[2]].is_valid, "Real-exe (notepad) fixture should be valid"
print("  VALIDITY DETECTION OK")

print()
print("=== Removal (auto-backup) check ===")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QEventLoop, QTimer
app = QApplication.instance() or QApplication([])

# Remove only the invalid fixture for now, to exercise the worker on a single entry.
target = test_ents[TAGS[1]]
worker = UninstallRemoveWorker([target], do_backup=True)
errs = []
worker.item_error.connect(lambda w, e: errs.append((w, e)))
backup_folder_holder = []
worker.backup_done.connect(lambda folder, ok, fail: backup_folder_holder.append((folder, ok, fail)))

loop = QEventLoop()
result_holder = []
worker.finished_all.connect(lambda ok, fail: (result_holder.append((ok, fail)), loop.quit()))
worker.start()
QTimer.singleShot(30_000, loop.quit)
loop.exec_()

assert result_holder, "remove worker did not finish in 30s"
ok, fail = result_holder[0]
print(f"  remove worker: ok={ok} fail={fail} errs={errs}")
assert ok == 1 and fail == 0
assert backup_folder_holder, "no backup_done signal received"
backup_folder, b_ok, b_fail = backup_folder_holder[0]
print(f"  backup folder: {backup_folder}  ({b_ok} ok, {b_fail} fail)")
assert os.path.isdir(backup_folder)
backups = os.listdir(backup_folder)
print(f"  backup files: {backups}")
assert any(f.endswith(".reg") and "clean_test_invalid_missing" in f for f in backups)

# Verify the orphan key is gone but the valid ones remain.
assert reg_key_info(HIVE, UNINSTALL_PARENT + "\\" + TAGS[1]) is None, "invalid fixture not deleted"
assert reg_key_info(HIVE, UNINSTALL_PARENT + "\\" + TAGS[0]) is not None, "MSI fixture wrongly deleted"
assert reg_key_info(HIVE, UNINSTALL_PARENT + "\\" + TAGS[2]) is not None, "notepad fixture wrongly deleted"
print("  POST-REMOVE STATE OK")

print()
print("=== Silent command detection ===")
from dataclasses import replace
from clean import silent_command, UninstallPage, UN_COL_NAME, UN_COL_SILENT
from PyQt5.QtCore import Qt
msi = test_ents[TAGS[0]]
cmd, how = silent_command(msi)
assert how == "msi" and cmd == "MsiExec.exe /X{00000000-0000-0000-0000-000000000000} /passive /norestart", cmd
assert silent_command(replace(msi, quiet_uninstall_string="x.exe /quiet")) == ("x.exe /quiet", "quiet")
inno = replace(msi, uninstall_string=r'"C:\Program Files\App\unins000.exe"', is_msi=False)
assert silent_command(inno) == (r'"C:\Program Files\App\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART', "inno")
nsis_dir = tempfile.mkdtemp(prefix="clean-nsis-")
nsis_exe = os.path.join(nsis_dir, "uninst.exe")
with open(nsis_exe, "wb") as f:
    f.write(b"MZ" + b"\0" * 4000 + b"Nullsoft.NSIS.exehead" + b"\0" * 100)
assert silent_command(replace(inno, uninstall_string=f'"{nsis_exe}"')) == (f'"{nsis_exe}" /S', "nsis")
plain = os.path.join(nsis_dir, "uninstall.exe")
with open(plain, "wb") as f:
    f.write(b"MZ" + b"\0" * 4000)
assert silent_command(replace(inno, uninstall_string=f'"{plain}"')) == (f'"{plain}"', "")
print("  SILENT DETECTION OK")

print()
print("=== Page: checkboxes drive the actions ===")
page = UninstallPage()
loop = QEventLoop()
page._enum_worker.finished_all.connect(lambda _n: QTimer.singleShot(0, loop.quit))
QTimer.singleShot(60_000, loop.quit)
loop.exec_()
page.cb_show_hidden.setChecked(True)
page.input.setText("Clean Test")
rows = {page.tree.topLevelItem(i).text(UN_COL_NAME): page.tree.topLevelItem(i)
        for i in range(page.tree.topLevelItemCount())}
assert set(rows) == {"Clean Test - Fake MSI", "Clean Test - cmd.exe as Uninstaller"}, set(rows)
assert rows["Clean Test - Fake MSI"].text(UN_COL_SILENT) == "msi"
for it in rows.values():
    it.setCheckState(UN_COL_NAME, Qt.Checked)
assert len(page._selected_entries()) == 2
assert page.btn_run.text() == "Uninstall (2)" and page.btn_uncheck.isEnabled()
page.input.setText("Fake MSI")                       # checks survive filtering
assert page.tree.topLevelItem(0).checkState(UN_COL_NAME) == Qt.Checked
assert len(page._selected_entries()) == 2
page._uncheck_all()
assert page._selected_entries() == [] and not page.btn_uncheck.isEnabled()
page.input.setText("Clean Test")
for i in range(page.tree.topLevelItemCount()):
    it = page.tree.topLevelItem(i)
    if it.text(UN_COL_NAME) == "Clean Test - Fake MSI":
        it.setCheckState(UN_COL_NAME, Qt.Checked)
page.cb_backup.setChecked(False)
page.remove_selected(confirm=False)                  # no dialog in between
loop = QEventLoop()
page._remove_worker.finished_all.connect(lambda *_: QTimer.singleShot(0, loop.quit))
QTimer.singleShot(30_000, loop.quit)
loop.exec_()
page._enum_worker.wait(30_000)
assert reg_key_info(HIVE, UNINSTALL_PARENT + "\\" + TAGS[0]) is None, "checked entry not removed"
assert reg_key_info(HIVE, UNINSTALL_PARENT + "\\" + TAGS[2]) is not None, "unchecked entry removed"
page.input.setText("")
drv = replace(msi, display_name="Windows Driver Package - Intel (e1dexpress) Net  (12.19.2.45)")
page.cb_show_hidden.setChecked(False)
assert not page._passes_filter(drv)
assert page._passes_filter(replace(msi, display_name="Windows Terminal"))
page.cb_show_hidden.setChecked(True)
assert page._passes_filter(drv)
page.shutdown()
import shutil as _sh
_sh.rmtree(nsis_dir, ignore_errors=True)
print("  PAGE CHECKBOXES OK")

# Clean up remaining fixtures + backup folder
for tag in TAGS:
    try:
        reg_delete_recursive(HIVE, UNINSTALL_PARENT + "\\" + tag)
    except OSError:
        pass
import shutil
shutil.rmtree(backup_folder, ignore_errors=True)

print()
print("STATUS: SUCCESS")
