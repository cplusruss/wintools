"""Contract test for ctxmenu.load_menu and the --ctxmenu-dump helper.

Read-only: the helper builds real shell menus for scratch paths in %TEMP% and
drive C:\\ and hands them back as JSON; no menu command is invoked and no
registry key is written.  The launcher is injected: a plain subprocess stands
in for Explorer, then the real Explorer chain runs once.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import ctxmenu  # noqa: E402

app = QApplication([])
ROOT = os.path.join(os.environ["TEMP"], "wintools-selftest-ctxmenu-helper")
shutil.rmtree(ROOT, ignore_errors=True)
FOLDER = os.path.join(ROOT, "dir")
FILE = os.path.join(ROOT, "scratch.txt")
os.makedirs(FOLDER)
Path(FILE).write_text("x")

CASES = (("folder", FOLDER), ("file", FILE), ("background", FOLDER),
         ("drive", "C:\\"))
BARE_GUID = re.compile(r"^[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$")

procs = []
launched = []


def subprocess_launch(exe, params, cwd):
    launched.append((exe, params, cwd))
    procs.append(subprocess.Popen(f'"{exe}" {params}', cwd=cwd))


def verb_of(item):
    # File Converter issues a fresh GUID verb for every instance
    return "<guid>" if BARE_GUID.match(item.verb) else item.verb


def shape(items):
    out = []
    for i in items:
        s = i.source
        out.append((
            i.text, i.raw, verb_of(i), i.separator,
            None if s is None else (s.kind, s.label, s.key, s.clsid, s.dll, s.scope),
            None if i.icon is None else (i.icon.width(), i.icon.height()),
            shape(i.children)))
    return out


def walk(items):
    for i in items:
        yield i
        yield from walk(i.children)


def icons(items):
    return sum(1 for i in walk(items) if i.icon is not None)


# ---- the helper round trip equals the in-process build ----
for kind, path in CASES:
    direct = ctxmenu.build_menu(kind, path)
    n = len(launched)
    t0 = time.time()
    viahelper = ctxmenu.load_menu(kind, path, elevated=True, launch=subprocess_launch)
    took = time.time() - t0
    assert len(launched) == n + 1, "elevated load_menu must launch exactly one helper"
    assert shape(viahelper) == shape(direct), kind
    assert icons(viahelper) == icons(direct), (kind, icons(viahelper), icons(direct))
    if kind == "folder":
        assert icons(direct) > 0, "no icon in the folder menu: icon round trip untested"
    print(f"{kind}: {len(list(walk(direct)))} rows, {icons(direct)} icons, "
          f"helper {took:.1f} s ok")

exe, params, cwd = launched[0]
assert os.path.basename(exe).lower() in ("pythonw.exe", "python.exe"), exe
assert "wintools.py" in params and "--ctxmenu-dump" in params, params
assert os.path.isfile(os.path.join(cwd, "wintools.py")), cwd
for p in procs:
    p.wait(timeout=30)

# ---- not elevated: built in-process, nothing launched ----


def refuse_launch(*_args):
    raise AssertionError("an unelevated load_menu launched a helper")


for kind, path in CASES[:2]:
    assert shape(ctxmenu.load_menu(kind, path, elevated=False, launch=refuse_launch)) \
        == shape(ctxmenu.build_menu(kind, path)), kind
print("unelevated builds in-process ok")

# ---- the outfile: in %TEMP%, unique per call, gone after reading ----
made = []
real_outfile = ctxmenu._outfile


def spy_outfile():
    made.append(real_outfile())
    return made[-1]


ctxmenu._outfile = spy_outfile
try:
    for _ in range(2):
        ctxmenu.load_menu("folder", FOLDER, elevated=True, launch=subprocess_launch)
finally:
    ctxmenu._outfile = real_outfile
assert len(made) == 2 and made[0] != made[1], made
for f in made:
    assert os.path.dirname(f).lower() == os.path.normpath(os.environ["TEMP"]).lower(), f
    assert f in launched[-1][1] or f in launched[-2][1], f
    assert not os.path.exists(f) and not os.path.exists(f + ".tmp"), f
for p in procs:
    p.wait(timeout=30)
print("outfile unique, in temp, deleted ok")

# ---- the dump is written to <outfile>.tmp and renamed ----
renames = []
real_replace = os.replace


def spy_replace(src, dst, *a, **kw):
    renames.append((src, dst, os.path.exists(src), os.path.exists(dst)))
    return real_replace(src, dst, *a, **kw)


target = os.path.join(ROOT, "dump.json")
os.replace = spy_replace
try:
    ctxmenu.dump_menu("folder", FOLDER, target)
finally:
    os.replace = real_replace
assert renames == [(target + ".tmp", target, True, False)], renames
assert not os.path.exists(target + ".tmp")
data = json.loads(Path(target).read_text(encoding="utf-8"))
assert data["items"] and "error" not in data
print("atomic dump ok")

# ---- a launcher that does nothing times out, nothing is listed ----
t0 = time.time()
try:
    ctxmenu.load_menu("folder", FOLDER, elevated=True, launch=lambda *a: None,
                      timeout=0.5)
except TimeoutError as e:
    assert str(e) == "menu helper timed out", e
else:
    raise AssertionError("no helper output did not time out")
assert 0.4 < time.time() - t0 < 5
assert ctxmenu.HELPER_TIMEOUT == 20
print("timeout ok")

# ---- a leftover the helper still holds open must not mask the timeout ----
held, planted = [], []
ctxmenu._outfile = lambda: (planted.append(real_outfile()), planted[-1])[1]


def hold_tmp(exe, params, cwd):
    held.append(open(planted[-1] + ".tmp", "w"))  # no delete sharing: os.remove fails


try:
    ctxmenu.load_menu("folder", FOLDER, elevated=True, launch=hold_tmp, timeout=0.5)
except TimeoutError as e:
    assert str(e) == "menu helper timed out", e
else:
    raise AssertionError("no helper output did not time out")
finally:
    ctxmenu._outfile = real_outfile
    for f in held:
        f.close()
    os.remove(planted[-1] + ".tmp")
print("timeout wins over a held leftover ok")

# ---- a helper that wrote an error surfaces it, nothing is listed ----
missing = os.path.join(ROOT, "no", "such", "dir")
try:
    ctxmenu.load_menu("folder", missing, elevated=True, launch=subprocess_launch)
except OSError as e:
    assert str(e) and "timed out" not in str(e), repr(e)
    print("helper error surfaces:", e)
else:
    raise AssertionError("helper error was swallowed")
for p in procs:
    p.wait(timeout=30)

# ---- the real chain: Explorer's shell starts the helper (works unelevated too) ----
t0 = time.time()
viaexplorer = ctxmenu.load_menu("folder", FOLDER, elevated=True)
assert shape(viaexplorer) == shape(ctxmenu.build_menu("folder", FOLDER))
print(f"explorer launch chain ok ({time.time() - t0:.1f} s)")

shutil.rmtree(ROOT, ignore_errors=True)
print("STATUS: SUCCESS")
