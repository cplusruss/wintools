"""Contract test for gpu.py: nvidia-smi parsing, command building, profile
XML round-trip, boot script, and GpuPage construction.  Read-only: no
nvidia-smi write command runs."""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import gpu  # noqa: E402
import tweaks  # noqa: E402

P = {
    "bus": "00000000:01:00.0", "power_limit": 220, "target_temp": 78,
    "gpu_lock": (210, 1800), "mem_lock": None, "cuda_clocks": True,
    "compute_mode": "Exclusive_Process", "accounting": False,
}


def test_commands():
    i = ["-i", P["bus"]]
    assert gpu.profile_commands(P) == [
        i + ["-pl", "220"], i + ["-gtt", "78"], i + ["-lgc", "210,1800"],
        i + ["-rmc"], i + ["-cc", "1"], i + ["-c", "3"], i + ["-am", "0"]]
    no_t = {**P, "target_temp": None}
    assert not any("-gtt" in c for c in gpu.profile_commands(no_t))


def test_xml_roundtrip():
    q = {**P, "target_temp": None, "gpu_lock": None, "mem_lock": (405, 9501)}
    xml = tweaks.config_to_xml([("perf", True)],
                               [gpu.profile_element(P), gpu.profile_element(q)])
    root = ET.fromstring(xml)
    assert tweaks.xml_to_config(xml) == [("perf", True)]
    assert gpu.profiles_from_root(root) == [P, q]


def test_boot_script():
    s = gpu.boot_script([P], r"C:\Windows\system32\nvidia-smi.exe")
    lines = s.split("\r\n")
    assert lines[0] == "@echo off"
    assert lines[1] == (r"C:\Windows\system32\nvidia-smi.exe -i "
                        "00000000:01:00.0 -pl 220")
    assert len(lines) == 1 + 7 + 1 and lines[-1] == ""


def test_reasons():
    assert gpu.reasons_text(0x20) == "thermal"
    assert gpu.reasons_text(0x05) == "idle, power cap"
    assert gpu.reasons_text(0) == ""


def test_live_hardware():
    gpus = gpu.read_gpus()
    assert gpus, "no GPUs"
    for g in gpus:
        assert g["power_min"] <= g["power_limit"] <= g["power_max"], g
        assert g["target_min"] <= g["target_temp"] <= g["target_max"], g
        assert g["compute_mode"] in gpu.COMPUTE_MODES, g["compute_mode"]
        assert g["dm_current"] in gpu.DRIVER_MODELS, g["dm_current"]
        assert g["gpu_clocks"][0] < g["gpu_clocks"][-1]
        assert len(g["mem_clocks"]) >= 2
    live = gpu.read_live()
    assert set(live) == {g["bus"] for g in gpus}, (live, gpus)
    print("live:", gpus[0]["bus"], live[gpus[0]["bus"]])
    return gpus


def test_page(gpus):
    app = QApplication.instance() or QApplication([])
    page = gpu.GpuPage()
    page.show()
    app.processEvents()
    assert len(page.boxes) == len(gpus)
    for box, g in zip(page.boxes, gpus):
        p = box.profile()
        assert p["bus"] == g["bus"]
        assert p["power_limit"] == g["power_limit"], (p, g)
        assert p["compute_mode"] == g["compute_mode"]
        assert box.live.text(), "live readout empty"
        box.set_profile(P | {"bus": g["bus"]})
        assert box.profile() == P | {"bus": g["bus"]}, box.profile()
    assert len(page.search_entries("GPU")) == 8 * len(gpus)
    page._timer.stop()


if __name__ == "__main__":
    test_commands()
    test_xml_roundtrip()
    test_boot_script()
    test_reasons()
    test_page(test_live_hardware())
    print("STATUS: SUCCESS")
