"""Contract test for FilesPage check memory and the byte-count signals.

Unchecked categories and unchecked files survive a rescan and a restart
(via the config dict), drive the summary and clean targets without the
category being expanded, and are pruned only by a complete scan of the
current controller. Byte counts above 2 GB cross signals unwrapped.
No real scan threads run and nothing is written to disk.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import clean  # noqa: E402

app = QApplication([])

BIG = 3_229_239_337
P1, P2, P3 = r"C:\fake\a.tmp", r"C:\fake\b.tmp", r"C:\fake\c.tmp"
FILES = [(P1, 100, 0), (P2, 200, 0), (P3, 400, 0)]

# ---- signals carry > 2 GB ----
got = []
sc = clean.ScanController(clean.CATEGORIES, [])
sc.recycle_info.connect(lambda k, s, n: got.append(s))
sc.files_batch.connect(lambda k, c, b: got.append(b))
sc.recycle_info.emit("recycle", BIG, 3531)
sc.files_batch.emit("temp", 1, BIG)
cw = clean.CleanWorker([], False, 0)
cw.finished_all.connect(lambda ok, fail, freed: got.append(freed))
cw.finished_all.emit(1, 0, BIG)
assert got == [BIG, BIG, BIG], got
print("signals ok: byte counts above 2 GB arrive intact")

saves = []
config = {}


def make_page():
    return clean.FilesPage(config, lambda: saves.append(1))


def fake_scan(page, files):
    scan = clean.ScanController(clean.CATEGORIES, [], parent=page)
    scan.category_done.connect(page._on_cat_done)
    page._scan = scan
    page._reset_tree_to_categories()
    scan.files_by_cat["temp"] = list(files)
    page._on_files_batch("temp", len(files), sum(s for _, s, _ in files))
    page._on_files_batch("browser", 1, 50)
    scan.files_by_cat["browser"] = [(r"C:\fake\cache", 50, 0)]
    return scan


def state(page, key):
    return page._cat_items[key].checkState(clean.COL_NAME)


def targets(page):
    return sorted(p for p, _ in page._collect_clean_targets()[0])


# ---- first run: everything checked ----
page = make_page()
assert all(state(page, k) == Qt.Checked for k in page._cat_items)
fake_scan(page, FILES)

# ---- user unchecks a category and a file ----
page._cat_items["browser"].setCheckState(clean.COL_NAME, Qt.Unchecked)
temp = page._cat_items["temp"]
temp.setExpanded(True)
assert temp.childCount() == 3
temp.child(1).setCheckState(clean.COL_NAME, Qt.Unchecked)
assert state(page, "temp") == Qt.PartiallyChecked
page._refresh_summary()
assert page.lbl_summary.text().startswith("Checked: 2 items, 500 B"), (
    page.lbl_summary.text()
)
assert targets(page) == [P1, P3], targets(page)

# ---- rescan: unchecks survive, without expanding ----
page._save_checks()
assert config["files_unchecked"] == {"cats": ["browser"], "files": {"temp": [P2]}}, (
    config
)
fake_scan(page, FILES)
assert state(page, "browser") == Qt.Unchecked
assert state(page, "temp") == Qt.PartiallyChecked
assert targets(page) == [P1, P3], targets(page)
print("rescan ok: unchecked category and file stay unchecked")

# ---- restart: new page from saved config ----
page2 = make_page()
assert state(page2, "browser") == Qt.Unchecked
assert state(page2, "temp") == Qt.PartiallyChecked
scan2 = fake_scan(page2, FILES)
assert targets(page2) == [P1, P3], targets(page2)
page2._cat_items["temp"].setExpanded(True)
kids = page2._cat_items["temp"]
assert [kids.child(i).checkState(clean.COL_NAME) for i in range(3)] == [
    Qt.Checked,
    Qt.Unchecked,
    Qt.Checked,
]
print("restart ok: checks restored from config")

# ---- a stale scan's category_done does not prune ----
fake_scan(page2, [(P1, 100, 0)])
scan2.category_done.emit("temp")
assert page2._unchecked_files["temp"] == {P2}

# ---- a stopped scan does not prune ----
scan3 = page2._scan
scan3._stop.set()
scan3.category_done.emit("temp")
assert page2._unchecked_files["temp"] == {P2}

# ---- a complete scan prunes vanished files ----
scan4 = fake_scan(page2, [(P1, 100, 0)])
scan4.category_done.emit("temp")
assert "temp" not in page2._unchecked_files, page2._unchecked_files
assert state(page2, "temp") == Qt.Checked
print("prune ok: only a complete scan of the live controller prunes")

# ---- re-checking a category clears its file unchecks ----
page2._unchecked_files["temp"] = {P2}
fake_scan(page2, FILES)
assert state(page2, "temp") == Qt.PartiallyChecked
page2._cat_items["temp"].setCheckState(clean.COL_NAME, Qt.Checked)
assert "temp" not in page2._unchecked_files
page2._bulk_check(Qt.Checked)
assert page2._unchecked_cats == set()
page2._save_checks()
assert config["files_unchecked"] == {"cats": [], "files": {}}, config
print("check all ok: memory cleared")

print("test_files_page_checks: all ok")
