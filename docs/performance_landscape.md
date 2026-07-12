# Performance Landscape

This document tracks public performance signals for photonic quantum hardware
targets and emulator stacks relevant to Photon-QDrivers.

These numbers are not directly comparable. Hardware vendors report different
metrics such as sampling time, QOPS, gate fidelity, readout fidelity, power, or
deployment readiness. Emulator projects report supported simulation methods,
backend acceleration, and benchmark infrastructure. Treat this as an integration
planning map, not as a ranking.

Last reviewed: 2026-07-07.

## Hardware Targets

| Target | Public performance signal | What it means for Photon-QDrivers | Source |
| --- | --- | --- | --- |
| Xanadu Borealis | 216 squeezed modes; one sample in about 36 us; exact classical simulation estimated at more than 9,000 years per sample; events up to 219 photons with mean photon number 125. | High-throughput sampling path needs compact IR lowering, batch submission, result streaming, and loss/noise metadata. | [Nature: Quantum computational advantage with a programmable photonic processor](https://www.nature.com/articles/s41586-022-04725-x) |
| Quandela Ascella / MosaiQ-6 | 12 modes, QOPS 144, all-to-all connectivity, 99.6 +/- 0.1% 1-qubit gate fidelity, 99.0 +/- 0.8% 2-qubit gate fidelity, 99% readout fidelity, 6 fully entangled qubits, 3 kW main-system power. | Adapter should expose device capabilities, cloud execution, gate-fidelity metadata, readout metadata, power/cooling metadata, and Perceval/Qiskit/myQLM compatibility. | [Quandela Ascella](https://www.quandela.com/products-and-services/ascella/) |
| Quandela Belenos / MosaiQ-12 | 24 modes, QOPS 576, all-to-all connectivity, 12 fully entangled qubits, 8 kW main-system power; Quandela states 4,000x more computing power than Ascella. | Useful target for capability scaling tests: max modes, max entangled qubits, shot batching, and device profile negotiation. | [Quandela Belenos](https://www.quandela.com/products-and-services/belenos/) |
| ORCA PT-1 | Rack-mounted, room-temperature photonic system built with optical fiber components; positioned for hybrid quantum-classical machine-learning workflows; deployed to PSNC and selected by Montana State University. | Adapter should prioritize on-premises deployment, Python/PyTorch-style workflow integration, user/session isolation, and HPC scheduler compatibility. | [ORCA PT-1](https://orcacomputing.com/orca-pt-1/) |
| ORCA PT-2 | Rack-mounted, room-temperature photonic system for AI/HPC environments; developer-friendly integration; PT-2 related testbed planned for GPU-based HPC cluster integration. | Adapter should support accelerator-adjacent execution, low-overhead job submission, and structured metadata for hybrid QPU/GPU workflows. | [ORCA PT-2](https://orcacomputing.com/orca-pt-2/) |
| PsiQuantum | Building utility-scale, fault-tolerant photonic quantum computers; silicon photonics platform; Omega chipset manufactured at GlobalFoundries; standard telecom fiber networking; Construct software for FTQC algorithm design and simulation. | Adapter uses PsiQDK / Construct for local FTQC resource estimation and simulation; live QPU execution remains a future integration point. | [PsiQuantum](https://www.psiquantum.com/) |
| QuiX / University of Twente lineage | 20-mode universal photonic processor reported 97.4% Haar-random amplitude fidelity, 99.5% permutation fidelity, 2.9 dB average optical loss, and 98% HOM visibility. | Good candidate profile for future universal interferometer adapters and calibration-aware compilation. | [20-Mode Universal Quantum Photonic Processor](https://arxiv.org/abs/2203.01801) |

## Emulator And Software Targets

| Target | Public performance signal | Best Photon-QDrivers use | Source |
| --- | --- | --- | --- |
| Perceval | Provides simulation backends optimized in C, benchmarks in the repository, and direct access to Quandela QPUs through Quandela Cloud. | Primary discrete-variable photonic adapter candidate; useful for local validation before Quandela hardware execution. | [Quandela/Perceval](https://github.com/Quandela/Perceval) |
| Piquasso | Task-specific high-performance simulators for Gaussian, Fock-space, and boson-sampling workflows; supports connectors including JAX and optimized backends for demanding simulations. | Strong emulator target for Gaussian/Fock workflows, differentiable experiments, and accelerator-ready local execution. | [Piquasso documentation](https://piquasso.readthedocs.io/en/stable/) |
| Lightworks | SDK for encoding linear-optic circuits; includes emulator backends, photonic-specific error models, dual-rail qubit tooling, tomography, and QPU-encoding error modelling. | Useful adapter target for linear-optics circuit validation, error-model testing, and dual-rail compilation experiments. | [Lightworks documentation](https://aegiq.github.io/lightworks/) |
| Strawberry Fields | Full-stack CV photonic library with simulator suite and differentiable TensorFlow backend; GitHub repository was archived on 2026-01-16. | Legacy compatibility adapter only; keep optional and avoid core dependency. | [XanaduAI/strawberryfields](https://github.com/XanaduAI/strawberryfields) |
| PennyLane-SF | Integrates Strawberry Fields with PennyLane; upstream notes it is not supported in newer PennyLane versions and is compatible up to PennyLane 0.29. | Legacy plugin path only; do not build new core behavior around it. | [PennyLaneAI/pennylane-sf](https://github.com/PennyLaneAI/pennylane-sf) |
| The Walrus | Fast hafnian, loop hafnian, and torontonian calculations powered by Numba; includes GBS-related algorithms and sampling utilities. | Kernel-level dependency candidate for GBS validation, probability checks, and emulator cross-checking. | [The Walrus documentation](https://the-walrus.readthedocs.io/en/latest/) |
| QuTiP | Open quantum systems framework using NumPy, SciPy, and Cython; maintains nightly benchmark plots and scaling plots. | Quantum-optics dynamics adapter for open-system validation, noise models, and detector/source modelling. | [QuTiP](https://qutip.org/), [QuTiP benchmarks](https://qutip.org/qutip-benchmark/) |
| Dynamiqs | JAX-based quantum systems simulation with GPU acceleration, differentiable solvers, and batched simulations for Schrodinger and Lindblad dynamics. | High-priority adapter for differentiable quantum-optics dynamics, batched parameter sweeps, and GPU/TPU execution. | [Dynamiqs documentation](https://www.dynamiqs.org/stable/) |

## Driver Design Implications

| Requirement | Why it matters |
| --- | --- |
| Capability discovery | Hardware targets expose different limits: modes, qubits, QOPS, fidelities, readout fidelity, cooling, and power. The Python backend contract must expose this before compilation. |
| Explicit adapter availability | Many targets require credentials, vendor SDKs, cloud accounts, or lab hardware. Unconfigured targets should fail with `BackendUnavailableError`, not partial execution. |
| Batch-first execution | Sampling hardware and emulators are most useful when jobs are batched and results stream back as structured counts and metadata. |
| Provenance metadata | Every result should record backend, target version, simulator method, hardware profile, shot count, seed when applicable, and whether results are measured, simulated, estimated, or vendor-reported. |
| Benchmark separation | Public vendor claims belong in this document. Reproducible Photon-QDrivers measurements should live in a future `benchmarks/` tree with pinned workloads and machine profiles. |
| Legacy isolation | Strawberry Fields and PennyLane-SF remain important historically, but their adapter paths should be optional and isolated from the modern core API. |

## Open Benchmark Work

- Define a common photonic workload suite: beam splitter mesh, phase sweep,
  boson-sampling toy problem, lossy channel model, detector readout model, and
  QEC-style syndrome stream.
- Add local benchmarks for `mock`, `emulator`, and future adapter packages.
- Track compile latency, submit latency, shots per second, result decoding time,
  memory use, and result-shape compatibility.
- Separate measured local results from vendor-reported or paper-reported
  performance.
