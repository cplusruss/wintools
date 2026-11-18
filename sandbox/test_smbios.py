"""Contract test for smbios.py: structure walk and string sets on synthetic
tables, a captured RSMB fixture from this PC, and the live table compared
with WMI and GetPhysicallyInstalledSystemMemory."""

import ctypes
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import smbios  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rsmb_7950x3d_b650_creator.bin"


def structure(stype, formatted, strings=(), handle=0):
    """Type, length, handle, formatted area, string set, double NUL."""
    body = bytes([stype, 4 + len(formatted)]) + handle.to_bytes(2, "little") + formatted
    text = b"".join(s.encode() + b"\0" for s in strings) or b"\0"
    return body + text + b"\0"


def raw_table(major, minor, *structs):
    data = b"".join(structs)
    return bytes([0, major, minor, 0]) + len(data).to_bytes(4, "little") + data


# ---- synthetic: walk, string sets, empty string sets, end marker ----
bios = structure(0, bytes([1, 2]) + b"\0\0" + bytes([3]) + b"\0" * 10,
                 ("Vendor Inc.", "1.2.3", "01/02/2024"), 0x10)
none = structure(1, b"\0" * 8, (), 0x11)                  # no strings at all
board = structure(2, bytes([1, 2, 3, 4]) + b"\0" * 6, ("Maker", "Model", "Rev A", "SN1"), 0x12)
end = structure(127, b"", (), 0x13)
t = smbios.parse(raw_table(3, 6, bios, none, board, end))
assert t.version == (3, 6), t.version
assert [s.type for s in t.structures] == [0, 1, 2, 127], [s.type for s in t.structures]
assert [s.handle for s in t.structures] == [0x10, 0x11, 0x12, 0x13]
assert t.structures[0].string(4) == "Vendor Inc."
assert t.structures[0].string(5) == "1.2.3"
assert t.structures[1].strings == []
bb = smbios.baseboard(t)
assert (bb.manufacturer, bb.product, bb.version, bb.serial) == (
    "Maker", "Model", "Rev A", "SN1"), bb
b = smbios.bios(t)
assert (b.vendor, b.version, b.date) == ("Vendor Inc.", "1.2.3", "01/02/2024"), b
print("synthetic ok")

# ---- structures that do not exist are "not exposed", not errors ----
no_board = smbios.parse(raw_table(3, 6, bios, end))
assert smbios.baseboard(no_board) is None
assert smbios.bios(smbios.parse(raw_table(3, 6, board, end))) is None
assert smbios.processors(no_board) == [] and smbios.memory_devices(no_board) == []
assert smbios.agesa(no_board) == ""

# a string index past the string set, or a field the structure is too short to hold,
# reads as an empty string
short = structure(2, bytes([1, 9, 3]), ("Maker", "Model", "Rev A"), 0x20)
bb = smbios.baseboard(smbios.parse(raw_table(3, 6, short, end)))
assert (bb.manufacturer, bb.product, bb.version, bb.serial) == ("Maker", "", "Rev A", ""), bb

# ---- type 40 additional information: the AGESA string, tag dropped ----
def additional(*texts):
    entries = b"".join(bytes([9, 0, 0, 5, n + 1]) + b"\0" * 4 for n in range(len(texts)))
    return structure(40, bytes([len(texts)]) + entries, texts, 0x30)


for texts, want in ((("AGESA!V9 ComboAm5PI 1.2.0.0a",), "ComboAm5PI 1.2.0.0a"),
                    (("To Be Filled", "AGESA!V9 AmdAgesa 1.0.0.2"), "AmdAgesa 1.0.0.2"),
                    (("AGESA V4 PI 1.2.3.4",), "PI 1.2.3.4"),
                    (("To Be Filled", "YEAR"), ""), (("AGESA!V9",), "")):
    assert smbios.agesa(smbios.parse(raw_table(3, 6, additional(*texts), end))) == want, texts
assert smbios.agesa(smbios.parse(raw_table(
    3, 6, additional("To Be Filled"), additional("AGESA!V9 ComboAm4v2 1.2.0.B"), end))) == \
    "ComboAm4v2 1.2.0.B"
try:
    smbios.agesa(smbios.parse(raw_table(3, 6, structure(40, bytes([1, 3, 0, 0]), ("x",)), end)))
    raise AssertionError("a truncated type 40 entry was accepted")
except smbios.SmbiosError:
    pass
print("absent structures / type 40 ok")

# ---- malformed tables raise instead of returning partial data ----
for bad, why in ((b"", "empty"), (bytes([0, 3, 6, 0]) + (99).to_bytes(4, "little") + b"\0" * 4, "length"),
                 (raw_table(3, 6, bios)[:-3], "cut")):
    try:
        smbios.parse(bad)
    except smbios.SmbiosError:
        pass
    else:
        raise AssertionError(f"malformed table ({why}) was accepted")
print("malformed ok")


# ---- type 17 field decoding ----
def memdev(size_word, mtype, speed, conf, detail, attrs, ext_size=0, form=9):
    f = bytearray(b"\0" * (0x28 - 4 + 0x2C - 0x28 + 4))
    f[0x08 - 4:0x0A - 4] = (64).to_bytes(2, "little")             # total width
    f[0x0A - 4:0x0C - 4] = (64).to_bytes(2, "little")             # data width
    f[0x0C - 4:0x0E - 4] = size_word.to_bytes(2, "little")
    f[0x0E - 4] = form
    f[0x10 - 4], f[0x11 - 4] = 1, 2                                # locators
    f[0x12 - 4] = mtype
    f[0x13 - 4:0x15 - 4] = detail.to_bytes(2, "little")
    f[0x15 - 4:0x17 - 4] = speed.to_bytes(2, "little")
    f[0x17 - 4], f[0x18 - 4], f[0x1A - 4] = 3, 4, 5                # mfr, serial, part
    f[0x1B - 4] = attrs
    f[0x1C - 4:0x20 - 4] = ext_size.to_bytes(4, "little")
    f[0x20 - 4:0x22 - 4] = conf.to_bytes(2, "little")
    return structure(17, bytes(f), ("DIMM 0", "P0 CHANNEL A", "Corsair", "SN", "PART"))


devs = smbios.memory_devices(smbios.parse(raw_table(3, 6, *[
    memdev(*a) for a in (
        (0x8000 | 4096, 0x22, 4800, 3600, 0x4080, 2),            # KB-unit size word
        (0x7FFF, 0x22, 4800, 3600, 0x4080, 2, 65536),             # extended: 64 GB
        (0, 0x22, 0, 0, 0, 0),                                   # empty slot
        (16384, 0x1A, 3200, 3200, 0x20A0, 1),                    # 16 GB DDR4 registered
    )] + [end])))
assert [d.size_mb for d in devs] == [4, 65536, None, 16384], [d.size_mb for d in devs]
assert devs[0].memory_type == "DDR5" and devs[3].memory_type == "DDR4"
assert devs[0].speed == 4800 and devs[0].configured_speed == 3600
assert devs[0].registered is False and devs[3].registered is True
assert devs[0].buffered is False and devs[3].buffered is True
assert [d.present for d in devs] == [True, True, False, True]
assert devs[0].device_locator == "DIMM 0" and devs[0].bank_locator == "P0 CHANNEL A"
assert (devs[0].manufacturer, devs[0].serial, devs[0].part_number) == ("Corsair", "SN", "PART")

# an unknown size is a present module with no size; an unknown memory type is no text
odd = smbios.memory_devices(smbios.parse(raw_table(3, 6, *[
    memdev(*a) for a in (
        (0xFFFF, 0x22, 4800, 3600, 0x4080, 2),                   # size unknown
        (8192, 0x02, 4800, 3600, 0x4080, 2),                     # memory type Unknown
        (8192, 0x01, 4800, 3600, 0x4080, 2),                     # memory type Other
        (8192, 0xFF, 4800, 3600, 0x4080, 2),                     # not in the table
    )] + [end])))
assert [(d.present, d.size_mb) for d in odd] == [(True, None), (True, 8192), (True, 8192),
                                                (True, 8192)], odd
assert [d.memory_type for d in odd] == ["DDR5", "", "", ""], [d.memory_type for d in odd]

# module form: form factor and type detail
for form, detail, kind in ((9, 0x4080, "UDIMM"), (9, 0x2080, "RDIMM"), (9, 0x8080, "LRDIMM"),
                           (9, 0x0080, "DIMM"), (0x0D, 0x4080, "SO-DIMM"),
                           (0x0F, 0x0080, "FB-DIMM"), (0x0C, 0x0080, "RIMM"),
                           (0x10, 0x0080, ""), (2, 0x0080, "")):
    d, = smbios.memory_devices(smbios.parse(raw_table(
        3, 6, memdev(8192, 0x22, 4800, 3600, detail, 2, form=form), end)))
    assert d.module_kind == kind, (form, hex(detail), d.module_kind)
    assert d.registered == (detail & 0x2000 != 0)
    assert d.buffered == (detail & 0xA000 != 0)
print("type 17 decode ok")


# ---- the captured fixture from this PC ----
tbl = smbios.parse(FIXTURE.read_bytes())
bb = smbios.baseboard(tbl)
assert (bb.manufacturer, bb.product, bb.version) == (
    "ASUSTeK COMPUTER INC.", "ProArt B650-CREATOR", "Rev 1.xx"), bb
b = smbios.bios(tbl)
assert (b.vendor, b.version, b.date) == (
    "American Megatrends Inc.", "2124", "07/17/2024"), b
devs = smbios.memory_devices(tbl)
assert len(devs) == 4 and all(d.size_mb == 32768 for d in devs), devs
assert {d.memory_type for d in devs} == {"DDR5"}
assert {d.part_number for d in devs} == {"CMK128GX5M4B5600C40"}
assert {d.manufacturer for d in devs} == {"Corsair"}
assert {d.speed for d in devs} == {4800} and {d.configured_speed for d in devs} == {3600}
assert [d.bank_locator for d in devs] == [
    "P0 CHANNEL A", "P0 CHANNEL A", "P0 CHANNEL B", "P0 CHANNEL B"], [d.bank_locator for d in devs]
procs = smbios.processors(tbl)
assert len(procs) == 1 and procs[0].socket == "AM5", procs
assert smbios.agesa(tbl) == "ComboAm5PI 1.2.0.0a", smbios.agesa(tbl)
assert all(d.present and d.module_kind == "UDIMM" for d in devs)
assert not any(d.registered or d.buffered for d in devs)
print("fixture ok")

# ---- live table: equal to WMI and to the installed RAM ----
live = smbios.load()
ps = ("$b=Get-CimInstance Win32_BaseBoard; $w=Get-CimInstance Win32_BIOS;"
      "[pscustomobject]@{bm=$b.Manufacturer;bp=$b.Product;bv=$b.Version;"
      "wm=$w.Manufacturer;wv=$w.SMBIOSBIOSVersion;wd=$w.ReleaseDate.ToUniversalTime().ToString('MM/dd/yyyy')}"
      "|ConvertTo-Json")
wmi = json.loads(subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                capture_output=True, text=True, check=True).stdout)
bb, b = smbios.baseboard(live), smbios.bios(live)
assert (bb.manufacturer, bb.product, bb.version) == (wmi["bm"], wmi["bp"], wmi["bv"]), (bb, wmi)
assert (b.vendor, b.version, b.date) == (wmi["wm"], wmi["wv"], wmi["wd"]), (b, wmi)

kib = ctypes.c_ulonglong()
ctypes.WinDLL("kernel32").GetPhysicallyInstalledSystemMemory(ctypes.byref(kib))
total_mb = sum(d.size_mb or 0 for d in smbios.memory_devices(live))
assert total_mb * 1024 == kib.value, (total_mb, kib.value)
assert smbios.processors(live)[0].socket
print(f"live ok: {bb.product}  BIOS {b.version}  {total_mb} MB")
print("STATUS: SUCCESS")
