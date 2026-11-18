#!/usr/bin/env python3
"""installer.py - the Installer tab: winget itself, a fixed set of packages
through winget, and the Firefox Clean Setup policy tweak."""

import codecs
import functools
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import clean
import tweaks
from initcfg import STATE_WORD
from keydiag import style_grid

COLS = ("Package", "Installed", "Status")
WINGET_LABEL = "WinGet"
TIGHTVNC = "GlavSoft.TightVNC"
PYTHON = "Python.Python.3.13"

# winget `install` exit codes for a package that is already there
# (microsoft/winget-cli doc/windows/package-manager/winget/returnCodes.md):
# PACKAGE_ALREADY_INSTALLED, INSTALL_ALREADY_INSTALLED, UPDATE_NOT_APPLICABLE
ALREADY_INSTALLED = {0x8A150061, 0x8A15010D, 0x8A15002B}
# "Restart your PC to finish installation": the install completed (same doc)
RESTART_REQUIRED = 0x8A150109
RESTART_STATE = "restart required"


def _python_version(pkg_id):
    m = re.fullmatch(r"Python\.Python\.(\d+)\.(\d+)", pkg_id)
    if not m:
        raise ValueError(pkg_id)
    return m[1], m[2]


def python_dir(pkg_id):
    return "C:\\Python\\%s%s" % _python_version(pkg_id)


def python_override(pkg_id):
    # python.org "Installing Without UI" (docs.python.org/3/using/windows.html):
    # /quiet = no UI, InstallAllUsers=1 = system-wide, PrependPath=1 = prepend
    # the install and Scripts directories to PATH, TargetDir = install folder.
    # --override replaces winget's own silent switch, so /quiet is repeated.
    return f"/quiet InstallAllUsers=1 PrependPath=1 TargetDir={python_dir(pkg_id)}"


def _python_row(pkg_id):
    major, minor = _python_version(pkg_id)
    return (f"Python {major}.{minor}", pkg_id,
            rf"Python {major}\.{minor}\.\d+ \(64-bit\)$")


# (label, winget id, regex for the uninstall DisplayName). Ids were checked
# against the microsoft/winget-pkgs manifests (winget's own source is
# unreachable from this machine: 0x80072efd). Everything: voidtools publishes
# 1.5 builds as voidtools.Everything.Alpha (last 1.5.0.1409a) and then
# voidtools.Everything.Beta (1.5.0.1423b, also the newest on voidtools.com);
# voidtools.Everything is 1.4 stable.
PACKAGES = (
    ("Dropbox", "Dropbox.Dropbox", r"Dropbox$"),
    ("TightVNC Server (x64)", TIGHTVNC, r"TightVNC$"),
    ("Firefox", "Mozilla.Firefox", r"Mozilla Firefox (\(|\d)"),
    _python_row(PYTHON),
    ("Everything", "voidtools.Everything.Beta",
     r"Everything 1\.5\.\d+\.\d+[ab]? \(\w+\)$"),
)
WINGET_ROW = 0
FIRST_PKG_ROW = 1
FIREFOX_ROW = len(PACKAGES) + 1


def winget_args(pkg_id, override=None):
    args = ["install", "--id", pkg_id, "-e", "--source", "winget", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity"]
    return args + ["--override", override] if override else args


def tightvnc_override(password):
    # TightVNC "Installing from MSI Packages": ADDLOCAL=Server installs the
    # server only, SERVER_REGISTER_AS_SERVICE=1 registers the service, and
    # each option is a SET_x=1 / VALUE_OF_x pair (the password needs
    # USEVNCAUTHENTICATION=1). A quote inside a quoted MSI value is doubled.
    quoted = password.replace('"', '""')
    return ("/quiet /norestart ADDLOCAL=Server SERVER_REGISTER_AS_SERVICE=1 "
            "SET_USEVNCAUTHENTICATION=1 VALUE_OF_USEVNCAUTHENTICATION=1 "
            f'SET_PASSWORD=1 VALUE_OF_PASSWORD="{quoted}"')


def resolve_winget():
    # a winget installed during this run is not on this process's PATH yet
    found = shutil.which("winget")
    if found:
        return found
    alias = os.path.join(os.environ["LOCALAPPDATA"],
                         r"Microsoft\WindowsApps\winget.exe")
    return alias if os.path.isfile(alias) else None


def winget_version():
    exe = resolve_winget()
    if exe is None:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL,
                           creationflags=tweaks.CREATE_NO_WINDOW, check=False)
    except OSError:  # stale App Execution Alias: winget cannot start
        return None
    out = r.stdout.strip() if r.returncode == 0 else ""
    return out or "n/a"


def failure_text(e):
    # only the OS error text or the type: a message could carry the VNC password
    return f"failed {getattr(e, 'strerror', None) or type(e).__name__}"


SCRUB_MASK = "********"
_BOMS = ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"))


def winget_log_dir():
    return os.path.join(os.environ["LOCALAPPDATA"], "Packages",
                        "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe",
                        "LocalState", "DiagOutputDir")


def _scrub_bytes(data, secret):
    # winget logs its own arguments: the override as the MSI sees it (quotes
    # doubled) and the raw command line (list2cmdline escapes a quote as \")
    doubled = secret.replace('"', '""')
    cmdline = re.sub(r'(\\*)"', r'\1\1\\"', doubled)
    bom, enc = next(((b, e) for b, e in _BOMS if data.startswith(b)),
                    (b"", "utf-8"))
    # surrogateescape round-trips stray bytes in UTF-8 but not in UTF-16
    errors = "surrogateescape" if enc == "utf-8" else "strict"
    text = data[len(bom):].decode(enc, errors)
    for form in sorted({secret, doubled, cmdline}, key=len, reverse=True):
        text = text.replace(form, SCRUB_MASK)
    return bom + text.encode(enc, errors)


def scrub_winget_logs(log_dir, start, secret):
    """Masks the secret in every WinGet-*.log last written at or after start
    (epoch seconds), keeping each file's encoding. Returns "" or the failure
    text of the first log that could not be rewritten; all are attempted."""
    err = ""
    for path in Path(log_dir).glob("WinGet-*.log"):
        try:
            if path.stat().st_mtime < start:
                continue
            data = path.read_bytes()
            scrubbed = _scrub_bytes(data, secret)
            if scrubbed != data:
                path.write_bytes(scrubbed)
        except (OSError, ValueError) as e:
            err = err or failure_text(e)
    return err


def run_winget(exe, args):
    # output is discarded: it is never shown, so it cannot leak an argument
    r = subprocess.run([exe, *args], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=tweaks.CREATE_NO_WINDOW, check=False)
    return r.returncode & 0xFFFFFFFF


# Latest stable microsoft/winget-cli release (GitHub API releases/latest, which
# skips pre-releases); assets matched by name pattern, never a pinned version.
# The dependencies zip holds one folder per architecture with the VCLibs /
# WindowsAppRuntime packages that a clean LTSC lacks.
_WINGET_PS = r"""
param([string]$Dir)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    $rel = Invoke-RestMethod 'https://api.github.com/repos/microsoft/winget-cli/releases/latest'
    $bundle = $rel.assets | Where-Object { $_.name -like 'Microsoft.DesktopAppInstaller_*.msixbundle' } | Select-Object -First 1
    $zip = $rel.assets | Where-Object { $_.name -eq 'DesktopAppInstaller_Dependencies.zip' } | Select-Object -First 1
    if (-not $bundle -or -not $zip) { throw 'winget release assets not found' }
    $bundlePath = Join-Path $Dir $bundle.name
    $zipPath = Join-Path $Dir $zip.name
    Invoke-WebRequest -Uri $bundle.browser_download_url -OutFile $bundlePath
    Invoke-WebRequest -Uri $zip.browser_download_url -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath (Join-Path $Dir 'deps')
    $deps = @(Get-ChildItem -Path (Join-Path $Dir 'deps') -Recurse -File |
        Where-Object { $_.Directory.Name -eq 'x64' -and ($_.Extension -eq '.appx' -or $_.Extension -eq '.msix') } |
        ForEach-Object { $_.FullName })
    if (-not $deps) { throw 'x64 dependency packages not found' }
    Add-AppxPackage -Path $bundlePath -DependencyPath $deps
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


def install_winget():
    """Returns "" or the failure text of the WinGet row."""
    scratch = tempfile.mkdtemp(prefix="wintools-winget-")
    try:
        script = os.path.join(scratch, "install.ps1")
        with open(script, "w", encoding="ascii") as f:
            f.write(_WINGET_PS)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-File", script, "-Dir", scratch],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, creationflags=tweaks.CREATE_NO_WINDOW,
            check=False)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if r.returncode == 0:
        return ""
    lines = [ln.strip() for ln in r.stderr.splitlines() if ln.strip()]
    return f"failed {lines[0] if lines else f'0x{r.returncode & 0xFFFFFFFF:08X}'}"


def install_step(pkg_id, override=None):
    """Returns "" or the failure text of one package row."""
    exe = resolve_winget()
    if exe is None:
        return "failed winget not found"
    rc = run_winget(exe, winget_args(pkg_id, override))
    if rc == RESTART_REQUIRED:
        return RESTART_STATE
    return "" if rc == 0 or rc in ALREADY_INSTALLED else f"failed 0x{rc:08X}"


def tightvnc_step(password):
    """Like install_step; afterwards winget's logs are scrubbed of the password
    whatever the outcome, and a scrub failure outranks the install result."""
    start = time.time()
    try:
        err = install_step(TIGHTVNC, tightvnc_override(password))
    except Exception as e:
        err = failure_text(e)
    return scrub_winget_logs(winget_log_dir(), start, password) or err


def firefox_step(tw):
    tw.apply(True)
    return ""


def installed_versions():
    """DisplayVersion per PACKAGES entry, None when not installed."""
    entries = clean.enumerate_uninstall_entries()
    out = []
    for _label, _id, match in PACKAGES:
        found = next((e for e in entries if re.match(match, e.display_name)),
                     None)
        out.append(None if found is None else found.display_version or "n/a")
    return out


def prompt_password(parent):
    text, ok = QInputDialog.getText(parent, "TightVNC", "VNC password",
                                    QLineEdit.Password)
    return text if ok else ""


class InstallWorker(QThread):
    """steps: [(row, label, fn)]; fn returns "", RESTART_STATE or a failure
    text, or raises. Only the exception type or its OS error text is kept: a
    message could carry an installer argument such as the VNC password."""

    status = pyqtSignal(int, str)
    progress = pyqtSignal(int)

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.errors = []
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        for i, (row, label, fn) in enumerate(self.steps, 1):
            if self._stop:
                break
            self.status.emit(row, "installing")
            try:
                err = fn()
            except Exception as e:
                err = failure_text(e)
            if err and err != RESTART_STATE:
                self.errors.append(f"{label}: {err}")
            self.status.emit(row, err or "installed")
            self.progress.emit(i)


class InstallerPage(QWidget):
    def __init__(self, report, refresh, parent=None):
        super().__init__(parent)
        self._report = report
        self._refresh = refresh
        self._worker = None
        self._total = 0
        self._tweak = next(t for t in tweaks.TWEAKS if t.key == "firefoxsetup")

        labels = [WINGET_LABEL, *(p[0] for p in PACKAGES), self._tweak.label]
        self.grid = style_grid(QTableWidget(len(labels), len(COLS)))
        self.grid.setHorizontalHeaderLabels(COLS)
        self.grid.horizontalHeader().setStretchLastSection(True)
        for r, label in enumerate(labels):
            first = QTableWidgetItem(label)
            first.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                           | Qt.ItemIsUserCheckable)
            self.grid.setItem(r, 0, first)
            self.grid.setItem(r, 1, QTableWidgetItem())
            self.grid.setItem(r, 2, QTableWidgetItem())

        self.btn_install = QPushButton("Install")
        self.btn_install.clicked.connect(self._install)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_states)
        self.status = QLabel()
        self.status.setWordWrap(True)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_install)
        bottom.addWidget(self.btn_refresh)
        bottom.addWidget(self.status, 1)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addWidget(self.grid, 1)
        v.addLayout(bottom)

        self.refresh_states()

    def _show(self, row, installed, wanted):
        self.grid.item(row, 1).setText(installed)
        self.grid.item(row, 0).setCheckState(Qt.Checked if wanted else Qt.Unchecked)

    def refresh_states(self):
        version = winget_version()
        self._show(WINGET_ROW, version or "", version is None)
        for r, ver in enumerate(installed_versions(), FIRST_PKG_ROW):
            self._show(r, ver or "", ver is None)
        state = self._tweak.state()
        self._show(FIREFOX_ROW, STATE_WORD[state], state is False)

    def checked_rows(self):
        return [r for r in range(self.grid.rowCount())
                if self.grid.item(r, 0).checkState() == Qt.Checked]

    def _install(self):
        rows = self.checked_rows()
        if not rows:
            return
        names = "\n".join(self.grid.item(r, 0).text() for r in rows)
        if QMessageBox.warning(self, "Install",
                               f"Install {len(rows)} items on this PC?\n\n{names}",
                               QMessageBox.Yes | QMessageBox.No,
                               QMessageBox.No) != QMessageBox.Yes:
            return
        for r in range(self.grid.rowCount()):
            self.grid.item(r, 2).setText("")
        steps = []
        for r in self.checked_rows():
            if r == WINGET_ROW:
                steps.append((r, WINGET_LABEL, install_winget))
            elif r == FIREFOX_ROW:
                steps.append((r, self._tweak.label,
                              functools.partial(firefox_step, self._tweak)))
            else:
                label, pkg_id, _match = PACKAGES[r - FIRST_PKG_ROW]
                if pkg_id == TIGHTVNC:
                    password = prompt_password(self)
                    if not password:
                        self.grid.item(r, 2).setText("skipped")
                        continue
                    fn = functools.partial(tightvnc_step, password)
                else:
                    override = python_override(pkg_id) if pkg_id == PYTHON else None
                    fn = functools.partial(install_step, pkg_id, override)
                steps.append((r, label, fn))
        if not steps:
            return
        for r, _label, _fn in steps:
            self.grid.item(r, 2).setText("queued")
        self._total = len(steps)
        self.btn_install.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.status.setText(f"0 of {self._total}")
        self._worker = InstallWorker(steps, self)
        self._worker.status.connect(self._set_status)
        self._worker.progress.connect(self._progress)
        self._worker.finished.connect(self._finish)
        self._worker.start()

    def _set_status(self, row, text):
        self.grid.item(row, 2).setText(text)

    def _progress(self, k):
        self.status.setText(f"{k} of {self._total}")

    def _finish(self):
        if self._worker is None:  # closed while the last step ran
            return
        errors = list(self._worker.errors)
        # the steps hold the VNC password inside their command line
        self._worker.steps = []
        text = "   ".join([f"{self._total - len(errors)} installed   "
                           f"{len(errors)} failed", *errors])
        self.status.setText(text)
        self._report(text)
        self.refresh_states()
        self._refresh()
        self.btn_install.setEnabled(True)
        self.btn_refresh.setEnabled(True)

    def shutdown(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.request_stop()
            worker.wait()
