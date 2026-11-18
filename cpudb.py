#!/usr/bin/env python3
"""cpudb.py - lookup tables for wintools's Hardware tab: CPU code names, sockets
and TDP by CPUID family / model / stepping, chipset names, graphics-board
vendors, NVIDIA GPU code names and JEDEC memory manufacturer ids.

Rows come from public vendor specifications, not from a CPU-Z dump; a
processor, chipset or GPU that is not listed yields no fields at all."""

import re
from typing import NamedTuple

AMD, INTEL = "AuthenticAMD", "GenuineIntel"

AM4, AM5 = "Socket AM4 (1331)", "Socket AM5 (LGA1718)"
H4, H5, V1 = "Socket H4 (LGA1151)", "Socket H5 (LGA1200)", "Socket V1 (LGA1700)"
LGA1851 = "Socket LGA1851"


class CpuInfo(NamedTuple):
    name: str
    code_name: str
    tdp: str
    package: str
    technology: str
    revision: str
    mult_min: float | None
    mult_max: float | None
    pcie_gen: int | None    # the CPU's own PCIe generation (datasheet)


class _Rule(NamedTuple):
    vendor: str
    family: int         # CPUID extended family
    model: int          # CPUID extended model
    code: str
    package: str
    nm: int
    revisions: dict     # stepping -> CPU-Z revision
    steppings: tuple | None
    brand: re.Pattern | None
    mult_min: float | None
    pcie: int | None


def _r(vendor, family, model, code, package, nm, revisions=None, steppings=None,
       brand=None, mult_min=None, pcie=None):
    return _Rule(vendor, family, model, code, package, nm, revisions or {}, steppings,
                 re.compile(brand) if brand else None, mult_min, pcie)


# More specific rules (stepping or brand pattern) precede the general one for
# the same family / model: the first match wins.  A part is mobile when its brand
# string carries a mobile suffix; the unsuffixed and G / GE parts are desktop.
_MOBILE_ZEN1 = r"Ryzen \d (?:PRO )?\d{4}(?:U|H)\b"
_MOBILE_ZEN2_3 = r"Ryzen \d (?:PRO )?\d{4}(?:U|H|HS|HX|C)\b"
_MOBILE_ZEN4 = r"Ryzen \d (?:PRO )?8\d{3}(?:U|H|HS|HX)\b"
_DESKTOP_APU_8000 = r"Ryzen \d (?:PRO )?8\d{3}GE?\b"
_INTEL_LAPTOP = r"i[3579]-\d{4,5}(?:H|HQ|HK|HX|HL)\b"
FP5, FP6, FP7 = "Socket FP5 (BGA1140)", "Socket FP6 (BGA1140)", "Socket FP7 (BGA)"
BGA1440, BGA1528, BGA1356 = "Socket BGA1440", "Socket BGA1528", "Socket BGA1356"
_COFFEE_REV = {0xA: "U0", 0xB: "B0", 0xC: "P0", 0xD: "R0"}
_RULES = (
    # ---- AMD Zen / Zen+ (family 17h) ----
    _r(AMD, 0x17, 0x01, "Whitehaven", "Socket TR4 (4094)", 14, brand=r"Threadripper", pcie=3),
    _r(AMD, 0x17, 0x01, "Naples", "Socket SP3 (4094)", 14, brand=r"EPYC", pcie=3),
    _r(AMD, 0x17, 0x01, "Summit Ridge", AM4, 14, {1: "ZP-B1", 2: "ZP-B2"}, pcie=3),
    _r(AMD, 0x17, 0x08, "Colfax", "Socket TR4 (4094)", 12, brand=r"Threadripper", pcie=3),
    _r(AMD, 0x17, 0x08, "Pinnacle Ridge", AM4, 12, {2: "PiR-B2"}, pcie=3),
    _r(AMD, 0x17, 0x11, "Raven Ridge", FP5, 14, {0: "RV-A0", 1: "RV-B0"},
       brand=_MOBILE_ZEN1, pcie=3),
    _r(AMD, 0x17, 0x11, "Raven Ridge", AM4, 14, {0: "RV-A0", 1: "RV-B0"}, pcie=3),
    _r(AMD, 0x17, 0x18, "Picasso", FP5, 12, {1: "PCO-B1"}, brand=_MOBILE_ZEN1, pcie=3),
    _r(AMD, 0x17, 0x18, "Picasso", AM4, 12, {1: "PCO-B1"}, pcie=3),
    # ---- AMD Zen 2 ----
    _r(AMD, 0x17, 0x31, "Castle Peak", "Socket sTRX4 (4094)", 7, brand=r"Threadripper",
       pcie=4),
    _r(AMD, 0x17, 0x31, "Rome", "Socket SP3 (4094)", 7, brand=r"EPYC", pcie=4),
    _r(AMD, 0x17, 0x71, "Matisse", AM4, 7, {0: "MTS-B0"}, pcie=4),
    _r(AMD, 0x17, 0x60, "Renoir", FP6, 7, {1: "RN-A1"}, brand=_MOBILE_ZEN2_3, pcie=3),
    _r(AMD, 0x17, 0x60, "Renoir", AM4, 7, {1: "RN-A1"}, pcie=3),
    _r(AMD, 0x17, 0x68, "Lucienne", FP6, 7, {1: "LCN-A1"}, pcie=3),
    # ---- AMD Zen 3 ----
    _r(AMD, 0x19, 0x21, "Vermeer", AM4, 7, {0: "VMR-B0", 2: "VMR-B2"}, pcie=4),
    _r(AMD, 0x19, 0x50, "Cezanne", FP6, 7, {0: "CZN-A0", 1: "CZN-A1"},
       brand=_MOBILE_ZEN2_3, pcie=3),
    _r(AMD, 0x19, 0x50, "Cezanne", AM4, 7, {0: "CZN-A0", 1: "CZN-A1"}, pcie=3),
    _r(AMD, 0x19, 0x40, "Rembrandt", "Socket FP7 (BGA1140)", 6, {1: "RMB-B1"}, pcie=4),
    _r(AMD, 0x19, 0x44, "Rembrandt", "Socket FP7 (BGA1140)", 6, {1: "RMB-B1"}, pcie=4),
    # ---- AMD Zen 4 ----
    _r(AMD, 0x19, 0x61, "Dragon Range", "Socket FL1 (BGA1801)", 5,
       brand=r"Ryzen \d \d{4}HX", pcie=5),
    _r(AMD, 0x19, 0x61, "Raphael", AM5, 5, {1: "RPL-B1", 2: "RPL-B2"}, mult_min=4.0, pcie=5),
    _r(AMD, 0x19, 0x74, "Phoenix", AM5, 4, brand=_DESKTOP_APU_8000, pcie=4),
    _r(AMD, 0x19, 0x74, "Hawk Point", FP7, 4, brand=_MOBILE_ZEN4, pcie=4),
    _r(AMD, 0x19, 0x74, "Phoenix", FP7, 4, {1: "PHX-A1"}, pcie=4),
    _r(AMD, 0x19, 0x75, "Phoenix", AM5, 4, brand=_DESKTOP_APU_8000, pcie=4),
    _r(AMD, 0x19, 0x75, "Hawk Point", FP7, 4, brand=_MOBILE_ZEN4, pcie=4),
    _r(AMD, 0x19, 0x75, "Phoenix", FP7, 4, pcie=4),
    _r(AMD, 0x19, 0x78, "Phoenix", AM5, 4, brand=_DESKTOP_APU_8000, pcie=4),
    _r(AMD, 0x19, 0x78, "Phoenix", FP7, 4, pcie=4),
    # ---- AMD Zen 5 (family 1Ah) ----
    _r(AMD, 0x1A, 0x44, "Fire Range", "Socket FL1 (BGA)", 4, brand=r"Ryzen \d 9\d{3}HX",
       pcie=5),
    _r(AMD, 0x1A, 0x44, "Granite Ridge", AM5, 4, {0: "GNR-B0"}, mult_min=4.0, pcie=5),
    _r(AMD, 0x1A, 0x20, "Strix Point", "Socket FP8 (BGA)", 4, {0: "STX-A0"}, pcie=4),
    _r(AMD, 0x1A, 0x60, "Krackan Point", "Socket FP8 (BGA)", 4, pcie=4),
    _r(AMD, 0x1A, 0x70, "Strix Halo", "Socket FP11 (BGA)", 4, pcie=4),
    # ---- Intel Core 6th - 14th generation ----
    _r(INTEL, 6, 0x5E, "Skylake", BGA1440, 14, {3: "R0"}, brand=_INTEL_LAPTOP, pcie=3),
    _r(INTEL, 6, 0x5E, "Skylake", H4, 14, {3: "R0"}, mult_min=8.0, pcie=3),
    _r(INTEL, 6, 0x4E, "Skylake", BGA1356, 14, pcie=3),
    _r(INTEL, 6, 0x9E, "Kaby Lake", BGA1440, 14, {9: "B0"}, steppings=(9,),
       brand=_INTEL_LAPTOP, pcie=3),
    _r(INTEL, 6, 0x9E, "Kaby Lake", H4, 14, {9: "B0"}, steppings=(9,), mult_min=8.0, pcie=3),
    _r(INTEL, 6, 0x9E, "Coffee Lake", BGA1440, 14, _COFFEE_REV, steppings=(0xA, 0xB, 0xC, 0xD),
       brand=_INTEL_LAPTOP, pcie=3),
    _r(INTEL, 6, 0x9E, "Coffee Lake", H4, 14, _COFFEE_REV, steppings=(0xA, 0xB, 0xC, 0xD),
       mult_min=8.0, pcie=3),
    _r(INTEL, 6, 0x8E, "Comet Lake", BGA1528, 14, brand=r"i[3579]-10\d{3}", pcie=3),
    _r(INTEL, 6, 0x8E, "Whiskey Lake", BGA1528, 14, steppings=(0xB, 0xC),
       brand=r"i[3579]-8\d{3}U", pcie=3),
    _r(INTEL, 6, 0x8E, "Kaby Lake-R", BGA1356, 14, brand=r"i[3579]-8\d{3}U", pcie=3),
    _r(INTEL, 6, 0x8E, "Kaby Lake", BGA1356, 14, pcie=3),
    _r(INTEL, 6, 0xA5, "Comet Lake", BGA1440, 14, brand=_INTEL_LAPTOP, pcie=3),
    _r(INTEL, 6, 0xA5, "Comet Lake", H5, 14, {2: "G0", 3: "G1", 5: "Q0"}, mult_min=8.0,
       pcie=3),
    _r(INTEL, 6, 0xA6, "Comet Lake", BGA1528, 14, pcie=3),
    _r(INTEL, 6, 0xA7, "Rocket Lake", H5, 14, {1: "B0"}, mult_min=8.0, pcie=4),
    _r(INTEL, 6, 0x8C, "Tiger Lake", "Socket BGA1449", 10, pcie=4),
    _r(INTEL, 6, 0x8D, "Tiger Lake", "Socket BGA1787", 10, pcie=4),
    _r(INTEL, 6, 0x97, "Alder Lake", "Socket BGA1964", 10, brand=_INTEL_LAPTOP, pcie=5),
    _r(INTEL, 6, 0x97, "Alder Lake", V1, 10, {2: "C0", 5: "H0"}, mult_min=8.0, pcie=5),
    _r(INTEL, 6, 0x9A, "Alder Lake", "Socket BGA1744", 10),
    _r(INTEL, 6, 0xB7, "Raptor Lake", "Socket BGA1964", 10, brand=_INTEL_LAPTOP, pcie=5),
    _r(INTEL, 6, 0xB7, "Raptor Lake", V1, 10, {1: "B0"}, mult_min=8.0, pcie=5),
    _r(INTEL, 6, 0xBF, "Raptor Lake", V1, 10, mult_min=8.0, pcie=5),
    _r(INTEL, 6, 0xBA, "Raptor Lake", "Socket BGA1744", 10),
    # ---- Intel Core Ultra ----
    _r(INTEL, 6, 0xAA, "Meteor Lake", "Socket BGA2049", 7),
    _r(INTEL, 6, 0xAC, "Meteor Lake", "Socket BGA2049", 7),
    _r(INTEL, 6, 0xC6, "Arrow Lake", LGA1851, 3, {2: "B0"}, pcie=5),
    _r(INTEL, 6, 0xC5, "Arrow Lake", "Socket BGA2049", 3),
)

# vendor, model number, TDP (W; Intel: processor base power), maximum multiplier.
# Mobile parts are left out: their TDP is configurable.
_SKU_TEXT = """
AMD 7950X3D 120 57   AMD 7950X 170 57   AMD 7900X3D 120 56   AMD 7900X 170 56
AMD 7900 65 54       AMD 7800X3D 120 50  AMD 7700X 105 54     AMD 7700 65 53
AMD 7600X 105 53     AMD 7600 65 51      AMD 7500F 65 50
AMD 9950X3D 170 57   AMD 9950X 170 57    AMD 9900X3D 120 55   AMD 9900X 120 56
AMD 9800X3D 120 52   AMD 9700X 65 55     AMD 9600X 65 54      AMD 9600 65 52
AMD 5950X 105 49     AMD 5900XT 105 48   AMD 5900X 105 48     AMD 5800X3D 105 45
AMD 5800X 105 47     AMD 5800 65 46      AMD 5700X3D 105 41   AMD 5700X 65 46
AMD 5700G 65 46      AMD 5700 65 46      AMD 5600X 65 46      AMD 5600GT 65 46
AMD 5600G 65 44      AMD 5600 65 44      AMD 5500GT 65 44     AMD 5500 65 42
AMD 3950X 105 47     AMD 3900XT 105 47   AMD 3900X 105 46     AMD 3800XT 105 47
AMD 3800X 105 45     AMD 3700X 65 44     AMD 3600XT 95 45     AMD 3600X 95 44
AMD 3600 65 42       AMD 3500X 65 41     AMD 3400G 65 42      AMD 3300X 65 43
AMD 3200G 65 40      AMD 3100 65 39
AMD 2700X 105 43     AMD 2700 65 41      AMD 2600X 95 42.5    AMD 2600 65 39
AMD 2400G 65 39      AMD 2200G 65 37
AMD 1800X 95 40      AMD 1700X 95 39     AMD 1700 65 37       AMD 1600X 95 40
AMD 1600 65 36       AMD 1500X 65 37     AMD 1400 65 34       AMD 1300X 65 37
AMD 1200 65 34
INTEL 6700K 91 42    INTEL 6600K 91 39   INTEL 6700 65 40     INTEL 6600 65 39
INTEL 6500 65 36     INTEL 6400 65 33
INTEL 7700K 91 45    INTEL 7600K 91 42   INTEL 7700 65 42     INTEL 7600 65 41
INTEL 7500 65 38     INTEL 7400 65 35
INTEL 8700K 95 47    INTEL 8086K 95 50   INTEL 8700 65 46     INTEL 8600K 95 43
INTEL 8600 65 43     INTEL 8500 65 41    INTEL 8400 65 40
INTEL 9900KS 127 50  INTEL 9900K 95 50   INTEL 9900 65 50     INTEL 9700K 95 49
INTEL 9700 65 47     INTEL 9600K 95 46   INTEL 9600 65 46     INTEL 9400 65 39
INTEL 10900K 125 53  INTEL 10850K 125 52 INTEL 10700K 125 51  INTEL 10600K 125 48
INTEL 10900 65 52    INTEL 10700 65 48   INTEL 10600 65 48    INTEL 10400 65 43
INTEL 11900K 125 53  INTEL 11700K 125 50 INTEL 11600K 125 49  INTEL 11900 65 52
INTEL 11700 65 49    INTEL 11600 65 48   INTEL 11400 65 44
INTEL 12900KS 150 55 INTEL 12900K 125 52 INTEL 12700K 125 50  INTEL 12600K 125 49
INTEL 12900 65 51    INTEL 12700 65 49   INTEL 12600 65 48    INTEL 12400 65 44
INTEL 12100 60 43
INTEL 13900KS 150 60 INTEL 13900K 125 58 INTEL 13700K 125 54  INTEL 13600K 125 51
INTEL 13900 65 56    INTEL 13700 65 52   INTEL 13600 65 50    INTEL 13500 65 48
INTEL 13400 65 46
INTEL 14900KS 150 62 INTEL 14900K 125 60 INTEL 14700K 125 56  INTEL 14600K 125 53
INTEL 14900 65 58    INTEL 14700 65 54   INTEL 14600 65 52    INTEL 14500 65 50
INTEL 14400 65 47
INTEL 285K 125 57    INTEL 265K 125 55   INTEL 245K 125 52    INTEL 285 65 56
INTEL 265 65 53      INTEL 245 65 51
"""
_SKUS = {}
_words = _SKU_TEXT.split()
for _i in range(0, len(_words), 4):
    _SKUS[(INTEL if _words[_i] == "INTEL" else AMD, _words[_i + 1])] = (
        float(_words[_i + 2]), float(_words[_i + 3]))

_MODEL_TOKEN = {
    AMD: re.compile(r"Ryzen \d (?:PRO )?(\d{4}[A-Za-z0-9]*)"),
    INTEL: re.compile(r"\bi[3579]-(\d{4,5}[A-Z]{0,2})\b|\bUltra [3579] (\d{3}[A-Z]{0,2})\b"),
}


def _sku(vendor, brand):
    # An F suffix (no integrated graphics) shares its sibling's row.
    m = _MODEL_TOKEN[vendor].search(brand)
    if m is None:
        return None
    token = m[1] or m[2] if vendor == INTEL else m[1]
    return _SKUS.get((vendor, token)) or (
        _SKUS.get((vendor, token[:-1])) if token.endswith("F") else None)


def clean_name(vendor, brand):
    if vendor == AMD:
        name = re.sub(r"\s+(?:\w+-Core Processor|with .*|w/ .*)$", "", brand)
    else:
        name = brand.replace("(R)", "").replace("(TM)", "")
        name = re.sub(r"^\d+(?:st|nd|rd|th) Gen\s+", "", name)
        name = re.sub(r"\s+(?:CPU\b.*|@.*)$", "", name)
        name = re.sub(r"\b(i[3579])-(\d)", r"\1 \2", name)
    return " ".join(name.split())


def lookup(vendor, ext_family, ext_model, stepping, brand):
    brand = " ".join(brand.split())
    for rule in _RULES:
        if (rule.vendor, rule.family, rule.model) != (vendor, ext_family, ext_model):
            continue
        if rule.steppings is not None and stepping not in rule.steppings:
            continue
        if rule.brand is not None and not rule.brand.search(brand):
            continue
        sku = _sku(vendor, brand)
        return CpuInfo(clean_name(vendor, brand), rule.code,
                       f"{sku[0]:.1f} W" if sku else "", rule.package, f"{rule.nm} nm",
                       rule.revisions.get(stepping, ""), rule.mult_min,
                       sku[1] if sku else None, rule.pcie)
    return None


# ====================================================================
#  CHIPSETS
# ====================================================================

# AMD host bridge (the CPU's root complex) by PCI device id; CPU-Z names them all alike
_AMD_HOST = {0x1450, 0x1480, 0x14D8}
_AMD_LPC = 0x790E   # FCH LPC bridge: the same id on every AM4 / AM5 chipset
# Longest first: B650E must win over B650
_AMD_CHIPSETS = ("X870E", "X870", "B850", "B840", "X670E", "X670", "B650E", "B650",
                 "A620", "X570", "B550", "A520", "X470", "B450", "A320", "B350", "X370")

# Intel LPC / eSPI bridge ids with a single known chipset
_INTEL_LPC = {
    0xA143: "H110", 0xA144: "H170", 0xA145: "Z170", 0xA146: "Q170", 0xA147: "Q150",
    0xA148: "B150", 0xA2C4: "H270", 0xA2C5: "Z270", 0xA2C6: "Q270", 0xA2C7: "Q250",
    0xA2C8: "B250", 0xA2C9: "Z370", 0xA303: "H310", 0xA304: "H370", 0xA305: "Z390",
    0xA306: "Q370", 0xA308: "B360",
}
# Intel LPC id ranges that identify only the series
_INTEL_SERIES = ((0x0680, 0x069F, "400"), (0x4380, 0x43FF, "500"),
                 (0x7A00, 0x7A7F, "700"), (0x7A80, 0x7AFF, "600"))


def chipset(vendor_id, device_id, board_model):
    """(vendor, name) for a host bridge or LPC bridge, the two boxes CPU-Z draws; an
    id that is not tabled gives the vendor and the id in hex."""
    if vendor_id == 0x1022:
        if device_id in _AMD_HOST:
            return "AMD", "Ryzen SOC"
        if device_id == _AMD_LPC:
            for token in _AMD_CHIPSETS:
                if re.search(rf"(?<![A-Z0-9]){token}(?![0-9])", board_model.upper()):
                    return "AMD", token
        return "AMD", f"{device_id:04X}"
    if vendor_id == 0x8086:
        if device_id in _INTEL_LPC:
            return "Intel", _INTEL_LPC[device_id]
        for lo, hi, series in _INTEL_SERIES:
            if lo <= device_id <= hi:
                return "Intel", f"{series} Series"
        return "Intel", f"{device_id:04X}"
    return f"{vendor_id:04X}", f"{device_id:04X}"


# ====================================================================
#  GRAPHICS
# ====================================================================

# PCI subsystem vendor id -> the vendor name CPU-Z prints for the board
_BOARD_VENDORS = {
    0x1043: "ASUSTeK Computer Inc.", 0x1462: "Micro-Star International Co., Ltd.",
    0x1458: "Gigabyte Technology Co., Ltd.", 0x3842: "EVGA Corporation",
    0x19DA: "ZOTAC International (MCO) Ltd.", 0x196E: "PNY Technologies Inc.",
    0x1569: "Palit Microsystems Inc.", 0x10B0: "Gainward Co. Ltd.",
    0x10DE: "NVIDIA Corporation", 0x1849: "ASRock Incorporation",
    0x1682: "XFX Pine Group Inc.", 0x148C: "PowerColor", 0x1DA2: "Sapphire Technology Limited",
    0x174B: "Sapphire Technology Limited", 0x1B4C: "Galaxy Microsystems Ltd.",
    0x107D: "Leadtek Research Inc.", 0x1028: "Dell Inc.", 0x103C: "Hewlett-Packard Company",
    0x17AA: "Lenovo", 0x1025: "Acer Incorporated",
}


def board_vendor(subsystem_vendor):
    return _BOARD_VENDORS.get(subsystem_vendor, f"0x{subsystem_vendor:04X}")


class NvGpu(NamedTuple):
    code_name: str          # chip with its SKU suffix where tabled (GA102-300)
    technology: str
    rops: int | None
    tmus: int | None
    cores: int | None
    memory_type: str        # "" where board variants differ


TURING, AMPERE, ADA, BLACKWELL = "12 nm", "8 nm", "5 nm", "5 nm"
# device id: chip, process, ROPs, TMUs, shader cores, memory.  A part whose SKU data
# is not tabled keeps its chip name and process only.
NVIDIA_GPUS = {dev: NvGpu(*row) for dev, row in {
    0x1E02: ("TU102-400", TURING, 96, 288, 4608, "GDDR6"),      # TITAN RTX
    0x1E04: ("TU102-300", TURING, 88, 272, 4352, "GDDR6"),      # RTX 2080 Ti
    0x1E07: ("TU102-300", TURING, 88, 272, 4352, "GDDR6"),
    0x1E81: ("TU104-450", TURING, 64, 192, 3072, "GDDR6"),      # RTX 2080 Super
    0x1E82: ("TU104-400", TURING, 64, 184, 2944, "GDDR6"),      # RTX 2080
    0x1E87: ("TU104-400", TURING, 64, 184, 2944, "GDDR6"),
    0x1E84: ("TU104-410", TURING, 64, 160, 2560, "GDDR6"),      # RTX 2070 Super
    0x1F02: ("TU106-400", TURING, 64, 144, 2304, "GDDR6"),      # RTX 2070
    0x1F07: ("TU106-400", TURING, 64, 144, 2304, "GDDR6"),
    0x1F06: ("TU106-410", TURING, 64, 136, 2176, "GDDR6"),      # RTX 2060 Super
    0x1F42: ("TU106-410", TURING, 64, 136, 2176, "GDDR6"),
    0x1F47: ("TU106-410", TURING, 64, 136, 2176, "GDDR6"),
    0x1F08: ("TU106-200", TURING, 48, 120, 1920, "GDDR6"),      # RTX 2060
    0x2182: ("TU116-400", TURING, 48, 96, 1536, "GDDR6"),       # GTX 1660 Ti
    0x2184: ("TU116-300", TURING, 48, 88, 1408, "GDDR5"),       # GTX 1660
    0x21C4: ("TU116-300", TURING, 48, 88, 1408, "GDDR6"),       # GTX 1660 Super
    0x2187: ("TU116-250", TURING, 32, 80, 1280, "GDDR6"),       # GTX 1650 Super
    0x1F82: ("TU117-300", TURING, 32, 56, 896, ""),             # GTX 1650
    0x2203: ("GA102-350", AMPERE, 112, 336, 10752, "GDDR6X"),   # RTX 3090 Ti
    0x2204: ("GA102-300", AMPERE, 112, 328, 10496, "GDDR6X"),   # RTX 3090
    0x2208: ("GA102-225", AMPERE, 112, 320, 10240, "GDDR6X"),   # RTX 3080 Ti
    0x2206: ("GA102-200", AMPERE, 96, 272, 8704, "GDDR6X"),     # RTX 3080
    0x2216: ("GA102-202", AMPERE, 96, 272, 8704, "GDDR6X"),
    0x220A: ("GA102-220", AMPERE, 96, 280, 8960, "GDDR6X"),     # RTX 3080 12 GB
    0x2414: ("GA103-200", AMPERE, None, None, None, "GDDR6"),   # RTX 3060 Ti (GA103)
    0x2482: ("GA104-400", AMPERE, 96, 192, 6144, "GDDR6X"),     # RTX 3070 Ti
    0x2484: ("GA104-300", AMPERE, 96, 184, 5888, "GDDR6"),      # RTX 3070
    0x2488: ("GA104-302", AMPERE, 96, 184, 5888, "GDDR6"),
    0x2486: ("GA104-200", AMPERE, 80, 152, 4864, "GDDR6"),      # RTX 3060 Ti
    0x2489: ("GA104-202", AMPERE, 80, 152, 4864, "GDDR6"),
    0x2503: ("GA106-300", AMPERE, 48, 112, 3584, "GDDR6"),      # RTX 3060
    0x2504: ("GA106-302", AMPERE, 48, 112, 3584, "GDDR6"),
    0x2507: ("GA106-150", AMPERE, 32, 80, 2560, "GDDR6"),       # RTX 3050
    0x2582: ("GA107", AMPERE, None, None, None, "GDDR6"),       # RTX 3050 (GA107)
    0x2584: ("GA107", AMPERE, None, None, None, "GDDR6"),       # RTX 3050 6 GB
    0x2684: ("AD102-300", ADA, 176, 512, 16384, "GDDR6X"),      # RTX 4090
    0x2685: ("AD102-250", ADA, 176, 456, 14592, "GDDR6X"),      # RTX 4090 D
    0x2702: ("AD103-400", ADA, 112, 320, 10240, "GDDR6X"),      # RTX 4080 Super
    0x2704: ("AD103-300", ADA, 112, 304, 9728, "GDDR6X"),       # RTX 4080
    0x2705: ("AD103-275", ADA, 96, 264, 8448, "GDDR6X"),        # RTX 4070 Ti Super
    0x2782: ("AD104-400", ADA, 80, 240, 7680, "GDDR6X"),        # RTX 4070 Ti
    0x2783: ("AD104-350", ADA, 80, 224, 7168, "GDDR6X"),        # RTX 4070 Super
    0x2786: ("AD104-250", ADA, 64, 184, 5888, "GDDR6X"),        # RTX 4070
    0x2803: ("AD106-350", ADA, 48, 136, 4352, "GDDR6"),         # RTX 4060 Ti
    0x2805: ("AD106-351", ADA, 48, 136, 4352, "GDDR6"),         # RTX 4060 Ti 16 GB
    0x2882: ("AD107-400", ADA, 48, 96, 3072, "GDDR6"),          # RTX 4060
    0x2B85: ("GB202-300", BLACKWELL, 176, 680, 21760, "GDDR7"),  # RTX 5090
    0x2B87: ("GB202", BLACKWELL, None, None, None, "GDDR7"),    # RTX 5090 D
    0x2C02: ("GB203-400", BLACKWELL, 112, 336, 10752, "GDDR7"),  # RTX 5080
    0x2C05: ("GB203-300", BLACKWELL, 96, 280, 8960, "GDDR7"),   # RTX 5070 Ti
    0x2F04: ("GB205-300", BLACKWELL, 64, 192, 6144, "GDDR7"),   # RTX 5070
    0x2D04: ("GB206-300", BLACKWELL, 48, 144, 4608, "GDDR7"),   # RTX 5060 Ti
    0x2D05: ("GB206-250", BLACKWELL, 48, 120, 3840, "GDDR7"),   # RTX 5060
}.items()}


def nvidia_gpu(device_id):
    return NVIDIA_GPUS.get(device_id)


# ====================================================================
#  MEMORY
# ====================================================================

# JEDEC JEP106 (continuation count, code), both without the parity bit
_JEDEC = {(0, 0x4E): "Samsung", (0, 0x2D): "SK Hynix", (0, 0x2C): "Micron",
          (1, 0x18): "Kingston", (2, 0x1E): "Corsair", (4, 0x4D): "G.Skill",
          (5, 0x1B): "Crucial"}


def jedec_name(text):
    # Firmware prints the id as the two SPD bytes, continuation count first
    # ("029E" is Corsair); the reverse byte order is accepted too.
    m = re.fullmatch(r"(?:0[xX])?([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})", text.strip())
    if m is None:
        return text
    first, second = int(m[1], 16) & 0x7F, int(m[2], 16) & 0x7F
    return _JEDEC.get((first, second)) or _JEDEC.get((second, first)) or text
