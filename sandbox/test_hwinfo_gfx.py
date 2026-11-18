"""Contract test for hwinfo DXGI adapters, the NVIDIA readout (nvidia-smi plus
NVML) and the Windows / DirectX / microcode readouts."""

import re
import sys
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gpu  # noqa: E402
import hwinfo  # noqa: E402

# ---- DXGI: hardware adapters only, bus location resolved ----
adapters = hwinfo.dxgi_adapters()
assert adapters, "no DXGI adapter"
for a in adapters:
    assert "Basic Render" not in a.name, a
    assert a.name and a.vendor and a.device and a.vram > 0, a
    assert a.bus is not None and a.device_number is not None, a
assert len(hwinfo.dxgi_adapters(include_virtual=True)) >= len(adapters)
assert all(a.error == "" for a in adapters), [a.error for a in adapters]
# exactly one adapter drives the primary display
assert [a.primary for a in adapters].count(True) == 1, [a.primary for a in adapters]
print("dxgi ok:", [(a.name, a.vendor, a.device, f"{a.revision:02X}", a.vram >> 20)
                   for a in adapters])

# ---- each adapter maps to a distinct PCI device (two identical cards here) ----
devs = hwinfo.pci_devices()
spots = [(a.bus, a.device_number, a.function) for a in adapters]
assert len(set(spots)) == len(spots), spots
for a in adapters:
    d = hwinfo.pci_device_at(devs, a.bus, a.device_number, a.function)
    assert (d.vendor, d.device, d.revision) == (a.vendor, a.device, a.revision), (a, d)
print("adapter to PCI mapping ok")

# ---- NVIDIA: nvidia-smi names equal DXGI names, clocks and limits are real ----
nv = [a for a in adapters if a.vendor == 0x10DE]
assert nv, "this PC has an NVIDIA adapter"
smi = gpu.run(["--query-gpu=pci.bus_id,name", "--format=csv,noheader,nounits"])
names = {}
for line in smi.strip().splitlines():
    bus_id, name = (f.strip() for f in line.split(","))
    m = re.fullmatch(r"[0-9A-F]{8}:([0-9A-F]{2}):([0-9A-F]{2})\.(\d)", bus_id)
    assert m, bus_id
    names[(int(m[1], 16), int(m[2], 16), int(m[3]))] = name
infos = hwinfo.nvidia_infos()
assert set(infos) == set(names), (set(infos), set(names))
for a in nv:
    spot = (a.bus, a.device_number, a.function)
    assert names[spot] == a.name, (names[spot], a.name)
    info = infos[spot]
    assert info.core_mhz > 0 and info.memory_mhz > 0, info
    assert not hasattr(info, "shader_mhz"), "CPU-Z leaves Shader / SoC empty on NVIDIA"
    assert info.core_mhz < 4000 and info.memory_mhz < 40000, info
    assert 10 < info.tdp_w < 1000, info
    assert info.bus_width in range(32, 8193, 32), info
    assert info.memory_mib > 0, info
    print(f"nvidia ok: {a.name} {spot} core {info.core_mhz} MHz  mem {info.memory_mhz} MHz  "
          f"{info.tdp_w} W  {info.bus_width}-bit  {info.memory_mib} MiB")

# ---- N/A, Not Supported and friends read as no value; anything else must be a number ----
for text in ("N/A", "[N/A]", "[Not Supported]", "Not Supported"):
    assert hwinfo._smi_number(text) is None, text
assert hwinfo._smi_number("350.00") == 350.0 and hwinfo._smi_number("210") == 210.0
try:
    hwinfo._smi_number("garbage")
    raise AssertionError("a non-number was accepted")
except hwinfo.HwError:
    pass

# ---- one adapter whose PCI location cannot be read is flagged, the others are not ----
real_location = hwinfo._pci_location
seen = []


def flaky(desc):
    seen.append(desc.Description)
    if len(seen) == 2:
        raise hwinfo.HwError("D3DKMTQueryAdapterInfo(test): 0xC0000001")
    return real_location(desc)


hwinfo._pci_location = flaky
try:
    mixed = hwinfo.dxgi_adapters()
finally:
    hwinfo._pci_location = real_location
assert len(mixed) == len(adapters), (len(mixed), len(adapters))
assert [bool(a.error) for a in mixed] == [False, True], [a.error for a in mixed]
bad = mixed[1]
assert "D3DKMT" in bad.error and bad.bus is None and bad.device_number is None
assert bad.name == adapters[1].name and bad.vendor == adapters[1].vendor
assert mixed[0] == adapters[0]
print("adapter error isolation ok")

# ---- Windows version: product, display version, build.UBR ----
text = hwinfo.windows_version()
key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                     r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
build = winreg.QueryValueEx(key, "CurrentBuildNumber")[0]
ubr = winreg.QueryValueEx(key, "UBR")[0]
disp = winreg.QueryValueEx(key, "DisplayVersion")[0]
assert text.endswith(f"{disp} ({build}.{ubr})"), (text, disp, build, ubr)
want = "Windows 11" if int(build) >= 22000 else "Windows 10"
assert text.startswith(want), text
print(f"windows ok: {text}")

# ---- DirectX: feature level of the default adapter ----
dx = hwinfo.directx_version()
assert re.fullmatch(r"DirectX 1[12] \(FL 1[12]_[0-2]\)", dx), dx
print(f"directx ok: {dx}")

# ---- no Direct3D 12 is "not exposed": the value is empty ----
real_load = hwinfo._load_d3d12


def missing():
    raise OSError("d3d12.dll not found")


class NoLevel:
    @staticmethod
    def D3D12CreateDevice(*_args):
        return 0x887A0004 - (1 << 32)          # DXGI_ERROR_UNSUPPORTED


hwinfo._load_d3d12 = missing
try:
    assert hwinfo.directx_version() == ""
    hwinfo._load_d3d12 = lambda: NoLevel
    assert hwinfo.directx_version() == ""
finally:
    hwinfo._load_d3d12 = real_load
assert hwinfo.directx_version() == dx

# ---- microcode from the registry: hex; AMD in the low dword, Intel in the high ----
mc = hwinfo.microcode()
key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                     r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
raw = winreg.QueryValueEx(key, "Update Revision")[0]
amd = hwinfo.identity().vendor == "AuthenticAMD"
rev = int.from_bytes(raw[:4] if amd else raw[4:8], "little")
assert mc == f"0x{rev:X}", (mc, raw)
print(f"microcode ok: {mc}")
print("STATUS: SUCCESS")
