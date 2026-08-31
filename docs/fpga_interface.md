# FPGA Interface

The FPGA layer owns timing-critical schedule execution and detector accounting.
P5 adds an instruction-level engine beside the earlier pulse-mask smoke path.
P6.0 now exposes that engine through a fixed 32-bit MMIO contract intended for
a Red Pitaya-side AXI bridge or daemon. It remains pre-synthesis and
board-neutral at the electrical boundary.

## P6.0 MMIO Board Interface

`red_pitaya_control_bridge.sv` exposes identity, protocol, instruction-width,
instruction-capacity, channel-count, and counter-width registers. Four 32-bit
data registers buffer each 128-bit P5 word. The control register emits clear,
push, last, and run pulses into `control_schedule_engine`.

Status and result registers expose loaded/ready/busy/done/error state, logical
device tick, acquisition interval and channel, saturated count, overflow,
dropped events, and the pulse-active mask. Writes to read-only addresses latch
MMIO error `0x80`. The complete address map and host framing are documented in
[`control_protocol.md`](control_protocol.md).

P6.0 also defines digestible board capabilities and correlated
`PQDR_BOARD_PROGRAM_V1`/`PQDR_BOARD_RESULT_V1` frames. The software bridge
accepts the existing P4 mailbox frame, verifies its compiled program and
envelope, lowers P5 words, and serializes the board result back into the
existing P4 result direction.

## P5 Compiled-Schedule Interface

`control_schedule_engine.sv` loads a sequence of 128-bit instructions using
`instruction_valid`, `instruction_ready`, `instruction_word`, and
`instruction_last`. `program_clear` resets the loaded image. `run_start` begins
one schedule template with an explicit `repetition_ticks` bound.

The packed fields are:

| Bits | Field |
| --- | --- |
| 127:124 | format version |
| 123:120 | opcode |
| 119:112 | channel index |
| 111:80 | start tick |
| 79:48 | duration ticks |
| 47:16 | argument word |
| 15:8 | acquisition kind |
| 7:0 | flags |

Format v1 supports source trigger, modulator pulse, phase update, sync, delay,
and count-acquisition instructions. Codes exist for other acquisition kinds,
but P5 rejects them until matching waveform, time-tag, coincidence, and
thresholded-event datapaths exist. Python lowering is implemented by
`photon_qdrivers.control.rtl.RTLProgram`.

Execution status is exposed through `engine_busy`, `engine_done`,
`engine_error`, `error_code`, and the logical `device_tick`. Observation signals
publish every decoded instruction field. `pulse_active_mask` exposes source and
modulator intervals. The acquisition interface reports its active/done state,
channel, half-open tick range, saturating count, overflow, and dropped events.

The engine accepts only nondecreasing start ticks and one active count
acquisition window. Shots and sweeps are host/runtime operations in v1. Phase,
sync, delay, amplitude, and flags are observable decoded fields; board-specific
phase registers and analog effects are not part of P5. The logical device tick
is independent of software and mailbox latency.

## Legacy Smoke Interface

`top_photon_qdriver.sv` retains the earlier mask-based test path:

- `clk` and `reset_n`;
- `command_valid`, `command_ready`, and `command_mask`;
- `pulse_valid` and `pulse_mask`;
- `detector_in`;
- `coincidence_count`.

This path still provides a compact integration smoke test for the pulse
scheduler, detector readout, and coincidence counter. It is not the compiled
P5 instruction loader.

## Validation State

The committed P5 fixture is lowered independently in Python and executed by a
self-checking Icarus Verilog testbench. Six decoded observations match exactly.
The acquisition counter saturates at three with overflow and one dropped event;
invalid-version, unsorted-program, and unsupported-acquisition loads report
stable error codes. The P6.0 MMIO testbench loads the same fixture through
register writes, reads the result registers, and matches the software board
model. Verilator lint covers the legacy top, P5 schedule engine, and P6.0 board
wrapper.

This establishes RTL simulation parity only. It does not establish synthesis,
place-and-route timing, clock-domain crossing correctness, board IO, or optical
accuracy.

## Physical-Board Work

P6.1 must add:

- an AXI mapping or deployed daemon connecting the P6.0 contract to a live Red
  Pitaya address space;
- clock-domain crossings, timing constraints, and reset sequencing;
- board-specific pin and electrical constraints;
- synthesized timing reports and a physical digital-loopback experiment.
