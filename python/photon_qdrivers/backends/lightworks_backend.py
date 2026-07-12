"""Optional Lightworks backend adapter."""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import (
    BackendExecutionError,
    BackendUnavailableError,
    CircuitValidationError,
)
from photon_qdrivers.ir import PhotonicCircuit, PhotonicOperation
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


class LightworksBackend:
    """Adapter for Lightworks linear-optics emulator workflows."""

    name = "lightworks"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._lw: Any | None = None
        self._emulator: Any | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("BS", "PS", "photon_counting"),
            max_modes=64,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "lightworks",
                "dependency": "lightworks",
                "execution": "local",
                "default_backend": "slos",
            },
        )
        self.device = PhotonicDevice(
            name="lightworks-local-emulator",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        try:
            self._lw = importlib.import_module("lightworks")
            self._emulator = importlib.import_module("lightworks.emulator")
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'lightworks' requires the optional dependency 'lightworks'. "
                "Install with `pip install photon-qdrivers[lightworks]` or "
                "`pip install lightworks`."
            ) from exc

        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        _validate_lightworks_circuit(circuit)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "lightworks",
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
                metadata={"backend": self.name, "adapter": "lightworks", "cancelled": True},
            )

        lw = self._require_lightworks()
        emulator = self._require_emulator()
        lightworks_circuit = _build_lightworks_circuit(lw, job.circuit)
        input_state = lw.State(_parse_input_state(job.circuit))
        sampler = _build_sampler(lw, lightworks_circuit, input_state, job, self.config)
        backend_name = str(self.config.options.get("backend", "slos"))
        backend = emulator.Backend(backend_name)
        raw_result = backend.run(sampler)
        counts = _sampling_result_to_counts(raw_result)

        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts=counts,
            metadata={
                "backend": self.name,
                "adapter": "lightworks",
                "execution": "local_emulator",
                "emulator_backend": backend_name,
                "device": self.device.name,
                "real_hardware": False,
                "result_format": "lightworks_sampling_counts",
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True

    def _require_lightworks(self) -> Any:
        if self._lw is None:
            raise BackendUnavailableError("Lightworks backend is not initialized.")
        return self._lw

    def _require_emulator(self) -> Any:
        if self._emulator is None:
            raise BackendUnavailableError("Lightworks emulator is not initialized.")
        return self._emulator


def _validate_lightworks_circuit(circuit: PhotonicCircuit) -> None:
    if "input_state" not in circuit.metadata:
        raise CircuitValidationError(
            "Lightworks circuits must include metadata.input_state, for example "
            "`metadata={\"input_state\": [1, 1, 0, 0]}`."
        )

    has_measurement = False
    for index, operation in enumerate(circuit.operations):
        if operation.name == "BS" and len(operation.modes) != 2:
            raise CircuitValidationError(f"Lightworks BS operation {index} must target two modes.")
        if operation.name == "PS" and len(operation.modes) != 1:
            raise CircuitValidationError(f"Lightworks PS operation {index} must target one mode.")
        if operation.name == "photon_counting":
            has_measurement = True

    if not has_measurement:
        raise CircuitValidationError("Lightworks circuits must include photon_counting measurement.")

    _parse_input_state(circuit)


def _build_lightworks_circuit(lw: Any, circuit: PhotonicCircuit) -> Any:
    lightworks_circuit = lw.PhotonicCircuit(circuit.modes)
    for operation in circuit.operations:
        if operation.kind == "measure":
            continue
        _add_operation(lightworks_circuit, operation)
    return lightworks_circuit


def _add_operation(lightworks_circuit: Any, operation: PhotonicOperation) -> None:
    if operation.name == "BS":
        reflectivity = _operation_reflectivity(operation)
        lightworks_circuit.bs(
            operation.modes[0],
            operation.modes[1],
            reflectivity=reflectivity,
        )
        return

    if operation.name == "PS":
        phi = operation.parameters.get("phi", operation.parameters.get("theta", 0.0))
        lightworks_circuit.ps(operation.modes[0], float(phi))
        return

    raise CircuitValidationError(f"Unsupported Lightworks operation '{operation.name}'.")


def _operation_reflectivity(operation: PhotonicOperation) -> float:
    if "reflectivity" in operation.parameters:
        reflectivity = float(operation.parameters["reflectivity"])
    elif "theta" in operation.parameters:
        reflectivity = math.sin(float(operation.parameters["theta"])) ** 2
    else:
        reflectivity = 0.5

    if not 0.0 <= reflectivity <= 1.0:
        raise CircuitValidationError("Lightworks BS reflectivity must be between 0 and 1.")
    return reflectivity


def _build_sampler(
    lw: Any,
    lightworks_circuit: Any,
    input_state: Any,
    job: PhotonicJob,
    config: BackendConfig,
) -> Any:
    sampler_options: dict[str, Any] = {}
    for key in ("min_detection", "random_seed", "sampling_mode"):
        if key in config.options:
            sampler_options[key] = config.options[key]

    return lw.Sampler(
        lightworks_circuit,
        input_state,
        job.shots,
        **sampler_options,
    )


def _parse_input_state(circuit: PhotonicCircuit) -> list[int]:
    raw_state = circuit.metadata["input_state"]
    if not isinstance(raw_state, Sequence) or isinstance(raw_state, (str, bytes)):
        raise CircuitValidationError(
            "Lightworks metadata.input_state must be a sequence with one non-negative "
            "photon count per mode."
        )
    if len(raw_state) != circuit.modes:
        raise CircuitValidationError(
            "Lightworks metadata.input_state must have one value per circuit mode."
        )

    state: list[int] = []
    for value in raw_state:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CircuitValidationError(
                "Lightworks metadata.input_state values must be non-negative integers."
            )
        state.append(value)
    return state


def _sampling_result_to_counts(result: Any) -> dict[str, int]:
    for attribute in ("counts", "results", "data", "samples", "sampling_results"):
        if hasattr(result, attribute):
            try:
                return _candidate_to_counts(getattr(result, attribute))
            except TypeError:
                continue

    if callable(getattr(result, "to_dict", None)):
        try:
            return _candidate_to_counts(result.to_dict())
        except TypeError:
            pass

    try:
        return _candidate_to_counts(result)
    except TypeError as exc:
        raise BackendExecutionError(
            "Could not normalize Lightworks sampling result into counts."
        ) from exc


def _candidate_to_counts(candidate: Any) -> dict[str, int]:
    if isinstance(candidate, Mapping):
        return {_format_state(state): int(count) for state, count in candidate.items()}

    if callable(getattr(candidate, "items", None)):
        return {_format_state(state): int(count) for state, count in candidate.items()}

    if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
        counts: dict[str, int] = {}
        for sample in candidate:
            key = _format_state(sample)
            counts[key] = counts.get(key, 0) + 1
        return counts

    raise TypeError("Unsupported Lightworks result shape.")


def _format_state(state: Any) -> str:
    if isinstance(state, str):
        return state
    if hasattr(state, "s"):
        state = state.s
    if hasattr(state, "tolist"):
        state = state.tolist()
    if isinstance(state, Sequence) and not isinstance(state, (str, bytes)):
        return "|" + ",".join(str(int(value)) for value in state) + ">"
    return str(state)
