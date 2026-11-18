"""Contract test for handlers that create but refuse to load outside Explorer.

A ContextMenuHandlers CLSID that CoCreateInstance builds but whose Initialize
or QueryContextMenu fails is listed after the live rows, separated from them,
unless its DLL sits under %SystemRoot%: those refuse inside Explorer too.
The refusal is injected at CoCreateInstance, so the real _probe classifies it.
The handlers' DLLs come from scratch CLSID registrations under
HKCU\\Software\\Classes\\CLSID, deleted afterwards.  Removal and restore run
against scratch roots under HKCU\\Software\\wintools-selftest-ctxmenu-refused;
the real Blocked and record keys are never touched.  The real menus are only
read.
"""

import os
import shutil
import sys
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pythoncom  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import ctxmenu  # noqa: E402

app = QApplication([])
HKCU = winreg.HKEY_CURRENT_USER
BASE = r"Software\wintools-selftest-ctxmenu-refused"
CLASSES = BASE + r"\Classes"
BLOCKED = BASE + r"\Blocked"
RECORD = BASE + r"\Removed"
ROOTS = ctxmenu.Roots(blocked=(HKCU, BLOCKED), record=(HKCU, RECORD),
                      classes=(("HKCU", HKCU, CLASSES),))
E_FAIL, NOT_REGISTERED = -2147467259, -2147221164
# a registered CLSID that is not a ContextMenuHandler of any folder menu
SHELLLINK = "{00021401-0000-0000-C000-000000000046}"
OPUS = "{E9FE4040-3C93-11D4-8006-00201860E88A}"
WORKFOLDERS = "{E61BF828-5E63-4287-BEF1-60B1A4FDE0E3}"
IPE = r"C:\Dropbox\Common\tools\ipe"
ROOT = os.path.join(os.environ["TEMP"], "wintools-selftest-ctxmenu-refused")
shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(ROOT)

# scratch handlers: CLSID -> (registered name, InprocServer32 or None)
CLSID_KEY = "Software\\Classes\\CLSID\\"
OUTSIDE, OUTSIDE2, NODLL, SYSTEM = (
    "{5E1F7E57-0000-4000-8000-00000000000%d}" % n for n in range(1, 5))
OUTSIDE_DLL = r"C:\Program Files\wintools-selftest\outside.dll"
SYSTEM_DLL = os.path.join(os.environ["SystemRoot"], "System32", "wintools-selftest.dll")
SCRATCH = {
    OUTSIDE: ("wintools selftest outside", OUTSIDE_DLL),
    OUTSIDE2: ("wintools selftest outside two", r"D:\Tools\wintools-selftest\two.dll"),
    NODLL: ("wintools selftest no dll", None),
    SYSTEM: ("wintools selftest system", SYSTEM_DLL),
}


def key_for(clsid):
    return r"HKCU\Software\Classes\Directory\shellex\ContextMenuHandlers\Fake" + clsid


class Handler:
    """Stands in for what CoCreateInstance returns: fails at the named step."""

    def __init__(self, fail):
        self.fail = fail

    def Initialize(self, pidl, data, key):
        if self.fail == "initialize":
            raise pythoncom.com_error(E_FAIL, "Unspecified error", None, None)

    def QueryInterface(self, iid):
        return self

    def QueryContextMenu(self, menu, index, first, last, flags):
        if self.fail == "query":
            raise pythoncom.com_error(E_FAIL, "Unspecified error", None, None)
        return 0


class Inject:
    """Registered handlers added to every menu's list, each forced to a state:
    'notregistered', 'initialize', 'query' or 'works'."""

    def __init__(self, states):
        self.states = states
        self.created = []

    def __enter__(self):
        self.create = pythoncom.CoCreateInstance
        self.handlers = ctxmenu._handlers
        pythoncom.CoCreateInstance = self._create
        ctxmenu._handlers = lambda classes: self.handlers(classes) + [
            (c, key_for(c)) for c in self.states]
        return self

    def __exit__(self, *exc):
        pythoncom.CoCreateInstance = self.create
        ctxmenu._handlers = self.handlers

    def _create(self, clsid, *args):
        state = self.states.get(str(clsid).upper())
        if state is None:
            return self.create(clsid, *args)
        self.created.append(clsid)
        if state == "notregistered":
            raise pythoncom.com_error(NOT_REGISTERED, "Class not registered", None, None)
        return Handler(state)


def values(path):
    try:
        with winreg.OpenKey(HKCU, path) as k:
            return dict((n, (d, t)) for n, d, t in (
                winreg.EnumValue(k, i) for i in range(winreg.QueryInfoKey(k)[1])))
    except FileNotFoundError:
        return {}


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


def register(clsid, name, dll):
    with winreg.CreateKey(HKCU, CLSID_KEY + clsid) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, name)
    if dll is not None:
        with winreg.CreateKey(HKCU, CLSID_KEY + clsid + r"\InprocServer32") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, dll)


def label(clsid):
    return SCRATCH[clsid][0]


def refused_rows(items):
    return [i for i in items if i.source and i.source.kind == "extension"
            and i.source.key.startswith(r"HKCU\Software\Classes\Directory\shellex"
                                        r"\ContextMenuHandlers\Fake")]


def shape(items):
    return [(i.text, i.verb, i.separator, i.source and i.source.clsid,
             shape(i.children)) for i in items]


def machine_refusals(kind, path):
    """Listed rows this machine's own handlers refuse (Directory Opus...)"""
    _cm, pidl, data = ctxmenu._shell_objects(kind, path)
    return sum(1 for c, k in ctxmenu._handlers(ctxmenu._menu_classes(kind, path))
               if ctxmenu._probe(c, pidl, data) is ctxmenu.REFUSED
               and not ctxmenu._in_system(ctxmenu._extension_source(c, k).dll))


def added(kind, path, states):
    """Rows that injecting `states` appends to the menu, with the live rows and
    the machine's own refused rows left exactly as they were."""
    base = ctxmenu.build_menu(kind, path)
    with Inject(states) as inj:
        rows = ctxmenu.build_menu(kind, path)
    assert shape(rows[:len(base)]) == shape(base), f"{kind}: earlier rows changed"
    return rows[len(base):], machine_refusals(kind, path), inj


def refused_tail(items):
    """The extension rows after the last separator: refused handlers."""
    cut = max(k for k, r in enumerate(items) if r.separator)
    return [r for r in items[cut + 1:] if r.source.kind == "extension"]


for name in SCRATCH:
    delete_tree(CLSID_KEY + name)
for name, (text, dll) in SCRATCH.items():
    register(name, text, dll)
try:
    # ---- the fixtures resolve to what each case needs, with _in_system untouched ----
    assert not ctxmenu._in_system(ctxmenu._extension_source(OUTSIDE).dll)
    assert not ctxmenu._in_system(ctxmenu._extension_source(NODLL).dll)
    assert ctxmenu._extension_source(NODLL).dll == ""
    assert ctxmenu._in_system(ctxmenu._extension_source(SYSTEM).dll)
    assert ctxmenu._extension_source(OUTSIDE).label == label(OUTSIDE)

    # ---- _probe tells the three outcomes apart ----
    _cm, pidl, data = ctxmenu._shell_objects("folder", ROOT)
    for state, want in (("notregistered", None), ("initialize", ctxmenu.REFUSED),
                        ("query", ctxmenu.REFUSED), ("works", [])):
        with Inject({SHELLLINK: state}):
            got = ctxmenu._probe(SHELLLINK, pidl, data)
        assert got is want or got == want, (state, got)
    print("probe outcomes ok")

    # ---- build_menu lists a created-but-refused handler after the live rows ----
    live = ctxmenu.build_menu("folder", ROOT)
    assert not refused_rows(live)
    extra, own, inj = added("folder", ROOT, {OUTSIDE: "initialize"})
    assert inj.created == [OUTSIDE], inj.created
    # the group opens with a separator unless the machine's own refused rows did
    assert [i.separator for i in extra] == ([True] if not own else []) + [False], extra
    row = extra[-1]
    assert row.text == label(OUTSIDE) == row.source.label, (row.text, row.source)
    assert (row.source.kind, row.source.clsid, row.source.key, row.source.dll) == (
        "extension", OUTSIDE, key_for(OUTSIDE), OUTSIDE_DLL), row.source
    assert row.removable and row.children == [] and not row.verb
    print(f"refused row ok: {row.text!r} after {own} machine refusal(s)")

    # a failing QueryContextMenu is refused the same way
    extra, own, _inj = added("folder", ROOT, {OUTSIDE: "query"})
    assert [i.source.clsid for i in extra if not i.separator] == [OUTSIDE]

    # a handler with no registered DLL is not a system handler: it is listed
    extra, own, _inj = added("folder", ROOT, {NODLL: "initialize"})
    assert [i.source.clsid for i in extra if not i.separator] == [NODLL]

    # a refusing handler whose DLL is under %SystemRoot% adds no row, no separator
    for state in ("initialize", "query"):
        extra, _own, inj = added("folder", ROOT, {SYSTEM: state})
        assert inj.created == [SYSTEM], "the system handler must still be probed"
        assert extra == [], f"system handler ({state}) must add no row"
    extra, own, _inj = added("folder", ROOT, {SYSTEM: "initialize",
                                              OUTSIDE: "initialize"})
    assert [i.separator for i in extra] == ([True] if not own else []) + [False]
    assert [i.source.clsid for i in extra if not i.separator] == [OUTSIDE]
    print("system handlers not listed ok")

    # creation failures (Class not registered) and working handlers are not listed
    extra, _own, _inj = added("folder", ROOT, {OUTSIDE: "notregistered",
                                               OUTSIDE2: "works"})
    assert extra == [], "non-refused handlers must not add rows"

    # several refusals share one separator and are all listed
    extra, own, _inj = added("folder", ROOT, {OUTSIDE: "initialize",
                                              OUTSIDE2: "query"})
    assert [i.separator for i in extra] == ([True] if not own else []) + [False, False]
    assert {i.source.clsid for i in extra if not i.separator} == {OUTSIDE, OUTSIDE2}
    print("several refusals ok")

    # every menu kind gets them
    for kind, path in (("file", os.path.join(os.environ["SystemRoot"], "win.ini")),
                       ("background", ROOT), ("drive", "C:\\")):
        extra, own, _inj = added(kind, path, {OUTSIDE: "initialize"})
        assert [i.separator for i in extra] == ([True] if not own else []) + [False], kind
    print("refused rows in every menu kind ok")

    # ---- the refused row removes and restores like a classic extension ----
    REG = CLASSES + r"\Directory\shellex\ContextMenuHandlers\Fake"
    SHEET = CLASSES + r"\Directory\shellex\PropertySheetHandlers\Fake"
    delete_tree(BASE)
    try:
        for path in (REG, SHEET):
            with winreg.CreateKey(HKCU, path) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, OUTSIDE)
        base = CLASSES + r"\Directory\shellex\ContextMenuHandlers"
        assert [e[1] for e in ctxmenu._entries(HKCU, base)] == [OUTSIDE]
        with Inject({OUTSIDE: "initialize"}):
            row = refused_rows(ctxmenu.build_menu("folder", ROOT))[0]
        sheet = values(SHEET)

        ctxmenu.remove(row.source, row.text, "folder", ROOTS)
        assert values(REG)[""] == ("-" + OUTSIDE, winreg.REG_SZ), values(REG)
        assert values(SHEET) == sheet, "other roles of the handler must stay"
        assert OUTSIDE not in values(BLOCKED), "registered handler is not blocked"
        assert ctxmenu._entries(HKCU, base) == [], "a removed handler is no longer listed"
        gone = ctxmenu.removed(ROOTS)
        assert len(gone) == 1 and (gone[0].text, gone[0].menu) == (row.text, "folder")
        assert gone[0].source.clsid == OUTSIDE and gone[0].source.label == row.text
        ctxmenu.restore(gone[0], ROOTS)
        assert values(REG)[""] == (OUTSIDE, winreg.REG_SZ), values(REG)
        assert values(RECORD) == {} and ctxmenu.removed(ROOTS) == []
        assert [e[1] for e in ctxmenu._entries(HKCU, base)] == [OUTSIDE]
        print("refused row remove / restore round trip ok")
    finally:
        delete_tree(BASE)

    # ---- the page: checkable, kept in Preview as a plain entry ----
    with Inject({OUTSIDE: "initialize"}):
        tree = ctxmenu.build_menu("folder", ROOT)
    ctxmenu.load_menu = lambda kind, path: tree
    ctxmenu.removed = lambda roots=None: []
    page = ctxmenu.ContextMenuPage()
    page.resize(900, 520)
    page.show()
    app.processEvents()
    tops = [page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())]
    last = tops[-1]
    assert last.text(0) == row.text
    cut = max(k for k, t in enumerate(tops) if t.data(0, Qt.UserRole).separator)
    assert all("ContextMenuHandlers" in t.data(0, Qt.UserRole).source.key
               for t in tops[cut + 1:]), "refused rows must trail the last separator"
    assert last.flags() & Qt.ItemIsUserCheckable and last.checkState(0) == Qt.Checked
    assert page.status.text() == "0 removed   0 restored", page.status.text()
    menu = page.preview_menu()
    entry = [a for a in menu.actions() if a.text() == row.text.replace("&", "&&")]
    assert len(entry) == 1 and entry[0].menu() is None and not entry[0].isSeparator()
    assert menu.actions()[-1] is entry[0]
    assert any(a.isSeparator() for a in menu.actions()[:-1])
    last.setCheckState(0, Qt.Unchecked)
    assert page.status.text() == "1 removed   0 restored", page.status.text()
    assert not [a for a in page.preview_menu().actions()
                if a.text() == row.text.replace("&", "&&")]
    print("page row checkable, preview entry ok")

    # ---- this machine's real refused rows: none is a %SystemRoot% handler ----
    for path in (ROOT, IPE):
        if not os.path.isdir(path):
            continue
        rows = ctxmenu.build_menu("folder", path)
        tail = refused_tail(rows)
        assert not [r for r in tail if ctxmenu._in_system(r.source.dll)], \
            [(r.text, r.source.dll) for r in tail]
        assert WORKFOLDERS not in [r.source.clsid.upper() for r in rows if r.source], \
            "Work Folders (System32) must not be listed"
        print(f"real refused rows for {path}:",
              [(r.text, r.source.dll) for r in tail] or "none")
        print("  Directory Opus listed:",
              OPUS in [r.source.clsid.upper() for r in tail])
finally:
    for name in SCRATCH:
        delete_tree(CLSID_KEY + name)

shutil.rmtree(ROOT, ignore_errors=True)
for path in [CLSID_KEY + c for c in SCRATCH] + [BASE]:
    try:
        winreg.CloseKey(winreg.OpenKey(HKCU, path))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError(f"scratch key left behind: {path}")
print("STATUS: SUCCESS")
