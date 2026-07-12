# C++ Runtime

The C++ layer is the host-runtime boundary for low-latency emulator and hardware
execution. It is intentionally vendor-neutral and now uses typed contracts
instead of raw string payloads.

## Core Types

- `RuntimeJob`: job id, serialized circuit IR, modes, shots, and operation list.
- `RuntimeResult`: job id, status, shots, counts, and message.
- `DeviceCapabilities`: mode limits, shot limits, supported operations, and
  hardware/realtime flags.
- `RuntimeError`, `ValidationError`, `TransportError`: explicit lifecycle,
  validation, and transport failures.

## Layering

```text
Runtime
  -> HAL
  -> Device
  -> FPGADriver
  -> Transport
```

The transport is abstract. The built-in `InMemoryTransport` is not a hardware
driver; it exists to test the runtime contract without a vendor SDK or board.

## Python Binding

The C++ runtime now exposes a small C ABI shared library,
`photon_qdrivers_capi`, with lifecycle, capability, submit, result, and error
functions. Python loads this library with `ctypes` through
`photon_qdrivers.NativeRuntime`.

The built-in Python backend `native` uses that binding:

```python
from photonic_driver import Driver

driver = Driver.load("native")
job = driver.compile({
    "type": "photonic_circuit",
    "modes": 2,
    "operations": [
        {"gate": "BS", "modes": [0, 1]},
        {"measure": "photon_counting", "modes": [0, 1]},
    ],
    "shots": 1000,
})
result = driver.run(job)
```

Build the shared library before using this backend:

```bash
cmake -S . -B build
cmake --build build
```

Set `PHOTON_QDRIVERS_NATIVE_LIBRARY` when the shared library is outside the
default local build directory.

### FPGA Mailbox Transport

The native backend can now use a concrete FPGA mailbox transport instead of the
default in-memory transport:

```python
from photonic_driver import Driver

driver = Driver.load(
    "native",
    transport="fpga_mailbox",
    command_path="/dev/photonq0_cmd",
    result_path="/dev/photonq0_result",
)
```

For hardware-in-the-loop tests, `command_path` and `result_path` may be regular
files. For a deployed board, they should point to character devices, named pipes,
or another driver-provided mailbox endpoint.

Command frames written by the host use this text protocol:

```text
PQDR_JOB_V1
job_id=<job id>
modes=<mode count>
shots=<shot count>
operations=BS,PS,photon_counting
circuit_ir=<serialized Photon-QDrivers circuit IR>
END
```

The result mailbox is expected to produce frames like:

```text
PQDR_RESULT_V1
job_id=<job id>
status=completed
shots=<shot count>
message=<optional message>
count=00:512
count=11:512
END
```

The transport scans result frames for the requested `job_id`, maps status into
`RuntimeResult.status`, and converts `count=<state>:<value>` lines into
`RuntimeResult.counts`.

### Red Pitaya Transport Profile

Red Pitaya is exposed as a board-specific native transport profile on top of the
same mailbox contract:

```python
from photonic_driver import Driver

driver = Driver.load(
    "native",
    transport="red_pitaya",
    command_path="/dev/photonq_redpitaya_cmd",
    result_path="/dev/photonq_redpitaya_result",
)
```

The C ABI entry point is `pqdr_runtime_create_red_pitaya(command_path,
result_path)`. It creates an `FPGAMailboxTransport` with the
`red-pitaya-stemlab-125-14` capability profile:

- `max_modes`: 8 logical modes, matching the current portable RTL defaults.
- `max_shots`: 1,000,000 per submitted job.
- `supported_operations`: `BS`, `PS`, and `photon_counting`.
- `realtime`: true.
- `hardware_backed`: true.

This is a host/runtime profile, not a complete Red Pitaya firmware image. On a
physical board, the command and result paths should be supplied by a Red Pitaya
board-side daemon, named pipes, character devices, or an AXI/FIFO bridge that
loads `PQDR_JOB_V1` frames into FPGA control logic and returns
`PQDR_RESULT_V1` frames.

## Next Hardware Step

The mailbox transport is the first concrete host-device transport path. The next
board-specific step is to adapt the Red Pitaya mailbox profile to one physical
interface:

- Red Pitaya Linux daemon using the board API or memory-mapped registers
- Red Pitaya FPGA FIFO/AXI bridge
- PCIe/DMA transport
- Ethernet transport
- USB transport
- Xilinx/AMD runtime
- Intel runtime
- Vendor SDK

That implementation should expose real `DeviceCapabilities`, serialize
`RuntimeJob` into a board command format, and decode firmware result buffers
into `RuntimeResult`.
