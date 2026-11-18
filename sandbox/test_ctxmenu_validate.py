"""Contract test for what the elevated app accepts from files other processes
can write: the helper outfile (ctxmenu.load_menu) and the HKCU removal record
(ctxmenu.removed).

Both feed remove() / restore(), which write to the registry, so a source must
name a shell verb or a handler registration under a Software\\Classes root and a
CLSID must be a GUID.  A malformed or stale-schema outfile is a ValueError, not
a crash.  Planted outfiles come from an injected launcher; records live under
HKCU\\Software\\wintools-selftest-ctxmenu-validate; nothing real is touched.
"""

import json
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
BASE = r"Software\wintools-selftest-ctxmenu-validate"
CLASSES = BASE + r"\Classes"
BLOCKED = BASE + r"\Blocked"
RECORD = BASE + r"\Removed"
ROOTS = ctxmenu.Roots(blocked=(HKCU, BLOCKED), record=(HKCU, RECORD),
                      classes=(("HKCU", HKCU, CLASSES),))
CLSID = "{12345678-1234-1234-1234-1234567890AB}"
OTHER = "{AAAAAAAA-0000-0000-0000-000000000000}"
PROD = ctxmenu.ROOTS  # what load_menu validates against
GOOD_VERB = r"HKCU\Software\Classes\Directory\shell\wintools-selftest"
GOOD_HANDLER = (r"HKLM\Software\Classes\Directory\shellex\ContextMenuHandlers"
                r"\wintools-selftest")
PACKAGED = "HKCR\\PackagedCom\\ClassIndex\\" + CLSID


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


def source(kind, key="", clsid=""):
    return {"kind": kind, "label": "x", "key": key, "clsid": clsid, "dll": "",
            "scope": ""}


def item(src=None, **over):
    return dict({"text": "x", "raw": "x", "verb": "", "separator": False,
                 "icon": None, "children": [], "source": src}, **over)


def rejects(call, field):
    try:
        call()
    except ValueError as e:
        assert f"unexpected {field} " in str(e), (field, str(e))
        return
    raise AssertionError(f"accepted a bad {field}")


# ---- the source validator ----
GOOD = [
    ("command", GOOD_VERB, ""),
    ("command", r"hklm\software\classes\*\SHELL\x", ""),
    ("extension", "", CLSID),
    ("extension", GOOD_HANDLER, CLSID),
    ("extension", r"HKLM\Software\Classes\*\shell\ANotepad++64", CLSID),
    ("extension", PACKAGED, CLSID),
    ("builtin", "", ""),
    ("builtin", "anything at all", "not a guid"),
]
for kind, key, clsid in GOOD:
    ctxmenu._validate_source(kind, key, clsid, PROD, "t")
BAD = [
    ("other", "", "", "kind"),
    ("command", r"HKCU\Software\wintools-review-scratch\evil", "", "key"),
    ("command", r"HKLM\Software\Classes\Directory", "", "key"),
    ("command", r"HKCR\Directory\shell\x", "", "key"),
    ("command", r"HKCU\Software\Classes2\Directory\shell\x", "", "key"),
    ("command", r"HKCU\Software\Run\shell\x", "", "key"),
    ("command", "", "", "key"),
    ("extension", "", "ANYTHING-NOT-A-GUID", "clsid"),
    ("extension", "", "", "clsid"),
    ("extension", "", CLSID + " ", "clsid"),
    ("extension", "", CLSID + "\n", "clsid"),
    ("extension", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", CLSID, "key"),
    ("extension", r"HKCU\Software\Classes\CLSID" + "\\" + CLSID, CLSID, "key"),
    ("extension", "HKCR\\PackagedCom\\ClassIndex\\" + OTHER, CLSID, "key"),
]
for kind, key, clsid, field in BAD:
    rejects(lambda: ctxmenu._validate_source(kind, key, clsid, PROD, "t"), field)
# the roots in force decide what is a Classes root
ctxmenu._validate_source("command", "HKCU\\" + CLASSES + r"\Directory\shell\x", "",
                         ROOTS, "t")
rejects(lambda: ctxmenu._validate_source("command", GOOD_VERB, "", ROOTS, "t"), "key")
print("source validator ok")

# ---- the removal record ----


def put(name, data, kind=winreg.REG_SZ):
    with winreg.CreateKey(HKCU, RECORD) as k:
        winreg.SetValueEx(k, name, 0, kind, data)


def clear():
    delete_tree(RECORD)


def record_rejects(name, data, field, kind=winreg.REG_SZ):
    clear()
    put(name, data, kind)
    rejects(lambda: ctxmenu.removed(ROOTS), field)
    clear()


HANDLER = "HKCU\\" + CLASSES + r"\Directory\shellex\ContextMenuHandlers\Fake"
delete_tree(BASE)
try:
    # well-formed records are read back
    put("command|HKCU\\" + CLASSES + r"\Directory\shell\fake", "folder|Fake")
    put("extension|" + CLSID, ["folder|Fake", "S" + CLSID + "|" + HANDLER,
                               "N|" + HANDLER + "2", "S|" + HANDLER + "3"],
        winreg.REG_MULTI_SZ)
    got = {e.name: e for e in ctxmenu.removed(ROOTS)}
    assert len(got) == 2, got
    assert got["extension|" + CLSID].regs == (
        (HANDLER, CLSID), (HANDLER + "2", None), (HANDLER + "3", ""))
    clear()

    verb_bad = r"command|HKCU\Software\wintools-review-scratch\evil"
    record_rejects(verb_bad, "folder|x", "key")
    record_rejects(r"command|HKLM\Software\Classes\Directory", "folder|x", "key")
    record_rejects("command|nobackslash", "folder|x", "key")
    record_rejects("command|", "folder|x", "key")
    record_rejects("extension|ANYTHING-NOT-A-GUID", "folder|x", "clsid")
    record_rejects("extension|", "folder|x", "clsid")
    record_rejects("extension|" + CLSID, ["folder|x", "S" + CLSID + r"|HKCU\Software\Run"],
                   "registration", winreg.REG_MULTI_SZ)
    record_rejects("extension|" + CLSID,
                   ["folder|x", "S" + CLSID + "|HKCU\\" + CLASSES + r"\Directory\shell\x"],
                   "registration", winreg.REG_MULTI_SZ)
    record_rejects("extension|" + CLSID,
                   ["folder|x", "S" + CLSID + r"|HKLM\Software\Classes\Directory"
                    r"\shellex\ContextMenuHandlers\X"],
                   "registration", winreg.REG_MULTI_SZ)
    record_rejects("extension|" + CLSID, ["folder|x", "S" + OTHER[:-1] + "|" + HANDLER],
                   "previous", winreg.REG_MULTI_SZ)
    record_rejects("extension|" + CLSID, ["folder|x", "Sevil|" + HANDLER],
                   "previous", winreg.REG_MULTI_SZ)
    # a value of the wrong registry type is an unreadable record, not a crash
    for data, kind in ((5, winreg.REG_DWORD), (b"\x00", winreg.REG_BINARY)):
        put("extension|" + CLSID, data, kind)
        try:
            ctxmenu.removed(ROOTS)
        except ValueError as e:
            assert "unreadable record" in str(e), e
        else:
            raise AssertionError(f"record of type {kind} accepted")
        clear()
    assert values(BLOCKED) == {} and values(RECORD) == {}
    print("removal record validated ok")
finally:
    delete_tree(BASE)

# ---- a planted or malformed outfile ----
captured = []
real_outfile = ctxmenu._outfile


def spy_outfile():
    captured.append(real_outfile())
    return captured[-1]


def plant(content):
    """Launcher that writes `content` (a document, or raw text) as the outfile."""
    def launch(exe, params, cwd):
        text = content if isinstance(content, str) else json.dumps(content)
        Path(captured[-1]).write_text(text, encoding="utf-8")
    return launch


def load(content):
    return ctxmenu.load_menu("folder", r"C:\Dropbox", elevated=True,
                             launch=plant(content))


ctxmenu._outfile = spy_outfile
SCRATCH = r"Software\wintools-review-scratch\evil"
try:
    ok = load({"items": [item(source("command", GOOD_VERB)),
                         item(source("extension", GOOD_HANDLER, CLSID)),
                         item(None, separator=True, text="", raw=""),
                         item(source("builtin"), children=[
                             item(source("extension", "", CLSID))])]})
    assert [i.text for i in ok] == ["x", "x", "", "x"] and ok[3].children[0].source.clsid == CLSID
    assert ok[0].removable and ok[2].separator and ok[2].source is None
    print("well-formed outfile accepted ok")

    # a planted source never reaches remove(): the load itself refuses it
    delete_tree(r"Software\wintools-review-scratch")
    winreg.CloseKey(winreg.CreateKey(HKCU, SCRATCH))
    rejects(lambda: load({"items": [item(source("command", "HKCU\\" + SCRATCH))]}), "key")
    rejects(lambda: load({"items": [item(source("extension", "", "NOT-A-GUID"))]}), "clsid")
    rejects(lambda: load({"items": [item(source("evil"))]}), "kind")
    rejects(lambda: load({"items": [item(None, children=[
        item(source("command", "HKCU\\" + SCRATCH))])]}), "key")
    assert values(SCRATCH) == {}, "a planted key was written"
    print("planted sources refused ok")

    # malformed or stale-schema files are a ValueError, never a KeyError / TypeError
    good = item(source("command", GOOD_VERB))
    shapes = {
        "missing item key": {"items": [{"text": "x"}]},
        "extra item key": {"items": [dict(good, extra=1)]},
        "missing source key": {"items": [item({k: v for k, v in source("command", GOOD_VERB).items()
                                               if k != "dll"})]},
        "extra source key": {"items": [item(dict(source("command", GOOD_VERB), extra=1))]},
        "list root": [1],
        "string root": "items",
        "no items": {},
        "extra root key": {"items": [], "extra": 1},
        "items not a list": {"items": {"a": 1}},
        "item not a dict": {"items": [5]},
        "text not a string": {"items": [dict(good, text=5)]},
        "separator not a bool": {"items": [dict(good, separator="no")]},
        "children not a list": {"items": [dict(good, children=5)]},
        "source not a dict": {"items": [dict(good, source="x")]},
        "source field not a string": {"items": [item(dict(source("command", GOOD_VERB),
                                                          key=5))]},
        "icon not a string": {"items": [dict(good, icon=5)]},
        "icon not base64": {"items": [dict(good, icon="@@@@")]},
        "icon not a png": {"items": [dict(good, icon="AAAA")]},
        "error not a string": {"error": 5},
        "error plus items": {"error": "x", "items": []},
    }
    for name, doc in shapes.items():
        try:
            load(doc)
        except ValueError as e:
            assert str(e), name
        else:
            raise AssertionError(f"{name}: accepted")
    for name, text in (("empty file", ""), ("not json", "{items"),
                       ("truncated", '{"items": [{"text": '),
                       ("nested too deep", "[" * 200000 + "]" * 200000),
                       ("deep children", json.dumps({"items": [good]}).replace(
                           '"children": []', '"children": ' + "[" * 5000 + "]" * 5000))):
        try:
            load(text)
        except ValueError as e:
            assert str(e), name
        else:
            raise AssertionError(f"{name}: accepted")
    # a genuine helper error is still an OSError carrying its text
    try:
        load({"error": "The system cannot find the file specified."})
    except OSError as e:
        assert str(e) == "The system cannot find the file specified.", e
    else:
        raise AssertionError("helper error swallowed")
    print(f"{len(shapes) + 5} malformed outfiles refused as ValueError ok")

    # the page shows it instead of crashing
    real_admin = ctxmenu.shell.IsUserAnAdmin
    real_launch = ctxmenu._explorer_launch
    ctxmenu.shell.IsUserAnAdmin = lambda: True
    try:
        page = ctxmenu.ContextMenuPage()
        for name, content in (("list root", [1]), ("missing key", {"items": [{"text": "x"}]}),
                              ("extra source key",
                               {"items": [item(dict(source("command", GOOD_VERB), extra=1))]}),
                              ("planted key",
                               {"items": [item(source("command", "HKCU\\" + SCRATCH))]})):
            ctxmenu._explorer_launch = plant(content)
            msg = page.reload()
            assert msg and page.status.text() == msg, (name, msg)
            assert page.tree.topLevelItemCount() == 0, name
    finally:
        ctxmenu.shell.IsUserAnAdmin = real_admin
        ctxmenu._explorer_launch = real_launch
    print("page reports a bad outfile in the status label ok")
finally:
    ctxmenu._outfile = real_outfile
    delete_tree(r"Software\wintools-review-scratch")
    delete_tree(BASE)

for path in (BASE, r"Software\wintools-review-scratch"):
    try:
        winreg.CloseKey(winreg.OpenKey(HKCU, path))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError(f"scratch key left behind: {path}")
print("STATUS: SUCCESS")
