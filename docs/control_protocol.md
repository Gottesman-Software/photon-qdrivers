# Control and Red Pitaya Bridge Protocol

Photon-QDrivers exposes two versioned mailbox directions. `PQDR_JOB_V1` and
`PQDR_RESULT_V1` carry the original circuit-job contract. The control plane uses
`PQDR_CONTROL_V1` and `PQDR_CONTROL_RESULT_V1` so compiled timing schedules and
acquisition evidence cannot be confused with ordinary circuit jobs.

All frames are UTF-8 text, begin with an exact protocol line, contain one
`key=value` field per line, and end with `END`. Unknown, duplicate, missing, or
malformed fields are rejected. Identifiers may not contain frame delimiters.

## Control Request

`PQDR_CONTROL_V1` contains:

| Field | Meaning |
| --- | --- |
| `job_id`, `program_id`, `profile_id` | Correlation identifiers |
| `profile_digest` | SHA-256 of the canonical hardware profile |
| `program_digest` | SHA-256 of `compiled_payload` |
| `envelope_digest` | SHA-256 binding identifiers, digests, and execution dimensions |
| `shots`, `repetition_ticks`, `sweep_points`, `event_count` | Declared execution dimensions |
| `compiled_payload_length` | UTF-8 byte length of the payload |
| `compiled_payload` | Canonical compiled-control JSON |

The C++ transport validates the payload length, program digest, and envelope
digest before accepting a request. The Python bridge reconstructs the compiled
program and independently checks every declared identity and execution
dimension before lowering it.

## Control Result

`PQDR_CONTROL_RESULT_V1` repeats the request correlation fields and adds:

| Field | Meaning |
| --- | --- |
| `acquisition_digest` | SHA-256 of the canonical acquisition payload |
| `status` | Completed or failed runtime state |
| `acquisition_count` | Number of normalized acquisition records |
| `total_device_ticks` | Logical schedule ticks, excluding host transport latency |
| `overflowed_acquisitions`, `dropped_events` | Finite-resource evidence |
| `acquisition_payload_length` | UTF-8 byte length of the payload |
| `acquisition_payload` | Canonical normalized acquisition JSON |
| `message` | Human-readable completion or error context |

The runtime rejects a result that does not match the submitted job, program,
profile, or envelope digest. It also rejects inconsistent lengths, digests,
counts, status values, and acquisition summaries.

## Fixed-Width RTL Image

The verified control schedule lowers into 128-bit version-1 instructions:

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

The current datapath accepts source trigger, modulator pulse, phase update,
sync, delay, and one count-acquisition window. It rejects incomplete channel
maps, non-count acquisitions, overlapping acquisition windows, unsorted
instructions, unsupported versions, multi-shot board images, and controller
sweeps.

## Board Frames and MMIO Mapping

`PQDR_BOARD_CAPABILITIES_V1` describes the Red Pitaya target, instruction and
channel limits, counter width, and fixed register map. Its canonical JSON has a
SHA-256 digest. `PQDR_BOARD_PROGRAM_V1` binds the control-envelope digest,
compiled-program digest, RTL-program digest, board identity, capability digest,
channel map, acquisition identity, and exact instruction words into an image
digest. `PQDR_BOARD_RESULT_V1` binds the image and capability digests to the
observed schedule and acquisition result.

The 32-bit register interface is:

| Address | Register |
| --- | --- |
| `0x00`-`0x14` | Identity, protocol, instruction width/capacity, channels, count width |
| `0x18` | Control: clear, push, last, run |
| `0x1c`-`0x20` | Status and error code |
| `0x24`-`0x3c` | Repetition, instruction count, tick, acquisition result, flags, pulse mask |
| `0x40`-`0x4c` | Four 32-bit instruction-word segments |
| `0x50`-`0x58` | Acquisition start, end, and channel |

Writing a read-only register latches error `0x80`. The host transport can use
regular files for deterministic loopback testing. A deployed Red Pitaya path
must expose the same command/result directions using a board daemon, character
device, named pipe, or AXI/FIFO-backed interface.

## Reproducible Loopback

Build and run all native and RTL checks with:

```bash
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
python -m pytest tests/control/test_native_protocol.py tests/control/test_board.py
python docs/examples/run_red_pitaya_control_loopback.py
```

The example uses temporary mailbox files and the deterministic software board
model; it requires no credentials, vendor SDK, calibration file, or private
endpoint.

This contract and its simulation tests establish host framing, digest
correlation, instruction-level execution, and MMIO readback. They do not prove
synthesis, place-and-route timing, physical board IO, transport latency, analog
signal fidelity, detector calibration, or optical correctness.

## P6.1 Physical Evidence Extension

P6.1 preserves every P6.0 address and adds observation-only registers from
`0x5c` through `0x74` for the physical protocol version, fabric clock, output
rise/fall ticks, input rise tick, high-cycle count, and seen flags. The
board-side `RedPitayaMMIOBoard` verifies the live P6.0 capabilities before
loading any image and emits `PQDR_PHYSICAL_EVIDENCE_V1` after a successful run.

Physical evidence additionally binds the `PQDR_BOARD_RESULT_V1` digest to the
deployed bitstream SHA-256, MMIO base address, 125 MHz clock, pin-channel
mapping, device-edge ticks, and host round-trip time. A locally constructed
evidence object or an HDL simulation does not establish that the FPGA was
synthesized, programmed, or electrically looped back.
