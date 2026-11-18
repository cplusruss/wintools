"""Contract test for pawnio.py and tools\\hw_probe.py, run from an unelevated
shell: IOCTL codes and byte-exact request packing, the module function tables
against the module binaries, zip verification and extraction, the resource
resolver, the Driver start-up errors, the bus mutex helper, thread pinning, and
the probe collectors against simulated SPD / SuperIO / MSR devices.  Nothing
here touches hardware.
"""

import contextlib
import ctypes
import hashlib
import importlib.util
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pawnio  # noqa: E402

PYTHON = r"C:\Python\313\python.exe"
ZIP = ROOT / "resource" / "release_0_2_11.zip"
BINS = ["AMDFamily17.bin", "RyzenSMU.bin", "IntelMSR.bin", "IntelMCHBAR.bin",
        "SmbusPIIX4.bin", "SmbusI801.bin", "LpcIO.bin"]
EXTRACTED = sorted(BINS + ["COPYING"])
SCRATCH = Path(r"C:\tmp") / "wintools-test-pawnio"
shutil.rmtree(SCRATCH, ignore_errors=True)
SCRATCH.mkdir(parents=True)


def raises(exc, text, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        assert text in str(e), (text, str(e))
        return e
    raise AssertionError(f"{fn} did not raise {exc.__name__}")


# ---- IOCTL codes: CTL_CODE(41394, fn, METHOD_BUFFERED, FILE_ANY_ACCESS) ----
assert pawnio.DEVICE_TYPE == 41394
assert pawnio.ctl_code(41394, 0x821) == 0xA1B22084 == 2712805508
assert pawnio.IOCTL_LOAD_BINARY == 0xA1B22084
assert pawnio.IOCTL_EXECUTE_FN == 0xA1B22104 == 2712805636
assert pawnio.IOCTL_VERSION == 0xA1B22184 == 2712805764
assert pawnio.DEVICE_PATH == "\\\\?\\GLOBALROOT\\Device\\PawnIO"
assert pawnio.SERVICE_NAME == "PawnIO"
assert pawnio.FN_NAME_LEN == 32
print("ioctl codes ok")

# ---- request packing, byte exact ----
req = pawnio.pack_execute("ioctl_read_msr", [0xC0010015])
assert req == (b"ioctl_read_msr" + bytes(18) + bytes.fromhex("1500 01c0 0000 0000")), req.hex()
assert len(req) == 40
assert pawnio.pack_execute("ioctl_x", []) == b"ioctl_x" + bytes(25)
neg = pawnio.pack_execute("ioctl_piix4_port_sel", [-1, 2])
assert neg[32:] == bytes.fromhex("ffffffffffffffff 0200000000000000"), neg.hex()
assert len(pawnio.pack_execute("ioctl_" + "a" * 25, [])) == 32   # 31 characters fit
raises(pawnio.PawnIOError, "function name", pawnio.pack_execute, "ioctl_" + "a" * 26, [])
raises(pawnio.PawnIOError, "ioctl_", pawnio.pack_execute, "read_msr", [])
raises(pawnio.PawnIOError, "input", pawnio.pack_execute, "ioctl_x", [1 << 64])
raises(pawnio.PawnIOError, "input", pawnio.pack_execute, "ioctl_x", [-(1 << 63) - 1])
assert pawnio.unpack_cells(bytes.fromhex("0100000000000000 ffffffffffffffff")) == [
    1, 0xFFFFFFFFFFFFFFFF]
assert pawnio.unpack_cells(b"") == []
raises(pawnio.PawnIOError, "multiple of 8", pawnio.unpack_cells, b"\x01" * 12)
assert pawnio.unpack_version(struct.pack("<I", 0x00020100)) == (2, 1, 0)
raises(pawnio.PawnIOError, "4 bytes", pawnio.unpack_version, b"\x00\x01")
print("packing ok")

# ---- load blob: 4-byte signature length, signature, image ----
raises(pawnio.PawnIOError, "blob", pawnio.check_blob, b"\x00\x01")
raises(pawnio.PawnIOError, "blob", pawnio.check_blob, struct.pack("<I", 100) + b"\x00" * 10)
pawnio.check_blob(struct.pack("<I", 2) + b"\xaa\xbb" + b"image")
print("blob check ok")

# ---- the zip ----
assert pawnio.ZIP_NAME == "release_0_2_11.zip"
assert pawnio.ZIP_SHA256 == "43608cb89bc84247fef1368a139013f7d043e17db6d6c8dfc9b46bf0905a81f4"
assert hashlib.sha256(ZIP.read_bytes()).hexdigest() == pawnio.ZIP_SHA256
pawnio.verify_zip(ZIP)
bad = SCRATCH / "corrupt.zip"
data = bytearray(ZIP.read_bytes())
data[len(data) // 2] ^= 0xFF
bad.write_bytes(data)
raises(pawnio.PawnIOError, "SHA256", pawnio.verify_zip, bad)
dest = SCRATCH / "out_bad"
raises(pawnio.PawnIOError, "SHA256", pawnio.extract_modules, bad, dest)
assert not dest.exists(), "nothing may be extracted from a corrupted zip"
print("zip sha256 ok: real passes, corrupted fails and extracts nothing")

# ---- extraction ----
dest = SCRATCH / "out_good"
written = pawnio.extract_modules(ZIP, dest)
assert sorted(p.name for p in dest.iterdir()) == EXTRACTED, sorted(p.name for p in dest.iterdir())
assert sorted(p.name for p in written) == EXTRACTED
with zipfile.ZipFile(ZIP) as z:
    for name in EXTRACTED:
        assert (dest / name).read_bytes() == z.read(name), name
print("extraction ok:", ", ".join(EXTRACTED))

# the packaged folder in the repo holds exactly that set, byte-identical
pkg = ROOT / "resource" / "pawnio"
assert sorted(p.name for p in pkg.iterdir()) == EXTRACTED, sorted(p.name for p in pkg.iterdir())
for name in EXTRACTED:
    assert (pkg / name).read_bytes() == (dest / name).read_bytes(), name
assert pawnio.resource_dir() == pkg.resolve()
for name in BINS:
    pawnio.check_blob(pawnio.module_bytes(name[:-4]))
print("packaged resource\\pawnio ok")

# ---- the resolver: source run and frozen run beside the exe agree ----
with mock.patch.object(sys, "frozen", True, create=True), \
        mock.patch.object(sys, "executable", str(ROOT / "wintools.exe")):
    assert pawnio.resource_dir() == pkg.resolve(), pawnio.resource_dir()
with tempfile.TemporaryDirectory(prefix="wintools-selftest-pawnio-", dir=r"C:\tmp") as scratch:
    scratch = Path(scratch).resolve()
    gone = scratch / "resource" / "pawnio"
    with mock.patch.object(sys, "frozen", True, create=True), \
            mock.patch.object(sys, "executable", str(scratch / "wintools.exe")):
        e = raises(FileNotFoundError, "missing", pawnio.resource_dir)
        assert str(e) == f"missing {gone}", str(e)
        gone.mkdir(parents=True)
        e = raises(FileNotFoundError, "missing", pawnio.module_bytes, "LpcIO")
        assert str(e) == f"missing {gone / 'LpcIO.bin'}", str(e)
print("resolver ok")

# ---- the function tables against the module binaries ----
assert sorted(pawnio.MODULES) == sorted(n[:-4] for n in BINS)
with zipfile.ZipFile(ZIP) as z:
    for mod, fns in pawnio.MODULES.items():
        found = set(re.findall(rb"ioctl_[a-z0-9_]+", z.read(mod + ".bin")))
        assert {f.encode() for f in fns} == found, (mod, sorted(fns), sorted(found))
print("module function tables match the binaries")

# ---- Driver start-up errors ----
ADMIN_MSG = "PawnIO: administrator required"
with mock.patch.object(pawnio, "is_admin", return_value=False):
    e = raises(pawnio.PawnIOError, ADMIN_MSG, pawnio.Driver)
    assert str(e) == ADMIN_MSG
if not pawnio.is_admin():
    e = raises(pawnio.PawnIOError, ADMIN_MSG, pawnio.Driver)
    assert str(e) == ADMIN_MSG
    print("this shell is not elevated: Driver() raises", ADMIN_MSG)
else:
    print("this shell is elevated: the real Driver() check was skipped")


def not_found():
    return pawnio.PawnIOError("CreateFileW: The system cannot find the file specified.", 2)


# service missing
with mock.patch.object(pawnio, "is_admin", return_value=True), \
        mock.patch.object(pawnio, "_open_device", side_effect=not_found()), \
        mock.patch.object(pawnio, "_service_state",
                          side_effect=pawnio.PawnIOError("PawnIO: driver not installed")):
    e = raises(pawnio.PawnIOError, "PawnIO: driver not installed", pawnio.Driver)
    assert str(e) == "PawnIO: driver not installed"
e = raises(pawnio.PawnIOError, "PawnIO: driver not installed",
           pawnio._service_state, "WintoolsNoSuchService")
assert str(e) == "PawnIO: driver not installed"
assert pawnio._service_state() in range(1, 8)
print("service missing and service state ok")

# service stopped: started once, then the device opens
calls = []
opens = iter([not_found(), 4321])


def fake_open():
    r = next(opens)
    if isinstance(r, Exception):
        raise r
    calls.append("open")
    return r


with mock.patch.object(pawnio, "is_admin", return_value=True), \
        mock.patch.object(pawnio, "_open_device", side_effect=fake_open), \
        mock.patch.object(pawnio, "_service_state", return_value=pawnio.SERVICE_STOPPED), \
        mock.patch.object(pawnio, "_start_service", side_effect=lambda: calls.append("start")), \
        mock.patch.object(pawnio, "_ioctl", return_value=struct.pack("<I", 0x00020100)), \
        mock.patch.object(pawnio, "_close_handle", side_effect=lambda h: calls.append(("close", h))), \
        mock.patch.object(time, "sleep"):
    drv = pawnio.Driver()
    assert calls == ["start", "open"], calls
    assert drv.version == (2, 1, 0)
    drv.close()
    assert calls[-1] == ("close", 4321), calls

# start_service=False never starts the service
opens = iter([not_found()])
calls.clear()
with mock.patch.object(pawnio, "is_admin", return_value=True), \
        mock.patch.object(pawnio, "_open_device", side_effect=fake_open), \
        mock.patch.object(pawnio, "_service_state", return_value=pawnio.SERVICE_STOPPED), \
        mock.patch.object(pawnio, "_start_service", side_effect=lambda: calls.append("start")):
    e = raises(pawnio.PawnIOError, "STOPPED", pawnio.Driver, start_service=False)
    assert "start" not in calls and pawnio.DEVICE_PATH in str(e), (calls, str(e))

# service running but the device is absent
with mock.patch.object(pawnio, "is_admin", return_value=True), \
        mock.patch.object(pawnio, "_open_device", side_effect=not_found()), \
        mock.patch.object(pawnio, "_service_state", return_value=pawnio.SERVICE_RUNNING), \
        mock.patch.object(time, "sleep"):
    e = raises(pawnio.PawnIOError, "RUNNING", pawnio.Driver)
    assert str(e).startswith("PawnIO:") and pawnio.DEVICE_PATH in str(e), str(e)

# any other open failure is the Win32 message, not a service start
denied = pawnio.PawnIOError("CreateFileW: Access is denied.", 5)
with mock.patch.object(pawnio, "is_admin", return_value=True), \
        mock.patch.object(pawnio, "_open_device", side_effect=denied), \
        mock.patch.object(pawnio, "_start_service") as start:
    raises(pawnio.PawnIOError, "Access is denied", pawnio.Driver)
    start.assert_not_called()
print("driver start-up paths ok")

# ---- load / execute / close through a patched _ioctl ----
log = []
handles = iter([100, 200, 300])


def fake_ioctl(handle, code, data, out_size, what):
    log.append((handle, code, bytes(data), out_size, what))
    if code == pawnio.IOCTL_VERSION:
        return struct.pack("<I", 0x00020100)
    if code == pawnio.IOCTL_EXECUTE_FN:
        return bytes.fromhex("2a00000000000000 ffffffffffffffff")[:out_size]
    return b""


with mock.patch.object(pawnio, "is_admin", return_value=True), \
        mock.patch.object(pawnio, "_open_device", side_effect=lambda: next(handles)), \
        mock.patch.object(pawnio, "_ioctl", side_effect=fake_ioctl), \
        mock.patch.object(pawnio, "_close_handle", side_effect=lambda h: log.append(("close", h))):
    drv = pawnio.Driver()
    assert log[0][:4] == (100, pawnio.IOCTL_VERSION, b"", 4), log[0]
    blob = pawnio.module_bytes("AMDFamily17")
    h = drv.load(blob)
    assert h == 200 and log[-1][:4] == (200, pawnio.IOCTL_LOAD_BINARY, blob, 0), log[-1][:2]
    assert drv.execute(h, "ioctl_read_msr", [0xC0010015], 2) == [0x2A, 0xFFFFFFFFFFFFFFFF]
    last = log[-1]
    assert last[:4] == (200, pawnio.IOCTL_EXECUTE_FN,
                        pawnio.pack_execute("ioctl_read_msr", [0xC0010015]), 16), last[:4]
    assert "ioctl_read_msr" in last[4] and "IOCTL_PIO_EXECUTE_FN" in last[4], last[4]
    raises(pawnio.PawnIOError, "returned", drv.execute, h, "ioctl_read_msr", [1], 4)
    mod = drv.open_module("AMDFamily17")
    assert log[-1][:4] == (300, pawnio.IOCTL_LOAD_BINARY, blob, 0)
    assert mod.call("ioctl_read_smn", [0x59800], 1) == [0x2A]
    raises(pawnio.PawnIOError, "ioctl_read_pm_table", mod.call, "ioctl_read_pm_table", [], 1)
    drv.close(200)
    assert log[-1] == ("close", 200)
    drv.close()
    assert {("close", 100), ("close", 300)} <= set(map(tuple, log[-2:]))
print("load, execute, close ok")

# ---- DeviceIoControl failure text names the function and the Win32 message ----
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = ctypes.c_void_p
k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
k32.CloseHandle.argtypes = [ctypes.c_void_p]
nul = k32.CreateFileW("NUL", 0xC0000000, 3, None, 3, 0, None)
e = raises(pawnio.PawnIOError, "DeviceIoControl", pawnio._ioctl, nul,
           pawnio.IOCTL_VERSION, b"", 4, "IOCTL_PIO_VERSION")
assert "IOCTL_PIO_VERSION" in str(e) and e.code, (str(e), e.code)
k32.CloseHandle(ctypes.c_void_p(nul))
print("ioctl failure text ok:", e)

# ---- bus mutex helper ----
for name, want in ((pawnio.MUTEX_SMBUS, r"Global\Access_SMBUS.HTP.Method"),
                   (pawnio.MUTEX_ISABUS, r"Global\Access_ISABUS.HTP.Method"),
                   (pawnio.MUTEX_PCI, r"Global\Access_PCI")):
    assert name == want, name
M = r"Local\wintools_test_pawnio_mutex"
held, release, result = threading.Event(), threading.Event(), {}


def holder():
    with pawnio.bus_lock(M, 2000):
        held.set()
        release.wait(5)


t = threading.Thread(target=holder)
t.start()
assert held.wait(5)
t0 = time.monotonic()
e = raises(pawnio.PawnIOError, "timed out", pawnio.bus_lock(M, 150).__enter__)
assert M in str(e) and 0.1 < time.monotonic() - t0 < 2, (str(e), time.monotonic() - t0)
release.set()
t.join()
with pawnio.bus_lock(M, 500):
    pass
with pawnio.bus_lock(M, 500):       # released: acquirable again
    pass
for real in (pawnio.MUTEX_SMBUS, pawnio.MUTEX_ISABUS, pawnio.MUTEX_PCI):
    with pawnio.bus_lock(real, 500):
        pass
print("mutex helper ok: acquire, release, timeout error")

# ---- thread pinning ----
k32.GetCurrentProcessorNumber.restype = ctypes.c_uint32


class GroupAffinity(ctypes.Structure):
    _fields_ = [("Mask", ctypes.c_size_t), ("Group", ctypes.c_uint16),
                ("Reserved", ctypes.c_uint16 * 3)]


def affinity():
    ga = GroupAffinity()
    k32.GetCurrentThread.restype = ctypes.c_void_p
    assert k32.GetThreadGroupAffinity(ctypes.c_void_p(k32.GetCurrentThread()), ctypes.byref(ga))
    return ga.Group, ga.Mask


before = affinity()
last = bin(before[1]).count("1") - 1
for cpu in (0, 1, 5, last):
    with pawnio.pin_thread(cpu):
        for _ in range(20):
            assert k32.GetCurrentProcessorNumber() == cpu
        assert affinity() == (0, 1 << cpu)
    assert affinity() == before
raises(pawnio.PawnIOError, "cpu", pawnio.pin_thread(4096).__enter__)
print("pin_thread ok, affinity restored", before)

# ====================================================================
#  the probe: collectors against simulated devices
# ====================================================================
spec = importlib.util.spec_from_file_location("hw_probe", ROOT / "tools" / "hw_probe.py")
hw = importlib.util.module_from_spec(spec)
sys.modules["hw_probe"] = hw
spec.loader.exec_module(hw)

lock_names = []


@contextlib.contextmanager
def fake_lock(name):
    lock_names.append(name)
    yield


def nak():
    return pawnio.PawnIOError("DeviceIoControl IOCTL_PIO_EXECUTE_FN ioctl_smbus_xfer: "
                              "The device is not ready.", 21)


class Spd5Hub:
    def __init__(self, data, mr11=0x00):
        assert len(data) == 1024
        self.data, self.mr = data, {0: 0x51, 1: 0x18, 2: 0x00, 0x0B: mr11}
        self.fail_at = None

    def read(self, cmd):
        if cmd < 0x80:
            return self.mr.get(cmd, 0)
        index = (self.mr[0x0B] & 7) * 128 + cmd - 0x80
        if index == self.fail_at:
            raise nak()
        return self.data[index]

    def write(self, cmd, value):
        assert cmd == 0x0B, f"unexpected hub write to register {cmd:#x}"
        self.mr[0x0B] = value


class Ee1004:
    def __init__(self, data):
        assert len(data) == 512
        self.data = data


class FakeBus:
    def __init__(self, devices, ee_page=0):
        self.devices, self.ee_page, self.writes = devices, ee_page, []
        self.has_ee = any(isinstance(d, Ee1004) for d in devices.values())

    def call(self, fn, inputs, n_out):
        if fn != "ioctl_smbus_xfer":
            raise AssertionError(fn)
        addr, rw, cmd, proto, *rest = inputs
        assert rw in (0, 1) and 0 <= addr <= 0x7F and len(inputs) >= 4
        if rw == 1:
            assert n_out >= 1, "a read needs an output cell"
            if proto == 1 and addr in (0x36, 0x37) and self.has_ee:
                if self.ee_page == addr - 0x36:
                    return [0]
                raise nak()
            dev = self.devices.get(addr)
            if dev is None or proto != 2:
                raise nak()
            if isinstance(dev, Ee1004):
                return [dev.data[self.ee_page * 256 + cmd]]
            return [dev.read(cmd)]
        assert len(inputs) >= 5, "a write needs the data cell"
        self.writes.append((addr, cmd, proto, rest[0]))
        if proto == 1 and addr in (0x36, 0x37) and self.has_ee:
            self.ee_page = addr - 0x36
            return []
        dev = self.devices.get(addr)
        if isinstance(dev, Spd5Hub) and proto == 2:
            dev.write(cmd, rest[0])
            return []
        raise AssertionError(f"unexpected write {inputs}")


def pattern(n, seed):
    return bytes((i * 7 + seed + (i >> 8)) & 0xFF for i in range(n))


# ---- SPD: two DDR5 hubs ----
d5a, d5b = pattern(1024, 1), pattern(1024, 9)
bus = FakeBus({0x50: Spd5Hub(d5a), 0x52: Spd5Hub(d5b, mr11=0x08)})
writes = []
lock_names.clear()
r = hw.collect_spd(bus.call, fake_lock, writes)
assert sorted(r["devices"]) == ["0x50", "0x52"] and len(r["absent"]) == 6, r
for key, data in (("0x50", d5a), ("0x52", d5b)):
    dev = r["devices"][key]
    assert dev["kind"] == "spd5_hub" and dev["mr0_mr1"] == [0x51, 0x18], dev
    assert dev["bytes_hex"] == data.hex() and dev["error"] is None
assert r["devices"]["0x52"]["mr11_before"] == 0x08 and r["devices"]["0x52"]["mr11_after"] == 0x08
assert r["devices"]["0x50"]["mr11_after"] == 0x00
assert bus.devices[0x50].mr[0x0B] == 0x00 and bus.devices[0x52].mr[0x0B] == 0x08
# writes: page 1..7 then back to 0, MR11 only, on the two hubs only, all logged
assert len(bus.writes) == 16 and {(a, c, p) for a, c, p, _ in bus.writes} == {
    (0x50, 0x0B, 2), (0x52, 0x0B, 2)}, bus.writes
assert [v for a, _, _, v in bus.writes if a == 0x50] == [1, 2, 3, 4, 5, 6, 7, 0]
assert [v for a, _, _, v in bus.writes if a == 0x52] == [9, 10, 11, 12, 13, 14, 15, 8]
assert len(writes) == 16 and all(w["module"] == "smbus" and w["fn"] == "ioctl_smbus_xfer"
                                 for w in writes), writes[:2]
assert set(lock_names) == {pawnio.MUTEX_SMBUS}
print("spd5 hubs ok: 1024 bytes each, MR11 restored to page 0, 16 logged page-select writes")

# hub left on page 3 by another tool: read from page 0, restore page 0
bus = FakeBus({0x50: Spd5Hub(d5a, mr11=0x03)})
r = hw.collect_spd(bus.call, fake_lock, [])
assert r["devices"]["0x50"]["bytes_hex"] == d5a.hex()
assert bus.devices[0x50].mr[0x0B] == 0x00 and r["devices"]["0x50"]["mr11_before"] == 3
# a failing byte: the error is recorded and the page is still restored
hub = Spd5Hub(d5a)
hub.fail_at = 3 * 128 + 5
bus = FakeBus({0x50: hub})
r = hw.collect_spd(bus.call, fake_lock, [])
dev = r["devices"]["0x50"]
assert dev["error"] and "page 3" in dev["error"] and hub.mr[0x0B] == 0x00, dev
assert dev["mr11_after"] == 0x00 and dev["bytes_hex"] == d5a[:3 * 128 + 5].hex()
# reserved bits in MR11: nothing is written and no page is read
bus = FakeBus({0x50: Spd5Hub(d5a, mr11=0x10)})
r = hw.collect_spd(bus.call, fake_lock, [])
dev = r["devices"]["0x50"]
assert "reserved" in dev["error"] and dev["bytes_hex"] == "" and not bus.writes, dev
print("spd5 odd page and mid-read failure ok")

# ---- SPD: two DDR4 EE1004 ----
d4a, d4b = pattern(512, 3), pattern(512, 5)
ddr4 = [bytearray(d4a), bytearray(d4b)]
for d in ddr4:
    d[0], d[1], d[2] = 0x23, 0x11, 0x0C
bus = FakeBus({0x51: Ee1004(bytes(ddr4[0])), 0x53: Ee1004(bytes(ddr4[1]))})
writes = []
r = hw.collect_spd(bus.call, fake_lock, writes)
assert sorted(r["devices"]) == ["0x51", "0x53"]
for key, data in (("0x51", ddr4[0]), ("0x53", ddr4[1])):
    dev = r["devices"][key]
    assert dev["kind"] == "ee1004" and dev["bytes_hex"] == bytes(data).hex(), dev
    assert dev["page_before"] == 0 and dev["page_after"] == 0 and dev["error"] is None
assert bus.writes == [(0x37, 0x00, 1, 0), (0x36, 0x00, 1, 0)], bus.writes
assert bus.ee_page == 0 and len(writes) == 2
# page left at 1 by another tool: select 0, read, select 1, read, back to 0
bus = FakeBus({0x51: Ee1004(bytes(ddr4[0]))}, ee_page=1)
r = hw.collect_spd(bus.call, fake_lock, [])
assert r["devices"]["0x51"]["bytes_hex"] == bytes(ddr4[0]).hex()
assert r["devices"]["0x51"]["page_before"] == 1 and bus.ee_page == 0
assert [w[0] for w in bus.writes] == [0x36, 0x37, 0x36], bus.writes
print("ee1004 ok: 512 bytes each, page select 0x37 then 0x36, restored to page 0")

# ---- SPD: nothing there, and an unidentified responder ----
bus = FakeBus({})
writes = []
r = hw.collect_spd(bus.call, fake_lock, writes)
assert r["devices"] == {} and len(r["absent"]) == 8 and not writes and not bus.writes


class Odd:
    def read(self, cmd):
        return 0xAB if cmd == 0 else cmd


bus = FakeBus({0x54: Odd()})
r = hw.collect_spd(bus.call, fake_lock, [])
dev = r["devices"]["0x54"]
assert dev["kind"] == "unidentified" and len(dev["bytes_hex"]) == 32 and not bus.writes, dev
print("no devices and unidentified responder ok: no writes")

# ---- SPD write guard ----
sb = hw.SpdBus(FakeBus({0x50: Spd5Hub(d5a)}).call, fake_lock, [])
raises(hw.WriteRefused, "0x50", sb.select_spd5_page, 0x50, 0x01)
raises(hw.WriteRefused, "EE1004", sb.select_ee_page, 1)
sb.identify_hub(0x50)
raises(hw.WriteRefused, "0x51", sb.select_spd5_page, 0x51, 0x01)
raises(hw.WriteRefused, "MR11", sb.select_spd5_page, 0x50, 0x10)
sb.select_spd5_page(0x50, 0x01)
sb.identify_ee1004()
raises(hw.WriteRefused, "page", sb.select_ee_page, 2)
print("spd write guard ok")


# ---- SuperIO: a Nuvoton-style chip at 0x2E, nothing at 0x4E ----
class FakeSio:
    def __init__(self, regs, chip_port=0x2E):
        self.regs, self.chip_port = bytearray(regs), chip_port
        self.port, self.config, self.seq, self.index, self.writes = None, False, [], 0, []

    def call(self, fn, inputs, n_out):
        if fn == "ioctl_select_slot":
            self.port, self.config, self.seq = {0: 0x2E, 1: 0x4E}[inputs[0]], False, []
            return []
        if self.port is None:
            raise pawnio.PawnIOError("ioctl: The device is not ready.", 21)
        if fn == "ioctl_pio_outb":
            port, val = inputs
            assert port in (self.port, self.port + 1), hex(port)
            self.writes.append((port, val))
            if self.port != self.chip_port:
                return []
            if port == self.port and not self.config:
                self.seq = self.seq + [val] if self.seq == [0x87][:len(self.seq)] else [val]
                if self.seq == [0x87, 0x87]:
                    self.config, self.seq = True, []
            elif port == self.port:
                if val == 0xAA:
                    self.config = False
                else:
                    self.index = val
            else:
                assert self.config
                self.regs[self.index] = val
            return []
        if fn == "ioctl_superio_inb":
            reg = inputs[0] & 0xFF
            return [self.regs[reg] if self.port == self.chip_port and self.config else 0xFF]
        raise AssertionError(fn)


regs = bytearray(pattern(256, 11))
regs[0x20], regs[0x21] = 0xD8, 0x02
sio = FakeSio(regs)
writes = []
lock_names.clear()
r = hw.collect_lpcio(sio.call, fake_lock, writes)
s0, s1 = r["slots"]["0x2E"], r["slots"]["0x4E"]
assert s0["family"] == "winbond" and s0["id_word"] == 0xD802 and s0["regs_hex"] == bytes(regs).hex()
assert s1["family"] is None and [t["family"] for t in s1["tries"]] == ["winbond", "ite"]
assert all(t["id_word"] == 0xFFFF for t in s1["tries"])
assert sio.writes == [(0x2E, 0x87), (0x2E, 0x87), (0x2E, 0xAA),
                      (0x4E, 0x87), (0x4E, 0x87), (0x4E, 0xAA),
                      (0x4E, 0x87), (0x4E, 0x01), (0x4E, 0x55), (0x4E, 0xAA),
                      (0x4E, 0x02), (0x4F, 0x02)], sio.writes
assert [(w["inputs"][0], w["inputs"][1]) for w in writes] == sio.writes
assert all(w["module"] == "lpcio" and w["fn"] == "ioctl_pio_outb" for w in writes)
assert not sio.config and sio.regs == regs, "config mode left open or register changed"
assert set(lock_names) == {pawnio.MUTEX_ISABUS}
print("lpcio ok: chip id 0xD802 at 0x2E, config mode entered and exited, 12 logged key writes")



# ---- SuperIO with --hwm: logical devices and hardware monitor banks ----
class FakeSioHwm(FakeSio):
    def __init__(self, regs, ldn_regs, bank_regs, base=0x290, vendor=(0x5C, 0xA3)):
        super().__init__(regs)
        self.ldn, self.bank, self.base, self.vendor = 0x05, 0x03, base, vendor
        self.ldn_regs, self.bank_regs = ldn_regs, bank_regs
        self.bars_found, self.hwm_index, self.hwm_writes = False, 0, []

    def call(self, fn, inputs, n_out):
        if fn == "ioctl_find_bars":
            assert self.config, "find_bars outside configuration mode"
            self.bars_found, self.ldn = True, 0xFE
            return []
        if fn == "ioctl_superio_outb":
            assert self.config and inputs[0] == 0x07, f"unexpected SuperIO write {inputs}"
            self.ldn = inputs[1]
            return []
        if fn == "ioctl_superio_inb" and self.port == self.chip_port and self.config:
            reg = inputs[0] & 0xFF
            if reg == 0x07:
                return [self.ldn]
            if reg >= 0x30:
                return [self.ldn_regs.get(self.ldn, bytes(256))[reg]]
        if fn in ("ioctl_pio_outb", "ioctl_pio_inb") and inputs[0] in (self.base + 5, self.base + 6):
            assert self.bars_found, "HWM port used before find_bars"
            return self.hwm(fn, inputs)
        return super().call(fn, inputs, n_out)

    def hwm(self, fn, inputs):
        data_port = inputs[0] == self.base + 6
        if fn == "ioctl_pio_outb":
            if not data_port:
                self.hwm_index = inputs[1]
                return []
            assert self.hwm_index == 0x4E, f"unexpected HWM write to register {self.hwm_index:#x}"
            self.bank = inputs[1]
            self.hwm_writes.append(inputs[1])
            return []
        assert data_port
        if self.hwm_index == 0x4E:
            return [self.bank]
        if self.hwm_index == 0x4F:
            return [self.vendor[0] if self.bank & 0x80 else self.vendor[1]]
        return [self.bank_regs[self.bank & 0x7F][self.hwm_index]]


ldn_regs = {n: bytes(pattern(256, 40 + n)) for n in range(0x20)}
ldn_regs[0x0B] = bytes(ldn_regs[0x0B][:0x60]) + b"\x02\x90" + bytes(ldn_regs[0x0B][0x62:])
bank_regs = [bytearray(pattern(256, 70 + b)) for b in range(16)]
for b, bank in enumerate(bank_regs):
    bank[0x4E], bank[0x4F] = b, 0xA3
sio = FakeSioHwm(regs, ldn_regs, bank_regs)
writes = []
r = hw.collect_lpcio(sio.call, fake_lock, writes, hwm=True)
h = r["slots"]["0x2E"]["hwm"]
assert "hwm" not in r["slots"]["0x4E"]
assert h["base"] == 0x290 and h["vendor_id"] == 0x5CA3 and h["ldn_before"] == 0x05 and \
    h["bank_before"] == 0x03, h
for n in range(0x20):
    assert h["ldn"][f"0x{n:X}"] == ldn_regs[n][0x30:].hex(), n
for b in range(16):
    assert h["banks"][f"0x{b:X}"] == bytes(bank_regs[b]).hex(), b
assert sio.ldn == 0x05 and sio.bank == 0x03 and not sio.config, "state not restored"
assert sio.hwm_writes == [0x80, 0x00, *range(16), 0x03], sio.hwm_writes
assert {w["fn"] for w in writes} == {"ioctl_pio_outb", "ioctl_superio_outb", "ioctl_find_bars"}
so = [w for w in writes if w["fn"] == "ioctl_superio_outb"]
assert len(so) == 0x20 + 1 and all(w["inputs"][0] == 0x07 for w in so)
assert sum("HWM bank select" in w["reason"] for w in writes) == 2 + 16 + 1
assert any("index-port writes" in w["reason"] for w in writes)
# a chip that is not Nuvoton / Winbond: no bank dump, bank select still restored
sio = FakeSioHwm(regs, ldn_regs, bank_regs, vendor=(0x12, 0x34))
r = hw.collect_lpcio(sio.call, fake_lock, [], hwm=True)
h = r["slots"]["0x2E"]["hwm"]
assert "banks" not in h and "vendor id 0x1234" in h["error"] and sio.bank == 0x03
assert sio.hwm_writes == [0x80, 0x00, 0x03], sio.hwm_writes
print("lpcio --hwm ok: LDN and bank select restored, only bank selects written")

# ---- the probe never calls a hardware-writing function it was not approved for ----
src = (ROOT / "tools" / "hw_probe.py").read_text(encoding="utf-8")
for fn in ("ioctl_write_msr", "ioctl_write_smu_register", "ioctl_send_smu_command",
           "ioctl_piix4_port_sel", "ioctl_clock_freq", "ioctl_set_sleep_mode",
           "ioctl_write_protection", "ioctl_read_qword", "ioctl_read_smu_register"):
    assert fn not in src, f"hw_probe.py references {fn}"
print("no unapproved write function is referenced")

# ---- AMD MSRs, SMN, UMC, SMU against simulated modules ----
k32.GetCurrentProcessorNumber.restype = ctypes.c_uint32
DENIED = pawnio.PawnIOError("DeviceIoControl IOCTL_PIO_EXECUTE_FN ioctl_read_msr: "
                            "Access is denied.", 5)


def amd_msr_call(fn, inputs, n_out):
    assert fn == "ioctl_read_msr" and n_out == 1
    if inputs[0] == 0xC0010062:
        raise DENIED
    return [(k32.GetCurrentProcessorNumber() << 32) | inputs[0]]


for want in (0xC0010015, 0xC0010061, 0xC0010062, 0xC0010063, 0xC0010293,
             *range(0xC0010064, 0xC001006C)):
    assert want in hw.AMD_MSRS, hex(want)
assert hw.AMD_PERF_MSRS == (0xC00000E7, 0xC00000E8)
slept = []
r = hw.collect_amd_msr(amd_msr_call, [0, 2, 4], sleep=slept.append)
assert sorted(r["cores"]) == ["0", "2", "4"] and slept == [0.1], (list(r["cores"]), slept)
for cpu in (0, 2, 4):
    got = r["cores"][str(cpu)]
    assert got["0xC0010015"] == (cpu << 32) | 0xC0010015, (cpu, got)
    assert "0xC0010062" not in got
    assert r["perf"][str(cpu)] == {"mperf": [(cpu << 32) | 0xC00000E7] * 2,
                                   "aperf": [(cpu << 32) | 0xC00000E8] * 2}
assert [(e["core"], e["addr"]) for e in r["errors"]] == [(0, "0xC0010062"), (2, "0xC0010062"),
                                                         (4, "0xC0010062")]
assert "Access is denied" in r["errors"][0]["error"] and isinstance(r["perf_interval_ns"], int)
print("amd msr ok: per-core pinned reads, denied MSR recorded, MPERF/APERF twice")


def smn_call(fn, inputs, n_out):
    assert fn == "ioctl_read_smn" and n_out == 1
    if inputs[0] == 0x50010:
        raise pawnio.PawnIOError("DeviceIoControl ioctl_read_smn: The device is not ready.", 21)
    return [inputs[0] ^ 0x5A5A5A5A]


lock_names.clear()
r = hw.collect_amd_smn(smn_call, fake_lock)
assert r["thm_tcon_cur_tmp"] == {"addr": "0x00059800", "value": 0x59800 ^ 0x5A5A5A5A}
assert [c["addr"] for c in r["ccd_temps"]] == [f"0x{0x59954 + 4 * i:08X}" for i in range(12)]
assert set(lock_names) == {pawnio.MUTEX_PCI}
lock_names.clear()
r = hw.collect_amd_umc(smn_call, fake_lock)
b0, b1 = r["blocks"]
assert (b0["base"], b0["end"]) == ("0x00050000", "0x000502FF") and len(b0["dwords"]) == 192
assert (b1["base"], b1["end"]) == ("0x00150000", "0x001502FF") and len(b1["dwords"]) == 192
assert b0["dwords"][4] is None and b0["error_count"] == 1 and b1["error_count"] == 0
assert b0["dwords"][5] == 0x50014 ^ 0x5A5A5A5A and "not ready" in b0["errors"][0]["error"]
assert set(lock_names) == {pawnio.MUTEX_PCI}
print("amd smn and umc ok")

smu_log = []


def smu_call(fn, inputs, n_out):
    smu_log.append((fn, n_out))
    return {"ioctl_resolve_pm_table": [0x540004, 0x7FFF0000], "ioctl_update_pm_table": [],
            "ioctl_get_code_name": [27], "ioctl_get_smu_version": [0x00540000],
            "ioctl_read_pm_table": [(0x22222222 << 32) | 0x11111111] * n_out}[fn]


@contextlib.contextmanager
def tracking_lock(name):
    smu_log.append(("lock", name))
    try:
        yield
    finally:
        smu_log.append(("unlock", name))


r = hw.collect_amd_smu(smu_call, tracking_lock)
assert r["code_name"] == 27 and r["smu_version"] == 0x540000
assert r["pm_table_version"] == 0x540004 and r["pm_table_base"] == 0x7FFF0000
assert r["pm_table_dwords"] == [0x11111111, 0x22222222] * 512
order = [e[0] for e in smu_log if e[0].startswith("ioctl_")]
assert order == ["ioctl_get_code_name", "ioctl_get_smu_version", "ioctl_resolve_pm_table",
                 "ioctl_update_pm_table", "ioctl_read_pm_table"], order
# the mailbox commands run under the PCI mutex, the table read does not
depth, inside = 0, {}
for e in smu_log:
    if e[0] == "lock":
        assert e[1] == pawnio.MUTEX_PCI
        depth += 1
    elif e[0] == "unlock":
        depth -= 1
    else:
        inside[e[0]] = depth
assert inside["ioctl_get_smu_version"] == inside["ioctl_resolve_pm_table"] == 1
assert inside["ioctl_update_pm_table"] == 1 and inside["ioctl_read_pm_table"] == 0
print("amd smu ok: mailbox commands under the PCI mutex")


# ---- Intel MSR and MCHBAR ----
def intel_call(fn, inputs, n_out):
    if fn == "ioctl_read_msr":
        if inputs[0] == 0x199:
            raise DENIED
        return [(k32.GetCurrentProcessorNumber() << 32) | inputs[0]]
    if fn == "ioctl_get_mchbar_addr":
        return [0xFEDC0000]
    if fn == "ioctl_read_dword":
        if inputs[0] >= 0x8000:
            raise pawnio.PawnIOError("DeviceIoControl ioctl_read_dword: Access is denied.", 5)
        return [inputs[0] ^ 0xA5A5]
    raise AssertionError(fn)


for want in (0xCE, 0x198, 0x199, 0x1A2, 0x19C, 0x1B1, 0x606, 0x611):
    assert want in hw.INTEL_MSRS, hex(want)
assert hw.INTEL_PERF_MSRS == (0xE7, 0xE8)
r = hw.collect_intel_msr(intel_call, [0, 2], sleep=lambda s: None)
assert r["cores"]["2"]["0xCE"] == (2 << 32) | 0xCE and "0x199" not in r["cores"]["2"]
assert [e["addr"] for e in r["errors"]] == ["0x199", "0x199"]
assert r["perf"]["0"]["mperf"] == [(0 << 32) | 0xE7] * 2
r = hw.collect_intel_mchbar(intel_call)
assert r["mchbar_addr"] == 0xFEDC0000
w0, w1 = r["windows"]
assert w0["base"] == "0x00004000" and len(w0["dwords"]) == 1024 and w0["error_count"] == 0
assert w0["dwords"][3] == (0x4000 + 12) ^ 0xA5A5
assert w1["base"] == "0x0000D800" and w1["error_count"] == len(w1["dwords"]) == 1536
print("intel msr and mchbar ok")

# ---- TSC measured against QueryPerformanceCounter ----
r = hw.collect_tsc()
assert 0.24 < r["qpc_delta"] / r["qpf"] < 0.30, r
assert 1.0e9 < r["tsc_hz"] < 8.0e9 and r["tsc_delta"] > 0, r
print(f"tsc ok: {r['tsc_hz'] / 1e6:.1f} MHz")

# ---- the probe end to end, dry run ----
out = SCRATCH / "dry.json"
cp = subprocess.run([PYTHON, str(ROOT / "tools" / "hw_probe.py"), "--dry-run", "--out", str(out)],
                    capture_output=True, text=True, cwd=ROOT, timeout=120)
assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
dump = json.loads(out.read_text(encoding="utf-8"))
for key in ("schema", "computer", "created", "elevated", "dry_run", "args", "writes", "sections"):
    assert key in dump, key
assert dump["schema"] == 1 and dump["dry_run"] is True and dump["writes"] == []
assert dump["elevated"] is pawnio.is_admin()
names = list(dump["sections"])
assert names == ["identity", "topology", "tsc", "driver", "amd_msr", "amd_smn", "amd_umc",
                 "amd_smu", "intel_msr", "intel_mchbar", "smbus_spd", "lpcio"], names
for name, sec in dump["sections"].items():
    assert sec["status"] in ("ok", "error", "skipped") and "detail" in sec and "data" in sec, name
for name in ("identity", "topology", "tsc"):
    assert dump["sections"][name]["status"] == "ok", (name, dump["sections"][name])
ident = dump["sections"]["identity"]["data"]
assert ident["vendor"] == "AuthenticAMD" and "brand" in ident and ident["family"] is not None
for name in ("driver", "amd_msr", "amd_smn", "amd_umc", "smbus_spd", "lpcio"):
    sec = dump["sections"][name]
    if pawnio.is_admin():
        assert sec["status"] in ("skipped", "error"), (name, sec)
    else:
        assert sec["status"] == "error" and sec["detail"] == ADMIN_MSG, (name, sec)
assert dump["sections"]["amd_smu"]["status"] == "skipped" and \
    "--smu" in dump["sections"]["amd_smu"]["detail"]
for name in ("intel_msr", "intel_mchbar"):
    assert dump["sections"][name]["status"] == "skipped" and \
        "GenuineIntel" in dump["sections"][name]["detail"]
lines = [ln for ln in cp.stdout.splitlines() if ln.split(" ")[0] in names]
assert [ln.split(" ")[0] for ln in lines] == names, cp.stdout
print("probe dry run ok:")
print(cp.stdout)

# the opt-in flags are recorded and lift the amd_smu skip (this shell then reports the admin error)
out2 = SCRATCH / "dry_flags.json"
cp = subprocess.run([PYTHON, str(ROOT / "tools" / "hw_probe.py"), "--dry-run", "--smu", "--hwm",
                     "--out", str(out2)], capture_output=True, text=True, cwd=ROOT, timeout=120)
assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
dump2 = json.loads(out2.read_text(encoding="utf-8"))
assert dump2["args"] == {"smu": True, "hwm": True} and dump2["writes"] == []
if not pawnio.is_admin():
    assert dump2["sections"]["amd_smu"]["status"] == "error"
    assert dump2["sections"]["amd_smu"]["detail"] == ADMIN_MSG
print("dry run with --smu --hwm ok")

shutil.rmtree(SCRATCH, ignore_errors=True)
print("STATUS: SUCCESS")
