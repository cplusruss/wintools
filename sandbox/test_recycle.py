"""Contract test for clean.recycle (SHFileOperationW wrapper).

Real recycling touches only a scratch folder created under %TEMP%; every
other case replaces clean._file_op, so the shell is never asked to destroy
anything and no permanent-delete prompt can appear.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clean  # noqa: E402

assert not hasattr(clean, "send2trash"), "send2trash must not be used in clean.py"

TEMP = os.path.normcase(os.path.realpath(tempfile.gettempdir()))


def scratch_paths(scratch):
    a = os.path.join(scratch, "wintools-selftest-a.txt")
    b = os.path.join(scratch, "wintools-selftest-b.log")
    folder = os.path.join(scratch, "wintools-selftest-folder")
    inner = os.path.join(folder, "inner.txt")
    Path(a).write_text("a")
    Path(b).write_text("b")
    os.makedirs(folder)
    Path(inner).write_text("i")
    return a, b, folder


with tempfile.TemporaryDirectory(prefix="wintools-selftest-recycle-") as scratch:
    assert os.path.normcase(os.path.realpath(scratch)).startswith(TEMP), scratch

    # ---- real recycle: small files and a small folder leave the scratch dir ----
    a, b, folder = scratch_paths(scratch)
    recycled, failed = clean.recycle([a, b, folder])
    assert recycled == [a, b, folder], (recycled, failed)
    assert failed == [], failed
    assert os.listdir(scratch) == [], os.listdir(scratch)
    print("real recycle ok: 2 files and a folder gone from the scratch dir")

    # ---- one bad path does not stop the rest (real shell, nothing to destroy) ----
    a, b, folder = scratch_paths(scratch)
    ghost = os.path.join(scratch, "wintools-selftest-ghost.txt")
    recycled, failed = clean.recycle([a, ghost, b, folder])
    assert recycled == [a, b, folder], (recycled, failed)
    assert [p for p, _e in failed] == [ghost], failed
    assert failed[0][1].startswith("error 0x"), failed
    assert os.listdir(scratch) == [], os.listdir(scratch)
    print("bad path isolated ok:", failed[0][1])

    # ---- flag contract: the shell must warn before any permanent delete ----
    seen = []

    def aborting(op):
        seen.append((op.wFunc, op.fFlags, op.pFrom))
        op.fAnyOperationsAborted = True
        return 0

    big = os.path.join(scratch, "wintools-selftest-big.bin")
    Path(big).write_text("x")
    with mock.patch.object(clean, "_file_op", aborting):
        recycled, failed = clean.recycle([big])
    func, flags, src = seen[0]
    assert func == clean.FO_DELETE, func
    for flag in (clean.FOF_ALLOWUNDO, clean.FOF_WANTNUKEWARNING,
                 clean.FOF_NOCONFIRMATION):
        assert flags & flag, (hex(flags), hex(flag))
    assert src == big, src
    print(f"flag contract ok: {flags:#x}")

    # ---- aborted -> failure, file kept ----
    assert recycled == [] and failed == [(big, "aborted")], (recycled, failed)
    assert os.path.exists(big)
    print("aborted is a failure ok")

    # ---- nonzero rc -> failure with the code ----
    with mock.patch.object(clean, "_file_op", lambda op: 0x78):
        recycled, failed = clean.recycle([big])
    assert recycled == [] and failed == [(big, "error 0x78")], (recycled, failed)
    assert os.path.exists(big)
    print("nonzero rc is a failure ok")

    # ---- one failure mid-list does not stop the rest ----
    x, y, z = (os.path.join(scratch, f"wintools-selftest-{n}.txt") for n in "xyz")

    def fail_y(op):
        return 0x402 if op.pFrom == y else 0

    with mock.patch.object(clean, "_file_op", fail_y):
        recycled, failed = clean.recycle([x, y, z])
    assert recycled == [x, z], recycled
    assert failed == [(y, "error 0x402")], failed
    print("mid-list failure ok")

    # ---- forward slashes are normalised before reaching the shell ----
    # (Qt's folder dialog hands back forward-slash roots)
    seen.clear()

    def accept(op):
        seen.append(op.pFrom)
        return 0

    fwd = scratch.replace("\\", "/") + "/wintools-selftest-fwd.txt"
    with mock.patch.object(clean, "_file_op", accept):
        recycled, failed = clean.recycle([fwd])
    assert seen == [fwd.replace("/", "\\")], seen
    assert recycled == [fwd] and failed == [], (recycled, failed)
    print("forward slashes normalised ok")

    # ---- MAX_PATH and longer never reach the shell: with long paths enabled
    # SHFileOperationW can destroy them instead of recycling ----
    seen.clear()
    long_path = "C:\\" + "d" * 250 + "\\wintools-selftest-long.txt"
    assert len(long_path) >= 260
    edge = "C:\\" + "e" * (259 - 3)
    assert len(edge) == 259
    with mock.patch.object(clean, "_file_op", accept):
        recycled, failed = clean.recycle([long_path, edge])
    assert seen == [edge], seen
    assert recycled == [edge], recycled
    assert failed == [(long_path, "path too long")], failed
    print("long paths refused ok")

print("test_recycle: all ok")
