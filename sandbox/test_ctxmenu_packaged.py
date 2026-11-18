"""Contract test for packaged (MSIX / sparse-package) shell-extension sources.

A CLSID registered only under HKCR\\PackagedCom\\ClassIndex is labelled with its
package name.  Removal and restore run against scratch roots under
HKCU\\Software\\wintools-selftest-ctxmenu-pkg; the real Blocked and record keys
are never touched.  The real menus are only read.
"""

import os
import shutil
import sys
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import ctxmenu  # noqa: E402

app = QApplication([])
HKCU, HKCR = winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT
BASE = r"Software\wintools-selftest-ctxmenu-pkg"
INDEX = BASE + r"\PackagedCom\ClassIndex"
REPO = BASE + r"\Repository"
BLOCKED = BASE + r"\Blocked"
RECORD = BASE + r"\Removed"
PKG = "{DDDDDDDD-1111-2222-3333-444444444444}"
BARE = "{EEEEEEEE-1111-2222-3333-444444444444}"
SENDTO = "{7BA4C740-9E81-11CF-99D3-00AA004AE837}"
FULL = "Fake.Package_1.2.3.0_x64__8wekyb3d8bbwe"
BARE_FULL = "Bare.Package_9.0.0.0_x64__8wekyb3d8bbwe"
FOLDER_PATH = r"C:\Fake\Package"
ROOTS = ctxmenu.Roots(
    blocked=(HKCU, BLOCKED), record=(HKCU, RECORD),
    classes=(("HKCU", HKCU, BASE + r"\Classes"),),
    packaged=("HKCU", HKCU, INDEX, REPO))
ROOT = os.path.join(os.environ["TEMP"], "wintools-selftest-ctxmenu-pkg")


def delete_tree(path):
    try:
        with winreg.OpenKey(HKCU, path) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                delete_tree(path + "\\" + sub)
    except FileNotFoundError:
        return
    winreg.DeleteKey(HKCU, path)


def values(path):
    try:
        with winreg.OpenKey(HKCU, path) as k:
            return dict((n, (d, t)) for n, d, t in (
                winreg.EnumValue(k, i) for i in range(winreg.QueryInfoKey(k)[1])))
    except FileNotFoundError:
        return {}


def subkeys(hive, path):
    with winreg.OpenKey(hive, path) as k:
        return [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])]


def classic(clsid):
    try:
        winreg.CloseKey(winreg.OpenKey(HKCR, "CLSID\\" + clsid))
    except FileNotFoundError:
        return False
    return True


# ---- the real machine: packaged-only CLSIDs carry their package name ----
real = [(c, subkeys(HKCR, rf"PackagedCom\ClassIndex\{c}")[0])
        for c in subkeys(HKCR, r"PackagedCom\ClassIndex") if not classic(c)]
assert real, "no packaged-only CLSID on this machine"
for clsid, full in real:
    src = ctxmenu._extension_source(clsid)
    assert src.kind == "extension" and src.clsid == clsid, src
    assert src.label == full.partition("_")[0], (src.label, full)
    assert src.key == "HKCR\\PackagedCom\\ClassIndex\\" + clsid, src.key
    assert src.scope == "all menus", src
    assert src.dll == "" or os.path.isdir(src.dll), src.dll
assert any(ctxmenu._extension_source(c).dll for c, _f in real), \
    "no packaged CLSID resolved its install folder"
print(f"{len(real)} packaged-only CLSIDs labelled by package name")

# a CLSID that has a classic registration stays classic
assert classic(SENDTO)
classic_src = ctxmenu._extension_source(SENDTO)
assert classic_src.label == ctxmenu._class_text("CLSID\\" + SENDTO) != SENDTO

# the menus a real folder gets: no packaged GUID row is left labelled by its GUID
os.makedirs(ROOT, exist_ok=True)
try:
    menu = ctxmenu.build_menu("folder", ROOT)
finally:
    shutil.rmtree(ROOT, ignore_errors=True)
pkgrows = [i for i in menu if i.source and i.source.kind == "extension"
           and i.source.key.startswith("HKCR\\PackagedCom\\ClassIndex\\")]
assert pkgrows, "no packaged row in the folder menu (is the shell elevated?)"
for i in pkgrows:
    assert not i.source.label.startswith("{"), i.source
    assert i.removable, i.text
print("packaged rows in the folder menu:",
      [(i.text, i.source.label) for i in pkgrows])

# ---- scratch roots: lookup, remove, restore, removed ----
delete_tree(BASE)
try:
    for clsid, full in ((PKG, FULL), (BARE, BARE_FULL), (SENDTO, FULL)):
        winreg.CloseKey(winreg.CreateKey(HKCU, "\\".join((INDEX, clsid, full))))
    with winreg.CreateKey(HKCU, REPO + "\\" + FULL) as k:
        winreg.SetValueEx(k, "PackageRootFolder", 0, winreg.REG_SZ, FOLDER_PATH)

    src = ctxmenu._extension_source(PKG, roots=ROOTS)
    assert src == ctxmenu.Source("extension", "Fake.Package",
                                 "HKCU\\" + INDEX + "\\" + PKG, PKG, FOLDER_PATH,
                                 "all menus"), src
    bare = ctxmenu._extension_source(BARE, roots=ROOTS)
    assert (bare.label, bare.dll) == ("Bare.Package", ""), bare
    assert ctxmenu._extension_source(SENDTO, roots=ROOTS).label == classic_src.label, \
        "a classic registration must win over the package index"
    unknown = ctxmenu._extension_source("{FFFFFFFF-0000-0000-0000-000000000000}",
                                        roots=ROOTS)
    assert unknown.label == unknown.clsid and unknown.key == "", unknown
    print("scratch lookup ok")

    ctxmenu.remove(src, "Open in Fake", "folder", ROOTS)
    assert values(BLOCKED) == {PKG: ("", winreg.REG_SZ)}, values(BLOCKED)
    assert values(RECORD) == {"extension|" + PKG: ("folder|Open in Fake",
                                                   winreg.REG_SZ)}, values(RECORD)
    got = ctxmenu.removed(ROOTS)
    assert len(got) == 1, got
    assert (got[0].text, got[0].menu, got[0].regs) == ("Open in Fake", "folder", ())
    assert got[0].source == src, got[0].source
    ctxmenu.restore(got[0], ROOTS)
    assert values(BLOCKED) == {} and values(RECORD) == {}, (values(BLOCKED),
                                                            values(RECORD))
    assert ctxmenu.removed(ROOTS) == []
    print("packaged remove / restore / removed round trip ok")
finally:
    delete_tree(BASE)

try:
    winreg.CloseKey(winreg.OpenKey(HKCU, BASE))
except FileNotFoundError:
    pass
else:
    raise AssertionError("scratch tree left behind")
print("STATUS: SUCCESS")
