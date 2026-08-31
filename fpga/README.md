# FPGA Firmware

This directory contains portable SystemVerilog modules for the timing-critical
part of Photon-QDrivers. The current RTL is board-neutral and focuses on the
core responsibilities needed before adding a PCIe, Ethernet, USB, AXI, or vendor
SDK transport.

## Modules

- `systemverilog/photon_qdriver_pkg.sv`: shared parameters, status enum, and
  P5 opcode/error contracts.
- `systemverilog/control_instruction_decoder.sv`: decodes and validates the
  fixed 128-bit P5 instruction.
- `systemverilog/control_schedule_engine.sv`: loads and executes one compiled
  schedule template in logical device ticks, with decoded observations, pulse
  masks, acquisition counting, saturation, and structured errors.
- `systemverilog/red_pitaya_control_bridge.sv`: exposes the P5 engine through
  the fixed P6.0 32-bit MMIO capability, instruction, status, and result map.
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
- `testbench/tb_control_schedule_engine.sv`: self-checking P5 schedule-parity,
  saturation, and fault-injection testbench.
- `testbench/tb_red_pitaya_control_bridge.sv`: self-checking P6.0 MMIO load,
  execution, result-readback, capability, and read-only-write testbench.
- `testbench/fixtures/p5_control_program.hex`: immutable six-instruction P5
  reference shared with Python and RTL tests.

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

The P5 reference test is:

```bash
iverilog -g2012 -I fpga/systemverilog \
  -o /tmp/tb_control_schedule_engine \
  fpga/testbench/tb_control_schedule_engine.sv
vvp /tmp/tb_control_schedule_engine \
  +PROGRAM=fpga/testbench/fixtures/p5_control_program.hex
```

The P6.0 register-interface test is:

```bash
iverilog -g2012 -I fpga/systemverilog \
  -o /tmp/tb_red_pitaya_control_bridge \
  fpga/testbench/tb_red_pitaya_control_bridge.sv
vvp /tmp/tb_red_pitaya_control_bridge \
  +PROGRAM=fpga/testbench/fixtures/p5_control_program.hex
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
`red-pitaya-stemlab-125-14`. P6.0 supplies the verified board-program bridge and
MMIO RTL wrapper. P6.1 must map the wrapper into a synthesized Red Pitaya image
or a live board daemon.

## Host Mailbox Contract

The C++ runtime includes `FPGAMailboxTransport`, which writes job frames to a
command mailbox and reads result frames from a result mailbox. During tests these
mailboxes can be regular files; on hardware they should be character devices,
named pipes, PCIe BAR-backed endpoints, or another driver-provided transport.

The legacy job path consumes `PQDR_JOB_V1` and produces `PQDR_RESULT_V1`. The
P4 control path consumes `PQDR_CONTROL_V1` and returns
`PQDR_CONTROL_RESULT_V1`; its frame contract is documented in
[`docs/control_protocol.md`](../docs/control_protocol.md). P5 adds the separate
fixed-width instruction image used inside the schedule engine. The P6.0
`P6BoardBridge` now verifies and correlates the P4 request, produces a
capability-bound P5 image, and serializes acquisition evidence into the P4
result direction.

## Next Production Steps

- Map the implemented P6.0 registers onto Red Pitaya AXI or a deployed board
  daemon.
- Add board-specific constraints for one selected board.
- Add CDC rules if host and control logic use different clocks.
- Execute the immutable P5 fixture through a Red Pitaya digital loopback and
  compare physical timing, counts, overflow, and dropped events.
