"""Contract test for hwinfo topology: GetLogicalProcessorInformationEx cores,
packages and caches, and the cache text derived from them."""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hwinfo  # noqa: E402

topo = hwinfo.topology()

# ---- counts against WMI and the OS ----
ps = ("Get-CimInstance Win32_Processor | Select-Object NumberOfCores,"
      "NumberOfLogicalProcessors | ConvertTo-Json -Compress")
wmi = json.loads(subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                capture_output=True, text=True, check=True).stdout)
wmi = [wmi] if isinstance(wmi, dict) else wmi
assert len(topo.cores) == sum(w["NumberOfCores"] for w in wmi), (len(topo.cores), wmi)
assert topo.threads == sum(w["NumberOfLogicalProcessors"] for w in wmi), (topo.threads, wmi)
assert topo.threads == os.cpu_count(), (topo.threads, os.cpu_count())
assert len(topo.packages) == len(wmi)
assert topo.package_cores(0) == len(topo.cores) and topo.package_threads(0) == topo.threads
assert all(bin(c.mask).count("1") in (1, 2) for c in topo.cores)
assert sorted(i for c in topo.cores for i in c.logical) == list(range(topo.threads))
print(f"counts ok: {len(topo.cores)} cores, {topo.threads} threads")

# ---- cache groups: count x size matches the raw GLPIEx totals ----
KINDS = {(1, "data"): "L1 data", (1, "instruction"): "L1 inst",
         (2, "unified"): "L2", (3, "unified"): "L3"}
for (level, kind), name in KINDS.items():
    raw = [c for c in topo.caches if c.level == level and c.kind == kind]
    assert raw, name
    groups = hwinfo.cache_groups(topo, level, kind)
    assert sum(g.count for g in groups) == len(raw), name
    assert sum(g.count * g.size for g in groups) == sum(c.size for c in raw), name
    assert [g.size for g in groups] == sorted((g.size for g in groups), reverse=True)
    expect = Counter(c.size for c in raw)
    assert {g.size: g.count for g in groups} == dict(expect), name

# ---- text: derived from the same data with an independent formula ----
def unit(size, long):
    n, u = (size >> 20, "MB") if size % (1 << 20) == 0 else (size // 1024, "KB")
    return f"{n} {u}" if not long else f"{n} {u[0]}Bytes"


for (level, kind), name in KINDS.items():
    raw = [c for c in topo.caches if c.level == level and c.kind == kind]
    counts = sorted(Counter(c.size for c in raw).items(), reverse=True)
    info = hwinfo.cache_info(topo, level, kind)
    if len(counts) == 1:
        (size, n), = counts
        assert info.summary == f"{n} x {unit(size, True)}", (name, info)
        assert info.size == unit(size, True), (name, info)
    else:
        want = " + ".join((f"{n} x " if n > 1 else "") + unit(size, False)
                          for size, n in counts)
        assert info.summary == want and info.size == want, (name, info, want)
    ways = {c.associativity for c in raw}
    assert info.ways == " + ".join(f"{w}-way" for w in sorted(ways, reverse=True)), (name, info)
    line = {c.line for c in raw}
    assert len(line) == 1 and f"{line.pop()}-byte line size" in info.descriptor, (name, info)
    assert info.descriptor.startswith(info.ways.replace("-way", "-way set associative")), \
        (name, info)
    print(f"{name}: {info.summary} | {info.ways} | {info.descriptor}")

# ---- this PC: CPU-Z shows the 3D V-Cache slice and the plain slice ----
if "7950X3D" in hwinfo.identity().brand:
    assert hwinfo.cache_info(topo, 3, "unified").summary == "96 MB + 32 MB"
    assert hwinfo.cache_info(topo, 1, "data").summary == "16 x 32 KBytes"
    assert hwinfo.cache_info(topo, 1, "data").ways == "8-way"
    assert hwinfo.cache_info(topo, 2, "unified").summary == "16 x 1 MBytes"

# ---- an absent cache level raises instead of printing zeros ----
try:
    hwinfo.cache_info(topo, 4, "unified")
except hwinfo.HwError:
    pass
else:
    raise AssertionError("missing cache level was accepted")

# ---- NUMA nodes: every logical processor belongs to exactly one node ----
assert set(topo.numa) == {0} or len(topo.numa) > 1, topo.numa
placed = sorted(g * 64 + b for spans in topo.numa.values() for g, mask in spans
                for b in range(64) if mask >> b & 1)
assert placed == list(range(topo.threads)), placed
print(f"numa ok: {len(topo.numa)} node(s)")


# ---- a synthetic two-node record stream ----
def record(relation, size, **at):
    raw = bytearray(size)
    raw[0:4] = relation.to_bytes(4, "little")
    raw[4:8] = size.to_bytes(4, "little")
    for off, data in at.items():
        raw[int(off[1:]):int(off[1:]) + len(data)] = data
    return bytes(raw)


def affinity(mask, group):
    return mask.to_bytes(8, "little") + group.to_bytes(2, "little") + bytes(6)


def proc_record(relation, mask, group):
    # processor core / package: GroupCount at 30, GROUP_AFFINITY at 32
    return record(relation, 48, o30=(1).to_bytes(2, "little"), o32=affinity(mask, group))


def numa_record(node, mask, group):
    # NUMA node: NodeNumber at 8, GroupCount at 30, GROUP_AFFINITY at 32
    return record(1, 48, o8=node.to_bytes(4, "little"), o30=(1).to_bytes(2, "little"),
                  o32=affinity(mask, group))


raw = b"".join((
    proc_record(0, 0b0000_0011, 0), proc_record(0, 0b0000_1100, 0),
    proc_record(0, 0b0011_0000, 0), proc_record(0, 0b1100_0000, 0),
    proc_record(3, 0b0000_1111, 0), proc_record(3, 0b1111_0000, 0),
    numa_record(0, 0b0000_1111, 0), numa_record(1, 0b1111_0000, 0)))
two = hwinfo.parse_topology(raw)
assert [c.logical for c in two.cores] == [(0, 1), (2, 3), (4, 5), (6, 7)], two.cores
assert [p.logical for p in two.packages] == [(0, 1, 2, 3), (4, 5, 6, 7)]
assert two.numa == {0: [(0, 0b1111)], 1: [(0, 0b1111_0000)]}, two.numa
assert two.threads == 8 and two.package_cores(0) == 2 and two.package_threads(1) == 4
# a node that lives in a second processor group
grouped = hwinfo.parse_topology(b"".join((
    proc_record(0, 0b11, 0), proc_record(3, 0b11, 0),
    numa_record(0, 0b11, 0), numa_record(1, 0b1111, 1))))
assert grouped.numa == {0: [(0, 0b11)], 1: [(1, 0b1111)]}, grouped.numa
# no records, or a record that overruns the buffer, are errors
for bad in (b"", raw[:40]):
    try:
        hwinfo.parse_topology(bad)
        raise AssertionError("a broken record stream was accepted")
    except hwinfo.HwError:
        pass
print("synthetic topology ok")
print("STATUS: SUCCESS")
