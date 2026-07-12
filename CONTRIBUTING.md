# Contributing

Thank you for contributing to Photon-QDrivers. This project is building a
universal driver layer for photonic quantum workloads, so contributions should
keep clear boundaries between the public Python API, C++ runtime, hardware
abstraction layer, FPGA firmware, and optional vendor/emulator plugins.

## Development Setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

Build and test:

```bash
pytest
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

## Contribution Areas

- Python API and backend contract improvements.
- Emulator adapters for Perceval, Piquasso, Lightworks, QuTiP, Dynamiqs, and
  related photonic or quantum-optics tools.
- Hardware adapters for configured vendor SDKs and lab devices.
- C++ runtime, HAL, transport, serialization, and safety checks.
- FPGA RTL, HLS kernels, testbenches, and board-specific integration.
- Documentation, examples, and benchmark methodology.

## Engineering Rules

- Keep the public user import as `from photonic_driver import Driver`.
- Keep implementation details in the internal `photon_qdrivers` package.
- Do not add real hardware claims without a source or reproducible lab data.
- Do not add a vendor dependency to the core package unless it is optional.
- Prefer small, focused pull requests.
- Add or update tests for behavior changes.
- Keep examples runnable without private credentials unless clearly marked.

## Benchmark Contributions

Benchmark PRs must state:

- Target backend, emulator, hardware, or firmware path.
- Exact circuit or workload.
- Number of modes/qubits, operations, shots, and precision/cutoff settings.
- Host CPU/GPU/FPGA board, memory, OS, compiler, and dependency versions.
- Whether results are measured, simulated, estimated, or vendor-reported.

Use `docs/performance_landscape.md` for public literature/vendor claims and a
future `benchmarks/` tree for reproducible local benchmark code.

## Pull Request Checklist

- Tests pass locally.
- Documentation is updated when public behavior changes.
- New public APIs have type annotations.
- Hardware or emulator integrations fail clearly when dependencies are missing.
- Security-sensitive details such as tokens, credentials, endpoints, and lab
  network information are not committed.

## Code Of Conduct

All contributors must follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
