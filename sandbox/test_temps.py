"""Contract test for temps.py: descriptor parsing against synthetic buffers,
the live sources, and the page's session min / max bookkeeping."""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import temps  # noqa: E402

app = QApplication([])

# ---- STORAGE_DEVICE_DESCRIPTOR: vendor + product from their offsets ----
head = struct.pack("<II4BIIII", 1, 64, 0, 0, 0, 0, 40, 48, 0, 0)
buf = head.ljust(40, b"\0") + b"ACME\0\0\0\0" + b"  FastDisk 9  \0"
assert temps.parse_device_name(buf) == "ACME FastDisk 9", temps.parse_device_name(buf)
buf = head[:12] + struct.pack("<I", 0) + head[16:]
buf = buf.ljust(48, b"\0") + b"CT4000T700SSD3\0"
assert temps.parse_device_name(buf) == "CT4000T700SSD3"
print("device name ok")

# ---- STORAGE_TEMPERATURE_DATA_DESCRIPTOR: signed temps per info entry ----
desc = struct.pack("<IIhhH2xQ", 1, 56, 89, 87, 2, 0)
info = (struct.pack("<HhhhBBBBI", 0, 45, 87, 0, 0, 0, 0, 0, 0)
        + struct.pack("<HhhhBBBBI", 1, -5, 87, 0, 0, 0, 0, 0, 0))
assert len(desc) == 24 and len(info) == 32
assert temps.parse_temperatures(desc + info) == [(0, 45), (1, -5)]
print("temperature descriptor ok")

# ---- live sources ----
rows, errors = temps.read_all()
assert not errors, errors
assert rows, "no temperature sensors found"
for dev, sensor, deg, src in rows:
    assert src in ("nvidia-smi", "drive"), src
    assert -40.0 < deg < 125.0, (dev, sensor, deg)
print(f"live ok: {len(rows)} sensors")
for r in rows:
    print("   ", r)

# ---- page: grid rows, session min / max, status ----
page = temps.TempsPage()
fake = [("GPU 0  Test", "Core", 50.0, "nvidia-smi"),
        ("Disk 0  Test", "Drive", 40.0, "drive")]
page._show(fake, [])
page._show([("GPU 0  Test", "Core", 62.5, "nvidia-smi"),
            ("Disk 0  Test", "Drive", 38.0, "drive")], ["drive: probe"])
g = page.grid
assert g.rowCount() == 2
assert [g.item(0, c).text() for c in range(6)] == [
    "GPU 0  Test", "Core", "62.5", "50.0", "62.5", "nvidia-smi"], \
    [g.item(0, c).text() for c in range(6)]
assert [g.item(1, c).text() for c in (2, 3, 4)] == ["38.0", "38.0", "40.0"]
assert page.status.text() == "2 sensors   drive: probe", page.status.text()
assert not g.alternatingRowColors() and g.showGrid()
print("page ok")

# ---- the poller runs while shown and stops cleanly ----
page.show()
app.processEvents()
page._worker.wait(10000)
app.processEvents()
assert g.rowCount() == len(rows), (g.rowCount(), len(rows))
page.hide()
assert not page._timer.isActive()
page.shutdown()
assert not page._worker.isRunning()
print("poller ok")
print("STATUS: SUCCESS")
