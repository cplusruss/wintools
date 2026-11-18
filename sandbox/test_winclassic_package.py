"""Contract test for the winclassic package layout: the five installer files
are in resource\\winclassic\\installers, ep_setup.exe is the build the reference
PC runs, the two downloads are the official builds, and the folder resolver
gives the same answer for a source run and a frozen run beside the exe.
Read-only: nothing is installed or written.

The checks that need the two downloaded installers come last, so a missing
download fails only those.
"""

import hashlib
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import winclassic  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "resource" / "winclassic"
INST = PKG / "installers"
EP_SHA256 = "3680AA912D3ED60FD4762B349701E280A3D34771B659F14809D3882ABABD64F0"
INSTALLED_EP = Path(r"C:\Program Files\ExplorerPatcher\ep_setup.exe")
# InstallerSha256 in winget-pkgs manifests\r\RamenSoftware\7+TaskbarTweaker\5.15.4
TT_SHA256 = "86E361F13F5394724A984E19E2534682DE9575A021EBD1F1683455E8A37B57FC"
# size of the windhawk_setup_offline.exe asset of the v1.6.1 release (GitHub API)
WINDHAWK_SIZE = 148002080
DOWNLOADS = ("windhawk_setup_offline.exe", "7tt_setup.exe")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


# ---- the names ----
assert sorted(winclassic.INSTALLERS.values()) == [
    "7tt_setup.exe", "ep_setup.exe", "marlett.ttf", "openshell_setup.exe",
    "windhawk_setup_offline.exe"]
print("installer names ok")

# ---- the resolver ----
assert winclassic.package_dir() == PKG.resolve(), winclassic.package_dir()
with mock.patch.object(sys, "frozen", True, create=True), \
        mock.patch.object(sys, "executable", str(ROOT / "wintools.exe")):
    assert winclassic.package_dir() == PKG.resolve(), winclassic.package_dir()
print("resolver ok: source run and frozen run beside the exe agree")

with tempfile.TemporaryDirectory(prefix="wintools-selftest-package-") as scratch:
    scratch = Path(scratch).resolve()  # %TEMP% may be an 8.3 short name
    gone = scratch / "resource" / "winclassic"
    with mock.patch.object(sys, "frozen", True, create=True), \
            mock.patch.object(sys, "executable", str(scratch / "wintools.exe")):
        try:
            winclassic.package_dir()
            raise AssertionError("missing package folder did not raise")
        except FileNotFoundError as e:
            assert str(e) == f"missing {gone}", str(e)
        (gone / "installers").mkdir(parents=True)
        assert winclassic.package_dir() == gone.resolve()
        assert winclassic.package_path("installers") == gone.resolve() / "installers"
        try:
            winclassic.package_path("installers", "ep_setup.exe")
            raise AssertionError("missing file did not raise")
        except FileNotFoundError as e:
            assert str(e) == f"missing {gone.resolve() / 'installers' / 'ep_setup.exe'}", str(e)
print("missing folder and file are errors naming the path ok")

# ---- the exe carries only the icons ----
import build_exe  # noqa: E402

data = build_exe.add_data()
assert data and all(item.endswith((";.", ";resource/icons")) for item in data), data
assert not any(w in item for item in data for w in ("winclassic", "installers", "capture"))
print("build_exe.py does not embed the package ok")

# ---- the files copied from the kit ----
for name in ("ep_setup.exe", "openshell_setup.exe", "marlett.ttf"):
    p = INST / name
    assert p.is_file() and p.stat().st_size > 0, f"missing {p}"
    head = p.read_bytes()[:4]
    assert head[:2] == b"MZ" if name.endswith(".exe") else head == b"\x00\x01\x00\x00", (p, head)
assert sha256(INST / "ep_setup.exe") == EP_SHA256, sha256(INST / "ep_setup.exe")
if INSTALLED_EP.is_file():
    assert sha256(INSTALLED_EP) == sha256(INST / "ep_setup.exe")
print("ep_setup.exe sha256 ok:", EP_SHA256)

total = sum(p.stat().st_size for p in PKG.rglob("*") if p.is_file())
print(f"package size so far: {total} bytes ({total / 1e6:.1f} MB)")

# ---- the two downloads are the official builds ----
absent = [name for name in DOWNLOADS if not (INST / name).is_file()]
assert not absent, f"downloads not placed in {INST}: {', '.join(absent)}"
for name in DOWNLOADS:
    assert (INST / name).read_bytes()[:2] == b"MZ", name
assert (INST / "windhawk_setup_offline.exe").stat().st_size == WINDHAWK_SIZE
assert sha256(INST / "7tt_setup.exe") == TT_SHA256
print("windhawk_setup_offline.exe size and 7tt_setup.exe sha256 ok")
total = sum(p.stat().st_size for p in PKG.rglob("*") if p.is_file())
print(f"package size: {total} bytes ({total / 1e6:.1f} MB)")
print("STATUS: SUCCESS")
