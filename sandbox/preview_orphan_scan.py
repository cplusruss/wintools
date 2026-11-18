"""Run the hot-spot orphan scan against the live registry and summarize what
shows up on this machine."""
import os
import sys
import time
from collections import Counter

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

import clean

app = QApplication.instance() or QApplication([])
worker = clean.OrphanScanWorker(["HKCR", "HKLM", "HKCU"], deep=False)
found = []
worker.match.connect(lambda m: found.append(m))
loop = QEventLoop()
worker.finished_all.connect(lambda *_: loop.quit())
t0 = time.perf_counter()
worker.start()
QTimer.singleShot(180_000, loop.quit)
loop.exec_()
dt = time.perf_counter() - t0
print(f"Hot-spot scan finished in {dt:0.1f}s")
print(f"Orphans found: {len(found)}")

BS = chr(92)
buckets = Counter()
for m in found:
    parts = m.key_path.split(BS)
    buckets[f"{m.hive_name}{BS}{BS.join(parts[:3])}"] += 1
print()
print("Top buckets:")
for k, v in buckets.most_common(20):
    print(f"  {v:>4}  {k}")

print()
print("Sample matches (first 10):")
for m in found[:10]:
    vn = m.value_name or "(default)"
    print(f"  {m.hive_name}{BS}{m.key_path[:70]:70}  val={vn[:24]:24}  missing={m.missing_path}")
