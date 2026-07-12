# Adapter Status

Photon-QDrivers keeps vendor and emulator dependencies optional. The core package
registers stable backend names, and each backend either executes through an
installed adapter or fails with `BackendUnavailableError`.

## Install Groups

Use `.[emulators]` for the public emulator stack in the active Python
environment. Some adapters are version-gated:

- Python 3.12+: modern emulator stack, including Dynamiqs.
- Python 3.10: legacy Strawberry Fields/Xanadu compatibility stack.

Use `.[hardware]` for public hardware/client dependencies. PsiQuantum remains a
separate `.[psiquantum]` extra because `psiqdk` is SDK-distribution dependent
and may require a private package source.

Runnable examples live in [docs/examples](examples/README.md).

## Current Adapter State

| Backend | Status | Install extra | Notes |
| --- | --- | --- | --- |
| `mock` | Built in | None | Deterministic local backend for tests and examples. |
| `emulator` | Built in | None | Deterministic contract emulator, not a physics-complete simulator. |
| `native` | Built in, requires local CMake build | None | Python backend that executes through the compiled C++ Runtime/HAL/Transport stack via the C ABI shared library. Supports in-memory and FPGA mailbox transports. |
| `perceval` | Implemented optional adapter | `.[perceval]` | Local Perceval `Processor` + `Sampler.sample_count()` path for `BS`, `PS`, and `photon_counting`. Requires `metadata.input_state`. |
| `piquasso` | Implemented optional adapter | `.[piquasso]` | Local Piquasso `Program` + `SamplingSimulator.execute()` path for `BS`, `PS`, and `photon_counting`. Requires `metadata.input_state`. |
| `lightworks` | Implemented optional adapter | `.[lightworks]` | Local Lightworks `PhotonicCircuit` + `Sampler` path through `lightworks.emulator.Backend`. Requires `metadata.input_state`. |
| `thewalrus` | Implemented optional adapter | `.[thewalrus]` | Local The Walrus hafnian, loop hafnian, torontonian, probability, and graph-sampling kernels. Uses metadata-defined GBS requests. |
| `qutip` | Implemented optional adapter | `.[qutip]` | Local QuTiP single-mode oscillator dynamics with `sesolve`/`mesolve`, Hamiltonian terms, collapse operators, and observables. |
| `dynamiqs` | Implemented optional adapter | `.[dynamiqs]` | Local Dynamiqs JAX single-mode oscillator dynamics with `sesolve`/`mesolve`, jump operators, methods, and observables. Dynamiqs requires Python 3.11+. |
| `strawberryfields` | Implemented optional legacy adapter | `.[strawberryfields]` | Local Strawberry Fields Fock-backend sampling for `BS`, `PS`, `S`, `D`, and `photon_counting`. Strawberry Fields is legacy and pinned to older Python environments; batched local Fock sampling falls back to repeated single-shot execution when required by the SDK. |
| `pennylane-sf` | Registered legacy target | Future package | PennyLane-SF compatibility target. Kept isolated because it is not supported on modern PennyLane. |
| `quandela` | Implemented optional hardware adapter | `.[quandela]` | Uses Perceval `RemoteProcessor` + `Sampler.sample_count` for Quandela Cloud QPU/simulator targets. Requires credentials and `metadata.input_state`. |
| `xanadu` | Implemented legacy hardware adapter | `.[xanadu]` | Uses Strawberry Fields `RemoteEngine` + `xanadu-cloud-client` for private or archived Xanadu Cloud-compatible endpoints. Xanadu Quantum Cloud is no longer public. |
| `orca` | Implemented hardware adapter | Private SDK or endpoint | Supports private ORCA SDK modules through `sdk_module` and configurable JSON HTTPS endpoints through `BackendConfig.endpoint`. |
| `psiquantum` | Implemented optional FTQC software adapter | `.[psiquantum]` | Uses PsiQuantum PsiQDK / Construct Workbench for local FTQC resource estimation and simulation. This is not live QPU execution. |

## Adapter Contract

Every adapter must implement:

- `initialize()`
- `compile(circuit)`
- `run(job)`
- `cancel(job_id)`
- `shutdown()`

Adapters should accept `BackendConfig`, expose `PhotonicDevice`, validate
capabilities before execution, and return `PhotonicResult`.

## The Walrus Request Shape

The Walrus backend is a kernel adapter, not a full circuit simulator. Use
metadata to select the kernel:

```python
driver = Driver.load("thewalrus")
job = driver.compile({
    "type": "photonic_circuit",
    "modes": 2,
    "operations": [{"measure": "photon_counting", "modes": [0, 1]}],
    "shots": 1000,
    "metadata": {
        "kernel": "hafnian_sample_graph",
        "adjacency_matrix": [[0.0, 1.0], [1.0, 0.0]],
        "n_mean": 2.0,
    },
})
```

Supported kernels are `hafnian`, `loop_hafnian`, `torontonian`,
`probabilities`, and `hafnian_sample_graph`.

## QuTiP Request Shape

The QuTiP backend is a dynamics adapter. The first supported model is
single-mode `oscillator_dynamics`:

```python
driver = Driver.load("qutip")
job = driver.compile({
    "type": "photonic_circuit",
    "modes": 1,
    "operations": [{"measure": "photon_counting", "modes": [0]}],
    "shots": 1000,
    "metadata": {
        "model": "oscillator_dynamics",
        "cutoff": 8,
        "times": [0.0, 0.5, 1.0],
        "initial_state": {"kind": "fock", "n": 1},
        "hamiltonian": [{"operator": "num", "coefficient": 1.0}],
        "collapse_operators": [{"operator": "destroy", "rate": 0.01}],
        "observables": [{"name": "n", "operator": "num"}],
    },
})
```

The adapter chooses `sesolve` unless collapse operators are present, in which
case it chooses `mesolve`. You can override with `metadata.solver`.

## Dynamiqs Request Shape

The Dynamiqs backend mirrors the QuTiP metadata shape for single-mode
`oscillator_dynamics`, but executes through Dynamiqs' JAX solvers:

```python
driver = Driver.load("dynamiqs")
job = driver.compile({
    "type": "photonic_circuit",
    "modes": 1,
    "operations": [{"measure": "photon_counting", "modes": [0]}],
    "shots": 1000,
    "metadata": {
        "model": "oscillator_dynamics",
        "cutoff": 8,
        "times": [0.0, 0.5, 1.0],
        "initial_state": {"kind": "coherent", "alpha": 0.5},
        "hamiltonian": [{"operator": "number", "coefficient": 1.0}],
        "jump_ops": [{"operator": "destroy", "rate": 0.01}],
        "observables": [{"name": "n", "operator": "number"}],
    },
})
```

The adapter chooses `sesolve` unless jump operators are present, in which case
it chooses `mesolve`. Use `metadata.method` or `load_backend(..., method="Tsit5")`
to select a Dynamiqs method.

## Strawberry Fields Request Shape

The Strawberry Fields backend is a legacy compatibility adapter for local Fock
simulations:

```python
driver = Driver.load("strawberryfields", cutoff_dim=6)
job = driver.compile({
    "type": "photonic_circuit",
    "modes": 2,
    "operations": [
        {"gate": "BS", "modes": [0, 1], "theta": 0.785, "phi": 0.0},
        {"gate": "PS", "mode": 0, "theta": 0.5},
        {"measure": "photon_counting", "modes": [0, 1]},
    ],
    "shots": 1000,
    "metadata": {"input_state": [1, 0]},
})
```

If `metadata.input_state` is omitted, the adapter starts from vacuum. This path
is intentionally isolated from the modern core because Strawberry Fields is
maintained as legacy compatibility.

## Implementation Order

1. Perceval local simulator adapter.
2. Piquasso local simulator adapter.
3. Lightworks local simulator adapter.
4. Shared credential/config handling for vendor SDK backends.
5. Async status polling, timeout, and cancellation behavior for cloud jobs.
6. The Walrus GBS kernel adapter.
7. QuTiP single-mode dynamics adapter.
8. Dynamiqs dynamics adapter.
9. Strawberry Fields legacy adapter.
10. Vendor SDK clients for Xanadu, Quandela, and ORCA.
11. Hardware backend path through the C++ runtime.
12. PsiQuantum PsiQDK / Construct adapter for FTQC resource estimation and simulation.
13. PsiQuantum live QPU execution adapter if a public or private execution API becomes available.
