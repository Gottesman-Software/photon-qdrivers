# FPGA Interface

The FPGA layer owns timing-critical schedule execution and detector accounting.
P5 adds an instruction-level engine beside the earlier pulse-mask smoke path.
P6.0 exposes that engine through a fixed 32-bit MMIO contract. P6.1 adds an
official Red Pitaya AXI-GP0 system-bus mapping and observation registers while
leaving the P6.0 addresses unchanged. The implementation remains pre-synthesis
and pre-deployment until reports and live-board evidence are captured.

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
place-and-route timing, deployed board IO, or optical accuracy.

## P6.1 Red Pitaya Mapping

`red_pitaya_sys_bus_adapter.sv` occupies system-bus slot 13 in the pinned
official `logic` image. The Zynq PS reaches that slot through AXI-GP0 at
physical base `0x40340000`. Both the adapter and schedule engine run on the
official 125 MHz fabric clock, so one physical device tick is 8 ns. There is no
clock-domain crossing inside this target.

The official top already constrains the expansion connector. The P6.1 overlay
drives the eight `exp_n_io`/DIO_N outputs from `pulse_active_mask` and samples
the eight `exp_p_io`/DIO_P inputs as detector events. The first bench uses
`DIO_N0 -> DIO_P4`. Observation-only registers are:

| Offset | Meaning |
| ---: | --- |
| `0x5c` | physical-observation protocol (`0x00010000`) |
| `0x60` | synthesized fabric clock in Hz |
| `0x64` | first loopback-output rising tick |
| `0x68` | first loopback-output falling tick |
| `0x6c` | first loopback-input rising tick |
| `0x70` | input-high cycles inside the acquisition window |
| `0x74` | output-rise, output-fall, and input-rise seen flags |

The P6.1 fixture deliberately drives output channel 0 over `[7, 11)` while a
two-bit count acquisition observes input channel 4 over the same half-open
interval. Simulation observes output rise 7, output fall 11, input rise 7,
four high cycles, saturated count 3, overflow, and one dropped event.

`RedPitayaMMIOBoard` verifies live capabilities, writes the exact P5 image,
polls bounded status transitions, reads both result and observation registers,
and emits `PQDR_PHYSICAL_EVIDENCE_V1`. That evidence binds the board/image
digests to the deployed bitstream SHA-256, fabric clock, device ticks, and host
round-trip time. It becomes physical evidence only after executing against a
connected board; the current Icarus result remains simulation evidence.
