"""Contract test for hwinfo SetupAPI / DEVPKEY: PCI devices, bridges, PCIe link
properties of the primary GPU and the highest root-port generation."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hwinfo  # noqa: E402

# ---- text helpers ----
assert hwinfo.link_speed_text(1) == "2.5 GT/s"
assert hwinfo.link_speed_text(4) == "16.0 GT/s"
assert hwinfo.link_speed_text(5) == "32.0 GT/s"
assert hwinfo.pcie_bus_text(4) == "PCI-Express 4.0"
assert hwinfo.pcie_bus_text(5, rate=True) == "PCI-Express 5.0 (32.0 GT/s)"
assert hwinfo.link_width_text(16) == "x16"
for bad in (0, 7):
    try:
        hwinfo.link_speed_text(bad)
        raise AssertionError(f"link speed {bad} was accepted")
    except hwinfo.HwError:
        pass
print("text ok")

# ---- the device list equals what the PnP manager reports as present ----
devs = hwinfo.pci_devices()
ps = ("(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'PCI\\*' }"
      " | Measure-Object).Count")
count = int(subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, check=True).stdout)
assert len(devs) == count, (len(devs), count)
for d in devs:
    assert d.instance_id.startswith("PCI\\VEN_"), d
    assert 0 < d.vendor <= 0xFFFF and 0 <= d.device <= 0xFFFF, d
    assert f"VEN_{d.vendor:04X}&DEV_{d.device:04X}" in d.instance_id, d
    assert 0 <= d.base_class <= 0xFF and 0 <= d.sub_class <= 0xFF, d
print(f"devices ok: {len(devs)}")

# ---- host bridge and ISA bridge ----
host = hwinfo.host_bridge(devs)
assert (host.base_class, host.sub_class) == (6, 0) and host.bus == 0, host
assert (host.dev_number, host.function) == (0, 0), host
isa = hwinfo.isa_bridge(devs)
assert (isa.base_class, isa.sub_class) == (6, 1), isa
assert isinstance(host.revision, int) and isinstance(isa.revision, int)
print(f"bridges ok: host {host.vendor:04X}:{host.device:04X} rev {host.revision:02X}  "
      f"isa {isa.vendor:04X}:{isa.device:04X} rev {isa.revision:02X}")

# ---- the primary GPU carries current and max link width / speed ----
gpu = hwinfo.dxgi_adapters()[0]
dev = hwinfo.pci_device_at(devs, gpu.bus, gpu.device_number, gpu.function)
assert (dev.vendor, dev.device) == (gpu.vendor, gpu.device), (dev, gpu)
assert dev.subsystem == gpu.subsystem, (hex(dev.subsystem), hex(gpu.subsystem))
for speed in (dev.current_speed, dev.max_speed):
    assert speed in range(1, 7), dev
for width in (dev.current_width, dev.max_width):
    assert width in (1, 2, 4, 8, 16, 32), dev
assert dev.current_speed <= dev.max_speed and dev.current_width <= dev.max_width, dev
print(f"gpu link ok: {dev.current_width}x @ {hwinfo.link_speed_text(dev.current_speed)} "
      f"of {dev.max_width}x @ {hwinfo.link_speed_text(dev.max_speed)}")

# ---- devices that are not there are "not exposed", not errors ----
assert hwinfo.host_bridge([]) is None and hwinfo.isa_bridge([]) is None
assert hwinfo.host_bridge([d for d in devs if (d.base_class, d.sub_class) != (6, 0)]) is None
assert hwinfo.isa_bridge([d for d in devs if (d.base_class, d.sub_class) != (6, 1)]) is None
assert hwinfo.pci_device_at(devs, 250, 31, 7) is None
assert hwinfo.pci_device_at(devs, gpu.bus, gpu.device_number, gpu.function) is dev
print("absent devices ok")

# ---- the board's PCIe generation: root ports only; nothing else is a source ----
roots = [d for d in devs if d.is_root_port]
assert roots and all((d.base_class, d.sub_class) == (6, 4) for d in roots)
exposed = [d.max_speed for d in roots if d.max_speed]
assert hwinfo.max_root_port_speed(devs) == (max(exposed) if exposed else None)
port = roots[0]._replace(max_speed=3, current_speed=None)
dev5 = dev._replace(is_root_port=False, current_speed=5, max_speed=5)
assert hwinfo.max_root_port_speed([port, dev5]) == 3, "root port data wins when present"
assert hwinfo.max_root_port_speed([roots[0]._replace(max_speed=None), dev5]) is None, \
    "an endpoint's link speed is not the board's"
assert hwinfo.max_root_port_speed([]) is None
print(f"board generation ok: {len(roots)} root ports, {len(exposed)} publishing")
print("STATUS: SUCCESS")
