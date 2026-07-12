# Architecture

Photon-QDrivers is organized around a layered control path:

## System Architecture

```mermaid
flowchart TD
    App["Research App / Notebook / Service"]
    Driver["Python API<br/>PhotonDriver"]
    IR["Validated IR<br/>PhotonicCircuit v1"]
    Caps["Capability Checks<br/>BackendCapabilities"]
    Backend{"Selected Backend"}

    Mock["Mock Backend<br/>fast tests"]
    Emulator["Local Emulator<br/>contract testing"]
    Simulator["Simulator Adapter<br/>SchroSIM plugin"]
    Runtime["C++ Runtime<br/>low-latency boundary"]

    HAL["Hardware Abstraction Layer<br/>device capabilities, calibration, timing"]
    FPGADriver["FPGA Driver<br/>transport, command buffers, result buffers"]
    Firmware["SystemVerilog Firmware"]
    Scheduler["Pulse Scheduler"]
    Readout["Detector Readout"]
    Counter["Coincidence Counter"]
    FPGA["Physical FPGA"]
    Photonics["Photonic Quantum Hardware<br/>sources, interferometers, detectors"]

    Registry["Plugin Registry"]
    Decoder["Decoder Adapter<br/>LiDMaS+ plugin"]
    Result["PhotonicResult<br/>counts, shots, status, metadata"]

    App --> Driver
    Driver --> IR
    IR --> Caps
    Caps --> Backend

    Backend --> Mock
    Backend --> Emulator
    Backend --> Simulator
    Backend --> Runtime

    Registry --> Simulator
    Registry --> Decoder

    Runtime --> HAL
    HAL --> FPGADriver
    FPGADriver --> Firmware
    Firmware --> Scheduler
    Firmware --> Readout
    Firmware --> Counter
    Scheduler --> FPGA
    Readout --> FPGA
    Counter --> FPGA
    FPGA --> Photonics

    Mock --> Result
    Emulator --> Result
    Simulator --> Result
    Runtime --> Result
    Result --> Decoder
    Result --> App
```

The current implementation already supports the Python API, validated IR, mock
backend, local emulator backend, plugin placeholders, C++ runtime boundary, HAL
boundary, FPGA driver boundary, and SystemVerilog module stubs.

## Compile and Run Flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Driver as PhotonDriver
    participant IR as PhotonicCircuit
    participant Caps as BackendCapabilities
    participant Backend as Active Backend
    participant Device as PhotonicDevice
    participant Result as PhotonicResult

    User->>Driver: load_backend("emulator" or "mock")
    Driver->>Backend: initialize()
    Backend-->>Driver: ready

    User->>Driver: compile(circuit_dict)
    Driver->>IR: normalize and validate schema
    IR-->>Driver: validated circuit
    Driver->>Caps: validate modes, shots, operations
    Caps-->>Driver: accepted
    Driver->>Backend: compile(PhotonicCircuit)
    Backend->>Device: attach capability metadata
    Backend-->>Driver: PhotonicJob

    User->>Driver: run(job)
    Driver->>Backend: run(PhotonicJob)
    Backend-->>Result: counts, status, metadata
    Result-->>Driver: normalized result
    Driver-->>User: result dictionary
```

## Emulator Execution Path

The target list separates real external engines from the internal deterministic
test backend. The built-in contract emulator remains useful for CI and result
schema tests, but it is not treated as a target physics emulator.

Emulator target roles:

- Perceval, Piquasso, and Lightworks: primary photonic circuit/sampling engines.
- QuTiP and Dynamiqs: quantum-optics and open-system dynamics engines for
  cavity, source, detector, loss, and noise modelling.
- The Walrus: Gaussian boson sampling and hafnian/torontonian kernels.
- Strawberry Fields and PennyLane-SF: legacy Strawberry Fields-family adapters.
- SchroSIM: planned adapter placeholder.

```mermaid
flowchart TD
    Targets["Target Photonic Emulators / Simulators"]
    Strawberry["Strawberry Fields<br/>archived legacy"]
    PennyLaneSF["PennyLane-SF<br/>legacy SF bridge"]
    Perceval["Perceval"]
    Piquasso["Piquasso"]
    Lightworks["Lightworks"]
    Walrus["The Walrus<br/>GBS kernels"]
    QuTiP["QuTiP<br/>quantum optics"]
    Dynamiqs["Dynamiqs<br/>JAX dynamics"]
    SchroSIM["SchroSIM<br/>planned adapter"]
    Circuit["User Circuit<br/>dict or PhotonicCircuit"]
    Driver["PhotonDriver"]
    IR["PhotonicCircuit v1<br/>validated IR"]
    Caps["BackendCapabilities<br/>mode, shots, operation checks"]
    Adapter{"Emulator Adapter"}
    Lowering["IR Lowering<br/>backend-specific circuit/program"]

    subgraph Models["Execution Models"]
        Contract["Contract deterministic counts"]
        CV["Continuous-variable<br/>Gaussian / Fock"]
        DV["Discrete-variable<br/>linear optics"]
        GBS["Boson sampling / GBS"]
        Noise["Noise and imperfection models"]
    end

    Samples["Samples / probabilities / state data"]
    Normalize["Result Normalizer"]
    Result["PhotonicResult<br/>counts, status, metadata"]
    Parity["Hardware Parity Checks<br/>same schema, capability model, tests"]

    Targets --> Strawberry
    Targets --> PennyLaneSF
    Targets --> Perceval
    Targets --> Piquasso
    Targets --> Lightworks
    Targets --> Walrus
    Targets --> QuTiP
    Targets --> Dynamiqs
    Targets --> SchroSIM

    Strawberry --> Adapter
    PennyLaneSF --> Adapter
    Perceval --> Adapter
    Piquasso --> Adapter
    Lightworks --> Adapter
    Walrus --> Adapter
    QuTiP --> Adapter
    Dynamiqs --> Adapter
    SchroSIM --> Adapter

    Circuit --> Driver
    Driver --> IR
    IR --> Caps
    Caps --> Adapter
    Adapter --> Lowering

    Lowering --> Contract
    Lowering --> CV
    Lowering --> DV
    Lowering --> GBS
    Lowering --> Noise

    Contract --> Samples
    CV --> Samples
    DV --> Samples
    GBS --> Samples
    Noise --> Samples

    Samples --> Normalize
    Normalize --> Result
    Result --> Parity
```

## Hardware Execution Path

```mermaid
flowchart TD
    subgraph Vendors["Target Photonic Hardware Vendors"]
        Xanadu["Xanadu"]
        Quandela["Quandela"]
        Orca["ORCA Computing"]
        PsiQuantum["PsiQuantum"]
    end

    Job["PhotonicJob<br/>validated and compiled"]
    Runtime["C++ Runtime"]
    HAL["HAL"]
    Final["PhotonicResult"]

    Xanadu --> Job
    Quandela --> Job
    Orca --> Job
    PsiQuantum --> Job
    Job --> Runtime
    Runtime --> HAL

    subgraph Transport["Hardware Transport"]
        PCIe["PCIe / DMA"]
        Ethernet["Ethernet"]
        USB["USB"]
        Vendor["Vendor SDK"]
    end

    HAL --> PCIe
    HAL --> Ethernet
    HAL --> USB
    HAL --> Vendor

    subgraph Driver["FPGA Driver"]
        Registers["Register Map"]
        CommandFIFO["Command FIFO"]
        ResultFIFO["Result FIFO"]
    end

    PCIe --> Registers
    Ethernet --> Registers
    USB --> Registers
    Vendor --> Registers
    Registers --> CommandFIFO

    subgraph Firmware["SystemVerilog Firmware"]
        SV["SystemVerilog Top"]
        Pulse["Pulse Scheduler"]
        Detect["Detector Readout"]
        Coinc["Coincidence Counter"]
    end

    CommandFIFO --> SV
    SV --> Pulse
    SV --> Detect
    Detect --> Coinc
    Coinc --> ResultFIFO

    Results["Raw Results"]
    Decode["Result Decoder"]

    ResultFIFO --> Results
    Results --> Decode
    Decode --> Final
```

## Backend Types

```mermaid
flowchart TD
    Contract["PhotonicBackend Contract"]
    Contract --> Mock["mock<br/>deterministic, fast, CI-friendly"]
    Contract --> Emulator["emulator<br/>contract-realistic, local"]
    Contract --> Simulator["simulator adapters<br/>SchroSIM, future engines"]
    Contract --> Hardware["hardware adapters<br/>vendor SDK or FPGA transport"]

    Mock --> Tests["unit tests"]
    Emulator --> Integration["workflow integration tests"]
    Simulator --> Physics["physics-level simulation"]
    Hardware --> HIL["hardware-in-the-loop tests"]
```

## Python API

The Python layer is the user-facing surface. It should remain convenient for
research code, notebooks, experiment orchestration, and CI simulation. The
initial `PhotonDriver` supports backend loading, symbolic compilation, job
execution, plugin registration, and registry inspection.

The Python API should not grow direct dependencies on vendor SDKs, FPGA tools,
or simulator packages unless those integrations are optional plugins.

Circuits are normalized into `PhotonicCircuit`, a versioned intermediate
representation. Backends receive validated IR objects instead of arbitrary
dictionaries. That contract is required before emulator or hardware adapters can
be made reliable.

## Backend Contract

All backends must expose:

- A stable `name`.
- A `PhotonicDevice` description.
- `initialize()`.
- `compile(circuit)`.
- `run(job)`.

Backends also publish `BackendCapabilities` so the driver can reject unsupported
mode counts, shot counts, and operations before execution.

## C++ Runtime

The C++ runtime is the future boundary for low-latency execution, resource
ownership, and Python bindings. It currently exposes placeholder methods:

- `initialize()`
- `submit_job()`
- `read_results()`
- `shutdown()`

The first real runtime milestone should define a stable job representation that
can be produced from Python and consumed by hardware or simulator backends.

## Hardware Abstraction Layer

The HAL should describe device-independent capabilities:

- Number of optical modes.
- Available operations and timing constraints.
- Detector topology.
- Calibration state.
- Result formats.
- Firmware and board capabilities.

Vendor-specific adapters should translate HAL calls into their own SDKs or
transport protocols.

## FPGA Driver

The FPGA driver owns communication with the FPGA image. Depending on board and
vendor, this may later mean PCIe, Ethernet, USB, AXI, DMA, memory-mapped IO, or
a vendor runtime. The initial C++ class only preserves the interface boundary.

## Firmware

The SystemVerilog stubs define first firmware responsibilities:

- Pulse scheduling.
- Detector readout.
- Coincidence counting.
- Top-level signal integration.

These modules are intentionally simple and should be expanded with testbenches,
clock-domain crossing rules, bus protocols, and board constraints before they
are treated as hardware-ready.
