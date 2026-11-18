#!/usr/bin/env python3
"""smbios.py - SMBIOS reader for wintools: the raw firmware table through
GetSystemFirmwareTable('RSMB'), the structure walk with string sets, and the
BIOS, baseboard, processor and memory-device records."""

import ctypes
import ctypes.wintypes as wt
import re
from typing import NamedTuple

RSMB = 0x52534D42   # 'RSMB'

# SMBIOS 3.x type 17 Memory Type; Other (1) and Unknown (2) are deliberately absent
MEMORY_TYPES = {
    0x12: "DDR", 0x13: "DDR2", 0x14: "DDR2 FB-DIMM", 0x18: "DDR3", 0x1A: "DDR4",
    0x1B: "LPDDR", 0x1C: "LPDDR2", 0x1D: "LPDDR3", 0x1E: "LPDDR4", 0x20: "HBM",
    0x21: "HBM2", 0x22: "DDR5", 0x23: "LPDDR5", 0x24: "HBM3",
}
DETAIL_UNBUFFERED = 1 << 14
DETAIL_REGISTERED = 1 << 13
DETAIL_LRDIMM = 1 << 15
FORM_DIMM, FORM_RIMM, FORM_SODIMM, FORM_FBDIMM = 0x09, 0x0C, 0x0D, 0x0F
# "AGESA!V9 ComboAm5PI 1.2.0.0a": the tag, then the version text
AGESA_RE = re.compile(r"AGESA\s*(?:!?V\d+)?\s+(\S.*)")

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.GetSystemFirmwareTable.restype = wt.DWORD
_k32.GetSystemFirmwareTable.argtypes = [wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD]


class SmbiosError(ValueError):
    pass


class Structure:
    # Field offsets are from the start of the structure, as the specification states them.

    def __init__(self, stype, handle, data, strings):
        self.type = stype
        self.handle = handle
        self.data = data
        self.strings = strings

    def has(self, off, n):
        return off + n <= len(self.data)

    def uint(self, off, n):
        if not self.has(off, n):
            raise SmbiosError(f"type {self.type}: no field at offset 0x{off:02X}")
        return int.from_bytes(self.data[off:off + n], "little")

    def string(self, off):
        # a field the structure is too short to hold, or an index past the string
        # set, is a string the firmware does not provide
        if not self.has(off, 1):
            return ""
        idx = self.data[off]
        return self.strings[idx - 1] if 0 < idx <= len(self.strings) else ""


class Table(NamedTuple):
    version: tuple
    structures: list

    def of_type(self, stype):
        return [s for s in self.structures if s.type == stype]


class Bios(NamedTuple):
    vendor: str
    version: str
    date: str


class Baseboard(NamedTuple):
    manufacturer: str
    product: str
    version: str
    serial: str


class Processor(NamedTuple):
    socket: str
    manufacturer: str
    version: str


class MemoryDevice(NamedTuple):
    present: bool           # a module sits in the slot (size word is not 0)
    size_mb: int | None     # None: empty slot, or a module of unknown size
    memory_type: str        # "" when SMBIOS says Other / Unknown
    speed: int | None
    configured_speed: int | None
    manufacturer: str
    part_number: str
    serial: str
    device_locator: str
    bank_locator: str
    form_factor: int
    type_detail: int

    @property
    def registered(self):
        return bool(self.type_detail & DETAIL_REGISTERED)

    @property
    def buffered(self):
        return bool(self.type_detail & (DETAIL_REGISTERED | DETAIL_LRDIMM))

    @property
    def module_kind(self):
        if self.form_factor == FORM_SODIMM:
            return "SO-DIMM"
        if self.form_factor == FORM_FBDIMM:
            return "FB-DIMM"
        if self.form_factor == FORM_RIMM:
            return "RIMM"
        if self.form_factor != FORM_DIMM:
            return ""
        for bit, kind in ((DETAIL_LRDIMM, "LRDIMM"), (DETAIL_REGISTERED, "RDIMM"),
                          (DETAIL_UNBUFFERED, "UDIMM")):
            if self.type_detail & bit:
                return kind
        return "DIMM"


def read_raw():
    size = _k32.GetSystemFirmwareTable(RSMB, 0, None, 0)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    buf = ctypes.create_string_buffer(size)
    if _k32.GetSystemFirmwareTable(RSMB, 0, buf, size) != size:
        raise ctypes.WinError(ctypes.get_last_error())
    return buf.raw


def parse(raw):
    if len(raw) < 8:
        raise SmbiosError("RSMB header truncated")
    length = int.from_bytes(raw[4:8], "little")
    if len(raw) < 8 + length:
        raise SmbiosError(f"RSMB declares {length} bytes, holds {len(raw) - 8}")
    data = raw[8:8 + length]
    out, pos = [], 0
    while pos < length:
        if pos + 4 > length:
            raise SmbiosError(f"structure header cut at {pos}")
        stype, slen = data[pos], data[pos + 1]
        if slen < 4 or pos + slen > length:
            raise SmbiosError(f"type {stype} at {pos}: bad length {slen}")
        text = pos + slen
        if data[text:text + 2] == b"\0\0":
            strings, nxt = [], text + 2
        else:
            end = data.find(b"\0\0", text)
            if end < 0:
                raise SmbiosError(f"type {stype} at {pos}: string set unterminated")
            strings = [s.decode("utf-8", "replace").strip()
                       for s in data[text:end].split(b"\0")]
            nxt = end + 2
        out.append(Structure(stype, int.from_bytes(data[pos + 2:pos + 4], "little"),
                             data[pos:pos + slen], strings))
        pos = nxt
        if stype == 127:
            break
    return Table((raw[1], raw[2]), out)


def load():
    return parse(read_raw())


def _first(table, stype):
    found = table.of_type(stype)
    return found[0] if found else None


def bios(table):
    s = _first(table, 0)
    return Bios(s.string(4), s.string(5), s.string(8)) if s else None


def baseboard(table):
    s = _first(table, 2)
    return Baseboard(s.string(4), s.string(5), s.string(6), s.string(7)) if s else None


def processors(table):
    return [Processor(s.string(4), s.string(7), s.string(0x10))
            for s in table.of_type(4)]


def _speed(s, off, ext_off):
    mts = s.uint(off, 2) if s.has(off, 2) else 0
    if mts == 0xFFFF:
        return s.uint(ext_off, 4)
    return mts or None


def _size(s):
    word = s.uint(0x0C, 2)
    if word == 0:
        return False, None
    if word == 0xFFFF:
        return True, None
    if word == 0x7FFF:
        return True, s.uint(0x1C, 4)
    return True, (word & 0x7FFF) // 1024 if word & 0x8000 else word


def memory_devices(table):
    out = []
    for s in table.of_type(17):
        present, size = _size(s)
        out.append(MemoryDevice(
            present, size, MEMORY_TYPES.get(s.uint(0x12, 1), ""),
            _speed(s, 0x15, 0x54), _speed(s, 0x20, 0x58),
            s.string(0x17), s.string(0x1A), s.string(0x18), s.string(0x10),
            s.string(0x11), s.uint(0x0E, 1), s.uint(0x13, 2)))
    return out


def agesa(table):
    """The AMD AGESA version text from the type 40 additional-information
    entries; '' when none carries one."""
    for s in table.of_type(40):
        pos = 5
        for _ in range(s.uint(4, 1)):
            length = s.uint(pos, 1)
            if length < 5:
                raise SmbiosError(f"type 40: entry of {length} bytes at offset {pos}")
            m = AGESA_RE.fullmatch(s.string(pos + 4))
            if m:
                return m[1]
            pos += length
    return ""
