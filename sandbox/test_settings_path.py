"""Contract test for wintools.settings_path() in source and frozen mode."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wintools  # noqa: E402

SCRIPT = os.path.abspath(wintools.__file__)
_MISSING = object()
saved = (sys.executable, getattr(sys, "frozen", _MISSING))

try:
    # ---- source mode: beside the script, not the interpreter ----
    if hasattr(sys, "frozen"):
        del sys.frozen
    sys.executable = r"C:\Python\313\pythonw.exe"
    p = wintools.settings_path()
    assert p == os.path.join(os.path.dirname(SCRIPT), "wintools.ini"), p
    print(f"source ok: {p}")

    # ---- frozen mode: <exe name>.ini beside the exe, follows a rename ----
    sys.frozen = True
    for exe, ini in [
        (r"C:\tool dir\wintools.exe", r"C:\tool dir\wintools.ini"),
        (r"D:\x\other.name.exe", r"D:\x\other.name.ini"),
    ]:
        sys.executable = exe
        p = wintools.settings_path()
        assert p == ini, p
        print(f"frozen ok: {exe} -> {p}")
finally:
    sys.executable = saved[0]
    if saved[1] is _MISSING:
        if hasattr(sys, "frozen"):
            del sys.frozen
    else:
        sys.frozen = saved[1]

print("STATUS: SUCCESS")
