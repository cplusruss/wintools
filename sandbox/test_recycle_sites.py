"""Contract test for the clean.py call sites of clean.recycle.

CleanWorker.run, EmptyFoldersPage._recycle_checked and
LargestFilesPage._recycle_checked must treat an item recycle() reports as
failed or aborted as not recycled and not freed. clean.recycle is a fake and
clean._file_op raises, so no path here ever reaches the shell.
"""

import os
import sys
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

import clean  # noqa: E402

app = QApplication([])

P1, P2, P3 = r"C:\fake\one", r"C:\fake\two", r"C:\fake\three"
ERRORS = {P2: "aborted", P3: "error 0x78"}


def fake_recycle(paths):
    recycled, failed = [], []
    for p in paths:
        if p in ERRORS:
            failed.append((p, ERRORS[p]))
        else:
            recycled.append(p)
    return recycled, failed


def shell_forbidden(op):
    raise AssertionError("the real shell was reached")


assert not hasattr(clean, "send2trash"), "send2trash must not be used in clean.py"

with mock.patch.object(clean, "_file_op", shell_forbidden), \
        mock.patch.object(clean, "recycle", fake_recycle):

    # ---- CleanWorker ----
    w = clean.CleanWorker([(P1, 100), (P2, 200), (P3, 400)], False, 0)
    errors, done = [], []
    w.item_error.connect(lambda p, e: errors.append((p, e)))
    w.finished_all.connect(lambda ok, fail, freed: done.append((ok, fail, freed)))
    w.run()
    assert errors == [(P2, "aborted"), (P3, "error 0x78")], errors
    assert done == [(1, 2, 100)], done
    print("CleanWorker ok: failed items reported, only recycled bytes freed")

    # ---- EmptyFoldersPage ----
    page = clean.EmptyFoldersPage()
    for p in (P1, P2, P3):
        page._on_found(p)
    page._bulk_check(Qt.Checked)
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        page._recycle_checked()
    left = [it.text(0) for it in page._items]
    assert left == [P2, P3], left
    assert page.tree.topLevelItemCount() == 2
    assert page.lbl_status.text() == "Recycled 1 folder(s); 2 failed.", page.lbl_status.text()
    assert page.lbl_summary.text() == "2 checked", page.lbl_summary.text()
    print("EmptyFoldersPage ok: failed folders stay listed")

    # ---- LargestFilesPage ----
    page = clean.LargestFilesPage()
    page._on_finished([(400, P3), (200, P2), (100, P1)], 0)
    page._bulk_check(Qt.Checked)
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        page._recycle_checked()
    left = [it.text(clean.LF_COL_PATH) for it in page._items]
    assert left == [P3, P2], left
    assert page.tree.topLevelItemCount() == 2
    assert page.lbl_status.text() == "Recycled 1 file(s); 2 failed.", page.lbl_status.text()
    assert page.lbl_summary.text().startswith("2 checked"), page.lbl_summary.text()
    print("LargestFilesPage ok: failed files stay listed")

print("test_recycle_sites: all ok")
