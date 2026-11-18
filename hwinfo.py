#!/usr/bin/env python3
"""hwinfo.py - Windows-exposed hardware readouts for wintools's Hardware tab,
all unelevated: CPUID through an executable thunk, logical processor and cache
topology, PDH core clocks, SetupAPI PCI properties, DXGI adapters, NVIDIA
clocks and limits, Windows / DirectX versions and CPU microcode."""

import contextlib
import ctypes
import ctypes.wintypes as wt
import functools
import re
import shutil
import winreg
from typing import NamedTuple

import gpu


class HwError(OSError):
    pass


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.VirtualAlloc.restype = ctypes.c_void_p
_k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
_k32.GetCurrentThread.restype = ctypes.c_void_p
_k32.SetThreadAffinityMask.restype = ctypes.c_size_t
_k32.SetThreadAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
_k32.GetLogicalProcessorInformationEx.restype = wt.BOOL
_k32.GetLogicalProcessorInformationEx.argtypes = [
    wt.DWORD, ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]


def _winerror(what):
    err = ctypes.get_last_error()
    return HwError(0, f"{what}: {ctypes.FormatError(err).strip()}", None, err)


# ====================================================================
#  CPUID
# ====================================================================

# Windows x64 convention: leaf in ECX, sub-leaf in EDX, result pointer in R8.
# RBX is callee-saved and CPUID clobbers it.
_CPUID_CODE = bytes.fromhex(
    "53"            # push rbx
    "89c8"          # mov eax, ecx
    "89d1"          # mov ecx, edx
    "0fa2"          # cpuid
    "418900"        # mov [r8], eax
    "41895804"      # mov [r8+4], ebx
    "41894808"      # mov [r8+8], ecx
    "4189500c"      # mov [r8+12], edx
    "5b"            # pop rbx
    "c3")           # ret


@functools.cache
def _thunk():
    addr = _k32.VirtualAlloc(None, len(_CPUID_CODE), 0x3000, 0x40)
    if not addr:
        raise _winerror("VirtualAlloc for the CPUID thunk")
    ctypes.memmove(addr, _CPUID_CODE, len(_CPUID_CODE))
    return ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)(addr)


def cpuid(leaf, subleaf=0):
    out = (ctypes.c_uint32 * 4)()
    _thunk()(leaf, subleaf, ctypes.addressof(out))
    return tuple(out)


@contextlib.contextmanager
def pinned(cpu):
    if not 0 <= cpu < 64:
        raise HwError(f"cpu {cpu}: only processor group 0 can be pinned")
    thread = _k32.GetCurrentThread()
    prev = _k32.SetThreadAffinityMask(thread, 1 << cpu)
    if not prev:
        raise _winerror(f"SetThreadAffinityMask(cpu {cpu})")
    try:
        yield
    finally:
        if not _k32.SetThreadAffinityMask(thread, prev):
            raise _winerror("SetThreadAffinityMask restore")


class Identity(NamedTuple):
    vendor: str
    brand: str
    family: int
    model: int
    stepping: int
    ext_family: int
    ext_model: int


def decode_signature(eax):
    # Family, model and stepping as CPU-Z shows them; the extended pair has the
    # extension fields folded in.
    stepping, model, family = eax & 0xF, (eax >> 4) & 0xF, (eax >> 8) & 0xF
    ext_model_bits, ext_family_bits = (eax >> 16) & 0xF, (eax >> 20) & 0xFF
    ext_family = family + ext_family_bits if family == 0xF else family
    ext_model = (ext_model_bits << 4) + model if family in (6, 0xF) else model
    return family, model, stepping, ext_family, ext_model


def hex_id(value):
    return f"{value:X}"


def _regs_text(*regs):
    return b"".join(r.to_bytes(4, "little") for r in regs).decode("ascii", "replace")


def identity():
    _, ebx, ecx, edx = cpuid(0)
    vendor = _regs_text(ebx, edx, ecx)
    if cpuid(0x80000000)[0] < 0x80000004:
        raise HwError("CPUID brand string leaves 0x80000002-4 are not implemented")
    brand = "".join(_regs_text(*cpuid(leaf)) for leaf in (0x80000002, 0x80000003, 0x80000004))
    fam, model, step, ext_fam, ext_model = decode_signature(cpuid(1)[0])
    return Identity(vendor, brand.strip("\0 "), fam, model, step, ext_fam, ext_model)


def format_instructions(vendor, read):
    amd = vendor == "AuthenticAMD"
    max_leaf, max_ext = read(0)[0], read(0x80000000)[0]
    _, _, c1, d1 = read(1)
    b7 = read(7, 0)[1] if max_leaf >= 7 else 0
    _, _, ec1, ed1 = read(0x80000001) if max_ext >= 0x80000001 else (0, 0, 0, 0)
    avx = bool(c1 >> 28 & 1 and c1 >> 27 & 1)   # AVX and OSXSAVE
    out = []
    if d1 >> 23 & 1:
        out.append("MMX(+)" if amd and ed1 >> 22 & 1 else "MMX")
    # CPU-Z 2.15 groups the SSE levels and lists SSSE3 on its own
    sse = [v for v, ok in (("1", d1 >> 25 & 1), ("2", d1 >> 26 & 1), ("3", c1 & 1),
                           ("4.1", c1 >> 19 & 1), ("4.2", c1 >> 20 & 1),
                           ("4A", amd and ec1 >> 6 & 1)) if ok]
    if sse:
        out.append(f"SSE ({', '.join(sse)})")
    for name, ok in (("SSSE3", c1 >> 9 & 1),
                     ("x86-64" if amd else "EM64T", ed1 >> 29 & 1),
                     ("AMD-V", amd and ec1 >> 2 & 1), ("VT-x", not amd and c1 >> 5 & 1),
                     ("AES", c1 >> 25 & 1), ("AVX", avx),
                     ("AVX2", avx and b7 >> 5 & 1), ("AVX512", avx and b7 >> 16 & 1),
                     ("FMA3", avx and c1 >> 12 & 1), ("SHA", b7 >> 29 & 1)):
        if ok:
            out.append(name)
    return ", ".join(out)


def instructions():
    return format_instructions(identity().vendor, cpuid)


def thunk_status():
    if not cpuid(0)[1]:
        raise HwError("CPUID leaf 0 returned no vendor string")
    return "OK"


# ====================================================================
#  TOPOLOGY AND CACHES  (GetLogicalProcessorInformationEx)
# ====================================================================

RELATION_CORE, RELATION_NUMA, RELATION_CACHE, RELATION_PACKAGE, RELATION_ALL = (
    0, 1, 2, 3, 0xFFFF)
CACHE_KINDS = {0: "unified", 1: "instruction", 2: "data", 3: "trace"}
FULLY_ASSOCIATIVE = 0xFF
ERROR_INSUFFICIENT_BUFFER = 122


class Core(NamedTuple):
    group: int
    mask: int
    logical: tuple      # logical processor numbers, group * 64 + bit


class Package(NamedTuple):
    logical: tuple


class Cache(NamedTuple):
    level: int
    kind: str
    associativity: int
    line: int
    size: int
    logical: tuple


class CacheGroup(NamedTuple):
    count: int
    size: int
    associativity: int
    line: int


class CacheInfo(NamedTuple):
    summary: str        # count x size per slice group
    size: str           # size per cache; slices joined when they differ
    ways: str
    descriptor: str


class Topology(NamedTuple):
    cores: list
    packages: list
    caches: list
    numa: dict          # node number -> [(processor group, affinity mask)]

    @property
    def threads(self):
        return sum(len(c.logical) for c in self.cores)

    def package_cores(self, i):
        mine = set(self.packages[i].logical)
        return sum(1 for c in self.cores if c.logical[0] in mine)

    def package_threads(self, i):
        return len(self.packages[i].logical)


def _bits(group, mask):
    return tuple(group * 64 + b for b in range(64) if mask >> b & 1)


def _spans(rec, count_off, mask_off):
    # the GROUP_AFFINITY array of a record: [(group, mask)]
    count = max(int.from_bytes(rec[count_off:count_off + 2], "little"), 1)
    return [(int.from_bytes(rec[mask_off + 16 * i + 8:mask_off + 16 * i + 10], "little"),
             int.from_bytes(rec[mask_off + 16 * i:mask_off + 16 * i + 8], "little"))
            for i in range(count)]


def _affinities(rec, count_off, mask_off):
    return tuple(i for group, mask in _spans(rec, count_off, mask_off)
                 for i in _bits(group, mask))


def _glpi_ex():
    size = wt.DWORD(0)
    _k32.GetLogicalProcessorInformationEx(RELATION_ALL, None, ctypes.byref(size))
    if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
        raise _winerror("GetLogicalProcessorInformationEx size query")
    buf = ctypes.create_string_buffer(size.value)
    if not _k32.GetLogicalProcessorInformationEx(RELATION_ALL, buf, ctypes.byref(size)):
        raise _winerror("GetLogicalProcessorInformationEx")
    return buf.raw[:size.value]


def topology():
    return parse_topology(_glpi_ex())


def parse_topology(raw):
    cores, packages, caches, numa, pos = [], [], [], {}, 0
    while pos < len(raw):
        relation = int.from_bytes(raw[pos:pos + 4], "little")
        size = int.from_bytes(raw[pos + 4:pos + 8], "little")
        if size < 8 or pos + size > len(raw):
            raise HwError(f"GetLogicalProcessorInformationEx: bad record size {size}")
        rec = raw[pos:pos + size]
        pos += size
        if relation == RELATION_NUMA:
            numa[int.from_bytes(rec[8:12], "little")] = _spans(rec, 30, 32)
        elif relation in (RELATION_CORE, RELATION_PACKAGE):
            logical = _affinities(rec, 30, 32)
            if relation == RELATION_PACKAGE:
                packages.append(Package(logical))
            else:
                group = int.from_bytes(rec[40:42], "little")
                cores.append(Core(group, int.from_bytes(rec[32:40], "little"), logical))
        elif relation == RELATION_CACHE:
            kind = CACHE_KINDS.get(int.from_bytes(rec[16:20], "little"))
            if kind is None:
                raise HwError("GetLogicalProcessorInformationEx: unknown cache type")
            caches.append(Cache(rec[8], kind, rec[9], int.from_bytes(rec[10:12], "little"),
                                int.from_bytes(rec[12:16], "little"),
                                _affinities(rec, 38, 40)))
    if not cores or not packages:
        raise HwError("GetLogicalProcessorInformationEx returned no cores or packages")
    return Topology(cores, packages, caches, numa)


def cache_groups(topo, level, kind):
    found = [c for c in topo.caches if c.level == level and c.kind == kind]
    if not found:
        raise HwError(f"no L{level} {kind} cache reported")
    counts = {}
    for c in found:
        key = (c.size, c.associativity, c.line)
        counts[key] = counts.get(key, 0) + 1
    return [CacheGroup(n, size, ways, line)
            for (size, ways, line), n in sorted(counts.items(), reverse=True)]


def _size_text(size, long):
    if size % (1 << 20) == 0:
        n, unit = size >> 20, "M"
    else:
        n, unit = size // 1024, "K"
    return f"{n} {unit}{'Bytes' if long else 'B'}"


def _ways_text(ways):
    return "Full" if ways == FULLY_ASSOCIATIVE else f"{ways}-way"


def cache_info(topo, level, kind):
    groups = cache_groups(topo, level, kind)
    if len(groups) == 1:
        g = groups[0]
        size = _size_text(g.size, True)
        summary = f"{g.count} x {size}"
    else:
        size = summary = " + ".join(
            (f"{g.count} x " if g.count > 1 else "") + _size_text(g.size, False)
            for g in groups)
    ways = list(dict.fromkeys(_ways_text(g.associativity) for g in groups))
    descr = list(dict.fromkeys(
        ("Fully associative" if g.associativity == FULLY_ASSOCIATIVE
         else f"{g.associativity}-way set associative") + f", {g.line}-byte line size"
        for g in groups))
    return CacheInfo(summary, size, " + ".join(ways), " + ".join(descr))


# ====================================================================
#  CORE CLOCKS  (PDH: % Processor Performance x Processor Frequency)
# ====================================================================

PDH_FMT_DOUBLE = 0x200
PDH_MORE_DATA = 0x800007D2
PDH_VALID = (0, 1)      # PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA
_PERF = r"\Processor Information(*)\% Processor Performance"
_FREQ = r"\Processor Information(*)\Processor Frequency"

_pdh = ctypes.WinDLL("pdh")
for _name in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData",
              "PdhGetFormattedCounterArrayW", "PdhCloseQuery"):
    getattr(_pdh, _name).restype = wt.DWORD


class _Counter(ctypes.Structure):
    _fields_ = [("CStatus", wt.DWORD), ("value", ctypes.c_double)]


class _CounterItem(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("fmt", _Counter)]


def _pdh_check(status, what):
    if status:
        raise HwError(f"{what}: PDH 0x{status:08X}")


def mhz_text(mhz):
    return f"{mhz:.2f} MHz"


def pdh_cpu(name, numa):
    """Logical processor of a `Processor Information` instance, which is named
    <NUMA node>,<processor number in its group>; None for the _Total instances."""
    if "_Total" in name:
        return None
    m = re.fullmatch(r"(\d+),(\d+)", name)
    if m is None:
        raise HwError(f"PDH instance {name!r} is not <NUMA node>,<processor>")
    node, number = int(m[1]), int(m[2])
    if node not in numa:
        raise HwError(f"PDH instance {name}: NUMA node {node} is not in the topology")
    for group, mask in numa[node]:
        if mask >> number & 1:
            return group * 64 + number
    raise HwError(f"PDH instance {name}: processor {number} is not in node {node}")


class CoreClocks:
    # The constructor primes the counters; each sample() covers the time since
    # the previous one.

    def __init__(self, topo):
        self._numa = topo.numa
        self._query = ctypes.c_void_p()
        self._counters = None
        self.last = None
        _pdh_check(_pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)), "PdhOpenQuery")
        try:
            self._counters = []
            for path in (_PERF, _FREQ):
                c = ctypes.c_void_p()
                _pdh_check(_pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(c)),
                           f"PdhAddEnglishCounter {path}")
                self._counters.append(c)
            _pdh_check(_pdh.PdhCollectQueryData(self._query), "PdhCollectQueryData")
        except HwError:
            self.close()
            raise

    def _values(self, counter):
        size, count = wt.DWORD(0), wt.DWORD(0)
        status = _pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
        if status != PDH_MORE_DATA:
            _pdh_check(status, "PdhGetFormattedCounterArray size")
        buf = ctypes.create_string_buffer(size.value)
        _pdh_check(_pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), buf),
            "PdhGetFormattedCounterArray")
        items = ctypes.cast(buf, ctypes.POINTER(_CounterItem))
        out = {}
        for i in range(count.value):
            cpu = pdh_cpu(items[i].name, self._numa)
            if cpu is None:
                continue
            if items[i].fmt.CStatus not in PDH_VALID:
                raise HwError(f"PDH instance {items[i].name}: status 0x{items[i].fmt.CStatus:08X}")
            out[cpu] = items[i].fmt.value
        return out

    def sample(self):
        if self._counters is None:
            raise HwError("clock query is closed")
        _pdh_check(_pdh.PdhCollectQueryData(self._query), "PdhCollectQueryData")
        perf, freq = (self._values(c) for c in self._counters)
        if perf.keys() != freq.keys():
            raise HwError("PDH performance and frequency instances differ")
        self.last = {cpu: perf[cpu] * freq[cpu] / 100 for cpu in perf}
        return self.last

    def per_core(self, topo):
        if self.last is None:
            raise HwError("no clock sample taken yet")
        try:
            return [self.last[core.logical[0]] for core in topo.cores]
        except KeyError as e:
            raise HwError(f"PDH reports no clock for logical processor {e.args[0]}") from None

    def close(self):
        if self._counters is not None:
            self._counters = None
            _pdh.PdhCloseQuery(self._query)


# ====================================================================
#  PCI  (SetupAPI + DEVPKEY_PciDevice_*)
# ====================================================================

class _Guid(ctypes.Structure):
    _fields_ = [("a", wt.DWORD), ("b", wt.WORD), ("c", wt.WORD), ("d", ctypes.c_ubyte * 8)]


class _DevPropKey(ctypes.Structure):
    _fields_ = [("fmtid", _Guid), ("pid", wt.DWORD)]


class _DevInfoData(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", _Guid), ("DevInst", wt.DWORD),
                ("Reserved", ctypes.c_size_t)]


def _guid(text):
    a, b, c, d, e = text.split("-")
    tail = bytes.fromhex(d + e)
    return _Guid(int(a, 16), int(b, 16), int(c, 16), (ctypes.c_ubyte * 8)(*tail))


_PCI_FMT = _guid("3ab22e31-8264-4b4e-9af5-a8d2d8e33e62")
_DEV_FMT = _guid("a45c254e-df1c-4efd-8020-67d146a850e0")
_KEY_BUS = _DevPropKey(_DEV_FMT, 23)
_KEY_ADDRESS = _DevPropKey(_DEV_FMT, 30)
_KEY_PCI = {name: _DevPropKey(_PCI_FMT, pid) for name, pid in (
    ("device_type", 1), ("current_speed", 9), ("current_width", 10), ("max_speed", 11),
    ("max_width", 12))}

DIGCF_PRESENT, DIGCF_ALLCLASSES = 0x2, 0x4
ERROR_NO_MORE_ITEMS, ERROR_NOT_FOUND = 259, 1168
PCI_ROOT_PORT = 8       # DEVPKEY_PciDevice_DeviceType: PciExpressRootPort
SPDRP_HARDWAREID = 1
INVALID_HANDLE = ctypes.c_void_p(-1).value

_sa = ctypes.WinDLL("setupapi", use_last_error=True)
_sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_sa.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD]
_sa.SetupDiEnumDeviceInfo.restype = wt.BOOL
_sa.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.POINTER(_DevInfoData)]
_sa.SetupDiGetDeviceInstanceIdW.restype = wt.BOOL
_sa.SetupDiGetDeviceInstanceIdW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(_DevInfoData), wt.LPWSTR, wt.DWORD,
    ctypes.POINTER(wt.DWORD)]
_sa.SetupDiGetDevicePropertyW.restype = wt.BOOL
_sa.SetupDiGetDevicePropertyW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(_DevInfoData), ctypes.POINTER(_DevPropKey),
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD]
_sa.SetupDiGetDeviceRegistryPropertyW.restype = wt.BOOL
_sa.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(_DevInfoData), wt.DWORD, ctypes.POINTER(wt.DWORD),
    ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
_sa.SetupDiDestroyDeviceInfoList.restype = wt.BOOL
_sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

LINK_GTS = {1: "2.5", 2: "5.0", 3: "8.0", 4: "16.0", 5: "32.0", 6: "64.0"}
_PCI_ID = re.compile(r"PCI\\VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})&SUBSYS_([0-9A-F]{8})"
                     r"&REV_([0-9A-F]{2})\\")


class PciDevice(NamedTuple):
    instance_id: str
    vendor: int
    device: int
    subsystem: int          # device << 16 | vendor, as in DXGI and the SUBSYS_ id
    revision: int
    base_class: int
    sub_class: int
    bus: int
    dev_number: int
    function: int
    current_speed: int | None
    max_speed: int | None
    current_width: int | None
    max_width: int | None
    is_root_port: bool


def link_speed_text(speed):
    if speed not in LINK_GTS:
        raise HwError(f"PCIe link speed code {speed} is not a generation")
    return f"{LINK_GTS[speed]} GT/s"


def pcie_bus_text(speed, rate=False):
    text = f"PCI-Express {speed}.0"
    return f"{text} ({link_speed_text(speed)})" if rate else text


def link_width_text(width):
    return f"x{width}"


def _property(devs, info, key):
    buf = ctypes.create_string_buffer(8)
    kind, need = wt.DWORD(), wt.DWORD()
    if not _sa.SetupDiGetDevicePropertyW(devs, ctypes.byref(info), ctypes.byref(key),
                                         ctypes.byref(kind), buf, 8, ctypes.byref(need), 0):
        if ctypes.get_last_error() == ERROR_NOT_FOUND:
            return None
        raise _winerror(f"SetupDiGetDeviceProperty pid {key.pid}")
    return int.from_bytes(buf.raw[:need.value], "little")


def _class_code(devs, info, instance):
    # Host bridges carry no DEVPKEY_PciDevice_BaseClass; every PCI device
    # carries a CC_bbss hardware id.
    buf = ctypes.create_unicode_buffer(2048)
    if not _sa.SetupDiGetDeviceRegistryPropertyW(
            devs, ctypes.byref(info), SPDRP_HARDWAREID, None, buf,
            ctypes.sizeof(buf), None):
        raise _winerror(f"{instance}: hardware ids")
    m = re.search(r"&CC_([0-9A-F]{2})([0-9A-F]{2})", ctypes.wstring_at(buf, 2048))
    if m is None:
        raise HwError(f"{instance}: no CC_ class code in its hardware ids")
    return int(m[1], 16), int(m[2], 16)


def pci_devices():
    devs = _sa.SetupDiGetClassDevsW(None, "PCI", None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if devs in (None, INVALID_HANDLE):
        raise _winerror("SetupDiGetClassDevs PCI")
    out = []
    try:
        info = _DevInfoData(ctypes.sizeof(_DevInfoData))
        for index in range(1024):
            if not _sa.SetupDiEnumDeviceInfo(devs, index, ctypes.byref(info)):
                if ctypes.get_last_error() != ERROR_NO_MORE_ITEMS:
                    raise _winerror("SetupDiEnumDeviceInfo")
                break
            buf = ctypes.create_unicode_buffer(260)
            if not _sa.SetupDiGetDeviceInstanceIdW(devs, ctypes.byref(info), buf, 260, None):
                raise _winerror("SetupDiGetDeviceInstanceId")
            m = _PCI_ID.match(buf.value)
            if m is None:
                raise HwError(f"unrecognised PCI instance id {buf.value}")
            ven, dev, sub, rev = (int(g, 16) for g in m.groups())
            prop = {name: _property(devs, info, key) for name, key in _KEY_PCI.items()}
            base, sub_class = _class_code(devs, info, buf.value)
            bus = _property(devs, info, _KEY_BUS)
            addr = _property(devs, info, _KEY_ADDRESS)
            if bus is None or addr is None:
                raise HwError(f"{buf.value}: no bus location")
            out.append(PciDevice(
                buf.value, ven, dev, sub, rev,
                base, sub_class, bus, addr >> 16, addr & 0xFFFF,
                prop["current_speed"], prop["max_speed"], prop["current_width"],
                prop["max_width"], prop["device_type"] == PCI_ROOT_PORT))
    finally:
        _sa.SetupDiDestroyDeviceInfoList(devs)
    return out


def _lowest(devs, base, sub):
    found = [d for d in devs if (d.base_class, d.sub_class) == (base, sub)]
    return min(found, key=lambda d: (d.bus, d.dev_number, d.function)) if found else None


def host_bridge(devs):
    return _lowest(devs, 6, 0)


def isa_bridge(devs):
    return _lowest(devs, 6, 1)


def pci_device_at(devs, bus, dev_number, function):
    for d in devs:
        if (d.bus, d.dev_number, d.function) == (bus, dev_number, function):
            return d
    return None


def max_root_port_speed(devs):
    # AMD AM4 / AM5 root ports publish no link properties: None, and the caller
    # falls back to the CPU's datasheet generation
    speeds = [d.max_speed for d in devs if d.is_root_port and d.max_speed]
    return max(speeds) if speeds else None


# ====================================================================
#  DXGI ADAPTERS  (+ D3DKMT for each adapter's PCI location)
# ====================================================================

DXGI_ADAPTER_FLAG_SOFTWARE = 2
DXGI_ERROR_NOT_FOUND = 0x887A0002 - (1 << 32)
KMTQAITYPE_ADAPTERADDRESS = 6
NO_LOCATION = 0xFFFFFFFF
_IID_FACTORY1 = _guid("770aae78-f26f-4dba-a829-253c83d1b387")

_dxgi = ctypes.WinDLL("dxgi")
_dxgi.CreateDXGIFactory1.restype = ctypes.c_long
_dxgi.CreateDXGIFactory1.argtypes = [ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)]
_gdi = ctypes.WinDLL("gdi32")
for _fn in ("D3DKMTOpenAdapterFromLuid", "D3DKMTQueryAdapterInfo", "D3DKMTCloseAdapter"):
    getattr(_gdi, _fn).restype = ctypes.c_long


class _AdapterDesc1(ctypes.Structure):
    _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", wt.UINT),
                ("DeviceId", wt.UINT), ("SubSysId", wt.UINT), ("Revision", wt.UINT),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t), ("LuidLow", wt.DWORD),
                ("LuidHigh", wt.LONG), ("Flags", wt.UINT)]


class _OpenFromLuid(ctypes.Structure):
    _fields_ = [("LuidLow", wt.DWORD), ("LuidHigh", wt.LONG), ("hAdapter", wt.UINT)]


class _QueryInfo(ctypes.Structure):
    _fields_ = [("hAdapter", wt.UINT), ("Type", wt.UINT),
                ("pPrivateDriverData", ctypes.c_void_p), ("PrivateDriverDataSize", wt.UINT)]


class _AdapterAddress(ctypes.Structure):
    _fields_ = [("BusNumber", wt.UINT), ("DeviceNumber", wt.UINT),
                ("FunctionNumber", wt.UINT)]


class _OutputDesc(ctypes.Structure):
    _fields_ = [("DeviceName", ctypes.c_wchar * 32), ("Left", wt.LONG), ("Top", wt.LONG),
                ("Right", wt.LONG), ("Bottom", wt.LONG), ("AttachedToDesktop", wt.BOOL),
                ("Rotation", wt.UINT), ("Monitor", ctypes.c_void_p)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetMonitorInfoW.restype = wt.BOOL
_user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
MONITORINFOF_PRIMARY = 1


class Adapter(NamedTuple):
    name: str
    vendor: int
    device: int
    subsystem: int
    revision: int
    vram: int
    bus: int | None
    device_number: int | None
    function: int | None
    primary: bool           # drives the primary display
    error: str              # why this adapter could not be fully read; "" when it could


def _vcall(obj, index, argtypes, *args):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[index])
    return method(obj, *args)


def _release(obj):
    _vcall(obj, 2, ())


def _pci_location(desc):
    opened = _OpenFromLuid(desc.LuidLow, desc.LuidHigh, 0)
    status = _gdi.D3DKMTOpenAdapterFromLuid(ctypes.byref(opened))
    if status:
        raise HwError(f"D3DKMTOpenAdapterFromLuid({desc.Description}): 0x{status & 0xFFFFFFFF:08X}")
    try:
        addr = _AdapterAddress()
        query = _QueryInfo(opened.hAdapter, KMTQAITYPE_ADAPTERADDRESS,
                           ctypes.cast(ctypes.byref(addr), ctypes.c_void_p), ctypes.sizeof(addr))
        status = _gdi.D3DKMTQueryAdapterInfo(ctypes.byref(query))
        if status:
            raise HwError(f"D3DKMTQueryAdapterInfo({desc.Description}): 0x{status & 0xFFFFFFFF:08X}")
    finally:
        _gdi.D3DKMTCloseAdapter(ctypes.byref(ctypes.c_uint(opened.hAdapter)))
    return addr.BusNumber, addr.DeviceNumber, addr.FunctionNumber


def _drives_primary(adapter):
    for index in range(32):
        output = ctypes.c_void_p()
        hr = _vcall(adapter, 7, (wt.UINT, ctypes.POINTER(ctypes.c_void_p)), index,
                    ctypes.byref(output))
        if hr == DXGI_ERROR_NOT_FOUND:
            return False
        if hr:
            raise HwError(f"IDXGIAdapter::EnumOutputs: 0x{hr & 0xFFFFFFFF:08X}")
        try:
            desc = _OutputDesc()
            hr = _vcall(output.value, 7, (ctypes.POINTER(_OutputDesc),), ctypes.byref(desc))
            if hr:
                raise HwError(f"IDXGIOutput::GetDesc: 0x{hr & 0xFFFFFFFF:08X}")
        finally:
            _release(output.value)
        if not desc.AttachedToDesktop:
            continue
        info = _MonitorInfo(ctypes.sizeof(_MonitorInfo))
        if not _user32.GetMonitorInfoW(desc.Monitor, ctypes.byref(info)):
            raise _winerror("GetMonitorInfo")
        if info.dwFlags & MONITORINFOF_PRIMARY:
            return True
    return False


def dxgi_adapters(include_virtual=False):
    # Software renderers and the virtual adapter Windows adds for a linked
    # (NVLink / SLI) pair have no PCI location; include_virtual keeps them.  An
    # adapter whose location or outputs cannot be read stays in the list with
    # its error.
    factory = ctypes.c_void_p()
    hr = _dxgi.CreateDXGIFactory1(ctypes.byref(_IID_FACTORY1), ctypes.byref(factory))
    if hr:
        raise HwError(f"CreateDXGIFactory1: 0x{hr & 0xFFFFFFFF:08X}")
    out = []
    try:
        for index in range(64):
            adapter = ctypes.c_void_p()
            hr = _vcall(factory.value, 12, (wt.UINT, ctypes.POINTER(ctypes.c_void_p)),
                        index, ctypes.byref(adapter))
            if hr == DXGI_ERROR_NOT_FOUND:
                break
            if hr:
                raise HwError(f"IDXGIFactory1::EnumAdapters1: 0x{hr & 0xFFFFFFFF:08X}")
            error, primary = "", False
            try:
                desc = _AdapterDesc1()
                hr = _vcall(adapter.value, 10, (ctypes.POINTER(_AdapterDesc1),),
                            ctypes.byref(desc))
                if hr:
                    raise HwError(f"IDXGIAdapter1::GetDesc1: 0x{hr & 0xFFFFFFFF:08X}")
                try:
                    primary = _drives_primary(adapter.value)
                except HwError as e:
                    error = str(e)
            finally:
                _release(adapter.value)
            software = bool(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)
            where = (None, None, None)
            if not software:
                try:
                    where = _pci_location(desc)
                except HwError as e:
                    error = str(e)
                if where[0] == NO_LOCATION:
                    where = (None, None, None)
            if where[0] is None and not error and not include_virtual:
                continue
            out.append(Adapter(desc.Description, desc.VendorId, desc.DeviceId, desc.SubSysId,
                               desc.Revision, desc.DedicatedVideoMemory, *where, primary,
                               error))
    finally:
        _release(factory.value)
    return out


# ====================================================================
#  NVIDIA  (nvidia-smi for clocks / limits, NVML for the memory bus)
# ====================================================================

NVML_ERROR_NOT_SUPPORTED = 3
_SMI_FIELDS = ("pci.bus_id", "clocks.gr", "clocks.mem", "power.default_limit", "memory.total")


class NvInfo(NamedTuple):
    core_mhz: float | None
    memory_mhz: float | None
    tdp_w: float | None
    bus_width: int | None
    memory_mib: float | None


def _smi_number(text):
    if "N/A" in text or "Not Supported" in text:
        return None
    try:
        return float(text)
    except ValueError:
        raise HwError(f"nvidia-smi returned {text!r} where a number belongs") from None


def _nvml_bus_width(bus_id):
    try:
        nvml = ctypes.WinDLL("nvml")
    except OSError as e:
        raise HwError(f"nvml.dll: {e}") from None
    for name in ("nvmlInit_v2", "nvmlShutdown", "nvmlDeviceGetHandleByPciBusId_v2",
                 "nvmlDeviceGetMemoryBusWidth"):
        getattr(nvml, name).restype = ctypes.c_int
    if nvml.nvmlInit_v2():
        raise HwError("nvmlInit_v2 failed")
    try:
        handle, width = ctypes.c_void_p(), ctypes.c_uint()
        rc = nvml.nvmlDeviceGetHandleByPciBusId_v2(bus_id.encode(), ctypes.byref(handle))
        if rc:
            raise HwError(f"nvmlDeviceGetHandleByPciBusId({bus_id}): NVML error {rc}")
        rc = nvml.nvmlDeviceGetMemoryBusWidth(handle, ctypes.byref(width))
        if rc == NVML_ERROR_NOT_SUPPORTED:
            return None
        if rc:
            raise HwError(f"nvmlDeviceGetMemoryBusWidth({bus_id}): NVML error {rc}")
        return width.value
    finally:
        nvml.nvmlShutdown()


def nvidia_infos():
    if shutil.which(gpu.SMI) is None:
        raise HwError(f"{gpu.SMI} not found")
    out = {}
    for line in gpu.run([f"--query-gpu={','.join(_SMI_FIELDS)}",
                         "--format=csv,noheader,nounits"]).strip().splitlines():
        bus_id, *nums = (f.strip() for f in line.split(","))
        m = re.fullmatch(r"[0-9A-Fa-f]{8}:([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2})\.(\d)", bus_id)
        if m is None or len(nums) != len(_SMI_FIELDS) - 1:
            raise HwError(f"unexpected nvidia-smi line {line!r}")
        core, mem, tdp, mib = (_smi_number(n) for n in nums)
        out[(int(m[1], 16), int(m[2], 16), int(m[3]))] = NvInfo(
            core, mem, tdp, _nvml_bus_width(bus_id), mib)
    return out


# ====================================================================
#  WINDOWS, DIRECTX, MICROCODE
# ====================================================================

_D3D_LEVELS = ((0xC200, "12_2"), (0xC100, "12_1"), (0xC000, "12_0"), (0xB100, "11_1"),
               (0xB000, "11_0"))
_IID_D3D12_DEVICE = _guid("189819f1-1db6-4b57-be54-1821339b85f7")


def _hklm(path, name):
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
        return winreg.QueryValueEx(key, name)[0]


def windows_version():
    nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    product, display = _hklm(nt, "ProductName"), _hklm(nt, "DisplayVersion")
    build, ubr = _hklm(nt, "CurrentBuildNumber"), _hklm(nt, "UBR")
    # Windows 11 still writes "Windows 10" into ProductName
    if int(build) >= 22000:
        product = product.replace("Windows 10", "Windows 11")
    return f"{product} {display} ({build}.{ubr})"


def _load_d3d12():
    return ctypes.WinDLL("d3d12")


def directx_version():
    try:
        d3d12 = _load_d3d12()
    except OSError:
        return ""
    d3d12.D3D12CreateDevice.restype = ctypes.c_long
    d3d12.D3D12CreateDevice.argtypes = [ctypes.c_void_p, wt.UINT, ctypes.POINTER(_Guid),
                                        ctypes.c_void_p]
    for level, name in _D3D_LEVELS:
        # a NULL device pointer only tests support: S_FALSE (1) means it would work
        if d3d12.D3D12CreateDevice(None, level, ctypes.byref(_IID_D3D12_DEVICE), None) in (0, 1):
            return f"DirectX 12 (FL {name})"
    return ""


def microcode():
    try:
        raw = _hklm(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "Update Revision")
    except FileNotFoundError:
        return ""
    if len(raw) < 8:
        raise HwError(f"Update Revision holds {len(raw)} bytes, expected 8")
    amd = identity().vendor == "AuthenticAMD"
    rev = int.from_bytes(raw[:4] if amd else raw[4:8], "little")
    return f"0x{rev:X}" if rev else ""
