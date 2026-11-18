"""Contract test for installer (Installer tab: winget, packages, Firefox Clean Setup).

Nothing is installed or downloaded: subprocess, the winget runner, the winget
bootstrap, the password prompt, the uninstall list and the firefoxsetup tweak
are all stubbed, so no PowerShell or winget process starts, HKLM is never
written and no dialog opens.
"""

import codecs
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox  # noqa: E402

import clean  # noqa: E402
import installer  # noqa: E402
import tweaks  # noqa: E402

app = QApplication([])
# the Install warning is covered by test_confirm_guards.py
mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes).start()
REAL_WINGET_VERSION = installer.winget_version
SECRET = 'S3cret "pw" 42'
FAKE_EXE = r"C:\fake\WindowsApps\winget.exe"
BASE = ["install", "--id", None, "-e", "--source", "winget", "--silent",
        "--accept-package-agreements", "--accept-source-agreements",
        "--disable-interactivity"]
OVERRIDE_PY = r"/quiet InstallAllUsers=1 PrependPath=1 TargetDir=C:\Python\313"


def cmd(pkg_id, *extra):
    return [pkg_id if a is None else a for a in BASE] + list(extra)


def vnc_override(password):
    return ("/quiet /norestart ADDLOCAL=Server SERVER_REGISTER_AS_SERVICE=1 "
            "SET_USEVNCAUTHENTICATION=1 VALUE_OF_USEVNCAUTHENTICATION=1 "
            f'SET_PASSWORD=1 VALUE_OF_PASSWORD="{password}"')


# ---- the package table and row layout ----
assert [(p[0], p[1]) for p in installer.PACKAGES] == [
    ("Dropbox", "Dropbox.Dropbox"),
    ("TightVNC Server (x64)", "GlavSoft.TightVNC"),
    ("Firefox", "Mozilla.Firefox"),
    ("Python 3.13", "Python.Python.3.13"),
    ("Everything", "voidtools.Everything.Beta"),
], installer.PACKAGES
assert installer.WINGET_ROW == 0 and installer.FIRST_PKG_ROW == 1
assert installer.FIREFOX_ROW == 6
assert installer.COLS == ("Package", "Installed", "Status")
print("package table ok")

# ---- command lines ----
assert installer.winget_args("X.Y") == cmd("X.Y")
assert installer.winget_args("X.Y", "/q A=1") == cmd("X.Y", "--override", "/q A=1")
assert installer.tightvnc_override("pw") == vnc_override("pw")
assert installer.tightvnc_override('a"b') == vnc_override('a""b')
ov = installer.tightvnc_override("pw")
assert "ADDLOCAL=Server " in ov and "Viewer" not in ov
print("winget / tightvnc command lines ok")

# ---- Python folder follows the package version ----
assert installer.python_dir("Python.Python.3.13") == r"C:\Python\313"
assert installer.python_dir("Python.Python.3.14") == r"C:\Python\314"
assert installer.python_dir("Python.Python.3.9") == r"C:\Python\39"
assert installer.python_override("Python.Python.3.13") == OVERRIDE_PY
assert installer.python_override("Python.Python.3.14") == \
    OVERRIDE_PY.replace("313", "314")
try:
    installer.python_dir("Python.Python")
    raise AssertionError("an id without a version did not raise")
except ValueError:
    pass
print("python folder derived from version ok")

# ---- the winget runner takes the resolved path ----
seen = {}


def fake_subprocess_run(argv, **kw):
    seen["argv"], seen["kw"] = argv, kw
    return SimpleNamespace(returncode=-1978334963, stdout="", stderr="")


with mock.patch.object(installer.subprocess, "run", fake_subprocess_run):
    rc = installer.run_winget(FAKE_EXE, cmd("X.Y", "--override", "/quiet"))
assert seen["argv"] == [FAKE_EXE, *cmd("X.Y", "--override", "/quiet")]
assert rc == 0x8A15010D, hex(rc)
assert seen["kw"]["creationflags"] == tweaks.CREATE_NO_WINDOW
assert seen["kw"]["check"] is False
assert seen["kw"]["stdout"] is installer.subprocess.DEVNULL
assert seen["kw"]["stderr"] is installer.subprocess.DEVNULL
assert installer.ALREADY_INSTALLED == {0x8A150061, 0x8A15010D, 0x8A15002B}
print("run_winget ok")

# ---- the password prompt ----
with mock.patch.object(QInputDialog, "getText",
                       return_value=("abc", True)) as q:
    assert installer.prompt_password(None) == "abc"
    assert q.call_args[0][3] == QLineEdit.Password, q.call_args
with mock.patch.object(QInputDialog, "getText", return_value=("abc", False)):
    assert installer.prompt_password(None) == ""
print("password prompt ok")

# ---- where winget lives: PATH first, then the WindowsApps alias ----
alias = r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\winget.exe"
with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}):
    with mock.patch.object(installer.shutil, "which",
                           return_value=r"D:\tools\winget.exe") as which:
        assert installer.resolve_winget() == r"D:\tools\winget.exe"
        assert which.call_args[0] == ("winget",)
    with mock.patch.object(installer.shutil, "which", return_value=None):
        with mock.patch.object(installer.os.path, "isfile",
                               lambda p: p == alias):
            assert installer.resolve_winget() == alias
        with mock.patch.object(installer.os.path, "isfile", lambda p: False):
            assert installer.resolve_winget() is None
print("resolve_winget ok")

# ---- winget --version ----
with mock.patch.object(installer, "resolve_winget", return_value=None):
    assert installer.winget_version() is None
with mock.patch.object(installer, "resolve_winget", return_value=FAKE_EXE):
    with mock.patch.object(
            installer.subprocess, "run",
            lambda argv, **kw: SimpleNamespace(
                returncode=0, stdout="v1.29.380\r\n", stderr="")):
        assert installer.winget_version() == "v1.29.380"
    with mock.patch.object(
            installer.subprocess, "run",
            lambda argv, **kw: SimpleNamespace(
                returncode=1, stdout="", stderr="x")):
        assert installer.winget_version() == "n/a"
    with mock.patch.object(installer.subprocess, "run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout="v1\n")
        installer.winget_version()
        assert run.call_args[0][0] == [FAKE_EXE, "--version"], run.call_args
    # a stale App Execution Alias raises from subprocess: winget is unavailable
    for exc in (OSError(1920, "The file cannot be accessed by the system"),
                FileNotFoundError(2, "no such file")):
        with mock.patch.object(installer.subprocess, "run", side_effect=exc):
            assert installer.winget_version() is None, exc
print("winget_version ok")

# ---- the winget bootstrap script: content only, PowerShell never starts ----
captured = {}


def fake_powershell(rc, err=""):
    def run(argv, **kw):
        captured["argv"], captured["kw"] = argv, kw
        captured["script"] = Path(argv[argv.index("-File") + 1]).read_text()
        captured["scratch"] = argv[argv.index("-Dir") + 1]
        assert os.path.isdir(captured["scratch"])
        return SimpleNamespace(returncode=rc, stdout="", stderr=err)
    return run


with mock.patch.object(installer.subprocess, "run", fake_powershell(0)):
    assert installer.install_winget() == ""
argv, kw, script = captured["argv"], captured["kw"], captured["script"]
scratch = captured["scratch"]
assert argv[:6] == ["powershell", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-File"], argv
assert argv[-2:] == ["-Dir", scratch], argv
assert argv[6].startswith(scratch + os.sep) and argv[6].endswith(".ps1")
assert Path(scratch).parent == Path(tempfile.gettempdir()), scratch
assert Path(scratch).name.startswith("wintools-winget-"), scratch
assert not os.path.exists(scratch), "scratch folder not deleted"
assert kw["creationflags"] == tweaks.CREATE_NO_WINDOW and kw["check"] is False
assert "https://api.github.com/repos/microsoft/winget-cli/releases/latest" in script
assert "Microsoft.DesktopAppInstaller_*.msixbundle" in script
assert "DesktopAppInstaller_Dependencies.zip" in script
assert "browser_download_url" in script
assert "Expand-Archive" in script
assert "'x64'" in script and ".appx" in script and ".msix'" in script
assert "Add-AppxPackage -Path $bundlePath -DependencyPath $deps" in script
assert "$ErrorActionPreference = 'Stop'" in script
assert not re.search(r"\d+\.\d+\.\d+", script), "a version number is pinned"
assert "msixbundle" in script and "Invoke-WebRequest" in script
for rc, err, want in ((1, "boom\nsecond line\n", "failed boom"),
                      (1, "", "failed 0x00000001"),
                      (-1, "\n  \n", "failed 0xFFFFFFFF")):
    with mock.patch.object(installer.subprocess, "run", fake_powershell(rc, err)):
        assert installer.install_winget() == want, (rc, err)
    assert not os.path.exists(captured["scratch"]), "scratch kept after failure"
print("winget bootstrap script ok")

# ---- a package step without winget fails cleanly and runs nothing ----
with mock.patch.object(installer, "resolve_winget", return_value=None), \
        mock.patch.object(installer, "run_winget") as runner:
    assert installer.install_step("Dropbox.Dropbox") == "failed winget not found"
    assert not runner.called
with mock.patch.object(installer, "resolve_winget", return_value=FAKE_EXE), \
        mock.patch.object(installer, "run_winget", return_value=0) as runner:
    assert installer.install_step("Dropbox.Dropbox") == ""
    assert runner.call_args[0] == (FAKE_EXE, cmd("Dropbox.Dropbox"))
    runner.return_value = 0x8A15010D
    assert installer.install_step("Dropbox.Dropbox") == ""
    runner.return_value = 0x8A150010
    assert installer.install_step("Dropbox.Dropbox") == "failed 0x8A150010"
    # 0x8A150109 "Restart your PC to finish installation": a completed install
    runner.return_value = 0x8A150109
    assert installer.install_step("Dropbox.Dropbox") == "restart required"
print("install_step ok")

# ---- winget diagnostic logs: the VNC password is scrubbed from the new ones ----
MASK = "********"
DQ = SECRET.replace('"', '""')    # as the MSI sees it in the override
CL = DQ.replace('"', '\\"')       # as the raw command line carries it
TEMPLATE = (
    'Command line Args: install --override "/quiet VALUE_OF_PASSWORD=\\"{cl}\\""\n'
    'Installer args: /quiet VALUE_OF_PASSWORD="{dq}"\n'
    "plain {raw} end {raw}\n"
    "caf\u00e9 S3cret-not-it\n")
DIRTY = TEMPLATE.format(raw=SECRET, dq=DQ, cl=CL)
CLEAN = TEMPLATE.format(raw=MASK, dq=MASK, cl=MASK)
START = int(time.time())  # whole seconds: mtimes round-trip exactly
assert DIRTY != CLEAN and "S3cret-not-it" in CLEAN


def put(folder, name, data, mtime):
    p = Path(folder, name)
    p.write_bytes(data)
    os.utime(p, (mtime, mtime))
    return p


def wipe(folder):
    for p in Path(folder).iterdir():
        os.chmod(p, stat.S_IWRITE)
        p.unlink()


ENCODERS = {
    "WinGet-utf8.log": lambda s: s.encode("utf-8"),
    "WinGet-utf8bom.log": lambda s: codecs.BOM_UTF8 + s.encode("utf-8"),
    "WinGet-utf16.log": lambda s: codecs.BOM_UTF16_LE + s.encode("utf-16-le"),
}
wlogs = tempfile.mkdtemp(prefix="wintools-selftest-wglogs-")
try:
    assert Path(wlogs).parent == Path(tempfile.gettempdir()), wlogs
    for name, enc in ENCODERS.items():
        put(wlogs, name, enc(DIRTY), START + 60)
    put(wlogs, "WinGet-edge.log", DIRTY.encode(), START)
    put(wlogs, "WinGet-bad.log",
        b"bad \x80\xc3 byte " + SECRET.encode() + b" " + DQ.encode(), START + 5)
    put(wlogs, "WinGet-nosecret.log", b"nothing here\n", START + 5)
    untouched = {
        "WinGet-old.log": put(wlogs, "WinGet-old.log", DIRTY.encode(), START - 1),
        "other.log": put(wlogs, "other.log", DIRTY.encode(), START + 60),
        "WinGet-notes.txt": put(wlogs, "WinGet-notes.txt", DIRTY.encode(),
                                START + 60),
    }
    before = {n: (p.read_bytes(), p.stat().st_mtime) for n, p in untouched.items()}

    assert installer.scrub_winget_logs(wlogs, START, SECRET) == ""
    for name, enc in {**ENCODERS, "WinGet-edge.log": ENCODERS["WinGet-utf8.log"]}.items():
        got = Path(wlogs, name).read_bytes()
        assert got == enc(CLEAN), (name, got)
    assert Path(wlogs, "WinGet-bad.log").read_bytes() == \
        b"bad \x80\xc3 byte " + MASK.encode() + b" " + MASK.encode()
    assert Path(wlogs, "WinGet-nosecret.log").read_bytes() == b"nothing here\n"
    for name, p in untouched.items():
        assert (p.read_bytes(), p.stat().st_mtime) == before[name], name
    for p in Path(wlogs).glob("WinGet-*.log"):
        if p.name == "WinGet-old.log":
            continue
        data = p.read_bytes()
        for form in (SECRET, DQ, CL):
            for enc in ("utf-8", "utf-16-le"):
                assert form.encode(enc) not in data, (p.name, form)

    # a secret without quotes: all three forms coincide
    wipe(wlogs)
    put(wlogs, "WinGet-a.log", b"x pw1234 y pw1234\n", START)
    assert installer.scrub_winget_logs(wlogs, START, "pw1234") == ""
    assert Path(wlogs, "WinGet-a.log").read_bytes() == b"x ******** y ********\n"

    # a log that cannot be rewritten is the error; the others are still scrubbed
    wipe(wlogs)
    ro = put(wlogs, "WinGet-a-locked.log", DIRTY.encode(), START + 1)
    put(wlogs, "WinGet-b-good.log", DIRTY.encode(), START + 1)
    ro_clean = put(wlogs, "WinGet-c-locked-clean.log", b"no secret\n", START + 1)
    os.chmod(ro, stat.S_IREAD)
    os.chmod(ro_clean, stat.S_IREAD)
    err = installer.scrub_winget_logs(wlogs, START, SECRET)
    assert err.startswith("failed ") and len(err) > len("failed "), err
    assert "S3cret" not in err and DQ not in err, err
    assert Path(wlogs, "WinGet-b-good.log").read_bytes() == CLEAN.encode()
    assert ro.read_bytes() == DIRTY.encode()
    os.chmod(ro, stat.S_IWRITE)
    os.chmod(ro_clean, stat.S_IWRITE)
    assert installer.scrub_winget_logs(wlogs, START, SECRET) == ""

    # a UTF-16 log that is not valid UTF-16 is an error, not a skip
    wipe(wlogs)
    put(wlogs, "WinGet-trunc.log", codecs.BOM_UTF16_LE + b"a\x00b", START + 1)
    err = installer.scrub_winget_logs(wlogs, START, SECRET)
    assert err.startswith("failed ") and "S3cret" not in err, err

    # no logs and no folder: nothing to scrub
    wipe(wlogs)
    assert installer.scrub_winget_logs(wlogs, START, SECRET) == ""
    assert installer.scrub_winget_logs(
        os.path.join(wlogs, "missing"), START, SECRET) == ""

    # the TightVNC step scrubs whatever winget did, including when it fails
    plant = {"readonly": False}

    def planting_run(result):
        def run(exe, args):
            ov = args[args.index("--override") + 1]
            assert f'VALUE_OF_PASSWORD="{DQ}"' in ov, ov
            p = put(wlogs, "WinGet-step.log",
                    f"Installer args: {ov}\nraw {SECRET}\n".encode(),
                    time.time() + 60)
            if plant["readonly"]:
                os.chmod(p, stat.S_IREAD)
            if isinstance(result, Exception):
                raise result
            return result
        return run

    with mock.patch.object(installer, "winget_log_dir", lambda: wlogs), \
            mock.patch.object(installer, "resolve_winget", return_value=FAKE_EXE):
        for result, want in ((0, ""), (0x8A150010, "failed 0x8A150010"),
                             (0x8A15010D, ""), (0x8A150109, "restart required"),
                             (RuntimeError(f"bad args {SECRET}"),
                              "failed RuntimeError")):
            wipe(wlogs)
            with mock.patch.object(installer, "run_winget", planting_run(result)):
                got = installer.tightvnc_step(SECRET)
            assert got == want, (result, got)
            text = Path(wlogs, "WinGet-step.log").read_text(encoding="utf-8")
            assert SECRET not in text and DQ not in text and MASK in text, text
        plant["readonly"] = True
        for result in (0, 0x8A150010):
            wipe(wlogs)
            with mock.patch.object(installer, "run_winget", planting_run(result)):
                got = installer.tightvnc_step(SECRET)
            assert got.startswith("failed ") and "S3cret" not in got, (result, got)
        plant["readonly"] = False
finally:
    for p in Path(wlogs).iterdir():
        os.chmod(p, stat.S_IWRITE)
    shutil.rmtree(wlogs, ignore_errors=True)
with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}):
    assert installer.winget_log_dir() == (
        r"C:\Users\x\AppData\Local\Packages"
        r"\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState\DiagOutputDir")
print("winget log scrub ok")

# ---- installed state and version from the uninstall list ----


def entry(name, ver):
    return SimpleNamespace(display_name=name, display_version=ver)


ENTRIES = [
    entry("Miniconda3 py313_25.7.0-2 (Python 3.13.5 64-bit)", "py313_25.7.0-2"),
    entry("Python 3.13.5 Core Interpreter (64-bit)", "3.13.5150.0"),
    entry("Python 3.13.5 Standard Library (64-bit)", "3.13.5150.0"),
    entry("Python Launcher", "3.13.5150.0"),
    entry("Python 3.12.1 (64-bit)", "3.12.1150.0"),
    entry("Dropbox Update Helper", "1.3.983.1"),
    entry("TightVNC", "2.8.85.0"),
    entry("Mozilla Firefox (x64 en-US)", "157.0"),
    entry("Dropbox", "273.4.4708"),
    entry("Python 3.13.5 (64-bit)", "3.13.5150.0"),
    entry("Everything", "1.4.1.1026"),
    entry("Everything 1.4.1.1026 (x64)", "1.4.1.1026"),
    entry("Voidtools Everything Toolbar", "1.0"),
    entry("Everything Search Helper 1.5.0.1383a (x64)", "9"),
    entry("Everything 1.5.0.1383a (x64)", "1.5.0.1383"),
]


def stub_entries():
    return list(ENTRIES)


with mock.patch.object(clean, "enumerate_uninstall_entries", stub_entries):
    assert installer.installed_versions() == [
        "273.4.4708", "2.8.85.0", "157.0", "3.13.5150.0", "1.5.0.1383"]
    ENTRIES[:] = [e for e in ENTRIES if e.display_name not in (
        "Dropbox", "Python 3.13.5 (64-bit)", "TightVNC",
        "Everything 1.5.0.1383a (x64)")]
    assert installer.installed_versions() == [None, None, "157.0", None, None], \
        "a helper, component, other Python minor or Everything 1.4 matched"
    ENTRIES.append(entry("Python 3.13.15 (64-bit)", "3.13.15150.0"))
    ENTRIES.append(entry("Everything 1.5.0.1423b (x64)", "1.5.0.1423"))
    got = installer.installed_versions()
    assert got[3] == "3.13.15150.0" and got[4] == "1.5.0.1423", got
    ENTRIES[:] = [e for e in ENTRIES if "Firefox" not in e.display_name]
    ENTRIES.append(entry("Mozilla Firefox 140.1.0esr (x64 en-US)", ""))
    assert installer.installed_versions()[2] == "n/a"
print("installed detection ok")

# ---- the page, against stubs ----
log = []
policy = []
winget_state = {"exe": None, "version": None}


class StubOp:
    on, off, off_key, path = True, False, None, "stub"

    def __init__(self, fail=False):
        self.val, self.fail = False, fail

    def available(self):
        return True

    def read(self):
        return self.val

    def is_on(self):
        return self.val

    def write(self, on):
        log.append("policy")
        if self.fail:
            raise PermissionError(5, "Access is denied")
        self.val = on
        policy.append(on)


op = StubOp()
stub_tweak = tweaks.Tweak("firefoxsetup", "Apps", "Apps",
                          "Firefox Clean Setup", [op])
catalog = [*[t for t in tweaks.TWEAKS if t.key != "firefoxsetup"], stub_tweak]

results = {}
calls = []
prompts = []
reports, refreshes = [], []
password = [SECRET]
bootstrap = {"result": "", "makes_winget": True}


page_logs = tempfile.mkdtemp(prefix="wintools-selftest-pagelogs-")
plant_ro = [False]


def fake_run(exe, args):
    pkg = args[args.index("--id") + 1]
    calls.append((exe, args))
    log.append(pkg)
    if pkg == installer.TIGHTVNC:  # winget logs the override verbatim
        p = put(page_logs, "WinGet-vnc.log",
                ("Installer args: " + args[args.index("--override") + 1]).encode(),
                time.time() + 60)
        if plant_ro[0]:
            os.chmod(p, stat.S_IREAD)
    res = results.get(pkg, 0)
    if isinstance(res, Exception):
        raise res
    return res


def fake_install_winget():
    log.append("winget-install")
    if bootstrap["makes_winget"] and not bootstrap["result"]:
        winget_state["exe"] = FAKE_EXE
        winget_state["version"] = "v1.29.380"
    return bootstrap["result"]


def fake_prompt(parent):
    prompts.append(parent)
    return password[0]


def wait_for(cond, what):
    end = time.time() + 20
    while not cond():
        app.processEvents()
        assert time.time() < end, f"timed out waiting for {what}"
        time.sleep(0.01)


def texts(page, col):
    return [page.grid.item(r, col).text() for r in range(page.grid.rowCount())]


def checks(page):
    return [page.grid.item(r, 0).checkState() == Qt.Checked
            for r in range(page.grid.rowCount())]


def check_only(page, rows):
    for r in range(page.grid.rowCount()):
        page.grid.item(r, 0).setCheckState(
            Qt.Checked if r in rows else Qt.Unchecked)


def reset(winget=True):
    wipe(page_logs)
    plant_ro[0] = False
    log.clear()
    calls.clear()
    prompts.clear()
    reports.clear()
    refreshes.clear()
    policy.clear()
    results.clear()
    password[:] = [SECRET]
    op.val, op.fail = False, False
    bootstrap.update(result="", makes_winget=True)
    winget_state.update(exe=FAKE_EXE if winget else None,
                        version="v1.29.380" if winget else None)


def run(page):
    page.btn_install.click()
    assert not page.btn_install.isEnabled()
    wait_for(page.btn_install.isEnabled, "worker")


def leaks(page):
    pool = [*texts(page, 0), *texts(page, 1), *texts(page, 2),
            page.status.text(), *reports,
            *(p.read_text("utf-8") for p in Path(page_logs).iterdir())]
    return [t for t in pool if "S3cret" in t]


ALL = range(7)
with mock.patch.object(tweaks, "TWEAKS", catalog), \
        mock.patch.object(installer, "winget_log_dir", lambda: page_logs), \
        mock.patch.object(clean, "enumerate_uninstall_entries", stub_entries), \
        mock.patch.object(installer, "run_winget", fake_run), \
        mock.patch.object(installer, "install_winget", fake_install_winget), \
        mock.patch.object(installer, "resolve_winget",
                          lambda: winget_state["exe"]), \
        mock.patch.object(installer, "winget_version",
                          lambda: winget_state["version"]), \
        mock.patch.object(installer, "prompt_password", fake_prompt):
    ENTRIES[:] = [
        entry("Dropbox", "273.4.4708"),
        entry("Python 3.13.5 (64-bit)", "3.13.5150.0"),
        entry("Python 3.13.5 Core Interpreter (64-bit)", "3.13.5150.0"),
    ]

    def refresh_cb():
        refreshes.append(1)

    reset()
    page = installer.InstallerPage(reports.append, refresh_cb)
    grid = page.grid
    assert grid.rowCount() == 7 and grid.columnCount() == 3
    assert [grid.horizontalHeaderItem(c).text() for c in range(3)] == [
        "Package", "Installed", "Status"]
    assert texts(page, 0) == ["WinGet", "Dropbox", "TightVNC Server (x64)",
                              "Firefox", "Python 3.13", "Everything",
                              "Firefox Clean Setup"]
    assert texts(page, 1) == ["v1.29.380", "273.4.4708", "", "",
                              "3.13.5150.0", "", "off"], texts(page, 1)
    assert texts(page, 2) == [""] * 7
    assert all(grid.item(r, 0).flags() & Qt.ItemIsUserCheckable
               for r in ALL)
    assert checks(page) == [False, False, True, True, False, True, True], \
        checks(page)
    assert page.btn_install.text() == "Install"
    assert page.btn_refresh.text() == "Refresh"
    print("page rows and default checks ok")

    # winget missing: no version, checked by default
    reset(winget=False)
    page.refresh_states()
    assert texts(page, 1)[0] == "" and checks(page)[0] is True
    reset()
    page.refresh_states()
    assert checks(page)[0] is False

    # policy already on: not checked by default
    op.val = True
    page.refresh_states()
    assert texts(page, 1)[6] == "on" and checks(page)[6] is False
    op.val = False
    page.refresh_states()
    assert checks(page)[6] is True

    # Refresh re-reads the uninstall list
    ENTRIES.append(entry("TightVNC", "2.8.85.0"))
    page.btn_refresh.click()
    assert texts(page, 1)[2] == "2.8.85.0"
    assert checks(page) == [False, False, False, True, False, True, True], \
        checks(page)
    ENTRIES.pop()
    page.refresh_states()
    print("refresh re-reads states ok")

    # ---- everything checked, winget missing: bootstrap first, resolved path used ----
    reset(winget=False)
    page.refresh_states()
    check_only(page, ALL)
    results.update({"Dropbox.Dropbox": 0x8A150061,
                    "Mozilla.Firefox": 0x8A150010})
    ENTRIES.append(entry("TightVNC", "2.8.85.0"))
    run(page)
    assert prompts == [page], prompts
    assert [e for e, _a in calls] == [FAKE_EXE] * 5, calls
    assert [a for _e, a in calls] == [
        cmd("Dropbox.Dropbox"),
        cmd("GlavSoft.TightVNC", "--override", vnc_override(
            SECRET.replace('"', '""'))),
        cmd("Mozilla.Firefox"),
        cmd("Python.Python.3.13", "--override", OVERRIDE_PY),
        cmd("voidtools.Everything.Beta"),
    ], calls
    assert log == ["winget-install", "Dropbox.Dropbox", "GlavSoft.TightVNC",
                   "Mozilla.Firefox", "Python.Python.3.13",
                   "voidtools.Everything.Beta", "policy"], log
    assert texts(page, 2) == ["installed", "installed", "installed",
                              "failed 0x8A150010", "installed", "installed",
                              "installed"], texts(page, 2)
    assert policy == [True] and op.val is True
    assert page.status.text() == \
        "6 installed   1 failed   Firefox: failed 0x8A150010", page.status.text()
    assert reports == [page.status.text()], reports
    assert refreshes, "the window was not refreshed"
    assert texts(page, 1)[0] == "v1.29.380" and texts(page, 1)[6] == "on"
    assert checks(page)[0] is False and checks(page)[6] is False
    assert not leaks(page), leaks(page)
    assert MASK in Path(page_logs, "WinGet-vnc.log").read_text("utf-8"), \
        "the TightVNC step did not scrub winget's log"
    assert page.btn_refresh.isEnabled()
    print(f"full run ok: {page.status.text()}")

    # ---- winget missing and its row unchecked: every package fails, nothing runs ----
    reset(winget=False)
    check_only(page, ALL[1:])
    run(page)
    assert not calls and "winget-install" not in log, (calls, log)
    assert texts(page, 2) == ["", *["failed winget not found"] * 5,
                              "installed"], texts(page, 2)
    assert page.status.text().startswith("1 installed   5 failed   "
                                         "Dropbox: failed winget not found")
    assert not leaks(page), leaks(page)
    print("missing winget fails every package ok")

    # ---- a failed bootstrap leaves the packages failing, not hanging ----
    reset(winget=False)
    bootstrap["result"] = "failed Add-AppxPackage: 0x80073CF3"
    check_only(page, ALL)
    run(page)
    assert not calls, calls
    assert texts(page, 2) == ["failed Add-AppxPackage: 0x80073CF3",
                              *["failed winget not found"] * 5,
                              "installed"], texts(page, 2)
    assert log == ["winget-install", "policy"], log
    print("failed bootstrap stops the packages ok")

    # ---- winget present and its row checked anyway: still first ----
    reset()
    check_only(page, (0, 1))
    results["Dropbox.Dropbox"] = 0
    run(page)
    assert log == ["winget-install", "Dropbox.Dropbox"], log
    assert [e for e, _a in calls] == [FAKE_EXE]
    print("winget row first ok")

    # ---- the Firefox row follows the Firefox package even when it fails ----
    reset()
    check_only(page, (3, 6))
    results["Mozilla.Firefox"] = 0x8A150010
    run(page)
    assert log == ["Mozilla.Firefox", "policy"], log
    assert not prompts, "prompted for a password with TightVNC unchecked"
    assert texts(page, 2) == ["", "", "", "failed 0x8A150010", "", "",
                              "installed"], texts(page, 2)
    print("firefox row after firefox package ok")

    # ---- Cancel / empty password skips TightVNC only ----
    for pw in ("", None):
        reset()
        password[:] = [pw or ""]
        check_only(page, ALL)
        run(page)
        assert "GlavSoft.TightVNC" not in log, log
        assert log == ["winget-install", "Dropbox.Dropbox", "Mozilla.Firefox",
                       "Python.Python.3.13", "voidtools.Everything.Beta",
                       "policy"], log
        assert texts(page, 2) == ["installed", "installed", "skipped",
                                  "installed", "installed", "installed",
                                  "installed"], texts(page, 2)
        assert page.status.text() == "6 installed   0 failed", page.status.text()
    print("empty password skips TightVNC only ok")

    # ---- a failure never stops the rest; no error text carries the password ----
    reset()
    check_only(page, ALL)
    results["Dropbox.Dropbox"] = 0x80070005
    results["GlavSoft.TightVNC"] = RuntimeError(f"bad args {SECRET}")
    results["Mozilla.Firefox"] = FileNotFoundError(2, "no such file")
    op.fail = True
    run(page)
    assert log == ["winget-install", "Dropbox.Dropbox", "GlavSoft.TightVNC",
                   "Mozilla.Firefox", "Python.Python.3.13",
                   "voidtools.Everything.Beta", "policy"], log
    assert texts(page, 2) == [
        "installed", "failed 0x80070005", "failed RuntimeError",
        "failed no such file", "installed", "installed",
        "failed Access is denied"], texts(page, 2)
    assert page.status.text().startswith("3 installed   4 failed"), \
        page.status.text()
    assert not leaks(page), leaks(page)
    assert op.val is False
    print(f"failures do not stop the run ok: {page.status.text()}")

    # ---- a winget log that cannot be rewritten is that row's error ----
    reset()
    plant_ro[0] = True
    check_only(page, (2,))
    run(page)
    row = texts(page, 2)[2]
    assert row.startswith("failed ") and "S3cret" not in row, row
    assert page.status.text().startswith("0 installed   1 failed   TightVNC"), \
        page.status.text()
    assert not [t for t in (*texts(page, 2), page.status.text(), *reports)
                if "S3cret" in t]
    print(f"unwritable winget log fails the row ok: {row}")

    # ---- 0x8A150109 is a completed install that needs a restart ----
    reset()
    check_only(page, (1, 3))
    results["Dropbox.Dropbox"] = 0x8A150109
    results["Mozilla.Firefox"] = 0x8A150010
    run(page)
    assert texts(page, 2) == ["", "restart required", "", "failed 0x8A150010",
                              "", "", ""], texts(page, 2)
    assert page.status.text() == \
        "1 installed   1 failed   Firefox: failed 0x8A150010", page.status.text()
    reset()
    check_only(page, (1,))
    results["Dropbox.Dropbox"] = 0x8A150109
    run(page)
    assert texts(page, 2)[1] == "restart required"
    assert page.status.text() == "1 installed   0 failed", page.status.text()
    assert reports == [page.status.text()], reports
    print("restart required counts as installed ok")

    # ---- an OSError from winget --version leaves winget unavailable ----
    reset()
    with mock.patch.object(installer, "winget_version", REAL_WINGET_VERSION), \
            mock.patch.object(installer.subprocess, "run",
                              side_effect=OSError(1920, "cannot be accessed")):
        stale = installer.InstallerPage(lambda _t: None, lambda: None)
    assert texts(stale, 1)[0] == "" and checks(stale)[0] is True
    stale.shutdown()
    print("page builds with a broken winget alias ok")

    # ---- nothing checked: no run, no prompt ----
    reset()
    check_only(page, ())
    page.btn_install.click()
    assert page.btn_install.isEnabled() and not log and not prompts
    assert not reports and not refreshes
    print("empty plan ok")

    # ---- close waits for the running step and skips the queued ones ----
    reset()
    release = threading.Event()
    gate = []

    def slow_run(exe, args):
        gate.append(args)
        release.wait(10)
        return 0

    check_only(page, (1, 3))
    with mock.patch.object(installer, "run_winget", slow_run):
        page.btn_install.click()
        wait_for(lambda: len(gate) == 1, "first step")
        assert page._worker.isRunning()
        threading.Timer(0.3, release.set).start()
        page.shutdown()
    assert page._worker is None and release.is_set()
    assert len(gate) == 1, "a queued step ran after shutdown"
    assert not reports, "a finished report arrived after shutdown"
    print("shutdown waits and stops the queue ok")
    page.shutdown()

wipe(page_logs)
shutil.rmtree(page_logs, ignore_errors=True)

# ---- the live catalog builds the page (read-only: winget --version, HKLM read) ----
live = installer.InstallerPage(lambda _t: None, lambda: None)
assert live.grid.rowCount() == 7
assert live.grid.item(0, 0).text() == "WinGet"
assert live.grid.item(6, 0).text() == "Firefox Clean Setup"
assert live.grid.item(6, 1).text() in ("on", "off", "n/a")
live.shutdown()
print("live page builds ok")

print("STATUS: SUCCESS")
