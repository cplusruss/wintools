"""Synthetic registry test for clean.py — search + cascade-empty-parents + delete."""
import os
import sys
import tempfile
import winreg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clean import (
    predict_empty_parents, attribute_cascade, reg_delete_recursive,
    reg_key_info, RegistrySearchWorker, reg_export,
)

ROOT = r"Software\__clean_test_zone__"
HIVE = winreg.HKEY_CURRENT_USER
BS = chr(92)  # backslash


def mk_key(path, value=None):
    winreg.CreateKey(HIVE, path)
    if value is not None:
        with winreg.OpenKey(HIVE, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "v", 0, winreg.REG_SZ, value)


def exists(path):
    return reg_key_info(HIVE, path) is not None


# Tear down anything left over from a previous test run.
try:
    reg_delete_recursive(HIVE, ROOT)
    print("cleaned up previous test zone")
except OSError:
    pass

# Fixture tree:
#   __clean_test_zone__/
#     a/b/c/key_match_me        target match
#     a/b/c/sibling_innocent    has a value; c must NOT cascade-delete
#     x/y/z/match_me            target match; full x/y/z cascade should be empty
#     keepers/anchor            has a value; never matched
mk_key(ROOT + r"\a\b\c\key_match_me")
mk_key(ROOT + r"\a\b\c\sibling_innocent", value="hello")
mk_key(ROOT + r"\x\y\z\match_me")
mk_key(ROOT + r"\keepers\anchor", value="keep")

# Search
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QEventLoop, QTimer

app = QApplication.instance() or QApplication([])
worker = RegistrySearchWorker("match_me", ["HKCU"])
found = []
worker.match.connect(lambda hive, path, ns, nv: found.append((hive, path, ns, nv)))
loop = QEventLoop()
worker.finished_all.connect(lambda n: loop.quit())
worker.start()
QTimer.singleShot(60_000, loop.quit)
loop.exec_()

zone_hits = [m for m in found if ROOT.lower() in m[1].lower()]
print("Matches inside test zone:")
for h, p, ns, nv in zone_hits:
    print(f"  {h}{BS}{p}   subkeys={ns} values={nv}")
assert len(zone_hits) == 2, f"expected 2 matches, got {len(zone_hits)}"

# Empty-parent predictor
matched_paths = [p for _h, p, _ns, _nv in zone_hits]
empties = predict_empty_parents(HIVE, matched_paths)
print("Predicted empty parents (deepest first):")
for p in sorted(empties, key=lambda s: -s.count(BS)):
    print(f"  {p}")

expected_in = {ROOT + r"\x\y\z", ROOT + r"\x\y", ROOT + r"\x"}
expected_out = {ROOT + r"\a\b\c", ROOT + r"\a\b", ROOT + r"\a"}
missing = expected_in - empties
extra = empties & expected_out
print(f"expected-in missing: {missing}")
print(f"expected-out present: {extra}")
assert not missing, f"cascade prediction missing: {missing}"
assert not extra, f"cascade prediction over-reached: {extra}"
print("CASCADE PREDICTION OK")

# Per-row attribution
print("Per-row cascade attribution:")
for h, p, _ns, _nv in zone_hits:
    chain = attribute_cascade(p, empties)
    print(f"  {p} -> {chain}")

# Delete pass (no backup, to keep test fast). Deepest first.
targets = [(h, p) for h, p, _, _ in zone_hits] + [("HKCU", p) for p in empties]
targets.sort(key=lambda t: -t[1].count(BS))
del_ok = del_fail = 0
for hive_name, path in targets:
    try:
        reg_delete_recursive(HIVE, path)
        del_ok += 1
    except OSError as e:
        del_fail += 1
        print(f"  delete failed {path}: {e}")
print(f"Deleted {del_ok}, failures {del_fail}")

# Verify state
assert exists(ROOT + r"\a\b\c\sibling_innocent"), "innocent sibling was destroyed!"
assert exists(ROOT + r"\keepers\anchor"), "anchor key was destroyed!"
assert not exists(ROOT + r"\a\b\c\key_match_me"), "matched key still present!"
assert not exists(ROOT + r"\x"), "x cascade not fully removed!"
print("POST-DELETE STATE OK")

# Final cleanup
reg_delete_recursive(HIVE, ROOT)
assert not exists(ROOT), "test zone cleanup failed"
print("TEST ZONE TORN DOWN")

# Backup smoke
mk_key(ROOT + r"\backup_target", value="b")
out = os.path.join(tempfile.gettempdir(), "clean_test_backup.reg")
ok, msg = reg_export("HKCU", ROOT + r"\backup_target", out)
print(f"reg_export ok={ok} msg={msg!r}")
print(f"backup file size = {os.path.getsize(out)} bytes")
assert ok and os.path.getsize(out) > 0
reg_delete_recursive(HIVE, ROOT)
try:
    os.remove(out)
except OSError:
    pass
print("BACKUP SMOKE OK")
print("STATUS: SUCCESS")
