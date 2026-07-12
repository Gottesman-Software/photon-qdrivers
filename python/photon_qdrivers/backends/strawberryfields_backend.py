"""Optional Strawberry Fields legacy backend adapter."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import BackendUnavailableError, CircuitValidationError
from photon_qdrivers.ir import PhotonicCircuit, PhotonicOperation
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


class StrawberryFieldsBackend:
    """Adapter for legacy Strawberry Fields local Fock simulations."""

    name = "strawberryfields"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._sf: Any | None = None
        self._ops: Any | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("BS", "PS", "S", "D", "photon_counting"),
            max_modes=16,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "strawberryfields",
                "dependency": "strawberryfields",
                "execution": "local_legacy",
                "default_backend": "fock",
            },
        )
        self.device = PhotonicDevice(
            name="strawberryfields-legacy-fock",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        try:
            self._sf = importlib.import_module("strawberryfields")
            self._ops = importlib.import_module("strawberryfields.ops")
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'strawberryfields' requires the optional dependency "
                "'strawberryfields'. Install with `pip install "
                "photon-qdrivers[strawberryfields]` or `pip install strawberryfields`."
            ) from exc

        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        _validate_strawberryfields_circuit(circuit)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "strawberryfields",
                "operation_count": len(circuit.operations),
                "modes": circuit.modes,
                "schema_version": circuit.schema_version,
                "config": self.config.public_dict(),
            },
        )

    def run(self, job: PhotonicJob) -> PhotonicResult:
        if not self.initialized:
            self.initialize()

        if job.job_id in self._cancelled_jobs:
            return PhotonicResult(
                job_id=job.job_id,
                backend_name=self.name,
                status=JobStatus.CANCELLED,
                shots=job.shots,
                counts={},
                metadata={
                    "backend": self.name,
                    "adapter": "strawberryfields",
                    "cancelled": True,
                },
            )

        sf = self._require_strawberryfields()
        ops = self._require_ops()
        program = _build_program(sf, ops, job.circuit)
        backend_name = str(self.config.options.get("backend", "fock"))
        backend_options = _backend_options(job.circuit, self.config)
        engine = sf.Engine(backend_name, backend_options=backend_options)
        try:
            raw_result = engine.run(program, shots=job.shots)
            counts = _samples_to_counts(getattr(raw_result, "samples", []))
            result_format = "strawberryfields_fock_samples"
        except NotImplementedError as exc:
            if not _is_batched_fock_sampling_error(exc, backend_name, job.shots):
                raise
            counts = _run_repeated_single_shots(
                sf,
                ops,
                job.circuit,
                backend_name=backend_name,
                backend_options=backend_options,
                shots=job.shots,
            )
            result_format = "strawberryfields_repeated_single_fock_samples"

        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts=counts,
            metadata={
                "backend": self.name,
                "adapter": "strawberryfields",
                "execution": "local_legacy_simulator",
                "simulator_backend": backend_name,
                "backend_options": _public_backend_options(backend_options),
                "device": self.device.name,
                "real_hardware": False,
                "result_format": result_format,
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True

    def _require_strawberryfields(self) -> Any:
        if self._sf is None:
            raise BackendUnavailableError("Strawberry Fields backend is not initialized.")
        return self._sf

    def _require_ops(self) -> Any:
        if self._ops is None:
            raise BackendUnavailableError("Strawberry Fields ops module is not initialized.")
        return self._ops


def _validate_strawberryfields_circuit(circuit: PhotonicCircuit) -> None:
    has_measurement = False
    for index, operation in enumerate(circuit.operations):
        if operation.name == "BS" and len(operation.modes) != 2:
            raise CircuitValidationError(
                f"Strawberry Fields BS operation {index} must target two modes."
            )
        if operation.name in {"PS", "S", "D"} and len(operation.modes) != 1:
            raise CircuitValidationError(
                f"Strawberry Fields {operation.name} operation {index} must target one mode."
            )
        if operation.name == "photon_counting":
            has_measurement = True

    if not has_measurement:
        raise CircuitValidationError(
            "Strawberry Fields circuits must include photon_counting measurement."
        )

    if "input_state" in circuit.metadata:
        _parse_input_state(circuit)


def _build_program(sf: Any, ops: Any, circuit: PhotonicCircuit) -> Any:
    program = sf.Program(circuit.modes)
    input_state = _parse_input_state(circuit) if "input_state" in circuit.metadata else [0] * circuit.modes
    with program.context as q:
        _apply_input_state(ops, q, input_state)
        for operation in circuit.operations:
            _add_operation(ops, q, operation, circuit_modes=circuit.modes)
    return program


def _apply_input_state(ops: Any, q: Any, input_state: Sequence[int]) -> None:
    for mode, photons in enumerate(input_state):
        if photons:
            _apply(ops.Fock(photons), q[mode])


def _add_operation(ops: Any, q: Any, operation: PhotonicOperation, *, circuit_modes: int) -> None:
    if operation.name == "BS":
        theta = float(operation.parameters.get("theta", operation.parameters.get("r", 0.7853981633974483)))
        phi = float(operation.parameters.get("phi", 0.0))
        _apply(ops.BSgate(theta, phi), (q[operation.modes[0]], q[operation.modes[1]]))
        return

    if operation.name == "PS":
        phi = float(operation.parameters.get("phi", operation.parameters.get("theta", 0.0)))
        _apply(ops.Rgate(phi), q[operation.modes[0]])
        return

    if operation.name == "S":
        r = float(operation.parameters.get("r", operation.parameters.get("amplitude", 0.0)))
        phi = float(operation.parameters.get("phi", 0.0))
        _apply(ops.Sgate(r, phi), q[operation.modes[0]])
        return

    if operation.name == "D":
        alpha = operation.parameters.get("alpha")
        if alpha is not None:
            magnitude = abs(complex(alpha))
            phi = _complex_phase(complex(alpha))
        else:
            magnitude = float(operation.parameters.get("r", operation.parameters.get("amplitude", 0.0)))
            phi = float(operation.parameters.get("phi", 0.0))
        _apply(ops.Dgate(magnitude, phi), q[operation.modes[0]])
        return

    if operation.name == "photon_counting":
        if len(operation.modes) == circuit_modes:
            _apply(ops.MeasureFock(), q)
        else:
            targets = tuple(q[mode] for mode in operation.modes)
            _apply(ops.MeasureFock(), targets)
        return

    raise CircuitValidationError(f"Unsupported Strawberry Fields operation '{operation.name}'.")


def _apply(instruction: Any, target: Any) -> None:
    instruction | target


def _backend_options(circuit: PhotonicCircuit, config: BackendConfig) -> dict[str, Any]:
    cutoff_dim = int(circuit.metadata.get("cutoff_dim", config.options.get("cutoff_dim", 5)))
    if cutoff_dim < 2:
        raise CircuitValidationError("Strawberry Fields cutoff_dim must be at least 2.")

    options = dict(config.options.get("backend_options", {}))
    options["cutoff_dim"] = cutoff_dim
    if "hbar" in config.options:
        options["hbar"] = float(config.options["hbar"])
    if "hbar" in circuit.metadata:
        options["hbar"] = float(circuit.metadata["hbar"])
    return options


def _public_backend_options(options: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in options.items()}


def _is_batched_fock_sampling_error(
    exc: NotImplementedError,
    backend_name: str,
    shots: int,
) -> bool:
    return backend_name == "fock" and shots > 1 and "shots" in str(exc)


def _run_repeated_single_shots(
    sf: Any,
    ops: Any,
    circuit: PhotonicCircuit,
    *,
    backend_name: str,
    backend_options: dict[str, Any],
    shots: int,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _ in range(shots):
        program = _build_program(sf, ops, circuit)
        engine = sf.Engine(backend_name, backend_options=backend_options)
        raw_result = engine.run(program, shots=1)
        _merge_counts(counts, _samples_to_counts(getattr(raw_result, "samples", [])))
    return counts


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for state, count in source.items():
        target[state] = target.get(state, 0) + count


def _parse_input_state(circuit: PhotonicCircuit) -> list[int]:
    raw_state = circuit.metadata["input_state"]
    if not isinstance(raw_state, Sequence) or isinstance(raw_state, (str, bytes)):
        raise CircuitValidationError(
            "Strawberry Fields metadata.input_state must be a sequence with one "
            "non-negative photon count per mode."
        )
    if len(raw_state) != circuit.modes:
        raise CircuitValidationError(
            "Strawberry Fields metadata.input_state must have one value per circuit mode."
        )

    state: list[int] = []
    for value in raw_state:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CircuitValidationError(
                "Strawberry Fields metadata.input_state values must be non-negative integers."
            )
        state.append(value)
    return state


def _samples_to_counts(samples: Any) -> dict[str, int]:
    if hasattr(samples, "tolist"):
        samples = samples.tolist()

    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        return {_format_state(samples): 1}

    if not samples:
        return {}

    if _is_flat_sample(samples):
        return {_format_state(samples): 1}

    counts: dict[str, int] = {}
    for sample in samples:
        key = _format_state(sample)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _is_flat_sample(sample: Sequence[Any]) -> bool:
    return all(isinstance(value, int) and not isinstance(value, bool) for value in sample)


def _format_state(state: Any) -> str:
    if hasattr(state, "tolist"):
        state = state.tolist()
    if isinstance(state, Sequence) and not isinstance(state, (str, bytes)):
        return "|" + ",".join(str(int(value)) for value in state) + ">"
    return str(state)


def _complex_phase(value: complex) -> float:
    if value == 0:
        return 0.0
    import math

    return math.atan2(value.imag, value.real)
