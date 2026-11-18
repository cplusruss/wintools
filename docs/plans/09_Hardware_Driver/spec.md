# 09 Hardware Driver (CPU-Z phase 2), step 1: PawnIO client and raw probe

Phase 2 fills the Hardware tab's driver-backed fields through PawnIO (the signed driver
already installed on this PC, service `PawnIO`, demand start) and its official signed
modules (`resource\release_0_2_11.zip`, from namazso/PawnIO.Modules 0.2.11, SHA256
43608cb89bc84247fef1368a139013f7d043e17db6d6c8dfc9b46bf0905a81f4). The agent shell is not
elevated and PawnIO needs administrator rights, so phase 2 runs in two steps:

1. (this spec) A PawnIO client, module packaging, and a read-only raw probe the user runs
   once elevated; it writes a JSON dump that becomes a test fixture.
2. (next spec) Decoders for every field, tested against that dump with the CPU-Z
   screenshot values in `docs\plans\08_Hardware_Tab\ref\` as expected results.

## User decisions (phase 2 overall)
- PawnIO + official modules; AMD Zen and Intel. Read-only hardware access, except the
  SMBus page-select writes that reading DDR4/DDR5 SPD requires (below).
- Fields: CPU Core Voltage, Multiplier (current and range), Bus Speed; Mainboard LPCIO;
  Memory DC Mode, Uncore Frequency, DRAM Frequency (measured), FSB:DRAM, CL, tRCD, tRP,
  tRAS, tRC, CR; SPD Max Bandwidth, SPD Ext., Week/Year, DRAM Manuf., timings table
  (JEDEC and XMP/EXPO columns, voltages); Sensors: CPU temperatures, core voltage, board
  SuperIO temperatures/fans/voltages where the chip is supported.

## Step 1 behaviour

### Module packaging
- Extract only the modules phase 2 uses into `resource\pawnio\`: `AMDFamily17.bin`,
  `RyzenSMU.bin`, `IntelMSR.bin`, `IntelMCHBAR.bin`, `SmbusPIIX4.bin`, `SmbusI801.bin`,
  `LpcIO.bin`, plus `COPYING`. Verify the zip's SHA256 first (value above); a mismatch is a
  genuine error and nothing is extracted. Resolve `resource\pawnio\` the same way the app
  resolves its other resources for source and frozen runs.

### `pawnio.py` client (no PawnIOLib.dll on this PC)
- Talk to the driver with CreateFileW + DeviceIoControl. Take the device path, IOCTL codes
  and buffer layouts from the PawnIO source on GitHub (namazso/PawnIO, which absorbed
  PawnIOLib); read it with WebFetch, cite the file and line in a code comment. No
  downloads.
- `Driver` opens the device (starting the `PawnIO` service with StartService when it is
  stopped; needs administrator), `load(module_bytes)` returns a handle,
  `execute(handle, fn_name, inputs: list[int], n_out) -> list[int]`, `close()`.
- Errors are genuine: not elevated -> `PawnIOError("PawnIO: administrator required")`,
  service missing -> `PawnIOError("PawnIO: driver not installed")`, IOCTL failure ->
  the Win32 message with the function name.
- Shared-bus etiquette: hold `Global\Access_SMBUS.HTP.Method` around SMBus transactions,
  `Global\Access_ISABUS.HTP.Method` around LPC/SuperIO access, `Global\Access_PCI` around
  PCI config access, as HWiNFO / CPU-Z / LibreHardwareMonitor do (create-or-open, wait with
  a timeout, genuine error on timeout).
- Per-core reads: run the execute on a thread pinned with SetThreadAffinityMask (group
  aware via SetThreadGroupAffinity), restoring afterwards.
- List each module's exported function names by reading the PawnIO.Modules source for
  that module (WebFetch); record them in `pawnio.py` constants with a source comment.

### `temp\..` -> `tools\hw_probe.py` raw probe (read-only, user runs elevated)
- A standalone script (`tools\hw_probe.py`, new folder in the repo) that the user runs from
  an elevated prompt: `C:\Python\313\python.exe tools\hw_probe.py`. It prints a one-line
  state per section and writes `sandbox\fixtures\hw_dump_<COMPUTERNAME>.json`.
- Captures raw values only, no decoding:
  - CPUID identity (vendor, family/model/stepping) for keying.
  - TSC frequency measured against QueryPerformanceCounter over 250 ms.
  - AMD: MSRs C0010015 (HWCR), C0010061-C0010063 (P-state limits/control/status),
    C0010064-C001006B (P-state definitions), C0010293 (hardware P-state status), 0xE7/0xE8
    (MPERF/APERF) twice 100 ms apart, per physical core (first logical processor). SMN
    reads: THM_TCON_CUR_TMP 0x00059800 and the CCD temperature block 0x00059954 + 4*i
    (i < 12); UMC0/UMC1 timing and config blocks (0x00050000-0x000502FF and
    0x00150000-0x001502FF, dword by dword; skip addresses the module rejects and record
    the error); the SMU PM table via RyzenSMU (version and the full table as dwords).
  - Intel: MSRs 0xCE (platform info), 0x198 (perf status), 0x199, 0x1A2 (temperature
    target), 0x19C per core, 0x1B1, 0xE7/0xE8 twice 100 ms apart, 0x606/0x611 (RAPL unit
    and package energy); MCHBAR base and the memory-controller timing block for the
    generation (IntelMCHBAR).
  - SMBus SPD: for each address 0x50-0x57 that answers, the full SPD (DDR5: 1024 bytes via
    the SPD5 hub page register MR11 at 0x0B; DDR4: 512 bytes via EE1004 page select at
    0x36/0x37). Writes are limited to exactly these page-select operations on addresses
    already identified as an SPD hub / EE1004; record which memory type was detected and
    every byte. Restore page 0 afterwards.
  - LpcIO: SuperIO chip id and vendor at 0x2E and 0x4E (enter/exit config mode per the
    module), plus the hardware-monitor bank registers the module exposes for that chip.
- Any section that fails records its error string and the probe continues.
- The probe never writes anything else: no MSR writes, no SMN writes, no PCI writes, no
  SuperIO writes beyond config-mode enter/exit.

### Not in step 1
- No decoding, no UI changes, no wintools.py changes.

## Ownership
New: `pawnio.py`, `tools\hw_probe.py`, `resource\pawnio\*`, `sandbox\test_pawnio.py`.
Read-only: everything else.

## Tests (`sandbox\test_pawnio.py`, unelevated)
- Module extraction: SHA256 check passes for the real zip and fails for a corrupted copy
  (in C:\tmp\); the extracted set equals the list above.
- IOCTL request packing/unpacking against the documented layouts, with byte-exact
  expected buffers.
- Not elevated: `Driver()` raises `PawnIOError` with the administrator message (this agent
  shell proves it).
- Probe dry-run: `hw_probe.py --dry-run` (unelevated) writes a dump whose sections each
  hold the administrator error, valid JSON, schema keys present.
- Mutex helper: acquire/release, timeout error.

## Rules for the implementer
- TDD: tests first, red, then green. Byte-compile; `ruff check` clean; no `ruff format` of
  whole files. Run every `sandbox\test_*.py`.
- No git, no worktrees, no downloads (WebFetch reads of GitHub source are allowed). Scratch
  outside the repo only in `C:\tmp\`. Write large files in pieces.
- Comments only for a non-obvious why (cite PawnIO source locations).
- Finish with `STATUS`, files changed, each test result, the exact command the user runs
  elevated, and the module function names found for each module.
