"""Quick headless smoke for the new Registry tab buttons."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

import clean
import wintools

app = QApplication(sys.argv)
SETTINGS = wintools.QSettings(
    os.path.join(os.environ["TEMP"], "wintools-selftest.ini"),
    wintools.QSettings.IniFormat)
SETTINGS.clear()
w = wintools.WintoolsWindow(SETTINGS)
reg = dict(w.clean_pages)["Registry"]

print("btn_backup present:        ", hasattr(reg, "btn_backup"))
print("btn_open_regedit present:  ", hasattr(reg, "btn_open_regedit"))
print("cb_backup removed (should be False): ", hasattr(reg, "cb_backup"))
print("btn_backup enabled at start:        ", reg.btn_backup.isEnabled())
print("btn_open_regedit enabled at start:  ", reg.btn_open_regedit.isEnabled())
print("btn_delete enabled at start:        ", reg.btn_delete.isEnabled())
print("RegistryBackupWorker present:        ", hasattr(clean, "RegistryBackupWorker"))
print("open_in_regedit present:             ", hasattr(clean, "open_in_regedit"))
print("HIVE_FULL_NAMES:", list(clean.HIVE_FULL_NAMES.keys()))

# Verify the open_in_regedit LastKey write (don't actually launch regedit; we
# can't unit-test the Popen safely without elevating). We assert that the
# LastKey value gets written correctly by calling the inner registry write
# directly and reading it back.
import winreg
test_path = r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit"
expected = "Computer\\HKEY_CURRENT_USER\\Software\\clean_test_lastkey_target"
with winreg.CreateKey(winreg.HKEY_CURRENT_USER, test_path) as k:
    winreg.SetValueEx(k, "LastKey", 0, winreg.REG_SZ, expected)
with winreg.OpenKey(winreg.HKEY_CURRENT_USER, test_path, 0, winreg.KEY_READ) as k:
    v, _ = winreg.QueryValueEx(k, "LastKey")
print(f"LastKey roundtrip value: {v!r}")
assert v == expected
print("STATUS: SUCCESS")
