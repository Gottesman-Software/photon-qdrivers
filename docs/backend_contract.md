# Backend Contract

Production emulator and hardware adapters must implement the same Python
backend contract:

- `name`: stable backend identifier.
- `device`: `PhotonicDevice` description.
- `initialize()`: prepare SDKs, transports, emulators, or hardware resources.
- `compile(circuit)`: accept a validated `PhotonicCircuit` and return a
  `PhotonicJob`.
- `run(job)`: execute a compiled job and return a normalized `PhotonicResult`.
- `cancel(job_id)`: request cancellation of a submitted job when supported.
- `shutdown()`: release emulator, SDK, transport, or hardware resources.

## Circuit IR

`PhotonicCircuit` is the first stable intermediate representation for the
Python layer. It validates:

- Schema version.
- Circuit type.
- Positive mode and shot counts.
- Operation shape.
- Mode references.
- Duplicate mode references inside one operation.

The API still accepts dictionaries through `photonic_driver.Driver.compile()`, but those
dictionaries are normalized before reaching a backend.

## Capability Checks

Backends expose `BackendCapabilities`, including:

- Supported operation names.
- Maximum modes.
- Maximum shots.
- Whether the backend supports emulation.
- Whether the backend controls real hardware.
- Whether the backend supports real-time execution.

Backends must reject circuits that exceed those limits before execution. This is
critical for hardware safety because the same user-level circuit may be valid IR
but invalid for a specific FPGA image, detector topology, or vendor device.

## Current Built-ins

- `mock`: fast deterministic backend for tests and API examples.
- `emulator`: deterministic local contract emulator. It is useful for workflow
  integration and result-shape testing, but it is not yet a physics-complete
  photonic simulator.
- `native`: C++ Runtime/HAL/Transport path exposed through a C ABI shared
  library and Python `ctypes` binding. It currently uses the in-memory transport
  and supports `BS`, `PS`, and `photon_counting`.
- `perceval`: optional Perceval adapter. Install with
  `python -m pip install ".[perceval]"` or `pip install perceval-quandela`.
  It currently supports local Perceval sampling for `BS`, `PS`, and
  `photon_counting` circuits with `metadata.input_state`.
- `piquasso`: optional Piquasso adapter. Install with
  `python -m pip install ".[piquasso]"` or `pip install piquasso`.
  It currently supports local Piquasso sampling for `BS`, `PS`, and
  `photon_counting` circuits with `metadata.input_state`.
- `lightworks`: optional Lightworks adapter. Install with
  `python -m pip install ".[lightworks]"` or `pip install lightworks`.
  It currently supports local Lightworks sampling for `BS`, `PS`, and
  `photon_counting` circuits with `metadata.input_state`.
- `thewalrus`: optional The Walrus adapter. Install with
  `python -m pip install ".[thewalrus]"` or `pip install thewalrus`.
  It currently supports metadata-defined GBS validation kernels: `hafnian`,
  `loop_hafnian`, `torontonian`, `probabilities`, and
  `hafnian_sample_graph`.
- `qutip`: optional QuTiP adapter. Install with
  `python -m pip install ".[qutip]"` or `pip install qutip`.
  It currently supports metadata-defined single-mode oscillator dynamics with
  `sesolve`, `mesolve`, Hamiltonian terms, collapse operators, and observables.
- `dynamiqs`: optional Dynamiqs adapter. Install with
  `python -m pip install ".[dynamiqs]"` or `pip install dynamiqs`.
  It currently supports metadata-defined single-mode oscillator dynamics with
  JAX-backed `sesolve`, `mesolve`, jump operators, methods, and observables.
  Dynamiqs requires Python 3.11+.
- `strawberryfields`: optional legacy Strawberry Fields adapter. Install with
  `python -m pip install ".[strawberryfields]"` or
  `pip install strawberryfields`. It currently supports local Fock-backend
  sampling for `BS`, `PS`, `S`, `D`, and `photon_counting`. Strawberry Fields
  is kept as legacy compatibility and is pinned to older Python environments.
  Current local Fock backends may reject batched shots, so the adapter can repeat
  single-shot runs and merge counts.
- `pennylane-sf`: registered legacy emulator target name that raises
  `BackendUnavailableError` until a compatibility adapter package is installed.
- `quandela`: optional hardware adapter through Perceval `RemoteProcessor`.
  Install with `python -m pip install ".[quandela]"` or
  `pip install perceval-quandela`. It supports `BS`, `PS`, and
  `photon_counting` circuits with `metadata.input_state`, then runs
  `Sampler.sample_count` on the configured Quandela Cloud platform.
- `xanadu`: optional legacy hardware adapter through Strawberry Fields
  `RemoteEngine` and `xanadu-cloud-client`. Install with
  `python -m pip install ".[xanadu]"` in a compatible legacy Python
  environment. Xanadu Quantum Cloud is no longer public, so this target is for
  private or archived XCC-compatible endpoints.
- `orca`: hardware adapter for ORCA-compatible deployments. It supports private
  SDK modules via `BackendConfig.options["sdk_module"]` and JSON HTTPS endpoints
  via `BackendConfig.endpoint`.
- `psiquantum`: optional PsiQuantum Construct / PsiQDK adapter for FTQC resource
  estimation and local simulation. Install with
  `python -m pip install ".[psiquantum]"` or `pip install psiqdk`. It is not a
  live QPU execution adapter. `psiqdk` may require a private package source, so
  it is not part of the public `.[hardware]` extra.

## Configuration

Backends receive a `BackendConfig` object when loaded:

```python
from photonic_driver import BackendConfig, Driver

config = BackendConfig(
    backend_name="perceval",
    profile="local",
    timeout_seconds=10,
    options={"processor_backend": "SLOS"},
)

driver = Driver.load("perceval", config=config)
```

Environment variables are also supported:

```bash
PHOTON_QDRIVERS_XANADU_TOKEN=...
PHOTON_QDRIVERS_XANADU_API_KEY=...
PHOTON_QDRIVERS_XANADU_CLIENT_ID=...
PHOTON_QDRIVERS_XANADU_CLIENT_SECRET=...
PHOTON_QDRIVERS_XANADU_ENDPOINT=...
PHOTON_QDRIVERS_XANADU_PROFILE=production
PHOTON_QDRIVERS_XANADU_TIMEOUT_SECONDS=30
PHOTON_QDRIVERS_XANADU_DEVICE_ID=...
PHOTON_QDRIVERS_XANADU_PROJECT_ID=...
PHOTON_QDRIVERS_ORCA_TOKEN=...
PHOTON_QDRIVERS_ORCA_ENDPOINT=...
PHOTON_QDRIVERS_ORCA_DEVICE=pt-2
PHOTON_QDRIVERS_PSIQUANTUM_PROFILE=local
```

Credentials must not be copied into job metadata, result metadata, logs, or
exceptions. Use `BackendConfig.public_dict()` when a backend needs to report
non-secret configuration provenance.

## Async, Timeout, And Cancellation

The synchronous path remains:

```python
result = driver.run(job)
```

For async execution:

```python
handle = driver.submit(job)
result = handle.result(timeout=10)
```

For bounded synchronous execution:

```python
result = driver.run(job, timeout=10)
```

If a timeout expires, the driver raises `JobTimeoutError` and requests backend
cancellation. Cancellation is best-effort because some SDKs, emulators, and
hardware transports may not be able to interrupt an already-running operation.

## Cloud Hardware Lifecycle

Hardware adapters can subclass `CloudHardwareBackend` and wrap a provider SDK
behind `CloudJobClient`. Provider statuses are normalized into `created`,
`queued`, `running`, `completed`, `failed`, and `cancelled` states. Completed
jobs return `PhotonicResult`; failed jobs raise `BackendExecutionError`; timed
out jobs request provider cancellation and raise `JobTimeoutError`.

See [Hardware adapter foundation](hardware_adapters.md) for the full adapter
author contract.

## Hardware Backend Requirements

A real hardware backend should add:

- A transport implementation such as PCIe, Ethernet, USB, AXI, or vendor SDK.
- Device discovery and capability reporting.
- Firmware version compatibility checks.
- Calibration state loading and validation.
- Command serialization and result decoding.
- Timeout, retry, and cancellation behavior.
- Hardware-safe bounds for pulse timing, power, detector windows, and buffers.
- Integration tests against an emulator and hardware-in-the-loop tests.
