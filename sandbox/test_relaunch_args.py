"""Contract test for wintools._relaunch_args() in source and frozen mode."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wintools  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(wintools.__file__))
_MISSING = object()
saved = (sys.executable, list(sys.argv), getattr(sys, "frozen", _MISSING))


def restore():
    sys.executable = saved[0]
    sys.argv[:] = saved[1]
    if saved[2] is _MISSING:
        if hasattr(sys, "frozen"):
            del sys.frozen
    else:
        sys.frozen = saved[2]


try:
    # ---- source mode: pythonw.exe beside the interpreter ----
    with tempfile.TemporaryDirectory() as d:
        py = os.path.join(d, "python.exe")
        pyw = os.path.join(d, "pythonw.exe")
        for p in (py, pyw):
            open(p, "w").close()
        if hasattr(sys, "frozen"):
            del sys.frozen
        sys.executable = py
        script = os.path.join(d, "my dir", "wintools.py")
        sys.argv[:] = [script, "--flag", "a b"]

        exe, params, cwd = wintools._relaunch_args()
        assert exe == pyw, exe
        assert params == subprocess.list2cmdline([script, "--flag", "a b"]), params
        assert '"a b"' in params and f'"{script}"' in params, params
        assert cwd == SCRIPT_DIR, cwd
        print(f"source ok: {exe} | {params} | {cwd}")

        # no pythonw.exe -> sys.executable
        os.remove(pyw)
        exe, params, cwd = wintools._relaunch_args()
        assert exe == py, exe
        assert cwd == SCRIPT_DIR, cwd
        print("source fallback ok")

    # ---- frozen mode: the exe itself, no script path ----
    with tempfile.TemporaryDirectory() as d:
        sub = os.path.join(d, "tool dir")
        os.mkdir(sub)
        frozen_exe = os.path.join(sub, "wintools.exe")
        sys.frozen = True
        sys.executable = frozen_exe
        sys.argv[:] = [frozen_exe, "--flag", "a b"]

        exe, params, cwd = wintools._relaunch_args()
        assert exe == frozen_exe, exe
        assert params == subprocess.list2cmdline(["--flag", "a b"]), params
        assert params == '--flag "a b"', params
        assert cwd == sub, cwd
        assert cwd != SCRIPT_DIR
        print(f"frozen ok: {exe} | {params} | {cwd}")

        sys.argv[:] = [frozen_exe]
        exe, params, cwd = wintools._relaunch_args()
        assert params == "", repr(params)
        print("frozen no-args ok")
finally:
    restore()

print("STATUS: SUCCESS")
