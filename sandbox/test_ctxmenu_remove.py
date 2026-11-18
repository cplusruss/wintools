"""Contract test for ctxmenu.remove / restore / removed.

Every key lives under HKCU\\Software\\wintools-selftest-ctxmenu: a fake verb
key, fake classes, a fake Blocked key and a fake record store, injected
through ctxmenu.Roots.  The real LegacyDisable / Blocked / record keys are never
touched; the scratch tree is deleted afterwards.
"""

import os
import sys
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ctxmenu  # noqa: E402

HKCU = winreg.HKEY_CURRENT_USER
BASE = r"Software\wintools-selftest-ctxmenu"
BLOCKED = BASE + r"\Blocked"
RECORD = BASE + r"\Removed"
CLSID = "{12345678-1234-1234-1234-1234567890AB}"
OTHER = "{AAAAAAAA-0000-0000-0000-000000000000}"
CLASSES = BASE + r"\Classes"
# a record is only read back when its key is a shell verb under a Classes root
VERB = CLASSES + r"\Directory\shell\fake"
ROOTS = ctxmenu.Roots(blocked=(HKCU, BLOCKED), record=(HKCU, RECORD),
                      classes=(("HKCU", HKCU, CLASSES),))
SYSTEM_DLL = os.path.join(os.environ["SystemRoot"], "system32", "fake.dll")


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
                winreg.EnumValue(k, i)
                for i in range(winreg.QueryInfoKey(k)[1])))
    except FileNotFoundError:
        return {}


delete_tree(BASE)
try:
    winreg.CloseKey(winreg.CreateKey(HKCU, VERB))
    cmd = ctxmenu.Source("command", "fake", "HKCU\\" + VERB, "", "", "Directory")
    ext = ctxmenu.Source("extension", "Fake", "", CLSID, "", "all menus")

    assert ctxmenu.removed(ROOTS) == []

    # ---- command: LegacyDisable on the verb key ----
    ctxmenu.remove(cmd, "Fake Item", "folder", ROOTS)
    assert values(VERB)["LegacyDisable"] == ("", winreg.REG_SZ), values(VERB)
    rec = values(RECORD)
    assert list(rec) == ["command|HKCU\\" + VERB], rec
    got = ctxmenu.removed(ROOTS)
    assert len(got) == 1, got
    assert (got[0].text, got[0].menu) == ("Fake Item", "folder"), got[0]
    assert got[0].source.kind == "command" and got[0].source.key == cmd.key
    ctxmenu.restore(got[0], ROOTS)
    assert "LegacyDisable" not in values(VERB), values(VERB)
    assert values(RECORD) == {} and ctxmenu.removed(ROOTS) == []
    print("command remove / restore ok")

    # ---- extension: Blocked value, a pre-existing entry is left alone ----
    with winreg.CreateKey(HKCU, BLOCKED) as k:
        winreg.SetValueEx(k, OTHER, 0, winreg.REG_SZ, "")
    ctxmenu.remove(ext, "Fake | Pipe", "file", ROOTS)
    assert values(BLOCKED)[CLSID] == ("", winreg.REG_SZ), values(BLOCKED)
    assert list(values(RECORD)) == ["extension|" + CLSID], values(RECORD)
    got = ctxmenu.removed(ROOTS)
    assert [(e.text, e.menu, e.source.kind, e.source.clsid) for e in got] == [
        ("Fake | Pipe", "file", "extension", CLSID)], got
    ctxmenu.restore(got[0], ROOTS)
    assert CLSID not in values(BLOCKED) and OTHER in values(BLOCKED)
    assert ctxmenu.removed(ROOTS) == []
    print("extension remove / restore ok")

    # ---- restore when Windows no longer has the value is still a restore ----
    ctxmenu.remove(cmd, "Fake Item", "folder", ROOTS)
    with winreg.OpenKey(HKCU, VERB, 0, winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, "LegacyDisable")
    ctxmenu.restore(ctxmenu.removed(ROOTS)[0], ROOTS)
    assert ctxmenu.removed(ROOTS) == []
    ctxmenu.remove(ext, "Fake", "file", ROOTS)
    with winreg.OpenKey(HKCU, BLOCKED, 0, winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, CLSID)
    ctxmenu.restore(ctxmenu.removed(ROOTS)[0], ROOTS)
    assert ctxmenu.removed(ROOTS) == []
    print("restore of an already-restored item ok")

    # ---- a failed write raises OSError and leaves no record behind ----
    missing = ctxmenu.Source("command", "gone", "HKCU\\" + CLASSES + r"\Directory\shell\gone",
                             "", "", "Directory")
    try:
        ctxmenu.remove(missing, "Gone", "folder", ROOTS)
    except OSError:
        pass
    else:
        raise AssertionError("missing verb key did not raise")
    assert values(RECORD) == {}, values(RECORD)

    real = winreg.SetValueEx

    def refuse(key, name, *rest):
        # only the block itself is refused: the record is written first and
        # must be rolled back
        if name in ("LegacyDisable", CLSID):
            raise PermissionError(5, "Access is denied")
        return real(key, name, *rest)

    winreg.SetValueEx = refuse
    try:
        for src in (cmd, ext):
            try:
                ctxmenu.remove(src, "Denied", "folder", ROOTS)
            except PermissionError as e:
                assert "Access is denied" in str(e), e
            else:
                raise AssertionError("refused write was swallowed")
    finally:
        winreg.SetValueEx = real
    assert values(RECORD) == {} and CLSID not in values(BLOCKED), \
        (values(RECORD), values(BLOCKED))
    assert "LegacyDisable" not in values(VERB)
    print("refused write surfaces as OSError, no record left ok")

    # ---- a refused remove() keeps the record of an earlier removal ----
    ctxmenu.remove(ext, "First", "folder", ROOTS)
    before = values(RECORD)
    assert list(before) == ["extension|" + CLSID], before
    winreg.SetValueEx = refuse
    try:
        try:
            ctxmenu.remove(ext, "Second", "file", ROOTS)
        except PermissionError:
            pass
        else:
            raise AssertionError("refused write was swallowed")
    finally:
        winreg.SetValueEx = real
    assert values(RECORD) == before, (values(RECORD), before)
    ctxmenu.restore(ctxmenu.removed(ROOTS)[0], ROOTS)
    assert values(RECORD) == {} and CLSID not in values(BLOCKED)
    print("refused remove keeps the earlier record ok")

    # ---- classic extension: disable every ContextMenuHandlers registration ----
    FORM_A = CLASSES + r"\ClsA\shellex\ContextMenuHandlers\Fake"
    FORM_B = CLASSES + r"\ClsB\Sub\shellex\ContextMenuHandlers" + "\\" + CLSID
    FORM_B_EMPTY = CLASSES + r"\ClsC\shellex\ContextMenuHandlers" + "\\" + CLSID
    SHEET = CLASSES + r"\ClsA\shellex\PropertySheetHandlers\Fake"
    DRAG = CLASSES + r"\ClsA\shellex\DragDropHandlers\Fake"
    OTHER_REG = CLASSES + r"\ClsA\shellex\ContextMenuHandlers\Other"
    OFF = CLASSES + r"\ClsE\shellex\ContextMenuHandlers\Fake"
    for path, initial in ((FORM_A, CLSID), (FORM_B, None), (FORM_B_EMPTY, ""),
                          (SHEET, CLSID), (DRAG, CLSID), (OTHER_REG, OTHER),
                          (OFF, "-" + CLSID)):
        with winreg.CreateKey(HKCU, path) as k:
            if initial is not None:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, initial)

    def default(path):
        return values(path).get("")

    snapshot = {p: values(p) for p in (SHEET, DRAG, OTHER_REG, OFF, BLOCKED)}
    menu_regs = (FORM_A, FORM_B, FORM_B_EMPTY)
    before = {p: values(p) for p in menu_regs}
    live = ctxmenu.Source("extension", "Fake", "", CLSID, "", "all menus")
    ctxmenu.remove(live, "Fake", "folder", ROOTS)
    for path in menu_regs:
        assert default(path) == ("-" + CLSID, winreg.REG_SZ), (path, values(path))
    assert {p: values(p) for p in snapshot} == snapshot, "untouched keys changed"
    assert CLSID not in values(BLOCKED), "Blocked list must not be used"
    rec = ctxmenu.removed(ROOTS)
    assert len(rec) == 1 and (rec[0].text, rec[0].menu) == ("Fake", "folder"), rec
    assert rec[0].source.kind == "extension" and rec[0].source.clsid == CLSID
    assert sorted(rec[0].regs, key=str) == sorted([
        ("HKCU\\" + FORM_A, CLSID), ("HKCU\\" + FORM_B, None),
        ("HKCU\\" + FORM_B_EMPTY, "")], key=str), rec[0].regs
    ctxmenu.restore(rec[0], ROOTS)
    assert {p: values(p) for p in menu_regs} == before, "restore is not exact"
    assert default(FORM_B) is None, "Form B must have no default value again"
    assert default(FORM_B_EMPTY) == ("", winreg.REG_SZ)
    assert {p: values(p) for p in snapshot} == snapshot
    assert values(RECORD) == {} and ctxmenu.removed(ROOTS) == []
    print("registration remove / restore exact ok")

    # a refused registration write undoes the earlier ones and leaves no record
    seen = []

    def refuse_second(key, name, *rest):
        if name == "" and str(rest[2]).startswith("-"):
            seen.append(rest[2])
            if len(seen) == 2:
                raise PermissionError(5, "Access is denied")
        return real(key, name, *rest)

    winreg.SetValueEx = refuse_second
    try:
        try:
            ctxmenu.remove(live, "Fake", "folder", ROOTS)
        except PermissionError:
            pass
        else:
            raise AssertionError("refused write was swallowed")
    finally:
        winreg.SetValueEx = real
    assert len(seen) == 2, seen
    assert {p: values(p) for p in menu_regs} == before, "partial write not undone"
    assert values(RECORD) == {} and CLSID not in values(BLOCKED)
    print("refused registration write undone ok")

    # ---- Explorer-command rows without a registration use the Blocked list ----
    package = "{CCCCCCCC-0000-0000-0000-000000000000}"
    guid_row = ctxmenu.Source("extension", "Terminal", "", package, "", "all menus")
    ctxmenu.remove(guid_row, "Open in Terminal", "folder", ROOTS)
    assert package in values(BLOCKED), values(BLOCKED)
    assert default(OTHER_REG) == (OTHER, winreg.REG_SZ), "registered row touched"
    assert {p: values(p) for p in menu_regs} == before
    ctxmenu.restore(ctxmenu.removed(ROOTS)[0], ROOTS)
    assert package not in values(BLOCKED) and values(RECORD) == {}
    print("blocked-list path ok")

    # ---- a %SystemRoot% server with no registration is built-in ----
    ghost = "{BBBBBBBB-0000-0000-0000-000000000000}"
    internal = ctxmenu.Source("extension", "Internal", "", ghost, SYSTEM_DLL,
                              "all menus")
    try:
        ctxmenu.remove(internal, "Internal", "background", ROOTS)
    except ValueError:
        pass
    else:
        raise AssertionError("system server without registration was removed")
    assert values(RECORD) == {} and ghost not in values(BLOCKED)
    sysreg = ctxmenu.Source("extension", "System", "", CLSID, SYSTEM_DLL, "all menus")
    ctxmenu.remove(sysreg, "System", "folder", ROOTS)  # registered: removable
    assert default(FORM_A) == ("-" + CLSID, winreg.REG_SZ)
    ctxmenu.restore(ctxmenu.removed(ROOTS)[0], ROOTS)
    assert {p: values(p) for p in menu_regs} == before

    def row(src):
        return ctxmenu.MenuItem(src.label, src.label, source=src)

    items = [row(internal), row(sysreg), row(live),
             ctxmenu.MenuItem("", separator=True)]
    ctxmenu._demote_internals(items, ROOTS)
    assert [i.separator or i.source.kind for i in items] == [
        "builtin", "extension", "extension", True], items
    assert not items[0].removable and items[1].removable and items[2].removable
    assert items[0].source.clsid == ghost and items[0].source.dll == SYSTEM_DLL
    print("system server without registration is built-in ok")

    # ---- a built-in row is never removable ----
    try:
        ctxmenu.remove(ctxmenu.BUILTIN, "Cut", "folder", ROOTS)
    except ValueError:
        pass
    else:
        raise AssertionError("built-in removal was accepted")
    assert values(RECORD) == {}, values(RECORD)

    # ---- the production roots are the documented keys ----
    assert ctxmenu.ROOTS.blocked == (
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked")
    assert ctxmenu.ROOTS.record == (HKCU, r"Software\wintools\ContextMenu\Removed")
    assert ctxmenu.ROOTS.classes == (
        ("HKCU", HKCU, r"Software\Classes"),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE, r"Software\Classes"))
finally:
    delete_tree(BASE)

try:
    winreg.CloseKey(winreg.OpenKey(HKCU, BASE))
except FileNotFoundError:
    pass
else:
    raise AssertionError("scratch tree left behind")
print("STATUS: SUCCESS")
