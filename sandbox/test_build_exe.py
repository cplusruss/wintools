"""Contract test for build_exe.py: builds dist\\wintools.exe and smoke-runs it.

A windowed exe that crashes at startup shows a modal dialog and never exits,
so failing to exit inside the timeout is the failure signal.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "wintools.exe"
TIMEOUT_S = 90

build = subprocess.run([sys.executable, str(ROOT / "build_exe.py")], cwd=ROOT)
assert build.returncode == 0, f"build_exe.py exit {build.returncode}"
assert EXE.is_file(), EXE
print(f"built: {EXE} ({EXE.stat().st_size / 1e6:.1f} MB)")

env = dict(os.environ, WINTOOLS_SMOKE_MS="4000", QT_QPA_PLATFORM="offscreen")
proc = subprocess.Popen([str(EXE), "--no-elevate"], env=env, cwd=ROOT)
try:
    rc = proc.wait(timeout=TIMEOUT_S)
except subprocess.TimeoutExpired:
    subprocess.run(["taskkill", "/f", "/t", "/pid", str(proc.pid)], capture_output=True)
    raise AssertionError(f"wintools.exe still running after {TIMEOUT_S} s") from None
assert rc == 0, f"wintools.exe exit code {rc}"
print("smoke run ok: exit 0")

print("STATUS: SUCCESS")
