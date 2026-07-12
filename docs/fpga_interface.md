# FPGA Interface

The FPGA layer is responsible for timing-critical behavior that should not be
managed by a high-level Python process. The current files are placeholders, but
the boundary is intentionally explicit.

## Responsibilities

The FPGA design should eventually handle:

- Emitting optical pulse schedules with deterministic timing.
- Driving modulator, source, phase-control, or synchronization channels.
- Reading detector events and timestamps.
- Counting coincidences inside configurable timing windows.
- Exposing result buffers to the host runtime.
- Supporting calibration and diagnostic registers.

## Current Signals

The top-level placeholder module exposes:

- `clk` and `reset_n`.
- `command_valid` and `command_ready` for simple command handoff.
- `command_mask` for placeholder channel selection.
- `pulse_valid` and `pulse_mask` for scheduled pulse output.
- `detector_in` for detector samples.
- `coincidence_count` for accumulated multi-detector events.

This is not a final bus protocol. It is a minimal starting point for local HDL
experiments and design discussion.

## Future Interface Work

Before real FPGA deployment, the project should add:

- A host bus protocol such as AXI, PCIe, Ethernet, USB, or board-specific IO.
- FIFO or DMA paths for command and result streaming.
- Register maps for configuration and status.
- Clock-domain crossing strategy.
- Timing constraints.
- Reset sequencing.
- Simulation testbenches.
- HDL lint and synthesis checks in CI.
