# 08 Hardware Tab: CPU-Z fidelity pass

Reference screenshots of CPU-Z 2.15 on this PC (authoritative for labels, field order,
layout, value formats, alignment): `ref\cpuz_cpu.png`, `ref\cpuz_mainboard.png`,
`ref\cpuz_memory.png`, `ref\cpuz_spd.png`, `ref\cpuz_graphics.png` in this folder. Open
them (the Read tool shows images) and match them. Caches has no screenshot; leave it.
Fields that need the driver stay empty (phase 2) but their boxes and labels must exist.

## All sub-tabs
- A label whose value box is empty is drawn gray (CPU-Z greys Rated FSB, DC Mode,
  Command Rate, Serial Number, Buffered, Correction, Registered, Shader / SoC ...); it
  turns black when the box has a value.
- Value alignment as in the screenshots: centered in most boxes; left-aligned for the
  Mainboard text fields (Manufacturer, Model, Bus Specs., BIOS Brand, Version) and SPD
  Part Number / Serial Number. Check each against the images.
- The Selection / Cores / Threads frame belongs to the CPU sub-tab (bottom of the CPU page,
  as in `cpuz_cpu.png`), not a bar shared by every sub-tab. The shared bottom bar keeps
  only the `Tools` drop-down (menu: `Clocks`).

## Mainboard (`cpuz_mainboard.png`)
- Chipset row: vendor box (`AMD`), name box (`Ryzen SOC`), `Rev.` box (`00`). Southbridge
  row: `AMD`, `B650`, `Rev.` `51`. LPCIO row: vendor box and chip box (both empty until
  phase 2).
- AMD Ryzen host bridges are named `Ryzen SOC` (CPU-Z); Intel host bridges keep the
  existing table naming split into vendor + name.
- BIOS: Brand; Version = `<SMBIOS type 0 version> - AMD AGESA <rest>` when SMBIOS type 40
  carries an `AGESA!V9 ComboAm5PI 1.2.0.0a` style string (here: `2124 - AMD AGESA
  ComboAm5PI 1.2.0.0a`; drop the `!V9` tag); plain version otherwise. Date with `CPU
  Microcode` on the same row to its right.
- Graphic Interface already matches; keep.

## Memory (`cpuz_memory.png`)
- General: left column Type, Size; right column Channel #, DC Mode, Uncore Frequency. No
  "Mem Controller Freq." row.
- Channel #: this PC shows `2 x 32-bit` (four DDR5 DIMMs on two channels). Use the
  distinct DIMM channel count as N in `N x 32-bit` for DDR5; `N x 64-bit` for DDR4 and
  older. Test this PC's exact text.
- Timings labels already match; values stay empty until phase 2 except DRAM Frequency.

## SPD (`cpuz_spd.png`)
- Rows: [slot combo][type box] ... `Module Size`; then left/right pairs: Max Bandwidth |
  SPD Ext.; Module Manuf. | Week/Year; DRAM Manuf. | Buffered; Part Number | Correction;
  Serial Number | Registered. No Ranks field.
- Type box: `DDR5 (UDIMM)` style: memory type plus module form, from SMBIOS form factor
  and type detail (UDIMM, RDIMM, SO-DIMM, LRDIMM ...).
- Registered / Buffered: text only when the module is registered / buffered; otherwise
  empty (gray label). Serial Number: empty when SMBIOS reports all zeros.
- Timings Table: CPU-Z draws read-only boxes, not a gridded table: a header row of
  profile names, a label column (Frequency, CAS# Latency, RAS# to CAS#, RAS# Precharge,
  tRAS, tRC, Command Rate, Voltage), value boxes in between. Columns are filled in phase 2
  (JEDEC #n / XMP-nnnn / EXPO-nnnn from SPD); in phase 1 show four empty columns with
  empty headers.

## Graphics (`cpuz_graphics.png`)
- Display Device Selection: device combo, `Perf Level` label, perf combo with `Current`.
  The adapter that drives the primary display gets a ` *` suffix in the device combo.
- GPU rows: Name; Board Manuf.; Code Name | Revision; Technology | TDP; ROPs / TMUs |
  Cores. A vendor text box (`NVIDIA` / `AMD` / `Intel`) top right, like the CPU tab.
- Code Name with the SKU suffix (`GA102-300`), ROPs / TMUs (`112 / 328`), Cores (`10496`),
  memory Type (`GDDR6X`) from the device-id table in `cpudb.py`; extend the table for the
  covered NVIDIA desktop parts.
- Board Manuf.: the full subsystem vendor name as CPU-Z prints it (`ASUSTeK Computer
  Inc.`, `Micro-Star International Co., Ltd.`, `Gigabyte Technology Co., Ltd.`, ...).
- Clocks: `GFX Core`, `Shader / SoC`, `Memory`, one decimal (`855.0 MHz`). Shader / SoC is
  empty on NVIDIA.
- Memory: Size (`24 GBytes`), Type, Vendor (empty unless a source exists), Bus Width
  (`384 bits`), in that order.

## Tests
- Update `sandbox\test_hardware_page.py` label/order assertions to these layouts and
  assert this PC's values from the screenshots wherever phase 1 has a source: Chipset
  `AMD` / `Ryzen SOC` / `00`, Southbridge `AMD` / `B650` / `51`, BIOS version with AGESA,
  Channel # `2 x 32-bit`, SPD type `DDR5 (UDIMM)`, empty Registered / Serial, GPU Code
  Name `GA102-300`, Board Manuf. `ASUSTeK Computer Inc.`, ROPs / TMUs `112 / 328`, Cores
  `10496`, Type `GDDR6X`, Size `24 GBytes`, Bus Width `384 bits`, the ` *` on the
  primary adapter, gray labels exactly on the empty boxes.
- `sandbox\test_smbios.py`: type-40 AGESA string parsed from the fixture.
- `sandbox\test_cpudb.py`: the new GPU table columns, AMD host bridge `Ryzen SOC`.
