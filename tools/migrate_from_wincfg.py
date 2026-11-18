"""One-time per-PC migration of wincfg state to wintools.

HKCU\\Software\\wincfg\\wincfg (QSettings) -> wintools.ini beside wintools.py
HKCU\\Software\\wincfg (undo records)      -> HKCU\\Software\\wintools
%ProgramData%\\wincfg                     -> %ProgramData%\\wintools
task "wincfg GPU settings"                -> "wintools GPU settings" (needs admin)
Copies only; the old key and folder are left for manual removal.
"""

import os
import shutil
import subprocess
import sys
import winreg
from pathlib import Path

from PyQt5.QtCore import QSettings

OLD, NEW = r"Software\wincfg", r"Software\wintools"
QSETTINGS_SUBKEY = "wincfg"
OLD_TASK = "wincfg GPU settings"
ROOT = Path(__file__).resolve().parent.parent


def copy_key(src, dst, skip=()):
    n = 0
    with (
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, src) as s,
        winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, dst) as d,
    ):
        nvals, nkeys = winreg.QueryInfoKey(s)[1], winreg.QueryInfoKey(s)[0]
        for i in range(nvals):
            name, data, typ = winreg.EnumValue(s, i)
            winreg.SetValueEx(d, name, 0, typ, data)
            n += 1
        subs = [winreg.EnumKey(s, i) for i in range(nkeys)]
    for sub in subs:
        if sub not in skip:
            n += copy_key(rf"{src}\{sub}", rf"{dst}\{sub}")
    return n


def main():
    ini = ROOT / "wintools.ini"
    if ini.exists():
        # Dropbox syncs the first migrated PC's file to the others
        print(f"settings: {ini} exists, skipped")
    else:
        old = QSettings("wincfg", "wincfg")
        new = QSettings(str(ini), QSettings.IniFormat)
        keys = old.allKeys()
        for k in keys:
            new.setValue(k, old.value(k))
        new.sync()
        if new.status() != QSettings.NoError:
            sys.exit(f"writing {ini} failed: status {new.status()}")
        print(f"settings: {len(keys)} keys -> {ini}")

    n = copy_key(OLD, NEW, skip=(QSETTINGS_SUBKEY,))
    print(f"registry: {n} values -> HKCU\\{NEW}")

    src = Path(os.environ["ProgramData"]) / "wincfg"
    dst = Path(os.environ["ProgramData"]) / "wintools"
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print(f"data: {src} -> {dst}")
    else:
        print(f"data: {src} absent")

    def schtasks(*args):
        return subprocess.run(["schtasks", *args], capture_output=True, text=True)

    if schtasks("/Query", "/TN", OLD_TASK).returncode:
        print(f"task: {OLD_TASK} absent")
        return
    sys.path.insert(0, str(ROOT))
    import gpu

    profiles = list(gpu.load_profiles().values())
    if not profiles:
        sys.exit(f"task: {OLD_TASK} exists but {gpu.PROFILE_PATH} has no profiles")
    gpu.enable_boot(profiles)
    r = schtasks("/Delete", "/F", "/TN", OLD_TASK)
    if r.returncode:
        sys.exit(f"deleting {OLD_TASK} failed: {(r.stdout + r.stderr).strip()}")
    print(f"task: {OLD_TASK} -> {gpu.TASK_NAME}")


if __name__ == "__main__":
    main()
