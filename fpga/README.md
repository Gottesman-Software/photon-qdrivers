# FPGA Firmware

This directory contains portable SystemVerilog modules for the timing-critical
part of Photon-QDrivers. The current RTL is board-neutral and focuses on the
core responsibilities needed before adding a PCIe, Ethernet, USB, AXI, or vendor
SDK transport.

## Modules

- `systemverilog/photon_qdriver_pkg.sv`: shared parameters, status enum, and
  package guard.
- `systemverilog/pulse_scheduler.sv`: accepts pulse commands, enforces
  non-empty masks, holds pulses for a configurable number of cycles, and reports
  busy/error state.
- `systemverilog/detector_readout.sv`: synchronizes detector inputs, captures
  rising-edge events, emits samples, and applies configurable holdoff.
- `systemverilog/coincidence_counter.sv`: accumulates detector events inside a
  configurable coincidence window and exposes count/bitmask outputs.
- `systemverilog/top_photon_qdriver.sv`: connects scheduler, readout, counter,
  status, and error signaling.
- `testbench/tb_top_photon_qdriver.sv`: self-checking simulation testbench.

## Simulation

Use any SystemVerilog-capable simulator. Examples:

```bash
verilator --lint-only -sv -I./fpga/systemverilog -f fpga/filelist.f
```

```bash
iverilog -g2012 -I fpga/systemverilog -o /tmp/tb_top_photon_qdriver \
  fpga/testbench/tb_top_photon_qdriver.sv
vvp /tmp/tb_top_photon_qdriver
```

When Verilator or Icarus Verilog are installed, CMake registers FPGA checks with
CTest:

```bash
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

## Board Targets

The recommended first hardware bench is Red Pitaya STEMlab 125-14 for lab-facing
IO, followed by Arty A7-100T for pure FPGA RTL validation and AMD Kria KV260 for
host/runtime transport work. See `docs/hardware_lab.md`.

## Red Pitaya Host Path

The native backend now includes a Red Pitaya profile:

```python
from photonic_driver import Driver

driver = Driver.load(
    "native",
    transport="red_pitaya",
    command_path="/dev/photonq_redpitaya_cmd",
    result_path="/dev/photonq_redpitaya_result",
)
```

This profile uses the shared mailbox protocol and reports the device as
`red-pitaya-stemlab-125-14`. The first production board integration should add
a Red Pitaya process or FPGA bridge that connects those paths to the portable
SystemVerilog modules in this directory.

## Host Mailbox Contract

The C++ runtime includes `FPGAMailboxTransport`, which writes job frames to a
command mailbox and reads result frames from a result mailbox. During tests these
mailboxes can be regular files; on hardware they should be character devices,
named pipes, PCIe BAR-backed endpoints, or another driver-provided transport.

Firmware or a board-side daemon should consume `PQDR_JOB_V1` frames and produce
matching `PQDR_RESULT_V1` frames. The frame format is documented in
`docs/cpp_runtime.md`.

## Next Production Steps

- Map the mailbox protocol onto command and result FIFOs.
- Add a memory-mapped register interface for status, control, and capability
  discovery.
- Add board-specific constraints for one selected board.
- Add CDC rules if host and control logic use different clocks.
- Add Verilator or simulator CI once a simulator is available.
