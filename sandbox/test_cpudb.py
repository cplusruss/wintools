"""Contract test for cpudb.py: CPU identification table, chipset, board vendor,
NVIDIA code names and JEDEC manufacturer names."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cpudb  # noqa: E402

AMD, INTEL = "AuthenticAMD", "GenuineIntel"

# ---- this PC: the CPU-Z reference screenshot ----
info = cpudb.lookup(AMD, 0x19, 0x61, 2, "AMD Ryzen 9 7950X3D 16-Core Processor        ")
assert info is not None
assert info.name == "AMD Ryzen 9 7950X3D", info.name
assert info.code_name == "Raphael", info.code_name
assert info.technology == "5 nm", info.technology
assert info.package == "Socket AM5 (LGA1718)", info.package
assert info.tdp == "120.0 W", info.tdp
assert info.revision == "RPL-B2", info.revision
assert (info.mult_min, info.mult_max) == (4.0, 57.0), (info.mult_min, info.mult_max)
print("7950X3D ok")

# ---- one or more keys per covered generation: (key, brand) -> code name, nm ----
GENS = (
    # AMD Zen 1 .. Zen 5, desktop and mobile
    ((AMD, 0x17, 0x01, 1), "AMD Ryzen 7 1800X Eight-Core Processor", "Summit Ridge", "14 nm"),
    ((AMD, 0x17, 0x08, 2), "AMD Ryzen 7 2700X Eight-Core Processor", "Pinnacle Ridge", "12 nm"),
    ((AMD, 0x17, 0x11, 0), "AMD Ryzen 5 2400G with Radeon Vega Graphics", "Raven Ridge", "14 nm"),
    ((AMD, 0x17, 0x71, 0), "AMD Ryzen 9 3900X 12-Core Processor", "Matisse", "7 nm"),
    ((AMD, 0x17, 0x60, 1), "AMD Ryzen 7 4800H with Radeon Graphics", "Renoir", "7 nm"),
    ((AMD, 0x19, 0x21, 0), "AMD Ryzen 9 5900X 12-Core Processor", "Vermeer", "7 nm"),
    ((AMD, 0x19, 0x50, 0), "AMD Ryzen 7 5700G with Radeon Graphics", "Cezanne", "7 nm"),
    ((AMD, 0x19, 0x44, 1), "AMD Ryzen 7 6800H with Radeon Graphics", "Rembrandt", "6 nm"),
    ((AMD, 0x19, 0x61, 2), "AMD Ryzen 5 7600X 6-Core Processor", "Raphael", "5 nm"),
    ((AMD, 0x19, 0x61, 2), "AMD Ryzen 9 7945HX 16-Core Processor", "Dragon Range", "5 nm"),
    ((AMD, 0x19, 0x74, 1), "AMD Ryzen 7 7840HS w/ Radeon 780M Graphics", "Phoenix", "4 nm"),
    ((AMD, 0x1A, 0x44, 0), "AMD Ryzen 9 9950X 16-Core Processor", "Granite Ridge", "4 nm"),
    ((AMD, 0x1A, 0x20, 0), "AMD Ryzen AI 9 HX 370 w/ Radeon 890M", "Strix Point", "4 nm"),
    # Intel Core 6th gen .. Core Ultra 200S
    ((INTEL, 6, 0x5E, 3), "Intel(R) Core(TM) i7-6700K CPU @ 4.00GHz", "Skylake", "14 nm"),
    ((INTEL, 6, 0x9E, 9), "Intel(R) Core(TM) i7-7700K CPU @ 4.20GHz", "Kaby Lake", "14 nm"),
    ((INTEL, 6, 0x9E, 0xA), "Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz", "Coffee Lake", "14 nm"),
    ((INTEL, 6, 0x9E, 0xC), "Intel(R) Core(TM) i9-9900K CPU @ 3.60GHz", "Coffee Lake", "14 nm"),
    ((INTEL, 6, 0xA5, 5), "Intel(R) Core(TM) i9-10900K CPU @ 3.70GHz", "Comet Lake", "14 nm"),
    ((INTEL, 6, 0xA7, 1), "11th Gen Intel(R) Core(TM) i9-11900K @ 3.50GHz", "Rocket Lake", "14 nm"),
    ((INTEL, 6, 0x97, 2), "12th Gen Intel(R) Core(TM) i9-12900K", "Alder Lake", "10 nm"),
    ((INTEL, 6, 0xB7, 1), "13th Gen Intel(R) Core(TM) i9-13900K", "Raptor Lake", "10 nm"),
    ((INTEL, 6, 0xB7, 1), "14th Gen Intel(R) Core(TM) i9-14900K", "Raptor Lake", "10 nm"),
    ((INTEL, 6, 0xAA, 4), "Intel(R) Core(TM) Ultra 7 155H", "Meteor Lake", "7 nm"),
    ((INTEL, 6, 0xC6, 2), "Intel(R) Core(TM) Ultra 9 285K", "Arrow Lake", "3 nm"),
)
for key, brand, code, nm in GENS:
    got = cpudb.lookup(*key, brand)
    assert got is not None, (key, brand)
    assert (got.code_name, got.technology) == (code, nm), (key, brand, got)
    assert got.package, (key, brand, got)
print(f"generations ok: {len(GENS)} keys")


# ---- name cleanup, TDP and revision on a few known SKUs ----
def pick(vendor, fam, model, step, brand):
    got = cpudb.lookup(vendor, fam, model, step, brand)
    assert got is not None, brand
    return got


k = pick(INTEL, 6, 0xB7, 1, "13th Gen Intel(R) Core(TM) i9-13900K")
assert (k.name, k.tdp, k.revision, k.package) == (
    "Intel Core i9 13900K", "125.0 W", "B0", "Socket V1 (LGA1700)"), k
kf = pick(INTEL, 6, 0xB7, 1, "13th Gen Intel(R) Core(TM) i9-13900KF")
assert kf.name == "Intel Core i9 13900KF" and kf.tdp == "125.0 W", kf
s = pick(INTEL, 6, 0x5E, 3, "Intel(R) Core(TM) i7-6700K CPU @ 4.00GHz")
assert (s.name, s.tdp, s.package) == (
    "Intel Core i7 6700K", "91.0 W", "Socket H4 (LGA1151)"), s
u = pick(INTEL, 6, 0xC6, 2, "Intel(R) Core(TM) Ultra 9 285K")
assert (u.name, u.tdp) == ("Intel Core Ultra 9 285K", "125.0 W"), u
z = pick(AMD, 0x1A, 0x44, 0, "AMD Ryzen 9 9950X 16-Core Processor")
assert (z.name, z.tdp, z.package) == (
    "AMD Ryzen 9 9950X", "170.0 W", "Socket AM5 (LGA1718)"), z
m = pick(AMD, 0x17, 0x71, 0, "AMD Ryzen 9 3900X 12-Core Processor")
assert (m.name, m.tdp, m.package) == (
    "AMD Ryzen 9 3900X", "105.0 W", "Socket AM4 (1331)"), m
mob = pick(AMD, 0x19, 0x44, 1, "AMD Ryzen 7 6800H with Radeon Graphics")
assert mob.name == "AMD Ryzen 7 6800H" and mob.tdp == "", mob
print("names / tdp ok")

# ---- the same family/model resolves by brand pattern ----
a = pick(AMD, 0x19, 0x61, 2, "AMD Ryzen 9 7945HX 16-Core Processor")
b = pick(AMD, 0x19, 0x61, 2, "AMD Ryzen 9 7950X 16-Core Processor")
assert a.code_name != b.code_name and a.package != b.package, (a, b)
print("brand pattern ok")

# ---- an unknown key gives no fields ----
assert cpudb.lookup(AMD, 0x99, 0x99, 0, "AMD Unknown") is None
assert cpudb.lookup(INTEL, 0x77, 0x01, 0, "Intel(R) Unknown") is None
assert cpudb.lookup("HygonGenuine", 0x18, 0x00, 1, "Hygon C86") is None
print("unknown ok")

# ---- review: desktop APUs and CPUs sharing a model with a mobile part ----
AM4_PKG, AM5_PKG = "Socket AM4 (1331)", "Socket AM5 (LGA1718)"
SHARED = (
    # (key, brand, code name, package or package fragment)
    ((AMD, 0x19, 0x50, 0), "AMD Ryzen 5 5500 6-Core Processor", "Cezanne", AM4_PKG),
    ((AMD, 0x19, 0x50, 0), "AMD Ryzen 7 5700 8-Core Processor", "Cezanne", AM4_PKG),
    ((AMD, 0x19, 0x50, 0), "AMD Ryzen 5 PRO 5650GE with Radeon Graphics", "Cezanne", AM4_PKG),
    ((AMD, 0x19, 0x50, 0), "AMD Ryzen 5 5600H with Radeon Graphics", "Cezanne", "FP6"),
    ((AMD, 0x19, 0x50, 0), "AMD Ryzen 7 PRO 5850U with Radeon Graphics", "Cezanne", "FP6"),
    ((AMD, 0x17, 0x60, 1), "AMD Ryzen 5 4500 6-Core Processor", "Renoir", AM4_PKG),
    ((AMD, 0x17, 0x60, 1), "AMD Ryzen 3 4100 4-Core Processor", "Renoir", AM4_PKG),
    ((AMD, 0x17, 0x60, 1), "AMD Ryzen 5 4600G with Radeon Graphics", "Renoir", AM4_PKG),
    ((AMD, 0x17, 0x60, 1), "AMD Ryzen 7 4800U with Radeon Graphics", "Renoir", "FP6"),
    ((AMD, 0x17, 0x18, 1), "AMD Ryzen 5 PRO 3500U w/ Radeon Vega Mobile Gfx", "Picasso", "FP5"),
    ((AMD, 0x17, 0x18, 1), "AMD Ryzen 5 3400G with Radeon Vega Graphics", "Picasso", AM4_PKG),
    ((AMD, 0x17, 0x11, 1), "AMD Ryzen 7 PRO 2700U w/ Radeon Vega Mobile Gfx", "Raven Ridge", "FP5"),
    ((AMD, 0x19, 0x75, 2), "AMD Ryzen 7 8700G w/ Radeon 780M Graphics", "Phoenix", AM5_PKG),
    ((AMD, 0x19, 0x74, 1), "AMD Ryzen 5 8600G w/ Radeon 760M Graphics", "Phoenix", AM5_PKG),
    ((AMD, 0x19, 0x75, 2), "AMD Ryzen 7 8840HS w/ Radeon 780M Graphics", "Hawk Point", "FP"),
    ((INTEL, 6, 0xA5, 2), "Intel(R) Core(TM) i7-10750H CPU @ 2.60GHz", "Comet Lake", "BGA"),
    ((INTEL, 6, 0x9E, 0xA), "Intel(R) Core(TM) i7-8750H CPU @ 2.20GHz", "Coffee Lake", "BGA"),
    ((INTEL, 6, 0x9E, 9), "Intel(R) Core(TM) i7-7700HQ CPU @ 2.80GHz", "Kaby Lake", "BGA"),
    ((INTEL, 6, 0x5E, 3), "Intel(R) Core(TM) i7-6700HQ CPU @ 2.60GHz", "Skylake", "BGA"),
    ((INTEL, 6, 0x97, 2), "12th Gen Intel(R) Core(TM) i9-12900HX", "Alder Lake", "BGA"),
    ((INTEL, 6, 0xB7, 1), "13th Gen Intel(R) Core(TM) i9-13980HX", "Raptor Lake", "BGA"),
    ((INTEL, 6, 0x8E, 0xC), "Intel(R) Core(TM) i7-10510U CPU @ 1.80GHz", "Comet Lake", "BGA"),
    ((INTEL, 6, 0x8E, 0xC), "Intel(R) Core(TM) i7-8565U CPU @ 1.80GHz", "Whiskey Lake", "BGA"),
    ((INTEL, 6, 0x8E, 0xA), "Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz", "Kaby Lake-R", "BGA"),
    ((INTEL, 6, 0x8E, 9), "Intel(R) Core(TM) i7-7500U CPU @ 2.70GHz", "Kaby Lake", "BGA"),
    # the desktop parts on the same models stay on their LGA sockets
    ((INTEL, 6, 0xA5, 5), "Intel(R) Core(TM) i9-10900K CPU @ 3.70GHz", "Comet Lake", "LGA1200"),
    ((INTEL, 6, 0x9E, 0xA), "Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz", "Coffee Lake", "LGA1151"),
    ((INTEL, 6, 0x97, 2), "12th Gen Intel(R) Core(TM) i9-12900K", "Alder Lake", "LGA1700"),
    ((INTEL, 6, 0xB7, 1), "13th Gen Intel(R) Core(TM) i9-13900K", "Raptor Lake", "LGA1700"),
)
for key, brand, code, pkg in SHARED:
    got = pick(*key, brand)
    assert got.code_name == code, (brand, got)
    if pkg in (AM4_PKG, AM5_PKG):
        assert got.package == pkg, (brand, got)
    else:
        assert pkg in got.package, (brand, got)
        assert ("LGA" not in got.package) == (pkg in ("BGA", "FP6", "FP5", "FP")), (brand, got)
print(f"shared models ok: {len(SHARED)} cases")

# ---- review: the CPU's PCIe generation is a datasheet column ----
for key, brand, gen in (
        ((AMD, 0x19, 0x61, 2), "AMD Ryzen 9 7950X3D 16-Core Processor", 5),
        ((AMD, 0x1A, 0x44, 0), "AMD Ryzen 9 9950X 16-Core Processor", 5),
        ((AMD, 0x19, 0x21, 0), "AMD Ryzen 9 5900X 12-Core Processor", 4),
        ((AMD, 0x17, 0x71, 0), "AMD Ryzen 9 3900X 12-Core Processor", 4),
        ((AMD, 0x19, 0x50, 0), "AMD Ryzen 7 5700G with Radeon Graphics", 3),
        ((AMD, 0x17, 0x08, 2), "AMD Ryzen 7 2700X Eight-Core Processor", 3),
        ((AMD, 0x17, 0x01, 1), "AMD Ryzen 7 1800X Eight-Core Processor", 3),
        ((AMD, 0x19, 0x75, 2), "AMD Ryzen 7 8700G w/ Radeon 780M Graphics", 4),
        ((INTEL, 6, 0xB7, 1), "14th Gen Intel(R) Core(TM) i9-14900K", 5),
        ((INTEL, 6, 0x97, 2), "12th Gen Intel(R) Core(TM) i9-12900K", 5),
        ((INTEL, 6, 0xC6, 2), "Intel(R) Core(TM) Ultra 9 285K", 5),
        ((INTEL, 6, 0xA7, 1), "11th Gen Intel(R) Core(TM) i9-11900K @ 3.50GHz", 4),
        ((INTEL, 6, 0xA5, 5), "Intel(R) Core(TM) i9-10900K CPU @ 3.70GHz", 3),
        ((INTEL, 6, 0x9E, 0xC), "Intel(R) Core(TM) i9-9900K CPU @ 3.60GHz", 3),
        ((INTEL, 6, 0x5E, 3), "Intel(R) Core(TM) i7-6700K CPU @ 4.00GHz", 3)):
    assert pick(*key, brand).pcie_gen == gen, (brand, pick(*key, brand).pcie_gen)
assert pick(INTEL, 6, 0xAA, 4, "Intel(R) Core(TM) Ultra 7 155H").pcie_gen is None
print("pcie generation ok")

# ---- chipset / southbridge: (vendor, name) as CPU-Z shows the two boxes ----
for dev in (0x1450, 0x1480, 0x14D8):
    assert cpudb.chipset(0x1022, dev, "") == ("AMD", "Ryzen SOC"), hex(dev)
assert cpudb.chipset(0x1022, 0x790E, "ProArt B650-CREATOR") == ("AMD", "B650")
assert cpudb.chipset(0x1022, 0x790E, "ROG STRIX B650E-F GAMING WIFI") == ("AMD", "B650E")
assert cpudb.chipset(0x1022, 0x790E, "ROG CROSSHAIR X870E HERO") == ("AMD", "X870E")
assert cpudb.chipset(0x1022, 0x790E, "Mystery Board") == ("AMD", "790E")
assert cpudb.chipset(0x1022, 0x1234, "ProArt B650-CREATOR") == ("AMD", "1234")
assert cpudb.chipset(0x8086, 0xA145, "") == ("Intel", "Z170")
assert cpudb.chipset(0x8086, 0xA2C9, "") == ("Intel", "Z370")
assert cpudb.chipset(0x8086, 0x7A84, "") == ("Intel", "600 Series")
assert cpudb.chipset(0x8086, 0x7A04, "") == ("Intel", "700 Series")
assert cpudb.chipset(0x8086, 0xFFFF, "") == ("Intel", "FFFF")
assert cpudb.chipset(0x1234, 0x00AB, "") == ("1234", "00AB")
print("chipset names ok")

# ---- graphics-board vendor: the full subsystem vendor name ----
for ven, name in ((0x1043, "ASUSTeK Computer Inc."), (0x1462, "Micro-Star International Co., Ltd."),
                  (0x1458, "Gigabyte Technology Co., Ltd."), (0x3842, "EVGA Corporation"),
                  (0x19DA, "ZOTAC International (MCO) Ltd."), (0x196E, "PNY Technologies Inc."),
                  (0x1569, "Palit Microsystems Inc."), (0x10B0, "Gainward Co. Ltd."),
                  (0x10DE, "NVIDIA Corporation")):
    assert cpudb.board_vendor(ven) == name, (hex(ven), cpudb.board_vendor(ven))
assert cpudb.board_vendor(0xBEEF) == "0xBEEF"
print("board vendors ok")

# ---- NVIDIA device id -> code name with SKU, process, ROPs, TMUs, cores, memory ----
g = cpudb.nvidia_gpu(0x2204)                              # RTX 3090: the CPU-Z screenshot
assert (g.code_name, g.technology, g.rops, g.tmus, g.cores, g.memory_type) == (
    "GA102-300", "8 nm", 112, 328, 10496, "GDDR6X"), g
g = cpudb.nvidia_gpu(0x2684)                              # RTX 4090
assert (g.code_name, g.technology, g.rops, g.tmus, g.cores) == (
    "AD102-300", "5 nm", 176, 512, 16384), g
g = cpudb.nvidia_gpu(0x1E04)                              # RTX 2080 Ti
assert (g.code_name, g.technology, g.rops, g.tmus, g.cores, g.memory_type) == (
    "TU102-300", "12 nm", 88, 272, 4352, "GDDR6"), g
g = cpudb.nvidia_gpu(0x2B85)                              # RTX 5090
assert (g.code_name, g.technology, g.cores, g.memory_type) == (
    "GB202-300", "5 nm", 21760, "GDDR7"), g
assert cpudb.nvidia_gpu(0x2184).memory_type == "GDDR5"    # GTX 1660
g = cpudb.nvidia_gpu(0x2582)                              # a part whose SKU data is not tabled
assert g.code_name == "GA107" and g.rops is None and g.tmus is None and g.cores is None, g
assert cpudb.nvidia_gpu(0xFFFF) is None
# 4 TMUs per SM everywhere; 64 cores per Turing SM, 128 per later SM
for dev, g in cpudb.NVIDIA_GPUS.items():
    if g.cores is not None:
        per_sm = 64 if g.code_name.startswith("TU1") else 128
        assert g.tmus == g.cores // per_sm * 4, (hex(dev), g)
print("nvidia gpus ok")

# ---- JEDEC ids: the count-then-code text SMBIOS strings carry, and the reverse ----
assert cpudb.jedec_name("Corsair") == "Corsair"
for text, name in (("802C", "Micron"), ("80CE", "Samsung"), ("80AD", "SK Hynix"),
                   ("04CD", "G.Skill"), ("029E", "Corsair"), ("859B", "Crucial"),
                   ("0198", "Kingston")):
    assert cpudb.jedec_name(text) == name, (text, cpudb.jedec_name(text))
    assert cpudb.jedec_name("0x" + text) == name, text
    assert cpudb.jedec_name(text[2:] + text[:2]) == name, (text[2:] + text[:2])   # reversed
assert cpudb.jedec_name("1234") == "1234"
assert cpudb.jedec_name("") == ""
print("jedec ok")
print("STATUS: SUCCESS")
