"""Contract test for ctxmenu.build_menu.

Builds the real shell menus for scratch paths in %TEMP% and for drive C:\\,
asks each item for its verb and attributes it to a registry source.  The only
writes are scratch HKCU verbs named wintools-selftest under
Directory\\Background\\shell and Drive\\shell, deleted afterwards.  No menu
command is ever invoked.
"""

import os
import re
import shutil
import sys
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pythoncom  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
from win32com.shell import shellcon  # noqa: E402

import ctxmenu  # noqa: E402
import tweaks  # noqa: E402

app = QApplication([])
ROOT = os.path.join(os.environ["TEMP"], "wintools-selftest-ctxmenu")
shutil.rmtree(ROOT, ignore_errors=True)
FOLDER = os.path.join(ROOT, "dir")
FILE = os.path.join(ROOT, "scratch.txt")
os.makedirs(FOLDER)
Path(FILE).write_text("x")

CASES = (("folder", FOLDER), ("file", FILE), ("background", FOLDER),
         ("drive", "C:\\"))
GUID = re.compile(r"^\{[0-9A-Fa-f-]{36}\}$")
HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}


def walk(items):
    for it in items:
        yield it
        yield from walk(it.children)


def key_exists(full):
    hive, sub = full.split("\\", 1)
    try:
        winreg.CloseKey(winreg.OpenKey(HIVES[hive], sub))
    except OSError:
        return False
    return True


HKCU = winreg.HKEY_CURRENT_USER
VERB = "wintools-selftest"
VERB_TEXT = "wintools selftest item"
SCRATCH_VERBS = {
    "background": "Software\\Classes\\Directory\\Background\\shell\\" + VERB,
    "drive": "Software\\Classes\\Drive\\shell\\" + VERB,
}


def delete_verb(sub):
    for key in (sub + "\\command", sub):
        try:
            winreg.DeleteKey(HKCU, key)
        except FileNotFoundError:
            pass


for sub in SCRATCH_VERBS.values():
    delete_verb(sub)
    with winreg.CreateKey(HKCU, sub) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, VERB_TEXT)
    with winreg.CreateKey(HKCU, sub + "\\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "cmd.exe /c exit")
try:
    menus = {}
    for kind, path in CASES:
        items = ctxmenu.build_menu(kind, path)
        menus[kind] = items
        real = [i for i in items if not i.separator]
        assert real, kind
        assert any(i.separator for i in items), f"{kind}: no separator flagged"
        assert all(not i.text or "&" not in i.text.replace("&&", "")
                   for i in walk(items)), f"{kind}: mnemonic left in text"
        for i in items:
            if i.separator:
                assert i.source is None and not i.text, (kind, i)
            else:
                assert i.source is not None, (kind, i.text)
                assert i.source.kind in ("command", "extension", "builtin"), i
        print(f"{kind}: {len(real)} items, "
              f"{sum(1 for i in walk(items) if i.children)} submenus")
        for i in real:
            s = i.source
            print(f"   {i.text[:34]:34} {i.verb[:24]:24} {s.kind:9} {s.label[:30]:30}"
                  f" {s.key[-46:]}")

    # a scratch verb of the background and drive menus is a command-sourced row
    # attributed to exactly the key that defines it
    for kind, sub in SCRATCH_VERBS.items():
        key = "HKCU\\" + sub
        hits = [i for i in walk(menus[kind]) if i.source and i.source.key == key]
        assert len(hits) == 1, (kind, [i.text for i in walk(menus[kind])])
        hit = hits[0]
        assert (hit.text, hit.verb) == (VERB_TEXT, VERB), (kind, hit.text, hit.verb)
        assert hit.source.kind == "command" and hit.removable, (kind, hit.source)
        assert hit.source.scope == sub.split("\\shell\\")[0].removeprefix(
            "Software\\Classes\\"), hit.source
        assert key_exists(key)

    folder = menus["folder"]
    assert any(i.raw != i.text for i in folder), "raw text must keep the &"
    # Explorer's flags drop Link Shell Extension's "Drop Here" submenu from the
    # folder menu; the background menu's "New" is the submenu left
    nested = [i for k in menus for i in walk(menus[k]) if i.children]
    assert nested, "no menu has a submenu"
    assert all(c.text is not None for c in nested[0].children)

    # built-in rows are shown but never removable
    by_text = {i.text: i for i in folder if not i.separator}
    for name in ("Cut", "Copy", "Delete", "Properties"):
        assert name in by_text, (name, sorted(by_text))
        assert by_text[name].source.kind == "builtin", name
        assert not by_text[name].removable, name
    # Explorer's flags add Rename to the folder menu
    assert "Rename" in by_text, sorted(by_text)
    assert by_text["Rename"].source.kind == "builtin" and not by_text["Rename"].removable
    for i in folder:
        if i.verb in ("open", "explore", "properties", "cut", "copy", "delete"):
            assert i.source.kind == "builtin", i.verb

    # a registry command is attributed to the key that really defines the verb
    commands = [i for i in folder if i.source and i.source.kind == "command"]
    assert commands, "no command-sourced row in the folder menu"
    for i in commands:
        s = i.source
        assert key_exists(s.key), s.key
        assert s.key.lower().endswith("\\shell\\" + i.verb.lower()), (s.key, i.verb)
        assert i.removable

    # {GUID} verbs are extensions keyed by that CLSID
    guids = [i for k in menus for i in walk(menus[k]) if GUID.match(i.verb)]
    assert guids, "no GUID-verb row anywhere"
    for i in guids:
        assert i.source.kind == "extension", (i.text, i.source)
        assert i.source.clsid.upper() == i.verb.upper(), (i.verb, i.source)
        assert i.removable

    # classic handlers without a verb are attributed by probing the handler
    for name in ("Include in library", "Send to"):
        hit = [i for i in folder if i.text == name]
        if hit:
            assert hit[0].source.kind == "extension", (name, hit[0].source)
            assert hit[0].source.clsid, name

    # every extension row resolves the server DLL when the CLSID registers one
    dlls = [i.source.dll for i in walk(folder)
            if i.source and i.source.kind == "extension" and i.source.dll]
    assert dlls and all(d for d in dlls)

    # the other menus carry the same attribution contract
    for kind in ("background", "drive"):
        cmds = [i for i in menus[kind] if i.source and i.source.kind == "command"]
        assert cmds, f"no command-sourced row in the {kind} menu"
        for i in cmds:
            assert key_exists(i.source.key), i.source.key
    for i in menus["background"]:
        if i.source and i.source.kind == "command":
            assert "\\directory\\background\\shell\\" in i.source.key.lower(), \
                i.source.key

    # a path the shell cannot parse fails loudly instead of returning nothing
    try:
        ctxmenu.build_menu("folder", os.path.join(ROOT, "no", "such", "dir"))
    except (OSError, pythoncom.com_error):
        pass
    else:
        raise AssertionError("missing path did not raise")

    # ---- probing matches a row only to the top-level items a handler adds ----
    PNG = os.path.join(ROOT, "scratch.png")
    tweaks.write_black_png(PNG, 8, 8)
    FILE_CONVERTER = "{af9b72b5-f4e4-44b0-a3d9-b55b748efe90}"
    HANDLER_KEY = "\\shellex\\contextmenuhandlers\\"
    for kind, path in (("file", PNG), ("file", FILE), ("folder", FOLDER)):
        rows = ctxmenu.build_menu(kind, path)
        for i in rows:
            if i.text in ("Rotate left", "Rotate right"):
                assert i.source.clsid.lower() != FILE_CONVERTER, (kind, i.text, i.source)
        probed = [i for i in rows if i.source and i.source.kind == "extension"
                  and HANDLER_KEY in i.source.key.lower()]
        _cm, pidl, data = ctxmenu._shell_objects(kind, path)
        trailing = rows[max(k for k, r in enumerate(rows) if r.separator) + 1:]
        live = 0
        for i in probed:
            top = ctxmenu._probe(i.source.clsid, pidl, data)
            if top is ctxmenu.REFUSED:
                # a handler that will not load is listed after the live rows
                assert i in trailing and not i.verb, (kind, i.text)
                continue
            live += 1
            assert top is not None, i.source
            assert i.text in [t.text for t in top], (kind, i.text, i.source.clsid)
        assert live, (kind, path)
        print(f"{kind} {os.path.basename(path)}: {live} probed rows ok, "
              f"{len(probed) - live} refused")


    def item(text, verb):
        return ctxmenu.MenuItem(text, text, verb)


    same = ctxmenu._same_item
    assert same(item("Edit", "?"), item("Edit", "?"))
    assert same(item("Edit", ""), item("Edit", "?"))
    assert not same(item("", "?"), item("", "?")), "empty text must never match"
    assert not same(item("Rotate right", "rotate90"), item("Rotate right", "SevenZip"))
    assert same(item("Rotate right", "ROTATE90"), item("Rotate right", "rotate90"))
    assert same(item("Edit", "verb"), item("Edit", "?")), "one side without a verb"
    assert not same(item("Edit", "x"), item("Other", "x"))
    # File Converter issues a fresh GUID verb for every instance
    assert same(item("File Converter", "093ee077-f377-401d-a818-80df379a522a"),
                item("File Converter", "18fadd5f-9475-4fea-a8bf-a526132f18f0"))
    print("same-item matching ok")



    # ---- the menu is read, and each handler probed, with Explorer's flags ----
    EXPLORER_FLAGS = shellcon.CMF_EXPLORE | shellcon.CMF_CANRENAME
    assert ctxmenu.FLAGS == EXPLORER_FLAGS, hex(ctxmenu.FLAGS)


    class FlagSpy:
        def __init__(self, inner, seen):
            self.inner, self.seen = inner, seen

        def QueryContextMenu(self, menu, index, first, last, flags):
            self.seen.append(flags)
            return self.inner.QueryContextMenu(menu, index, first, last, flags)

        def QueryInterface(self, iid):
            return FlagSpy(self.inner.QueryInterface(iid), self.seen)

        def __getattr__(self, name):
            return getattr(self.inner, name)


    seen = []
    real_objects, real_create = ctxmenu._shell_objects, pythoncom.CoCreateInstance


    def spy_objects(kind, path):
        cm, pidl, data = real_objects(kind, path)
        return FlagSpy(cm, seen), pidl, data


    def spy_create(*args):
        return FlagSpy(real_create(*args), seen)


    ctxmenu._shell_objects = spy_objects
    pythoncom.CoCreateInstance = spy_create
    try:
        ctxmenu.build_menu("folder", FOLDER)
    finally:
        ctxmenu._shell_objects, pythoncom.CoCreateInstance = real_objects, real_create
    assert len(seen) > 1 and set(seen) == {EXPLORER_FLAGS}, [hex(f) for f in seen]
    print(f"explorer flags on {len(seen)} QueryContextMenu calls ok")

finally:
    for sub in SCRATCH_VERBS.values():
        delete_verb(sub)
for sub in SCRATCH_VERBS.values():
    try:
        winreg.CloseKey(winreg.OpenKey(HKCU, sub))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError(f"scratch verb left behind: {sub}")

shutil.rmtree(ROOT, ignore_errors=True)
print("STATUS: SUCCESS")
