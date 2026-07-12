"""Optional Piquasso backend adapter."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import BackendUnavailableError, CircuitValidationError
from photon_qdrivers.ir import PhotonicCircuit, PhotonicOperation
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


class PiquassoBackend:
    """Adapter for Piquasso local photonic simulations."""

    name = "piquasso"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._pq: Any | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("BS", "PS", "photon_counting"),
            max_modes=32,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "piquasso",
                "dependency": "piquasso",
                "execution": "local",
                "default_simulator": "SamplingSimulator",
            },
        )
        self.device = PhotonicDevice(
            name="piquasso-local-simulator",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        try:
            self._pq = importlib.import_module("piquasso")
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'piquasso' requires the optional dependency 'piquasso'. "
                "Install with `pip install photon-qdrivers[piquasso]` or "
                "`pip install piquasso`."
            ) from exc

        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        _validate_piquasso_circuit(circuit)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "piquasso",
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
                metadata={"backend": self.name, "adapter": "piquasso", "cancelled": True},
            )

        pq = self._require_piquasso()
        program = _build_piquasso_program(pq, job.circuit)
        simulator = _build_simulator(pq, job.circuit.modes, self.config)
        raw_result = simulator.execute(program, shots=job.shots)
        counts = _samples_to_counts(getattr(raw_result, "samples", []))

        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts=counts,
            metadata={
                "backend": self.name,
                "adapter": "piquasso",
                "execution": "local_simulator",
                "device": self.device.name,
                "real_hardware": False,
                "result_format": "piquasso_particle_number_samples",
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True

    def _require_piquasso(self) -> Any:
        if self._pq is None:
            raise BackendUnavailableError("Piquasso backend is not initialized.")
        return self._pq


def _validate_piquasso_circuit(circuit: PhotonicCircuit) -> None:
    if "input_state" not in circuit.metadata:
        raise CircuitValidationError(
            "Piquasso circuits must include metadata.input_state, for example "
            "`metadata={\"input_state\": [1, 1, 0, 0]}`."
        )

    has_measurement = False
    for index, operation in enumerate(circuit.operations):
        if operation.name == "BS" and len(operation.modes) != 2:
            raise CircuitValidationError(f"Piquasso BS operation {index} must target two modes.")
        if operation.name == "PS" and len(operation.modes) != 1:
            raise CircuitValidationError(f"Piquasso PS operation {index} must target one mode.")
        if operation.name == "photon_counting":
            has_measurement = True

    if not has_measurement:
        raise CircuitValidationError("Piquasso circuits must include photon_counting measurement.")

    _parse_input_state(circuit)


def _build_piquasso_program(pq: Any, circuit: PhotonicCircuit) -> Any:
    with pq.Program() as program:
        _apply(pq.Q(), pq.StateVector(_parse_input_state(circuit)))
        for operation in circuit.operations:
            _add_operation(pq, operation, circuit_modes=circuit.modes)
    return program


def _add_operation(pq: Any, operation: PhotonicOperation, *, circuit_modes: int) -> None:
    if operation.name == "BS":
        _apply(pq.Q(*operation.modes), _build_beamsplitter(pq, operation))
        return

    if operation.name == "PS":
        theta = operation.parameters.get("theta", operation.parameters.get("phi", 0.0))
        _apply(pq.Q(operation.modes[0]), pq.Phaseshifter(phi=float(theta)))
        return

    if operation.name == "photon_counting":
        if len(operation.modes) == circuit_modes:
            _apply(pq.Q(all), pq.ParticleNumberMeasurement())
        else:
            _apply(pq.Q(*operation.modes), pq.ParticleNumberMeasurement())
        return

    raise CircuitValidationError(f"Unsupported Piquasso operation '{operation.name}'.")


def _build_beamsplitter(pq: Any, operation: PhotonicOperation) -> Any:
    parameters: dict[str, float] = {}
    if "theta" in operation.parameters:
        parameters["theta"] = float(operation.parameters["theta"])
    if "phi" in operation.parameters:
        parameters["phi"] = float(operation.parameters["phi"])
    return pq.Beamsplitter(**parameters)


def _apply(target: Any, instruction: Any) -> None:
    target | instruction


def _build_simulator(pq: Any, modes: int, config: BackendConfig) -> Any:
    simulator_name = str(config.options.get("simulator", "SamplingSimulator"))
    try:
        simulator_cls = getattr(pq, simulator_name)
    except AttributeError as exc:
        raise BackendUnavailableError(f"Piquasso simulator '{simulator_name}' is not available.") from exc

    piquasso_config = _build_piquasso_config(pq, config)
    if piquasso_config is None:
        return simulator_cls(d=modes)
    return simulator_cls(d=modes, config=piquasso_config)


def _build_piquasso_config(pq: Any, config: BackendConfig) -> Any | None:
    config_options = {
        key: config.options[key]
        for key in ("cutoff", "hbar")
        if key in config.options
    }
    if not config_options:
        return None
    if not hasattr(pq, "Config"):
        return None
    return pq.Config(**config_options)


def _parse_input_state(circuit: PhotonicCircuit) -> list[int]:
    raw_state = circuit.metadata["input_state"]
    if not isinstance(raw_state, Sequence) or isinstance(raw_state, (str, bytes)):
        raise CircuitValidationError(
            "Piquasso metadata.input_state must be a sequence with one non-negative "
            "photon count per mode."
        )
    if len(raw_state) != circuit.modes:
        raise CircuitValidationError(
            "Piquasso metadata.input_state must have one value per circuit mode."
        )

    state: list[int] = []
    for value in raw_state:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CircuitValidationError(
                "Piquasso metadata.input_state values must be non-negative integers."
            )
        state.append(value)
    return state


def _samples_to_counts(samples: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        key = _format_sample(sample)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _format_sample(sample: Any) -> str:
    if hasattr(sample, "tolist"):
        sample = sample.tolist()
    if not isinstance(sample, Sequence) or isinstance(sample, (str, bytes)):
        return str(sample)
    return "|" + ",".join(str(int(value)) for value in sample) + ">"
