"""Contract test for keydiag.KeyDiagPage event classification.

Feeds a synthetic event stream straight into the hook queue - no real
keyboard and no global hook is installed.
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import keydiag  # noqa: E402
from keydiag import (  # noqa: E402
    LLKHF_INJECTED, WM_KEYDOWN, WM_KEYUP, KeyDiagPage,
    keyboard_delay_ms, keyboard_repeat_ms,
)

E_VK, E_SCAN = 0x45, 0x12          # 'E' on a US layout
R_VK, R_SCAN = 0x52, 0x13          # 'R'
EXPECTED_MS = 30                   # from the stub FilterKeys reader below

app = QApplication([])


def page():
    p = KeyDiagPage(lambda: (True, 250, EXPECTED_MS))
    p.threshold.setValue(40)
    assert p.expected_ms == EXPECTED_MS, p.expected_ms
    return p


def feed(p, events):
    """events: (t_ms, down, vk, scan, flags)"""
    for t_ms, down, vk, scan, flags in events:
        p.hook.events.append(
            (t_ms / 1000.0, WM_KEYDOWN if down else WM_KEYUP, vk, scan, flags))
    p.anomalies_only.setChecked(False)
    p._drain()


def classes(p):
    col = keydiag.EVENT_COLS.index("class")
    return [p.events.item(r, col).text() for r in range(p.events.rowCount())]


# ---- a plain keystroke ----
p = page()
feed(p, [(1000, True, E_VK, E_SCAN, 0), (1080, False, E_VK, E_SCAN, 0)])
assert classes(p) == ["press", "release"], classes(p)
assert p.counts["chatter"] == 0
print("plain press ok")

# ---- switch bounce: released and re-pressed 5 ms later ----
p = page()
feed(p, [
    (1000, True, E_VK, E_SCAN, 0),
    (1003, False, E_VK, E_SCAN, 0),
    (1008, True, E_VK, E_SCAN, 0),
    (1090, False, E_VK, E_SCAN, 0),
])
assert classes(p) == ["press", "release", "chatter", "release"], classes(p)
assert p.counts["chatter"] == 1
st = p.keys[(E_VK, E_SCAN)]
assert abs(st["min_gap"] - 5.0) < 0.01, st["min_gap"]
print(f"chatter ok: min gap {st['min_gap']:.1f} ms")

# ---- a human double-tap is not chatter ----
p = page()
feed(p, [
    (1000, True, E_VK, E_SCAN, 0),
    (1050, False, E_VK, E_SCAN, 0),
    (1200, True, E_VK, E_SCAN, 0),
])
assert classes(p) == ["press", "release", "press"], classes(p)
assert p.counts["chatter"] == 0
print("double-tap not flagged ok")

# ---- held key repeating at the configured rate ----
p = page()
feed(p, [
    (1000, True, E_VK, E_SCAN, 0),
    (1250, True, E_VK, E_SCAN, 0),
    (1250 + EXPECTED_MS, True, E_VK, E_SCAN, 0),
    (1250 + 2 * EXPECTED_MS, True, E_VK, E_SCAN, 0),
])
assert classes(p) == ["press", "repeat", "repeat", "repeat"], classes(p)
assert p.counts["repeat-fast"] == 0
print("auto-repeat ok")

# ---- repeat arriving far faster than configured ----
p = page()
feed(p, [
    (1000, True, E_VK, E_SCAN, 0),
    (1002, True, E_VK, E_SCAN, 0),
    (1004, True, E_VK, E_SCAN, 0),
])
assert classes(p) == ["press", "repeat-fast", "repeat-fast"], classes(p)
print("repeat-fast ok")

# ---- synthesised by another process ----
p = page()
feed(p, [
    (1000, True, E_VK, E_SCAN, LLKHF_INJECTED),
    (1010, False, E_VK, E_SCAN, LLKHF_INJECTED),
])
assert classes(p) == ["injected", "injected"], classes(p)
assert p.counts["injected"] == 2
print("injected ok")

# ---- per-key totals and the worst-key readout ----
p = page()
stream = []
t = 1000
for _ in range(3):                       # E chatters three times
    stream += [(t, True, E_VK, E_SCAN, 0), (t + 3, False, E_VK, E_SCAN, 0),
               (t + 9, True, E_VK, E_SCAN, 0), (t + 60, False, E_VK, E_SCAN, 0)]
    t += 200
stream += [(t, True, R_VK, R_SCAN, 0), (t + 70, False, R_VK, R_SCAN, 0)]
feed(p, stream)
assert p.keys[(E_VK, E_SCAN)]["chatter"] == 3, p.keys[(E_VK, E_SCAN)]
assert p.keys[(R_VK, R_SCAN)]["chatter"] == 0
assert p.summary.rowCount() == 2, p.summary.rowCount()
assert p.summary.item(0, 0).text() == p.keys[(E_VK, E_SCAN)]["name"]
assert "chatter 3" in p.status.text(), p.status.text()
assert "worst" in p.status.text(), p.status.text()
print(f"summary ok: {p.status.text()}")

# ---- anomalies-only hides the clean events ----
p = page()
p.hook.events.append((1.0, WM_KEYDOWN, E_VK, E_SCAN, 0))
p.hook.events.append((1.08, WM_KEYUP, E_VK, E_SCAN, 0))
p.hook.events.append((1.083, WM_KEYDOWN, E_VK, E_SCAN, 0))
p.anomalies_only.setChecked(True)
p._drain()
assert classes(p) == ["chatter"], classes(p)
print("anomalies filter ok")

# ---- clear resets everything ----
p._clear()
assert p.events.rowCount() == 0 and p.summary.rowCount() == 0
assert not any(p.counts.values()) and not p.keys
print("clear ok")

# ---- live system readouts ----
delay, repeat = keyboard_delay_ms(), keyboard_repeat_ms()
assert 250 <= delay <= 1000, delay
assert 33 <= repeat <= 400, repeat
name = keydiag.key_name(E_VK, E_SCAN, 0)
assert name.strip(), repr(name)
print(f"system readouts ok: delay {delay} ms  repeat {repeat:.0f} ms  "
      f"scan {E_SCAN:02X} = {name!r}")

# ---- native Windows repeat: SPI round-trip, original restored ----
saved_delay = keydiag.keyboard_delay_index()
saved_speed = keydiag.keyboard_speed_index()
print(f"windows repeat before: delay index {saved_delay} "
      f"speed index {saved_speed}")
try:
    keydiag.set_keyboard_delay(3)
    keydiag.set_keyboard_speed(8)
    assert keydiag.keyboard_delay_index() == 3, keydiag.keyboard_delay_index()
    assert keydiag.keyboard_speed_index() == 8, keydiag.keyboard_speed_index()
    assert keydiag.keyboard_delay_ms() == 1000, keydiag.keyboard_delay_ms()
    slow = keydiag.keyboard_repeat_ms()

    keydiag.set_keyboard_delay(0)
    keydiag.set_keyboard_speed(keydiag.SPEED_MAX)
    assert keydiag.keyboard_delay_ms() == 250, keydiag.keyboard_delay_ms()
    fast = keydiag.keyboard_repeat_ms()
    assert slow > fast * 2, (slow, fast)
finally:
    keydiag.set_keyboard_delay(saved_delay)
    keydiag.set_keyboard_speed(saved_speed)
assert keydiag.keyboard_delay_index() == saved_delay
assert keydiag.keyboard_speed_index() == saved_speed
print(f"windows repeat ok: slowest {slow:.0f} ms  fastest {fast:.0f} ms, "
      f"original restored")

# ---- the real hook: install, receive a keystroke, uninstall ----
# VK_F24 has no default action in any shell or app, so injecting it cannot
# disturb whatever the user has focused.
VK_F24 = keydiag.VK_F24


def pump(predicate, timeout=3.0):
    # No sleeping in here: a low-level hook is only delivered while the
    # installing thread is retrieving messages, so blocking the thread is
    # what makes this flaky.
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
    return predicate()


hook = keydiag.KeyHook()
assert not hook.running()
hook.start()
assert hook.running()
print("hook installed ok")

seen = hook.prove_delivery()
assert seen, "no F24 event reached the hook"
assert not hook.events, list(hook.events)
assert len(seen) >= 2, seen
assert seen[0][1] == keydiag.WM_KEYDOWN, seen[0]
assert seen[1][1] == keydiag.WM_KEYUP, seen[1]
assert seen[0][4] & keydiag.LLKHF_INJECTED, hex(seen[0][4])
print(f"hook delivered {len(seen)} F24 events, flags=0x{seen[0][4]:02x}")

hook.stop()
assert not hook.running()
hook.stop()          # idempotent
hook.start()         # restartable after a stop
assert hook.running()
hook.start()         # idempotent
hook.stop()
print("hook start/stop lifecycle ok")

# ---- prove_delivery confirms delivery and discards its probe ----
p = page()
p.hook.start()
assert p.hook.prove_delivery(), "prove_delivery could not confirm delivery"
assert not p.hook.events, list(p.hook.events)
assert p.events.rowCount() == 0 and not any(p.counts.values()), p.counts
p.hook.stop()
print("prove_delivery ok, probe not counted")

# ---- an undeliverable hook must report, not pretend to capture ----
# Suppressing the probe tap is indistinguishable, from the page's side, from
# a hook Windows has silently dropped.
p = page()
real_tap, keydiag.tap_probe_key = keydiag.tap_probe_key, lambda: None
try:
    p._toggle()
finally:
    keydiag.tap_probe_key = real_tap
assert not p.timer.isActive(), "drain timer started on an unproven hook"
assert not p.hook.running(), "unproven hook left installed"
assert p.btn_capture.isEnabled()
assert p.btn_capture.text() == "Start capture", p.btn_capture.text()
assert "no events were delivered" in p.status.text(), p.status.text()
print(f"unproven hook reported: {p.status.text()}")

# ---- the same path the Start capture button drives ----
p = page()
p._toggle()
assert p.hook.running(), p.status.text()
assert p.btn_capture.text() == "Stop capture"
assert p.btn_capture.isEnabled()
assert "capturing" in p.status.text(), p.status.text()

keydiag.tap_probe_key()
assert pump(lambda: p.events.rowCount() > 0), \
    f"drain timer produced no rows; status={p.status.text()}"
assert p.counts["injected"] >= 2, p.counts
assert "injected" in classes(p), classes(p)

p._toggle()
assert not p.hook.running()
assert p.btn_capture.text() == "Start capture"
print(f"capture button path ok: {p.status.text()}")

print("STATUS: SUCCESS")
