# 08 Hardware Tab (CPU-Z replica), phase 1

A top-level **Hardware** tab that replicates CPU-Z (screenshot reference: CPU-Z 2.15 CPU
tab on this PC, AMD Ryzen 9 7950X3D) and absorbs the Temperatures tab as a Sensors
sub-tab. Phase 1 fills every field Windows exposes without a kernel driver. Phase 2
(separate spec, later) adds PawnIO-backed fields: core voltage, bus speed, multiplier,
memory timings, full SPD, CPU/board sensors, LPCIO.

## User decisions

- One Hardware tab with sub-tabs, in CPU-Z order: CPU, Caches, Mainboard, Memory, SPD,
  Graphics, then Sensors and About. No Bench sub-tab. No Save report. No Validate.
- The Temperatures top-level tab is removed; its page becomes the Sensors sub-tab. The GPU
  settings tab stays separate.
- Extras: a Clocks window (per-core live clocks, CPU-Z Tools > Clocks) and live refresh
  every second while the Hardware tab is visible.
- Driver-backed fields (phase 2) for AMD Zen and Intel. Phase 1 leaves them empty.

## Look (as close to CPU-Z as Qt allows)

- Each sub-tab mirrors CPU-Z's layout: titled group boxes ("Processor", "Clocks (Core
  #0)", "Cache", "Motherboard", "BIOS", "Graphic Interface", "General", "Timings",
  "Memory Slot Selection", "Timings Table", "GPU", "Clocks", "Memory"...), right-aligned
  black labels, values in read-only sunken boxes (read-only QLineEdit, white background,
  dark navy text like CPU-Z), same field order and same label text as CPU-Z, multi-column
  rows where CPU-Z has them (e.g. Code Name | Max TDP, Family | Model | Stepping).
- CPU tab top-right logo box: a framed box with the vendor name text (`AMD` / `Intel`);
  no brand artwork.
- Bottom bar of the Hardware tab like CPU-Z's: `Selection` combo (`Socket #1`), `Cores`,
  `Threads` readouts, and a `Tools` drop-down button whose menu has `Clocks`.
- Tahoma 8 and `Windows` style come from the app. Follow
  `C:\Dropbox\Common\lib\claude\md\qt-ui-conventions.md` (grids: black 1px gridlines, no
  zebra) for the SPD timings table and the Clocks list.
- A field with no data source in phase 1 is an empty box, never a guess or placeholder.

## Data sources (no driver)

Fail loudly in data paths: an API that should work and fails raises (and the sub-tab shows
the error text in place of its fields, e.g. `SMBIOS: <error>`); a field that is simply not
exposed stays empty.

### CPU
- CPUID via a ctypes executable thunk (VirtualAlloc PAGE_EXECUTE_READWRITE, x64 machine
  code taking leaf/subleaf, returning EAX..EDX). Pin to a core with
  SetThreadAffinityMask when a per-core value is needed, restore afterwards.
- Specification = brand string (0x80000002-4). Family/Model/Stepping, Ext. Family/Ext.
  Model shown in hex exactly as CPU-Z (`F`, `1`, `2`, `19`, `61` on this PC).
- Instructions line in CPU-Z format: `MMX(+), SSE (1, 2, 3, 3S, 4.1, 4.2, 4A), SSSE3,
  x86-64, AES, AVX, AVX2, AVX512, FMA3, SHA` (include each only when its CPUID bit is
  set; `MMX(+)` for AMD extended MMX, `SSE4A` only on AMD, `AVX512` variants as CPU-Z,
  `VT-x` / `AMD-V`, `EM64T` for Intel as CPU-Z shows).
- A table module `cpudb.py` keyed by vendor + family/ext model/stepping (and brand-string
  pattern where models share a key) gives Name (CPU-Z style, e.g. `AMD Ryzen 9 7950X3D`),
  Code Name, Max TDP, Package, Technology, Revision, and the multiplier range
  (min - max). Cover AMD Zen 1 through Zen 5 desktop/mobile and Intel Core 6th gen through
  Core Ultra 200S. Unknown CPU: those fields empty.
- Package also cross-checked with SMBIOS type 4 socket designation when the table has
  none.
- Cores / Threads and per-socket counts from GetLogicalProcessorInformationEx.
- Clocks (Core #0): Core Speed live = PDH `\Processor Information(0,N)\% Processor
  Performance` x `Processor Frequency` / 100 (what Task Manager uses), in `MHz` with two
  decimals. Multiplier, Bus Speed, Rated FSB: empty in phase 1.
- Cache group: from GetLogicalProcessorInformationEx RelationCache: `16 x 32 KBytes`,
  `8-way`; L3 with differing slices shown as CPU-Z does (`96 MB + 32 MB` on this PC).

### Caches
- One group per level (L1 D-Cache, L1 I-Cache, Level 2, Level 3): Size, Descriptor
  (`8-way set associative, 64-byte line size`), and the count x size line, from the same
  RelationCache data.

### Mainboard
- SMBIOS via GetSystemFirmwareTable('RSMB'), parsed in a `smbios.py` module (structure
  walk, string sets): type 0 BIOS (Brand, Version, Date), type 2 baseboard (Manufacturer,
  Model, revision), type 4 processor, type 16/17 memory, type 7 caches if useful.
- Chipset / Southbridge: PCI host bridge and ISA/LPC bridge (class 06/00 and 06/01) via
  SetupAPI hardware IDs (VEN/DEV/REV), named through a table in `cpudb.py` (AMD 600/800
  series, Intel 100-800 series; unknown: vendor name + device id hex).
- Bus Specs: the highest PCIe generation among root ports (DEVPKEY_PciDevice_MaxLinkSpeed),
  CPU-Z text `PCI-Express 5.0 (32.0 GT/s)`.
- Graphic Interface: for the primary display adapter, Bus (`PCI-Express 4.0`), Current /
  Max Supported Link Width (`x16`) and Link Speed (`2.5 GT/s` / `16.0 GT/s`) from
  DEVPKEY_PciDevice_CurrentLinkWidth/Speed and MaxLinkWidth/Speed.
- LPCIO: empty (phase 2). CPU Microcode: empty unless exposed in the registry
  (`HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0` `Update Revision`); use it when
  present.

### Memory
- General: Type (SMBIOS 17 memory type, e.g. `DDR5`), Size (total of populated modules,
  `64 GBytes`), Channel # only when derivable from SMBIOS bank/device locators naming the
  channel (count distinct channels; DDR5 shows `N x 32-bit` as CPU-Z: 2 sub-channels per
  DIMM channel), else empty. Mem Controller Freq / Uncore Freq: empty (phase 2).
- Timings: DRAM Frequency = SMBIOS configured speed / 2 in MHz (`2400.0 MHz`); the rest
  empty (phase 2).

### SPD
- Memory Slot Selection combo over SMBIOS type-17 devices (populated and empty, labelled
  `Slot #1`..., CPU-Z style). Per slot: module type (`DDR5`), Module Size (`32 GBytes`),
  Max Bandwidth (`DDR5-4800 (2400 MHz)` from SMBIOS max speed), Module Manuf. (SMBIOS
  manufacturer, JEDEC id mapped to name when SMBIOS gives a hex id), Part Number, Serial
  Number, Ranks (`Dual` / `Single` from SMBIOS attributes), Registered from type detail.
  DRAM Manuf., Week/Year, SPD Ext., timings table: empty (phase 2).

### Graphics
- Display Device Selection combo over DXGI adapters (skip the Microsoft Basic Render
  Driver). Per adapter from DXGI: Name, vendor/device/subsystem/revision (Revision box),
  dedicated memory Size.
- NVIDIA adapters additionally through nvidia-smi (reuse `gpu.py`'s runner) and, where
  needed, nvml.dll via ctypes: clocks (Core / Shader / Memory, current), TDP (default
  power limit), Memory Bus Width, Board Manuf. from the PCI subsystem vendor id (table:
  ASUS, MSI, Gigabyte, EVGA, Zotac, PNY, Palit, Gainward, Inno3D, NVIDIA...), Code Name and
  Technology from a device-id table (Turing, Ampere, Ada, Blackwell desktop parts).
- Memory Type / Vendor: empty unless NVML or nvidia-smi exposes them.

### Sensors
- The current TempsPage (`temps.py`) as the sub-tab content, unchanged in behaviour.
  Its polling stays as today (it already polls); do not run it while hidden if it already
  stops then.

### About
- Windows version (product name, display version, build.UBR), DirectX version, CPUID
  thunk status. Values only.

## Live refresh and Clocks window
- A 1 s QTimer runs only while the Hardware tab is the current top-level tab; it updates
  the CPU tab's Core Speed (for the core picked by the Clocks group, Core #0 default) and
  the Clocks window. No other polling in phase 1.
- Clocks window (Tools > Clocks): modeless, a grid with one row per core (`Core #0` ...)
  and the live clock in MHz; Multiplier and Bus columns present but empty in phase 1.
- Heavy reads (SMBIOS, SetupAPI, DXGI, nvidia-smi) happen once when the tab is first shown
  (lazy, like other pages' `_built`), not at app start.

## wintools.py integration
- Replace the `Temperatures` tab with `Hardware` (same position). Update the icons tuple
  (new icon key `hardware`, `resource\icons\tab_hardware.ico` with 16/24/32/48/256 frames
  drawn programmatically: a CPU chip glyph), `TAB_TERMS` (`Hardware`: cpu-z, cpu,
  processor, mainboard, motherboard, memory, spd, ram, bios, sensors, temps,
  temperatures, clocks), `closeEvent` shutdown, and anything referencing `temps_page`.
- The finder's tab entries pick the new tab up automatically.

## Ownership

New: `hardware.py` (page, sub-tabs, Clocks window), `hwinfo.py` (CPUID thunk, GLPIEx,
PDH clocks, SetupAPI/DEVPKEY, DXGI, NVML), `smbios.py`, `cpudb.py`,
`resource\icons\tab_hardware.ico`, `sandbox\test_hwinfo_*.py`, `sandbox\test_smbios.py`,
`sandbox\test_cpudb.py`, `sandbox\test_hardware_page.py`.
Edit: `wintools.py` (tab list, icons, TAB_TERMS, closeEvent, temps references),
`temps.py` only if embedding needs it, `sandbox\test_wintools_window.py`,
`sandbox\test_tab_icons.py`, any existing temps test.

## Tests
- cpuid: brand string equals `HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0`
  `ProcessorNameString` (trimmed); family/model/stepping decode matches the registry
  `Identifier` string; instruction list on this PC contains `AVX512` and `SHA`.
- cpudb: this PC's key gives Raphael / 5 nm / Socket AM5 (LGA1718) / 120.0 W / RPL-B2 /
  `AMD Ryzen 9 7950X3D`; a handful of Intel and AMD keys from each covered generation;
  an unknown key gives no fields.
- smbios: parse a captured raw table fixture (save this PC's RSMB blob under
  `sandbox\fixtures\`) and the live table; baseboard and BIOS strings equal WMI
  Win32_BaseBoard / Win32_BIOS; type-17 sizes sum to the installed RAM
  (GetPhysicallyInstalledSystemMemory).
- caches: counts x sizes per level match GLPIEx totals; this PC's L3 text is
  `96 MB + 32 MB` (or the exact CPU-Z equivalent you derive from the data; assert the
  derivation, not a hard-coded string, when the machine differs).
- clocks: PDH per-core values positive and below 2x the max multiplier x 100 MHz.
- PCIe link: the primary GPU reports a current and max width/speed.
- page: offscreen, every sub-tab builds, labels match the CPU-Z label list in the spec
  order, empty phase-2 boxes are empty strings, no tooltips anywhere, live timer runs
  only while the tab is current, Clocks window rows = logical cores' core count.
- wintools window/icon tests updated for the new tab; full sandbox suite passes.

## Rules for the implementer
- TDD: tests first, red, then green.
- No user-visible explainer text: labels, units, values, state readouts, genuine errors.
  No tooltips.
- Fail loudly in data paths; narrow try/except only around genuinely optional reads.
- Comments only for a non-obvious why. Match the surrounding style.
- `ruff check` clean on changed files; do not `ruff format` whole files.
- Byte-compile, then run every `sandbox\test_*.py` with `C:\Python\313\python.exe`.
- No git, no worktrees, no downloads, nothing created in `C:\` directly (scratch:
  `C:\tmp\`). Write large files in pieces (Write ~150 lines, then Edit to append).
- Finish with `STATUS: SUCCESS` or `STATUS: FAIL [reason]`, files changed, each test file
  with its result, and this PC's values for every CPU-tab field.
