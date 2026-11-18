"""Contract test for wintools._isolate_children(): frozen builds mark the
environment every child inherits so a later launch of the exe from one of
them (Explorer as the shell) ignores this instance's stale _PYI_* vars."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wintools  # noqa: E402

VAR = "PYINSTALLER_RESET_ENVIRONMENT"
saved_env = os.environ.pop(VAR, None)
had_frozen = hasattr(sys, "frozen")
try:
    if had_frozen:
        del sys.frozen
    wintools._isolate_children()
    assert VAR not in os.environ, "source run must leave the environment alone"
    print("source ok")

    sys.frozen = True
    wintools._isolate_children()
    assert os.environ.get(VAR) == "1", os.environ.get(VAR)
    print("frozen ok")
finally:
    os.environ.pop(VAR, None)
    if saved_env is not None:
        os.environ[VAR] = saved_env
    if not had_frozen and hasattr(sys, "frozen"):
        del sys.frozen

print("STATUS: SUCCESS")
