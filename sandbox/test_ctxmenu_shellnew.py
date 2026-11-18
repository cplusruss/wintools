"""Contract test for the New submenu part of ctxmenu (shellnew_menu,
shellnew_removed, remove / restore on a "shellnew" source).

Every key lives under HKCU\\Software\\wintools-test-shellnew: two fake Classes
roots (labelled HKCU and HKLM), a fake record store and a fake Explorer cache
key, injected through ctxmenu.Roots.  The real Classes and cache keys are never
touched; the scratch tree is deleted afterwards.
"""

import os
import sys
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import ctxmenu  # noqa: E402

app = QApplication([])

HKCU = winreg.HKEY_CURRENT_USER
BASE = r"Software\wintools-test-shellnew"
USER = BASE + r"\ClassesUser"
MACH = BASE + r"\ClassesMachine"
CACHE = BASE + r"\Cache"
RECORD = BASE + r"\Removed"
ROOTS = ctxmenu.Roots(
    blocked=(HKCU, BASE + r"\Blocked"), record=(HKCU, RECORD),
    classes=(("HKCU", HKCU, USER), ("HKLM", HKCU, MACH)),
    shellnew_cache=(HKCU, CACHE))


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


def mk(root, sub, **vals):
    with winreg.CreateKey(HKCU, (root + "\\" + sub) if sub else root) as k:
        for name, data in vals.items():
            winreg.SetValueEx(k, "" if name == "default" else name, 0,
                              winreg.REG_SZ, data)


def exists(root, sub):
    try:
        winreg.CloseKey(winreg.OpenKey(HKCU, (root + "\\" + sub) if sub else root))
    except FileNotFoundError:
        return False
    return True


def values(root, sub):
    with winreg.OpenKey(HKCU, (root + "\\" + sub) if sub else root) as k:
        return {n: d for n, d, _t in (
            winreg.EnumValue(k, i) for i in range(winreg.QueryInfoKey(k)[1]))}


def rows(items):
    return {i.source.label: i for i in items if i.source and i.source.kind == "shellnew"}


def exts(items):
    return [i.source.label for i in items if i.source and i.source.kind == "shellnew"]


delete_tree(BASE)
try:
    # ---- 1: which entries are shown ----
    mk(USER, r".a\ShellNew", Command="x")
    mk(USER, ".b", default="Pb")
    mk(USER, r".b\Pb\ShellNew", FileName="t.b")
    mk(USER, r".c\ShellNew")
    mk(USER, r".g\ShellNew", default="")
    mk(USER, ".d", default="Pd")
    mk(USER, r".d\Pd\ShellNew")
    mk(USER, r".d\ShellNew", NullFile="")
    mk(USER, r".n\ShellNew", nullfile="")
    items = ctxmenu.shellnew_menu(ROOTS)
    assert exts(items) == [".a", ".b", ".n"], exts(items)
    assert items[2 + 1].source.key == "HKCU\\" + USER + r"\.a\ShellNew"
    assert items[2 + 1].source.scope == "HKCU" and items[3].source.clsid == ""
    assert ctxmenu._record_name(items[3].source) == "shellnew|.a"
    print("shown rule ok")

    # ---- 2: HKCU overrides HKLM in the merged view ----
    delete_tree(BASE)
    mk(USER, ".e", default="P2")
    mk(USER, r".e\P2\ShellNew", Data="1")
    mk(USER, "P2", default="Two")
    mk(MACH, ".e", default="P1")
    mk(MACH, r".e\P1\ShellNew", FileName="1")
    mk(MACH, "P1", default="One")
    got = rows(ctxmenu.shellnew_menu(ROOTS))
    assert list(got) == [".e"] and got[".e"].text == "Two", got
    assert got[".e"].source.key == "HKCU\\" + USER + r"\.e\P2\ShellNew"
    mk(MACH, r".y\ShellNew", NullFile="")
    mk(USER, ".y")
    got = rows(ctxmenu.shellnew_menu(ROOTS))
    assert got[".y"].source.scope == "HKLM", got[".y"].source
    mk(USER, r".y\ShellNew")
    assert rows(ctxmenu.shellnew_menu(ROOTS))[".y"].source.scope == "HKCU+HKLM"
    print("merged view ok")

    # ---- 3: text precedence ----
    delete_tree(BASE)
    mk(USER, ".m", default="Pm")
    mk(USER, r".m\ShellNew", NullFile="", MenuText="Menu")
    mk(USER, "Pm", default="Prog", FriendlyTypeName="Friendly")
    mk(USER, ".f", default="Pf")
    mk(USER, r".f\ShellNew", NullFile="")
    mk(USER, "Pf", default="Prog F", FriendlyTypeName="Friendly F")
    mk(USER, ".p", default="Pp")
    mk(USER, r".p\ShellNew", NullFile="")
    mk(USER, "Pp", default="Prog P")
    mk(USER, r".x\ShellNew", NullFile="")
    mk(MACH, ".w", default="Pw")
    mk(MACH, r".w\ShellNew", NullFile="")
    mk(USER, ".q", default="Pq")
    mk(USER, r".q\ShellNew", NullFile="", MenuText="@%SystemRoot%\\system32\\shell32.dll,-4161")
    got = rows(ctxmenu.shellnew_menu(ROOTS))
    texts = {e: r.text for e, r in got.items()}
    assert texts[".m"] == "Menu" and texts[".f"] == "Friendly F", texts
    assert texts[".p"] == "Prog P" and texts[".x"] == ".x" and texts[".w"] == ".w", texts
    assert texts[".q"] and not texts[".q"].startswith("@"), texts
    # a MenuText naming a DLL that is gone falls through to the next source
    mk(USER, ".u", default="Pu")
    mk(USER, r".u\ShellNew", NullFile="", MenuText="@C:\\gone\\gone.dll,-1")
    mk(USER, "Pu", FriendlyTypeName="@C:\\gone\\gone.dll,-2", default="Prog U")
    mk(USER, r".v\_ShellNew", NullFile="", MenuText="@C:\\gone\\gone.dll,-1")
    assert rows(ctxmenu.shellnew_menu(ROOTS))[".u"].text == "Prog U"
    assert [e.text for e in ctxmenu.shellnew_removed(ROOTS)] == [".v"]
    print("text precedence ok")

    # ---- 4: order ----
    delete_tree(BASE)
    for e in (".Zed", ".alpha", ".b"):
        mk(USER, e + r"\ShellNew", NullFile="")
    items = ctxmenu.shellnew_menu(ROOTS)
    assert [i.text for i in items[:2]] == ["Folder", "Shortcut"], items[:2]
    assert all(i.source.kind == "builtin" and not i.removable for i in items[:2])
    assert items[2].separator and not items[2].children
    assert exts(items) == [".alpha", ".b", ".Zed"], exts(items)
    print("order ok")

    # ---- 5: hide / restore ----
    delete_tree(BASE)
    mk(USER, ".h", default="Ph")
    mk(USER, r".h\ShellNew", NullFile="", Foo="1")
    mk(USER, r".h\ShellNew\Config", Bar="2")
    mk(USER, r".h\_ShellNew", Stale="1")
    mk(USER, r".h\Ph\ShellNew", FileName="t.h")
    mk(MACH, r".h\ShellNew", NullFile="")
    mk(MACH, r"Ph\ShellNew", NullFile="")
    mk(CACHE, "", Classes="x")
    src = rows(ctxmenu.shellnew_menu(ROOTS))[".h"].source
    ctxmenu.remove(src, "H", "new", ROOTS)
    assert not exists(USER, r".h\ShellNew") and not exists(USER, r".h\Ph\ShellNew")
    assert not exists(MACH, r".h\ShellNew")
    assert exists(MACH, r"Ph\ShellNew"), "only .ext and its direct subkeys"
    assert values(USER, r".h\_ShellNew") == {"NullFile": "", "Foo": "1"}
    assert values(USER, r".h\_ShellNew\Config") == {"Bar": "2"}
    assert values(USER, r".h\Ph\_ShellNew") == {"FileName": "t.h"}
    assert exists(MACH, r".h\_ShellNew") and not exists(CACHE, "")
    assert not exists(RECORD, "") and ctxmenu.removed(ROOTS) == []
    assert ".h" not in rows(ctxmenu.shellnew_menu(ROOTS))
    gone = ctxmenu.shellnew_removed(ROOTS)
    assert [(e.name, e.menu, e.source.kind) for e in gone] == [
        ("shellnew|.h", "new", "shellnew")], gone
    mk(CACHE, "", Classes="x")
    ctxmenu.restore(gone[0], ROOTS)
    assert values(USER, r".h\ShellNew") == {"NullFile": "", "Foo": "1"}
    assert values(USER, r".h\Ph\ShellNew") == {"FileName": "t.h"}
    assert exists(MACH, r".h\ShellNew") and not exists(CACHE, "")
    assert not exists(USER, r".h\_ShellNew") and not exists(MACH, r".h\_ShellNew")
    assert ctxmenu.shellnew_removed(ROOTS) == []
    assert ".h" in rows(ctxmenu.shellnew_menu(ROOTS))
    # a missing cache key is fine
    ctxmenu.remove(src, "H", "new", ROOTS)
    ctxmenu.restore(ctxmenu.shellnew_removed(ROOTS)[0], ROOTS)

    # restore with a live ShellNew beside a _ShellNew: nothing changes
    ctxmenu.remove(src, "H", "new", ROOTS)
    mk(USER, r".h\Ph\ShellNew", FileName="live")
    mk(CACHE, "", Classes="x")
    entry = ctxmenu.Removed("shellnew|.h", "H", "new", src)
    try:
        ctxmenu.restore(entry, ROOTS)
    except FileExistsError as e:
        assert r".h\Ph\_ShellNew" in str(e), e
    else:
        raise AssertionError("restore over a live ShellNew did not raise")
    assert exists(USER, r".h\_ShellNew") and not exists(USER, r".h\ShellNew")
    assert exists(MACH, r".h\_ShellNew") and exists(CACHE, "")
    assert values(USER, r".h\Ph\ShellNew") == {"FileName": "live"}

    # a hide that fails on HKLM (not elevated) puts the HKCU keys back
    delete_tree(BASE)
    mk(USER, r".r\ShellNew", NullFile="")
    mk(USER, r".r\Pr\ShellNew", NullFile="")
    mk(MACH, r".r\ShellNew", NullFile="")
    real_rename = ctxmenu._rename_key

    def refuse_machine(hive, parent, old, new):
        if parent.startswith(MACH):
            raise PermissionError(5, "Access is denied")
        real_rename(hive, parent, old, new)

    ctxmenu._rename_key = refuse_machine
    try:
        ctxmenu.remove(rows(ctxmenu.shellnew_menu(ROOTS))[".r"].source, "R", "new", ROOTS)
    except PermissionError:
        pass
    else:
        raise AssertionError("refused HKLM rename did not raise")
    finally:
        ctxmenu._rename_key = real_rename
    assert exists(USER, r".r\ShellNew") and exists(USER, r".r\Pr\ShellNew")
    assert not exists(USER, r".r\_ShellNew") and not exists(USER, r".r\Pr\_ShellNew")
    assert exists(MACH, r".r\ShellNew")
    print("hide / restore ok")

    # ---- 6: hidden list ----
    delete_tree(BASE)
    mk(USER, r".i\_ShellNew", FileName="t")
    mk(USER, r".j\_ShellNew")
    mk(MACH, ".k", default="Pk")
    mk(MACH, r".k\Pk\_ShellNew", Data="1", MenuText="Kay")
    mk(USER, r".live\ShellNew", NullFile="")
    mk(USER, r".live\_ShellNew", NullFile="")
    got = ctxmenu.shellnew_removed(ROOTS)
    assert [e.name for e in got] == ["shellnew|.i", "shellnew|.k"], got
    assert got[0].text == ".i" and got[1].text == "Kay", got
    assert got[1].source.scope == "HKLM" and got[1].menu == "new"
    print("hidden list ok")

    # ---- 7: page ----
    assert ("New", "new") in ctxmenu.KINDS
    page = ctxmenu.ContextMenuPage()
    page.cmb_menu.setCurrentIndex(page.cmb_menu.findData("new"))
    assert not page.edt_path.isEnabled() and not page.btn_browse.isEnabled()
    assert page.btn_reload.isEnabled()
    page.cmb_menu.setCurrentIndex(page.cmb_menu.findData("file"))
    assert page.edt_path.isEnabled() and page.btn_browse.isEnabled()
    print("page ok")
finally:
    delete_tree(BASE)
print("ALL OK")
