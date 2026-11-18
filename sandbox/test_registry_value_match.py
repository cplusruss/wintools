"""Verify the Registry tab now matches against value names and value data,
not just key paths."""
import os
import sys
import winreg

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QEventLoop, QTimer, Qt
from PyQt5.QtWidgets import QApplication

import clean
import wintools

ROOT = r"Software\__clean_value_match__"
HIVE = winreg.HKEY_CURRENT_USER
NEEDLE = "marker9876"


def mk_key(path, values=None):
    winreg.CreateKey(HIVE, path)
    if values:
        with winreg.OpenKey(HIVE, path, 0, winreg.KEY_SET_VALUE) as k:
            for nm, data in values.items():
                winreg.SetValueEx(k, nm, 0, winreg.REG_SZ, data)


try:
    clean.reg_delete_recursive(HIVE, ROOT)
except OSError:
    pass

# Fixture:
#   key_named_<NEEDLE>     -> matched by KEY PATH
#   value_name             -> matched by VALUE NAME (a value named '<NEEDLE>_setting')
#   value_data             -> matched by VALUE DATA (a value whose data contains NEEDLE)
#   both                   -> value name AND value data both contain NEEDLE
#   plain                  -> none, should not match
mk_key(ROOT + r"\key_named_" + NEEDLE)
mk_key(ROOT + r"\value_name", values={NEEDLE + "_setting": "ordinary data"})
mk_key(ROOT + r"\value_data", values={"InstallPath": r"C:\Apps\contains-" + NEEDLE + r"\bin"})
mk_key(ROOT + r"\both", values={NEEDLE + "_x": NEEDLE + "_y"})
mk_key(ROOT + r"\plain", values={"unrelated": "nothing here"})

# Drive the search synchronously.
app = QApplication.instance() or QApplication([])
worker = clean.RegistrySearchWorker(NEEDLE, ["HKCU"], search_values=True)
seen = []
worker.match.connect(lambda hive, path, ns, nv, km, vm: seen.append({
    "hive": hive, "path": path, "n_sub": ns, "n_val": nv,
    "key_matched": km, "value_matches": list(vm),
}))
loop = QEventLoop()
worker.finished_all.connect(lambda *_: loop.quit())
worker.start()
QTimer.singleShot(60_000, loop.quit)
loop.exec_()

zone = [m for m in seen if ROOT.lower() in m["path"].lower()]
print(f"Zone matches: {len(zone)}")
for m in zone:
    print(f"  {m['path'][-30:]:30}  key_match={m['key_matched']}  values={m['value_matches']}")

paths = sorted(m["path"] for m in zone)
expected = sorted([
    ROOT + r"\key_named_" + NEEDLE,
    ROOT + r"\value_name",
    ROOT + r"\value_data",
    ROOT + r"\both",
])
assert paths == expected, f"expected {expected}, got {paths}"
print("All four expected matches found, 'plain' correctly skipped.")

by_path = {m["path"]: m for m in zone}
# key_named_<NEEDLE>: key_matched True, value_matches []
m = by_path[ROOT + r"\key_named_" + NEEDLE]
assert m["key_matched"] is True
assert m["value_matches"] == []

# value_name: key_matched False, one value-name hit
m = by_path[ROOT + r"\value_name"]
assert m["key_matched"] is False
assert len(m["value_matches"]) == 1
nm, data, name_hit, data_hit = m["value_matches"][0]
assert nm == NEEDLE + "_setting"
assert name_hit is True and data_hit is False

# value_data: key_matched False, one value-data hit
m = by_path[ROOT + r"\value_data"]
assert m["key_matched"] is False
assert len(m["value_matches"]) == 1
nm, data, name_hit, data_hit = m["value_matches"][0]
assert nm == "InstallPath"
assert name_hit is False and data_hit is True

# both: key_matched False, value-name + value-data hit on the same value
m = by_path[ROOT + r"\both"]
assert m["key_matched"] is False
assert len(m["value_matches"]) == 1
nm, data, name_hit, data_hit = m["value_matches"][0]
assert name_hit is True and data_hit is True
print("Per-match attribution: OK")

# Re-run with search_values=False — should only find the key-path one.
worker2 = clean.RegistrySearchWorker(NEEDLE, ["HKCU"], search_values=False)
seen2 = []
worker2.match.connect(lambda hive, path, ns, nv, km, vm: seen2.append(path))
loop2 = QEventLoop()
worker2.finished_all.connect(lambda *_: loop2.quit())
worker2.start()
QTimer.singleShot(60_000, loop2.quit)
loop2.exec_()
zone2 = [p for p in seen2 if ROOT.lower() in p.lower()]
print(f"With search_values=False, zone matches: {zone2}")
assert zone2 == [ROOT + r"\key_named_" + NEEDLE]
print("Disabling value search returns only the key-path match: OK")

# Now drive the UI and verify the 'Matched in' column.
SETTINGS = wintools.QSettings(
    os.path.join(os.environ["TEMP"], "wintools-selftest.ini"),
    wintools.QSettings.IniFormat)
SETTINGS.clear()
w = wintools.WintoolsWindow(SETTINGS)
reg = dict(w.clean_pages)["Registry"]
reg.input.setText(NEEDLE)
for h_name, cb in reg.cb_hives.items():
    cb.setChecked(h_name == "HKCU")
reg.cb_search_values.setChecked(True)
reg.start_search()
loop3 = QEventLoop()
reg._worker.finished_all.connect(lambda *_: loop3.quit())
QTimer.singleShot(60_000, loop3.quit)
loop3.exec_()
app.processEvents()
print()
ui_rows = [r for r in reg._rows if ROOT.lower() in r["path"].lower()]
print(f"UI rows: {len(ui_rows)}")
for r in ui_rows:
    it = r["item"]
    matched_in = it.text(clean.REG_COL_MATCH)
    print(f"  {r['path'][-30:]:30}  matched_in={matched_in!r}")
    assert matched_in, f"empty 'Matched in' column for {r['path']}"
print("'Matched in' column populated for every row.")

# Cleanup
clean.reg_delete_recursive(HIVE, ROOT)
print()
print("STATUS: SUCCESS")
