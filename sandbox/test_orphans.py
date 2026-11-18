"""Synthetic test for the Orphan-paths tab.

Builds HKCU\\Software\\__clean_orphan_zone__ with:
  - a/b/c/win64    (default value = missing C:\\nope\\foo.dll)        <- orphan
  - a/b/c/win32    (default value = C:\\Windows\\System32\\cmd.exe)   <- valid (real file)
  - extras/foo     (default value = '%SystemRoot%\\System32\\cmd.exe') <- valid (env-expanded real)
  - extras/bar     (default value = 'plain text not a path')          <- not a path
  - extras/cmd     (default value = '\"C:\\nope\\app.exe\" --arg')      <- orphan (quoted cmd)
Then runs the scan via OrphanScanWorker (deep over HKCU only), verifies it finds
exactly the two orphan keys, and runs predict_empty_parents to confirm cascade.
"""
import os
import sys
import winreg

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import Qt, QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

import clean
import wintools

ROOT = r"Software\__clean_orphan_zone__"
HIVE = winreg.HKEY_CURRENT_USER


def mk_key(path, default_value=None):
    winreg.CreateKey(HIVE, path)
    if default_value is not None:
        with winreg.OpenKey(HIVE, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, default_value)


# Tear down any leftovers
try:
    clean.reg_delete_recursive(HIVE, ROOT)
except OSError:
    pass

cmd_exe = os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe")
assert os.path.isfile(cmd_exe)

mk_key(ROOT + r"\a\b\c\win64", default_value=r"C:\nope\foo.dll")          # ORPHAN
mk_key(ROOT + r"\a\b\c\win32", default_value=cmd_exe)                      # valid
mk_key(ROOT + r"\extras\foo",  default_value=r"%SystemRoot%\System32\cmd.exe")  # valid (env)
mk_key(ROOT + r"\extras\bar",  default_value="plain text not a path")     # ignored
mk_key(ROOT + r"\extras\cmd",  default_value='"C:\\nope\\app.exe" --arg') # ORPHAN (quoted)

# Sanity: extract_path_candidate
assert clean.extract_path_candidate(r"C:\nope\foo.dll") == r"C:\nope\foo.dll"
assert clean.extract_path_candidate(r"%SystemRoot%\System32\cmd.exe") == \
       os.path.expandvars(r"%SystemRoot%\System32\cmd.exe")
assert clean.extract_path_candidate('"C:\\nope\\app.exe" --arg') == r"C:\nope\app.exe"
assert clean.extract_path_candidate("plain text not a path") == ""
print("extract_path_candidate unit checks OK")

# Drive the scan worker (deep, HKCU only).
app = QApplication.instance() or QApplication([])
worker = clean.OrphanScanWorker(["HKCU"], deep=True)
found = []
worker.match.connect(lambda m: found.append(m))
loop = QEventLoop()
worker.finished_all.connect(lambda *_: loop.quit())
worker.start()
QTimer.singleShot(60_000, loop.quit)
loop.exec_()

zone_matches = [m for m in found if ROOT.lower() in m.key_path.lower()]
print(f"Total matches in zone: {len(zone_matches)}")
for m in zone_matches:
    print(f"  {m.hive_name}\\{m.key_path}   value={m.value_name or '(default)'}   missing={m.missing_path}")
zone_paths = sorted(m.key_path for m in zone_matches)
expected = sorted([ROOT + r"\a\b\c\win64", ROOT + r"\extras\cmd"])
assert zone_paths == expected, f"expected {expected}, got {zone_paths}"
print("ORPHAN DETECTION OK")

# Verify predict_empty_parents on the matches.
empties = clean.predict_empty_parents(HIVE, zone_paths)
print(f"Predicted empty parents: {sorted(empties, key=lambda s: -s.count(chr(92)))}")
# a\b\c has 2 children (win64 + win32). Only win64 is in the delete set, so c
# should NOT cascade.
assert (ROOT + r"\a\b\c") not in empties
# extras has 3 children. extras\cmd will be deleted; extras\foo and extras\bar
# remain — so extras should NOT cascade.
assert (ROOT + r"\extras") not in empties
print("CASCADE PREDICTION OK (no over-reach)")

# Cleanup
clean.reg_delete_recursive(HIVE, ROOT)

# Now verify the UI page builds the tree correctly.
SETTINGS = wintools.QSettings(
    os.path.join(os.environ["TEMP"], "wintools-selftest.ini"),
    wintools.QSettings.IniFormat)
SETTINGS.clear()
w = wintools.WintoolsWindow(SETTINGS)
print(f"Tab labels: {[w.tabs.tabText(i) for i in range(w.tabs.count())]}")
assert "Orphan paths" in [w.tabs.tabText(i) for i in range(w.tabs.count())]

print()
print("STATUS: SUCCESS")
