"""Contract test for hwinfo PDH clocks: live per-core frequency from
% Processor Performance x Processor Frequency, and the mapping of
`Processor Information` instance names (<NUMA node>,<processor>) to logical
processors."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cpudb  # noqa: E402
import hwinfo  # noqa: E402

# ---- instance names are "<NUMA node>,<index in group>", not "<group>,<index>" ----
two_nodes = {0: [(0, 0x0000FFFF)], 1: [(0, 0xFFFF0000)]}
assert hwinfo.pdh_cpu("0,3", two_nodes) == 3
assert hwinfo.pdh_cpu("0,15", two_nodes) == 15
assert hwinfo.pdh_cpu("1,17", two_nodes) == 17        # node 1 is not group 1
assert hwinfo.pdh_cpu("1,31", two_nodes) == 31
for total in ("0,_Total", "1,_Total", "_Total"):
    assert hwinfo.pdh_cpu(total, two_nodes) is None, total
split_groups = {0: [(0, 0xF)], 1: [(1, 0xF)]}         # a node in a second processor group
assert hwinfo.pdh_cpu("0,2", split_groups) == 2
assert hwinfo.pdh_cpu("1,2", split_groups) == 66
for bad in ("1,9", "0,16", "2,0", "x,1", "0,y"):
    try:
        hwinfo.pdh_cpu(bad, two_nodes)
        raise AssertionError(f"instance {bad!r} was placed")
    except hwinfo.HwError:
        pass
print("instance mapping ok")

ident = hwinfo.identity()
topo = hwinfo.topology()
info = cpudb.lookup(ident.vendor, ident.ext_family, ident.ext_model, ident.stepping,
                    ident.brand)
assert info is not None and info.mult_max, "this PC must be in cpudb"
ceiling = 2 * info.mult_max * 100

clocks = hwinfo.CoreClocks(topo)
try:
    time.sleep(0.25)
    first = clocks.sample()
    time.sleep(0.25)
    second = clocks.sample()
    for sample in (first, second):
        assert sorted(sample) == list(range(topo.threads)), sorted(sample)
        for cpu, mhz in sample.items():
            assert 0 < mhz < ceiling, (cpu, mhz, ceiling)

    per_core = clocks.per_core(topo)
    assert len(per_core) == len(topo.cores)
    assert all(0 < m < ceiling for m in per_core), per_core
    assert per_core == [second[core.logical[0]] for core in topo.cores]
finally:
    clocks.close()

# a topology that cannot place the instances PDH reports is an error, not a guess
wrong = topo._replace(numa={0: [(0, 0x0000FFFF)], 1: [(0, 0xFFFF0000)]})
clocks = hwinfo.CoreClocks(wrong)
try:
    time.sleep(0.2)
    try:
        clocks.sample()
        raise AssertionError("instances outside the node masks were accepted")
    except hwinfo.HwError:
        pass
finally:
    clocks.close()

assert hwinfo.mhz_text(4192.184) == "4192.18 MHz"
assert hwinfo.mhz_text(399.999) == "400.00 MHz"
try:
    clocks.sample()
    raise AssertionError("closed query was sampled")
except hwinfo.HwError:
    pass
print(f"clocks ok: core 0 {hwinfo.mhz_text(second[0])}, ceiling {ceiling} MHz")
print("STATUS: SUCCESS")
