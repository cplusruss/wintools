"""Contract test for hwinfo CPUID: the executable thunk, signature decode,
the instruction list (synthetic registers and this PC) and core pinning."""

import ctypes
import re
import sys
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hwinfo  # noqa: E402

key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                     r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
reg_name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
reg_ident = winreg.QueryValueEx(key, "Identifier")[0]
reg_vendor = winreg.QueryValueEx(key, "VendorIdentifier")[0]

# ---- raw thunk: leaf 0 spells the vendor in EBX, EDX, ECX ----
eax, ebx, ecx, edx = hwinfo.cpuid(0)
vendor = b"".join(r.to_bytes(4, "little") for r in (ebx, edx, ecx)).decode("ascii")
assert vendor == reg_vendor, (vendor, reg_vendor)
assert eax >= 7, eax
assert hwinfo.cpuid(0x80000000)[0] >= 0x80000008
# sub-leaf is honoured: the cache leaf enumerates caches, the last sub-leaf reports type 0
cache_leaf = 0x8000001D if vendor == "AuthenticAMD" else 4
types = [hwinfo.cpuid(cache_leaf, i)[0] & 0x1F for i in range(8)]
assert types[0] != 0 and 0 in types, types
print(f"thunk ok: {vendor}  max leaf {eax}")

# ---- identity against the registry ----
ident = hwinfo.identity()
assert ident.vendor == reg_vendor
assert ident.brand == reg_name, (ident.brand, reg_name)
m = re.fullmatch(r"\w+ Family (\d+) Model (\d+) Stepping (\d+)", reg_ident)
assert m, reg_ident
assert (ident.ext_family, ident.ext_model, ident.stepping) == tuple(map(int, m.groups())), \
    (ident, reg_ident)
print(f"identity ok: {ident}")

# ---- signature decode: AMD Zen 4 (CPU-Z shows F 1 2 19 61) and Intel Raptor Lake ----
assert hwinfo.decode_signature(0x00A60F12) == (0xF, 1, 2, 0x19, 0x61)
assert hwinfo.decode_signature(0x000B0671) == (6, 7, 1, 6, 0xB7)
assert hwinfo.decode_signature(0x000906EA) == (6, 0xE, 0xA, 6, 0x9E)
assert hwinfo.decode_signature(0x00800F82) == (0xF, 8, 2, 0x17, 0x08)
assert hwinfo.hex_id(0xF) == "F" and hwinfo.hex_id(0x19) == "19" and hwinfo.hex_id(0xB7) == "B7"
print("decode ok")


# ---- instruction list from synthetic registers ----
def bits(*positions):
    return sum(1 << p for p in positions)


def fake(vendor_id, leaf1, leaf7, ext1):
    regs = {(0, 0): (13, 0, 0, 0), (1, 0): leaf1, (7, 0): leaf7,
            (0x80000000, 0): (0x80000008, 0, 0, 0), (0x80000001, 0): ext1}
    return lambda leaf, sub=0: regs[(leaf, sub)]


AMD = fake("AuthenticAMD",
           (0, 0, bits(0, 9, 19, 20, 25, 27, 28, 12), bits(23, 25, 26)),
           (0, bits(5, 16, 29), 0, 0),
           (0, 0, bits(2, 6), bits(22, 29)))
assert hwinfo.format_instructions("AuthenticAMD", AMD) == (
    "MMX(+), SSE (1, 2, 3, 4.1, 4.2, 4A), SSSE3, x86-64, AMD-V, "
    "AES, AVX, AVX2, AVX512, FMA3, SHA")
INTEL = fake("GenuineIntel",
             (0, 0, bits(0, 5, 9, 19, 20, 25, 27, 28, 12), bits(23, 25, 26)),
             (0, bits(5, 29), 0, 0),
             (0, 0, bits(6), bits(29)))               # SSE4A bit set, but Intel
assert hwinfo.format_instructions("GenuineIntel", INTEL) == (
    "MMX, SSE (1, 2, 3, 4.1, 4.2), SSSE3, EM64T, VT-x, AES, AVX, "
    "AVX2, FMA3, SHA")
BARE = fake("GenuineIntel", (0, 0, 0, 0), (0, 0, 0, 0), (0, 0, 0, 0))
assert hwinfo.format_instructions("GenuineIntel", BARE) == ""
NO_OS_AVX = fake("GenuineIntel", (0, 0, bits(28), 0), (0, bits(5), 0, 0), (0, 0, 0, 0))
assert "AVX" not in hwinfo.format_instructions("GenuineIntel", NO_OS_AVX).split(", "), \
    "AVX needs OSXSAVE"
print("instruction format ok")

# ---- this PC ----
text = hwinfo.instructions()
tokens = text.split(", ")
assert "AVX512" in tokens and "SHA" in tokens and "AES" in tokens, text
if "7950X3D" in hwinfo.identity().brand:
    # CPU-Z 2.15 on this PC, Hyper-V hiding AMD-V
    assert text == ("MMX(+), SSE (1, 2, 3, 4.1, 4.2, 4A), SSSE3, x86-64, AES, AVX, AVX2, "
                    "AVX512, FMA3, SHA"), text
print(f"instructions ok: {text}")

# ---- pinning to a core: same answers, previous affinity restored ----
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentThread.restype = ctypes.c_void_p
k32.SetThreadAffinityMask.restype = ctypes.c_size_t
k32.SetThreadAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]


def current_mask():
    prev = k32.SetThreadAffinityMask(k32.GetCurrentThread(), 1)
    k32.SetThreadAffinityMask(k32.GetCurrentThread(), prev)
    return prev


before = current_mask()
last = bin(before).count("1") - 1
for cpu in (0, last):
    with hwinfo.pinned(cpu):
        assert current_mask() == 1 << cpu, (cpu, hex(current_mask()))
        assert hwinfo.identity().brand == reg_name
assert current_mask() == before, (hex(current_mask()), hex(before))
try:
    with hwinfo.pinned(64):
        raise AssertionError("pinned(64) was accepted")
except hwinfo.HwError:
    pass
assert current_mask() == before
print("pinning ok")
print("STATUS: SUCCESS")
