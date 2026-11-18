"""Contract test for wintools.set_filterkeys / read_filterkeys round-trip.

Mutates the live FilterKeys settings, then restores the original struct.
"""

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filterkeys import (  # noqa: E402
    FILTERKEYS, FKF_AVAILABLE, FKF_FILTERKEYSON,
    read_filterkeys, set_filterkeys, write_filterkeys,
)

assert ctypes.sizeof(FILTERKEYS) == 24, ctypes.sizeof(FILTERKEYS)

original = read_filterkeys()
print(f"original: flags=0x{original.dwFlags:08x} delay={original.iDelayMSec} "
      f"repeat={original.iRepeatMSec} wait={original.iWaitMSec} "
      f"bounce={original.iBounceMSec}")

try:
    set_filterkeys(True, 123, 7)
    got = read_filterkeys()
    assert got.dwFlags & FKF_FILTERKEYSON, hex(got.dwFlags)
    assert got.dwFlags & FKF_AVAILABLE, hex(got.dwFlags)
    assert got.iDelayMSec == 123, got.iDelayMSec
    assert got.iRepeatMSec == 7, got.iRepeatMSec
    assert got.iWaitMSec == 0, got.iWaitMSec
    print("on: round-trip 123/7 ok")

    set_filterkeys(False, 0, 0)
    got = read_filterkeys()
    assert not (got.dwFlags & FKF_FILTERKEYSON), hex(got.dwFlags)
    print("off: FKF_FILTERKEYSON cleared ok")
finally:
    write_filterkeys(original, persist=True)

back = read_filterkeys()
assert back.dwFlags == original.dwFlags, (hex(back.dwFlags), hex(original.dwFlags))
assert back.iDelayMSec == original.iDelayMSec
assert back.iRepeatMSec == original.iRepeatMSec
print("restored ok")
print("STATUS: SUCCESS")
