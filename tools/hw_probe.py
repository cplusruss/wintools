#!/usr/bin/env python3
"""hw_probe.py - raw hardware probe for wintools's Hardware tab, step 1 of the
CPU-Z phase 2.  Run from an elevated prompt:

    C:\\Python\\313\\python.exe tools\\hw_probe.py

It prints one line per section and writes sandbox\\fixtures\\hw_dump_<COMPUTERNAME>.json.
Raw values only, no decoding.  Hardware writes are limited to the SPD page-select
operations on addresses already identified as SPD5 hubs / EE1004, and SuperIO
config-mode enter and exit.  --smu (SMU mailbox commands for the PM table) and
--hwm (SuperIO logical-device and hardware-monitor bank selects) are opt-in;
every write is listed in the dump's "writes"."""

import argparse
import ctypes
import ctypes.wintypes as wt
import functools
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hwinfo  # noqa: E402
import pawnio  # noqa: E402

SCHEMA = 1
AMD, INTEL = "AuthenticAMD", "GenuineIntel"
SECTION_NAMES = ("identity", "topology", "tsc", "driver", "amd_msr", "amd_smn", "amd_umc",
                 "amd_smu", "intel_msr", "intel_mchbar", "smbus_spd", "lpcio")

# The module allowlists decide what can be read: AMDFamily17.p L88 (the C00000E7/E8
# aliases are the readable MPERF/APERF; C0010062 is not on the list, the read is
# recorded as denied), IntelMSR.p L70.
AMD_MSRS = (0xC0010015, 0xC0010061, 0xC0010062, 0xC0010063, *range(0xC0010064, 0xC001006C),
            0xC0010071, 0xC0010293, 0xC0010299, 0xC001029A, 0xC001029B)
AMD_PERF_MSRS = (0xC00000E7, 0xC00000E8)
INTEL_MSRS = (0xCE, 0x198, 0x199, 0x1A2, 0x19C, 0x1B1, 0x1AD, 0x606, 0x611)
INTEL_PERF_MSRS = (0xE7, 0xE8)

SMN_THM_TCON_CUR_TMP = 0x00059800
SMN_CCD_TEMP, CCD_COUNT = 0x00059954, 12
UMC_BLOCKS = ((0x00050000, 0x000502FF), (0x00150000, 0x001502FF))
MCHBAR_WINDOWS = ((0x4000, 0x4FFF), (0xD800, 0xEFFF))
PM_TABLE_QWORDS = 512       # RyzenSMU.p L693: at most PAGE_SIZE / 8 qwords
PERF_INTERVAL_S = 0.1
SMBUS_FIRST, SMBUS_LAST = 0x50, 0x57
ERRORS_KEPT = 4


class Skip(Exception):
    pass


class WriteRefused(Exception):
    pass


def hex_min(v):
    return f"0x{v:X}"


def hex8(v):
    return f"0x{v:08X}"


class Tally:
    def __init__(self):
        self.ok = self.failed = 0
        self.first = None

    def good(self):
        self.ok += 1

    def bad(self, e):
        self.failed += 1
        self.first = self.first or str(e)

    def verify(self, what):
        if self.failed and not self.ok:
            raise pawnio.PawnIOError(f"{what}: all {self.failed} reads failed: {self.first}")

    def text(self):
        return f"{self.ok} reads" + (f", {self.failed} failed" if self.failed else "")


# ====================================================================
#  NO DRIVER NEEDED
# ====================================================================

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.VirtualAlloc.restype = ctypes.c_void_p
_k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
_k32.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_int64)]
_k32.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_int64)]

# rdtsc; shl rdx, 32; or rax, rdx; ret
_RDTSC_CODE = bytes.fromhex("0f31" "48c1e220" "4809d0" "c3")


@functools.cache
def _rdtsc():
    addr = _k32.VirtualAlloc(None, len(_RDTSC_CODE), 0x3000, 0x40)
    if not addr:
        raise pawnio.PawnIOError(f"VirtualAlloc for the RDTSC thunk: "
                                 f"{ctypes.FormatError(ctypes.get_last_error()).strip()}")
    ctypes.memmove(addr, _RDTSC_CODE, len(_RDTSC_CODE))
    return ctypes.CFUNCTYPE(ctypes.c_uint64)(addr)


def _qpc():
    v = ctypes.c_int64()
    if not _k32.QueryPerformanceCounter(ctypes.byref(v)):
        raise pawnio.PawnIOError("QueryPerformanceCounter failed")
    return v.value


def collect_tsc():
    freq = ctypes.c_int64()
    if not _k32.QueryPerformanceFrequency(ctypes.byref(freq)):
        raise pawnio.PawnIOError("QueryPerformanceFrequency failed")
    rdtsc = _rdtsc()
    with pawnio.pin_thread(0):
        q0, t0 = _qpc(), rdtsc()
        while _qpc() - q0 < freq.value // 4:
            pass
        q1, t1 = _qpc(), rdtsc()
    out = {"cpu": 0, "qpf": freq.value, "qpc_delta": q1 - q0, "tsc_delta": t1 - t0}
    out["tsc_hz"] = out["tsc_delta"] * freq.value / out["qpc_delta"]
    out["summary"] = f"{out['tsc_hz'] / 1e6:.1f} MHz over {out['qpc_delta'] * 1000 // freq.value} ms"
    return out


def collect_identity():
    ident = hwinfo.identity()
    leaves = {hex8(leaf): list(hwinfo.cpuid(leaf)) for leaf in (0, 1, 0x80000001)}
    return {"vendor": ident.vendor, "brand": ident.brand, "family": ident.ext_family,
            "model": ident.ext_model, "stepping": ident.stepping, "base_family": ident.family,
            "base_model": ident.model, "cpuid": leaves,
            "summary": f"{ident.vendor} {ident.brand}, family {ident.ext_family:X}h "
                       f"model {ident.ext_model:X}h stepping {ident.stepping}"}


def collect_topology():
    topo = hwinfo.topology()
    cores = [{"group": c.group, "mask": c.mask, "logical": list(c.logical)} for c in topo.cores]
    return {"cores": cores, "packages": [list(p.logical) for p in topo.packages],
            "numa": {str(n): [list(span) for span in spans] for n, spans in topo.numa.items()},
            "first_logical": [c.logical[0] for c in topo.cores],
            "summary": f"{len(topo.cores)} cores, {topo.threads} threads"}


# ====================================================================
#  MSRS  (AMDFamily17 / IntelMSR, read on a pinned thread per physical core)
# ====================================================================

def _collect_msrs(call, cores, msrs, perf_msrs, sleep):
    cores_out, perf_out, errors, tally = {}, {}, [], Tally()

    def read(cpu, addr):
        try:
            v = call("ioctl_read_msr", [addr], 1)[0]
        except pawnio.PawnIOError as e:
            tally.bad(e)
            errors.append({"core": cpu, "addr": hex_min(addr), "error": str(e)})
            return None
        tally.good()
        return v

    for cpu in cores:
        got = cores_out[str(cpu)] = {}
        with pawnio.pin_thread(cpu):
            for addr in msrs:
                v = read(cpu, addr)
                if v is not None:
                    got[hex_min(addr)] = v

    def sweep():
        row = {}
        for cpu in cores:
            with pawnio.pin_thread(cpu):
                row[cpu] = [read(cpu, addr) for addr in perf_msrs]
        return row

    first = sweep()
    t0 = time.perf_counter_ns()
    sleep(PERF_INTERVAL_S)
    second = sweep()
    interval = time.perf_counter_ns() - t0
    for cpu in cores:
        perf_out[str(cpu)] = {"mperf": [first[cpu][0], second[cpu][0]],
                              "aperf": [first[cpu][1], second[cpu][1]]}
    tally.verify("MSR reads")
    return {"cores": cores_out, "perf": perf_out, "perf_interval_ns": interval,
            "errors": errors, "summary": f"{len(cores)} cores, {tally.text()}"}


def collect_amd_msr(call, cores, sleep=time.sleep):
    return _collect_msrs(call, cores, AMD_MSRS, AMD_PERF_MSRS, sleep)


def collect_intel_msr(call, cores, sleep=time.sleep):
    return _collect_msrs(call, cores, INTEL_MSRS, INTEL_PERF_MSRS, sleep)


# ====================================================================
#  AMD SMN, UMC, SMU  (AMDFamily17 ioctl_read_smn, RyzenSMU)
# ====================================================================

def _smn(call, addr):
    return call("ioctl_read_smn", [addr], 1)[0] & 0xFFFFFFFF


def _smn_value(call, addr, tally):
    entry = {"addr": hex8(addr)}
    try:
        entry["value"] = _smn(call, addr)
        tally.good()
    except pawnio.PawnIOError as e:
        entry["error"] = str(e)
        tally.bad(e)
    return entry


def collect_amd_smn(call, lock):
    tally = Tally()
    with lock(pawnio.MUTEX_PCI):
        thm = _smn_value(call, SMN_THM_TCON_CUR_TMP, tally)
        ccd = [_smn_value(call, SMN_CCD_TEMP + 4 * i, tally) for i in range(CCD_COUNT)]
    tally.verify("SMN reads")
    return {"thm_tcon_cur_tmp": thm, "ccd_temps": ccd, "summary": tally.text()}


def _dword_window(read, base, end, tally):
    dwords, errors, count = [], [], 0
    for addr in range(base, end + 1, 4):
        try:
            dwords.append(read(addr))
            tally.good()
        except pawnio.PawnIOError as e:
            dwords.append(None)
            count += 1
            tally.bad(e)
            if len(errors) < ERRORS_KEPT:
                errors.append({"addr": hex8(addr), "error": str(e)})
    return {"base": hex8(base), "end": hex8(end), "dwords": dwords,
            "error_count": count, "errors": errors}


def collect_amd_umc(call, lock):
    tally, blocks = Tally(), []
    for base, end in UMC_BLOCKS:
        with lock(pawnio.MUTEX_PCI):
            blocks.append(_dword_window(lambda a: _smn(call, a), base, end, tally))
    tally.verify("UMC reads")
    return {"blocks": blocks, "summary": tally.text()}


def collect_amd_smu(call, lock):
    out, errors = {}, {}

    def step(key, fn):
        try:
            return fn()
        except pawnio.PawnIOError as e:
            errors[key] = str(e)
            return None

    out["code_name"] = step("code_name", lambda: call("ioctl_get_code_name", [], 1)[0])
    with lock(pawnio.MUTEX_PCI):
        out["smu_version"] = step("smu_version", lambda: call("ioctl_get_smu_version", [], 1)[0])
        resolved = step("pm_table_resolve", lambda: call("ioctl_resolve_pm_table", [], 2))
        out["pm_table_version"], out["pm_table_base"] = resolved or (None, None)
        if resolved:
            step("pm_table_update", lambda: call("ioctl_update_pm_table", [], 0))
    qwords = step("pm_table_read", lambda: call("ioctl_read_pm_table", [], PM_TABLE_QWORDS)) \
        if resolved else None
    out["pm_table_dwords"] = [d for q in qwords for d in (q & 0xFFFFFFFF, q >> 32)] \
        if qwords else None
    out["errors"] = errors
    if errors and out["code_name"] is None and out["pm_table_dwords"] is None:
        raise pawnio.PawnIOError(f"SMU reads failed: {next(iter(errors.values()))}")
    version = out["pm_table_version"]
    out["summary"] = (f"PM table version {version:#x}, {len(out['pm_table_dwords'] or [])} dwords"
                      if version is not None else "no PM table")
    return out


# ====================================================================
#  INTEL MCHBAR  (IntelMCHBAR: 4-byte aligned dword reads inside the mapping)
# ====================================================================

def collect_intel_mchbar(call):
    addr = call("ioctl_get_mchbar_addr", [], 1)[0]
    tally, windows = Tally(), []
    for base, end in MCHBAR_WINDOWS:
        windows.append(_dword_window(lambda a: call("ioctl_read_dword", [a], 1)[0],
                                     base, end, tally))
    tally.verify("MCHBAR reads")
    return {"mchbar_addr": addr, "windows": windows,
            "summary": f"MCHBAR {addr:#x}, {tally.text()}"}


# ====================================================================
#  SMBUS SPD  (SmbusPIIX4 / SmbusI801 ioctl_smbus_xfer)
# ====================================================================

# ioctl_smbus_xfer cells (SmbusPIIX4.p L625, SmbusI801.p L795): in = [address,
# read 1 / write 0, command, protocol, data], out = the byte read.  Protocol 1
# (BYTE) sends the command cell as the byte, protocol 2 (BYTE_DATA) sends
# command then data; a write needs in[4] present (L676 / L846 case block).
#
# SPD5 hub, as Linux drivers/hwmon/spd5118.c uses it: MR0:MR1 reads 0x5118
# (detect), MR11 = register 0x0B, bits 2:0 select the NVM page, bit 3 is the
# legacy addressing bit and is preserved, NVM bytes sit at 0x80 + offset, 128
# bytes per page, 8 pages.  EE1004, as drivers/misc/eeprom/ee1004.c: write byte
# 0x00 to address 0x36 selects page 0, to 0x37 page 1; a read ACKs on the address
# of the current page; 256 bytes per page.
SPD5_ID = (0x51, 0x18)
SPD5_MR11, SPD5_NVM_BASE, SPD5_PAGE_SIZE, SPD5_PAGES = 0x0B, 0x80, 128, 8
EE_SPA = 0x36
EE_PAGE_SIZE = 256
SPD_TYPE_BYTE, DDR4_TYPE, DDR3_TYPE = 2, 0x0C, 0x0B
UNIDENTIFIED_BYTES = 16


class SpdBus:
    """SMBus access that can write only an SPD page select, and only to an
    address already identified as the matching device."""

    def __init__(self, call, lock, writes):
        self.call, self.lock, self.writes = call, lock, writes
        self.hubs, self.ee1004 = set(), False

    def read_byte_data(self, addr, reg):
        return self.call("ioctl_smbus_xfer", [addr, 1, reg, 2], 1)[0] & 0xFF

    def read_byte(self, addr):
        return self.call("ioctl_smbus_xfer", [addr, 1, 0, 1], 1)[0] & 0xFF

    def identify_hub(self, addr):
        self.hubs.add(addr)

    def identify_ee1004(self):
        self.ee1004 = True

    def select_spd5_page(self, addr, mr11):
        if addr not in self.hubs:
            raise WriteRefused(f"SMBus write to {hex(addr)}: not identified as an SPD5 hub")
        if not 0 <= mr11 <= 0x0F:
            raise WriteRefused(f"SMBus write of MR11 = {mr11:#x}: only bits 3:0 are allowed")
        self._write([addr, 0, SPD5_MR11, 2, mr11], f"SPD5 hub {hex(addr)} page select (MR11)")

    def select_ee_page(self, page):
        if not self.ee1004:
            raise WriteRefused("SMBus write to 0x36/0x37: EE1004 not identified")
        if page not in (0, 1):
            raise WriteRefused(f"EE1004 page {page}: only pages 0 and 1 exist")
        self._write([EE_SPA + page, 0, 0, 1, 0], f"EE1004 page select {page}")

    def _write(self, inputs, reason):
        self.writes.append({"module": "smbus", "fn": "ioctl_smbus_xfer", "inputs": inputs,
                            "reason": reason})
        self.call("ioctl_smbus_xfer", inputs, 0)


def _read_spd5(bus, addr):
    dev = {"kind": "spd5_hub", "mr0_mr1": list(SPD5_ID), "error": None,
           "restore_error": None, "bytes_hex": ""}
    smbus = pawnio.MUTEX_SMBUS
    try:
        with bus.lock(smbus):
            before = bus.read_byte_data(addr, SPD5_MR11)
    except pawnio.PawnIOError as e:
        dev["error"] = f"MR11 read: {e}"
        return dev
    dev["mr11_before"] = before
    if before & ~0x0F:      # spd5118.c rejects a hub whose MR11 has reserved bits set
        dev["error"] = f"MR11 reads {before:#04x}: reserved bits set, page select not touched"
        return dev
    data, current, page = bytearray(), before & 7, 0
    try:
        try:
            for page in range(SPD5_PAGES):
                with bus.lock(smbus):
                    if page != current:
                        current = page      # assume it changed even when the write fails
                        bus.select_spd5_page(addr, before & ~7 | page)
                    for off in range(SPD5_PAGE_SIZE):
                        data.append(bus.read_byte_data(addr, SPD5_NVM_BASE + off))
        except pawnio.PawnIOError as e:
            dev["error"] = f"page {page}: {e}"
    finally:
        dev["bytes_hex"] = data.hex()
        try:
            with bus.lock(smbus):
                if current != 0:
                    bus.select_spd5_page(addr, before & ~7)
                after = bus.read_byte_data(addr, SPD5_MR11)
            dev["mr11_after"] = after
            if after & 7:
                dev["restore_error"] = f"MR11 reads {after:#04x} after the restore, page is not 0"
        except pawnio.PawnIOError as e:
            dev["restore_error"] = f"restore failed: {e}"
    return dev


def _ee_current_page(bus):
    for page in (0, 1):
        try:
            bus.read_byte(EE_SPA + page)
        except pawnio.PawnIOError:
            continue
        return page
    return None


def _read_ee1004(bus, addrs, page_before):
    devs = {a: {"kind": "ee1004", "page_before": page_before, "error": None,
                "restore_error": None} for a in addrs}
    bufs = {a: bytearray() for a in addrs}
    smbus, current, page = pawnio.MUTEX_SMBUS, 0, 0     # the caller selected page 0
    try:
        try:
            for page in (0, 1):
                with bus.lock(smbus):
                    if page != current:
                        current = page
                        bus.select_ee_page(page)
                    for a in addrs:
                        if devs[a]["error"]:
                            continue
                        try:
                            for off in range(EE_PAGE_SIZE):
                                bufs[a].append(bus.read_byte_data(a, off))
                        except pawnio.PawnIOError as e:
                            devs[a]["error"] = f"page {page}: {e}"
        except pawnio.PawnIOError as e:
            for d in devs.values():
                d["error"] = d["error"] or f"page {page}: {e}"
    finally:
        after = restore_error = None
        try:
            with bus.lock(smbus):
                if current != 0:
                    bus.select_ee_page(0)
                after = _ee_current_page(bus)
            if after != 0:
                restore_error = f"EE1004 reports page {after} after the restore"
        except pawnio.PawnIOError as e:
            restore_error = f"restore failed: {e}"
        for a, d in devs.items():
            d.update(bytes_hex=bufs[a].hex(), page_after=after, restore_error=restore_error)
    return devs


def _read_plain(bus, addr, kind, count, error=None):
    dev = {"kind": kind, "error": error, "bytes_hex": ""}
    data = bytearray()
    try:
        with bus.lock(pawnio.MUTEX_SMBUS):
            for off in range(count):
                data.append(bus.read_byte_data(addr, off))
    except pawnio.PawnIOError as e:
        dev["error"] = f"byte {len(data)}: {e}"
    dev["bytes_hex"] = data.hex()
    return dev


def _read_others(bus, addrs):
    devices = {}
    with bus.lock(pawnio.MUTEX_SMBUS):
        page_before = _ee_current_page(bus)     # ACK probe of 0x36 / 0x37, no write
    if page_before is not None:
        bus.identify_ee1004()
        if page_before == 1:        # the type byte lives on page 0
            try:
                with bus.lock(pawnio.MUTEX_SMBUS):
                    bus.select_ee_page(0)
            except pawnio.PawnIOError as e:
                return {hex(a): {"kind": "unidentified", "bytes_hex": "",
                                 "error": f"EE1004 page select 0: {e}"} for a in addrs}
    types = {}
    for a in addrs:
        try:
            with bus.lock(pawnio.MUTEX_SMBUS):
                types[a] = bus.read_byte_data(a, SPD_TYPE_BYTE)
        except pawnio.PawnIOError as e:
            devices[hex(a)] = {"kind": "unidentified", "error": f"type byte: {e}", "bytes_hex": ""}
    ddr4 = [a for a in types if types[a] == DDR4_TYPE and page_before is not None]
    if ddr4:
        devices.update({hex(a): d for a, d in _read_ee1004(bus, ddr4, page_before).items()})
    for a, t in types.items():
        if a in ddr4:
            continue
        if t == DDR3_TYPE:
            devices[hex(a)] = _read_plain(bus, a, "ddr3_spd", 256)
        elif t == DDR4_TYPE:
            devices[hex(a)] = _read_plain(bus, a, "ddr4_no_page_select", EE_PAGE_SIZE,
                                          "no EE1004 page address answered")
        else:
            devices[hex(a)] = _read_plain(bus, a, "unidentified", UNIDENTIFIED_BYTES)
    return devices


def collect_spd(call, lock, writes):
    bus = SpdBus(call, lock, writes)
    ids, absent, devices = {}, {}, {}
    with lock(pawnio.MUTEX_SMBUS):
        for addr in range(SMBUS_FIRST, SMBUS_LAST + 1):
            try:
                ids[addr] = (bus.read_byte_data(addr, 0), bus.read_byte_data(addr, 1))
            except pawnio.PawnIOError as e:
                absent[hex(addr)] = str(e)
    hubs = [a for a, i in ids.items() if i == SPD5_ID]
    for addr in hubs:
        bus.identify_hub(addr)
        devices[hex(addr)] = _read_spd5(bus, addr)
    others = [a for a in ids if a not in hubs]
    if others:
        devices.update(_read_others(bus, others))
    failed = [k for k, d in devices.items() if d["error"] or d.get("restore_error")]
    kinds = ", ".join(f"{k} {d['kind']}" for k, d in sorted(devices.items()))
    return {"devices": dict(sorted(devices.items())), "absent": absent,
            "summary": (kinds or "no SPD device answered at 0x50-0x57")
            + (f"; problems at {', '.join(failed)}" if failed else "")}


# ====================================================================
#  SUPERIO  (LpcIO)
# ====================================================================

# LpcIO.p never enters or leaves configuration mode (no key sequence anywhere in
# the module; find_bars L97 only needs a valid chip id), so the keys go through
# ioctl_pio_outb to the selected index port, as LibreHardwareMonitor does
# (Hardware/Motherboard/Lpc/LpcPort.cs): Winbond / Nuvoton / Fintek 0x87 0x87 and
# 0xAA to leave; ITE 0x87 0x01 0x55 then 0x55 (0xAA on port 0x4E) and register
# 0x02 <- 0x02 to leave.  LHM skips the ITE exit on 0x4E; here it is sent on both
# ports so a chip that did enter does not stay in configuration mode.
LPC_SLOTS = ((0, 0x2E), (1, 0x4E))
CHIP_ID_HI, CHIP_ID_LO, LDN_SELECT = 0x20, 0x21, 0x07
LDN_COUNT, LDN_FIRST_REG = 0x20, 0x30
# LHM Lpc/LpcIO.cs: Winbond / Nuvoton hardware monitor is logical device 0x0B, I/O
# base in registers 0x60/0x61.  LHM Lpc/Nct677X.cs: index port base + 5, data port
# base + 6, bank select register 0x4E (the bank is written to the data port, then
# the register to the index port), vendor id 0x5CA3 read as bank 0x80 reg 0x4F
# (high) and bank 0x00 reg 0x4F (low); the highest bank any NCT679x register uses is 0x0C.
HWM_LDN, HWM_ADDR, HWM_DATA, HWM_BANK_REG, HWM_VENDOR_REG = 0x0B, 5, 6, 0x4E, 0x4F
HWM_VENDOR_ID, HWM_BANKS = 0x5CA3, 16


def _log(writes, fn, inputs, reason):
    writes.append({"module": "lpcio", "fn": fn, "inputs": inputs, "reason": reason})


def _outb(call, writes, port, value, reason):
    _log(writes, "ioctl_pio_outb", [port, value], reason)
    call("ioctl_pio_outb", [port, value], 0)


def _enter(call, writes, port, family):
    keys = (0x87, 0x87) if family == "winbond" else (0x87, 0x01, 0x55, 0xAA if port == 0x4E else 0x55)
    for key in keys:
        _outb(call, writes, port, key, f"enter config mode ({family})")


def _exit(call, writes, port, family):
    if family == "winbond":
        _outb(call, writes, port, 0xAA, "exit config mode (winbond)")
    else:
        _outb(call, writes, port, 0x02, "exit config mode (ite)")
        _outb(call, writes, port + 1, 0x02, "exit config mode (ite)")


def _sio_in(call, reg):
    return call("ioctl_superio_inb", [reg], 1)[0] & 0xFF


def _valid_id(id_word):
    return id_word >> 8 not in (0x00, 0xFF)


def _try_family(call, writes, port, family):
    _enter(call, writes, port, family)
    regs = b""
    try:
        id_word = _sio_in(call, CHIP_ID_HI) << 8 | _sio_in(call, CHIP_ID_LO)
        if _valid_id(id_word):
            regs = bytes(_sio_in(call, r) for r in range(256))
    finally:
        _exit(call, writes, port, family)
    return id_word, regs


def _select_ldn(call, writes, ldn, reason):
    _log(writes, "ioctl_superio_outb", [LDN_SELECT, ldn], reason)
    call("ioctl_superio_outb", [LDN_SELECT, ldn], 0)


def collect_hwm(call, lock, writes, port):
    out, before = {"ldn": {}}, None
    with lock(pawnio.MUTEX_ISABUS):
        _enter(call, writes, port, "winbond")
        try:
            before = _sio_in(call, LDN_SELECT)
            _log(writes, "ioctl_find_bars", [], "the module scans register 0x07 to find I/O bases")
            call("ioctl_find_bars", [], 0)
            try:
                for ldn in range(LDN_COUNT):
                    _select_ldn(call, writes, ldn, "read logical device registers")
                    out["ldn"][hex_min(ldn)] = bytes(
                        _sio_in(call, r) for r in range(LDN_FIRST_REG, 0x100)).hex()
            finally:
                _select_ldn(call, writes, before, "restore logical device select")
        finally:
            _exit(call, writes, port, "winbond")
    out["ldn_before"] = before
    regs = bytes.fromhex(out["ldn"][hex_min(HWM_LDN)])
    base = (regs[0x60 - LDN_FIRST_REG] << 8 | regs[0x61 - LDN_FIRST_REG]) & 0xFFF8
    out["base"] = base
    if not 0x100 <= base < 0xFFF8:
        out["error"] = f"hardware monitor base {base:#x} is not a usable I/O address"
        return out
    addr_port, data_port, index_writes = base + HWM_ADDR, base + HWM_DATA, 0

    def read(reg):
        nonlocal index_writes
        index_writes += 1
        call("ioctl_pio_outb", [addr_port, reg], 0)
        return call("ioctl_pio_inb", [data_port], 1)[0] & 0xFF

    def select_bank(value, reason):
        nonlocal index_writes
        index_writes += 1
        call("ioctl_pio_outb", [addr_port, HWM_BANK_REG], 0)
        _outb(call, writes, data_port, value, reason)

    try:
        with lock(pawnio.MUTEX_ISABUS):
            bank_before = out["bank_before"] = read(HWM_BANK_REG)
            try:
                select_bank(0x80, "HWM bank select (vendor id high)")
                hi = read(HWM_VENDOR_REG)
                select_bank(0x00, "HWM bank select (vendor id low)")
                lo = read(HWM_VENDOR_REG)
                out["vendor_id"] = hi << 8 | lo
                if out["vendor_id"] == HWM_VENDOR_ID:
                    out["banks"] = {}
                    for bank in range(HWM_BANKS):
                        select_bank(bank, "HWM bank select")
                        out["banks"][hex_min(bank)] = bytes(read(r) for r in range(256)).hex()
                else:
                    out["error"] = f"vendor id {out['vendor_id']:#06x}, not {HWM_VENDOR_ID:#06x}"
            finally:
                select_bank(bank_before, "HWM bank select restore")
    finally:
        _log(writes, "ioctl_pio_outb", [addr_port], f"{index_writes} index-port writes that "
             "address registers for the reads")
    return out


def collect_lpcio(call, lock, writes, hwm=False):
    slots = {}
    for slot, port in LPC_SLOTS:
        call("ioctl_select_slot", [slot], 0)
        entry = {"family": None, "id_word": None, "tries": []}
        for family in ("winbond", "ite"):
            with lock(pawnio.MUTEX_ISABUS):
                id_word, regs = _try_family(call, writes, port, family)
            entry["tries"].append({"family": family, "id_word": id_word})
            if _valid_id(id_word):
                entry.update(family=family, id_word=id_word, regs_hex=regs.hex())
                break
        if hwm and entry["family"] == "winbond":
            try:
                entry["hwm"] = collect_hwm(call, lock, writes, port)
            except pawnio.PawnIOError as e:
                entry["hwm"] = {"error": str(e)}
        slots[hex_min(port)] = entry
    found = [f"{p} {e['family']} {e['id_word']:#06x}" for p, e in slots.items() if e["family"]]
    return {"slots": slots, "summary": ", ".join(found) or "no SuperIO answered at 0x2E or 0x4E"}


# ====================================================================
#  SECTIONS AND THE DUMP
# ====================================================================

class Context:
    def __init__(self, args):
        self.args, self.writes = args, []
        self.identity = self.first_logical = None
        self._driver = self._driver_error = None
        self._modules = {}

    def vendor(self):
        if self.identity is None:
            raise pawnio.PawnIOError("the identity section failed, CPU vendor unknown")
        return self.identity["vendor"]

    def require_vendor(self, vendor):
        if self.vendor() != vendor:
            raise Skip(f"needs {vendor}, this CPU is {self.vendor()}")

    def cores(self):
        if self.first_logical is None:
            raise pawnio.PawnIOError("the topology section failed, no core list")
        return self.first_logical

    def driver(self):
        if self._driver_error is not None:
            raise self._driver_error
        if self._driver is None:
            try:
                self._driver = pawnio.Driver(start_service=not self.args.dry_run)
            except pawnio.PawnIOError as e:
                self._driver_error = e
                raise
        return self._driver

    def module(self, name):
        driver = self.driver()
        if self.args.dry_run:
            raise Skip("dry run, hardware not accessed")
        if name not in self._modules:
            self._modules[name] = driver.open_module(name)
        return self._modules[name]

    def close(self):
        if self._driver is not None:
            self._driver.close()


def sec_identity(ctx):
    ctx.identity = collect_identity()
    return ctx.identity


def sec_topology(ctx):
    data = collect_topology()
    ctx.first_logical = data["first_logical"]
    return data


def sec_tsc(ctx):
    return collect_tsc()


def sec_driver(ctx):
    info = {"device_path": pawnio.DEVICE_PATH}
    try:
        info["service"] = pawnio.service_info()
    except pawnio.PawnIOError as e:
        info["service_error"] = str(e)
    try:
        driver = ctx.driver()
    except pawnio.PawnIOError as e:
        e.partial = info
        raise
    info["version"] = list(driver.version)
    info["summary"] = "PawnIO " + ".".join(map(str, driver.version))
    return info


def sec_amd_msr(ctx):
    ctx.require_vendor(AMD)
    return collect_amd_msr(ctx.module("AMDFamily17").call, ctx.cores())


def sec_amd_smn(ctx):
    ctx.require_vendor(AMD)
    return collect_amd_smn(ctx.module("AMDFamily17").call, pawnio.bus_lock)


def sec_amd_umc(ctx):
    ctx.require_vendor(AMD)
    return collect_amd_umc(ctx.module("AMDFamily17").call, pawnio.bus_lock)


def sec_amd_smu(ctx):
    ctx.require_vendor(AMD)
    if not ctx.args.smu:
        raise Skip("opt-in: --smu sends SMU mailbox commands")
    return collect_amd_smu(ctx.module("RyzenSMU").call, pawnio.bus_lock)


def sec_intel_msr(ctx):
    ctx.require_vendor(INTEL)
    return collect_intel_msr(ctx.module("IntelMSR").call, ctx.cores())


def sec_intel_mchbar(ctx):
    ctx.require_vendor(INTEL)
    return collect_intel_mchbar(ctx.module("IntelMCHBAR").call)


def sec_smbus_spd(ctx):
    name = {AMD: "SmbusPIIX4", INTEL: "SmbusI801"}.get(ctx.vendor())
    if name is None:
        raise Skip(f"no SMBus module for {ctx.vendor()}")
    module = ctx.module(name)
    identity = module.call("ioctl_identity", [], 3)
    data = collect_spd(module.call, pawnio.bus_lock, ctx.writes)
    data.update(module=name, identity=identity)
    if not data["devices"]:
        e = pawnio.PawnIOError("no SPD device answered at 0x50-0x57")
        e.partial = data
        raise e
    return data


def sec_lpcio(ctx):
    return collect_lpcio(ctx.module("LpcIO").call, pawnio.bus_lock, ctx.writes, hwm=ctx.args.hwm)


SECTIONS = (("identity", sec_identity), ("topology", sec_topology), ("tsc", sec_tsc),
            ("driver", sec_driver), ("amd_msr", sec_amd_msr), ("amd_smn", sec_amd_smn),
            ("amd_umc", sec_amd_umc), ("amd_smu", sec_amd_smu), ("intel_msr", sec_intel_msr),
            ("intel_mchbar", sec_intel_mchbar), ("smbus_spd", sec_smbus_spd),
            ("lpcio", sec_lpcio))
assert tuple(n for n, _ in SECTIONS) == SECTION_NAMES


def run_section(ctx, fn):
    try:
        data = fn(ctx)
    except Skip as e:
        return {"status": "skipped", "detail": str(e), "data": {}}
    except OSError as e:
        return {"status": "error", "detail": str(e), "data": getattr(e, "partial", {})}
    except Exception as e:  # the probe records any section failure and carries on
        return {"status": "error", "detail": f"{type(e).__name__}: {e}", "data": {},
                "traceback": traceback.format_exc()}
    return {"status": "ok", "detail": "", "data": data}


def _compact(text):
    # one line per list of scalars; lists holding brackets, braces or strings with them stay as dumped
    return re.sub(r"\[\s*([^\[\]{}]*?)\s*\]",
                  lambda m: "[" + re.sub(r"\s*\n\s*", " ", m.group(1)) + "]", text)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hw_probe")
    for flag in ("--dry-run", "--smu", "--hwm"):
        ap.add_argument(flag, action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    computer = os.environ["COMPUTERNAME"]
    out = Path(args.out) if args.out else ROOT / "sandbox" / "fixtures" / f"hw_dump_{computer}.json"
    ctx, sections, interrupted, close_error = Context(args), {}, False, None
    print(f"hw_probe: {computer}, elevated {pawnio.is_admin()}, dry run {args.dry_run}")
    try:
        for name, fn in SECTIONS:
            rec = sections[name] = run_section(ctx, fn)
            text = rec["data"].get("summary", "") if rec["status"] == "ok" else rec["detail"]
            print(f"{name:<13}{rec['status']:<9}{text}", flush=True)
    except KeyboardInterrupt:
        interrupted = True
        print("interrupted")
    try:
        ctx.close()
    except OSError as e:
        close_error = str(e)
        print(f"close: {close_error}")
    for name, _ in SECTIONS:
        sections.setdefault(name, {"status": "skipped", "detail": "interrupted", "data": {}})
    dump = {"schema": SCHEMA, "computer": computer,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "elevated": pawnio.is_admin(), "dry_run": args.dry_run,
            "args": {"smu": args.smu, "hwm": args.hwm}, "interrupted": interrupted,
            "close_error": close_error, "writes": ctx.writes, "sections": sections}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_compact(json.dumps(dump, indent=1)) + "\n", encoding="utf-8")
    counts = {s: sum(r["status"] == s for r in sections.values()) for s in ("ok", "error", "skipped")}
    print(f"wrote {out}")
    print(f"{counts['ok']} ok, {counts['error']} error, {counts['skipped']} skipped; "
          f"{len(ctx.writes)} hardware writes logged")


if __name__ == "__main__":
    main()
