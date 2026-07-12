"""Optional Perceval backend adapter."""

from __future__ import annotations

import importlib
from typing import Any

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import BackendUnavailableError, CircuitValidationError
from photon_qdrivers.ir import PhotonicCircuit, PhotonicOperation
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


class PercevalBackend:
    """Adapter for Perceval local photonic simulations.

    The dependency is optional. Install it with `photon-qdrivers[perceval]` or
    `pip install perceval-quandela`.
    """

    name = "perceval"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._pcvl: Any | None = None
        self._sampler_cls: Any | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("BS", "PS", "photon_counting"),
            max_modes=32,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "perceval",
                "dependency": "perceval-quandela",
                "execution": "local",
            },
        )
        self.device = PhotonicDevice(
            name="perceval-local-simulator",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        try:
            self._pcvl = importlib.import_module("perceval")
            algorithm = importlib.import_module("perceval.algorithm")
            self._sampler_cls = algorithm.Sampler
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'perceval' requires the optional dependency "
                "'perceval-quandela'. Install with `pip install "
                "photon-qdrivers[perceval]` or `pip install perceval-quandela`."
            ) from exc

        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        _validate_perceval_circuit(circuit)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "perceval",
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
                metadata={"backend": self.name, "adapter": "perceval", "cancelled": True},
            )

        pcvl = self._require_perceval()
        sampler_cls = self._require_sampler()
        circuit = _build_perceval_circuit(pcvl, job.circuit)
        input_state = _build_input_state(pcvl, job.circuit)
        processor = pcvl.Processor(
            str(self.config.options.get("processor_backend", "SLOS")),
            circuit,
        )
        min_detected = int(self.config.options.get("min_detected_photons", 0))
        if hasattr(processor, "min_detected_photons_filter"):
            processor.min_detected_photons_filter(min_detected)
        processor.with_input(input_state)

        sampler = sampler_cls(processor)
        sample_result = sampler.sample_count(job.shots)
        raw_counts = sample_result.get("results", sample_result)
        counts = {str(state): int(count) for state, count in raw_counts.items()}

        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts=counts,
            metadata={
                "backend": self.name,
                "adapter": "perceval",
                "execution": "local_simulator",
                "device": self.device.name,
                "real_hardware": False,
                "result_format": "perceval_basic_state_counts",
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True

    def _require_perceval(self) -> Any:
        if self._pcvl is None:
            raise BackendUnavailableError("Perceval backend is not initialized.")
        return self._pcvl

    def _require_sampler(self) -> Any:
        if self._sampler_cls is None:
            raise BackendUnavailableError("Perceval sampler is not initialized.")
        return self._sampler_cls


def _validate_perceval_circuit(circuit: PhotonicCircuit) -> None:
    if "input_state" not in circuit.metadata:
        raise CircuitValidationError(
            "Perceval circuits must include metadata.input_state, for example "
            "`metadata={\"input_state\": [1, 1, 0, 0]}`."
        )

    for index, operation in enumerate(circuit.operations):
        if operation.name == "BS" and len(operation.modes) != 2:
            raise CircuitValidationError(f"Perceval BS operation {index} must target two modes.")
        if operation.name == "PS" and len(operation.modes) != 1:
            raise CircuitValidationError(f"Perceval PS operation {index} must target one mode.")


def _build_perceval_circuit(pcvl: Any, circuit: PhotonicCircuit) -> Any:
    perceval_circuit = pcvl.Circuit(circuit.modes)
    for operation in circuit.operations:
        if operation.kind == "measure":
            continue
        _add_operation(pcvl, perceval_circuit, operation)
    return perceval_circuit


def _add_operation(pcvl: Any, perceval_circuit: Any, operation: PhotonicOperation) -> None:
    if operation.name == "BS":
        component = _build_bs(pcvl, operation)
        perceval_circuit.add(tuple(operation.modes), component)
        return

    if operation.name == "PS":
        theta = operation.parameters.get("theta", operation.parameters.get("phi", 0.0))
        perceval_circuit.add(operation.modes[0], pcvl.PS(float(theta)))
        return

    raise CircuitValidationError(f"Unsupported Perceval operation '{operation.name}'.")


def _build_bs(pcvl: Any, operation: PhotonicOperation) -> Any:
    theta = operation.parameters.get("theta")
    phi = operation.parameters.get("phi")
    if theta is None and phi is None:
        return pcvl.BS()
    if theta is not None and phi is None:
        return pcvl.BS(theta=float(theta))
    if theta is None and phi is not None:
        return pcvl.BS(phi=float(phi))
    return pcvl.BS(theta=float(theta), phi=float(phi))


def _build_input_state(pcvl: Any, circuit: PhotonicCircuit) -> Any:
    raw_state = circuit.metadata["input_state"]
    if isinstance(raw_state, str):
        return pcvl.BasicState(raw_state)

    if not isinstance(raw_state, list | tuple) or len(raw_state) != circuit.modes:
        raise CircuitValidationError(
            "Perceval metadata.input_state must be a BasicState string or a sequence "
            "with one non-negative photon count per mode."
        )

    state: list[int] = []
    for value in raw_state:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CircuitValidationError(
                "Perceval metadata.input_state values must be non-negative integers."
            )
        state.append(value)
    return pcvl.BasicState(state)
