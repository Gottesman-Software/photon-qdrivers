"""PsiQuantum Construct / PsiQDK adapter.

PsiQuantum's public software path is Construct and PsiQDK, focused on
fault-tolerant quantum computing (FTQC) algorithm development, simulation,
native gate-set compilation, and resource estimation. This backend therefore
integrates PsiQDK as a local software adapter, not as live QPU execution.
"""

from __future__ import annotations

import importlib
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


_SUPPORTED_MODELS = {"resource_estimate", "simulate", "workbench_program"}
_SUPPORTED_OPERATIONS = (
    "H",
    "X",
    "Y",
    "Z",
    "S",
    "T",
    "RX",
    "RY",
    "RZ",
    "CX",
    "CNOT",
    "CZ",
    "CCX",
    "Toffoli",
    "SWAP",
    "measure",
    "logical_measure",
)


class PsiQuantumBackend:
    """Adapter for PsiQuantum Construct / PsiQDK Workbench workflows."""

    name = "psiquantum"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._sdk: Any | None = None
        self._workbench: Any | None = None
        self._qre: Any | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=_SUPPORTED_OPERATIONS,
            max_modes=None,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "psiqdk",
                "dependency": "psiqdk",
                "execution": "ftqc_software",
                "supported_models": sorted(_SUPPORTED_MODELS),
                "live_qpu_execution": False,
            },
        )
        self.device = PhotonicDevice(
            name="psiquantum-construct-psiqdk",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        sdk_module_name = _sdk_module_name(self.config)
        workbench_module_name = _workbench_module_name(self.config, sdk_module_name)
        qre_module_name = _qre_module_name(self.config, workbench_module_name)
        try:
            self._sdk = importlib.import_module(sdk_module_name)
            self._workbench = importlib.import_module(workbench_module_name)
            self._qre = importlib.import_module(qre_module_name)
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'psiquantum' requires PsiQuantum's PsiQDK / Workbench. "
                "Install with `pip install photon-qdrivers[psiquantum]` or "
                "`pip install psiqdk`."
            ) from exc

        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        model = _validate_psiqdk_request(circuit)
        logical_qubits = _logical_qubits(circuit, self.config)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "psiqdk",
                "model": model,
                "logical_qubits": logical_qubits,
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
                metadata={"backend": self.name, "adapter": "psiqdk", "cancelled": True},
            )

        workbench = self._require_workbench()
        qre = self._require_qre()
        execution = _build_workbench_execution(workbench, job.circuit, self.config)
        model = _model(job.circuit)

        if model == "simulate":
            sdk_result = _run_simulation(workbench, execution)
            counts = _extract_counts(sdk_result) or {}
            provider_metadata = _metadata_without_counts(sdk_result)
            result_kind = "simulation"
        else:
            sdk_result = _estimate_resources(qre, execution)
            counts = _extract_counts(sdk_result) or {}
            provider_metadata = {"resources": _to_plain_data(sdk_result)}
            result_kind = "resource_estimate"

        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts=counts,
            metadata={
                "backend": self.name,
                "adapter": "psiqdk",
                "execution": "ftqc_software",
                "model": model,
                "result_kind": result_kind,
                "device": self.device.name,
                "logical_qubits": execution["logical_qubits"],
                "operation_mapping": {
                    "applied": execution["applied_operations"],
                    "skipped": execution["skipped_operations"],
                },
                "sdk_module": _sdk_module_name(self.config),
                "real_hardware": False,
                "provider_metadata": provider_metadata,
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True

    def _require_workbench(self) -> Any:
        if self._workbench is None:
            raise BackendUnavailableError("PsiQuantum backend is not initialized.")
        return self._workbench

    def _require_qre(self) -> Any:
        if self._qre is None:
            raise BackendUnavailableError("PsiQuantum QRE module is not initialized.")
        return self._qre


def _validate_psiqdk_request(circuit: PhotonicCircuit) -> str:
    model = _model(circuit)
    if model not in _SUPPORTED_MODELS:
        supported = ", ".join(sorted(_SUPPORTED_MODELS))
        raise CircuitValidationError(
            f"PsiQuantum metadata.model must be one of: {supported}."
        )

    if circuit.modes < 1:
        raise CircuitValidationError("PsiQuantum jobs require at least one logical qubit.")

    strict = bool(circuit.metadata.get("strict_operation_mapping", False))
    if strict and not circuit.operations:
        raise CircuitValidationError(
            "PsiQuantum strict operation mapping requires at least one operation."
        )

    for index, operation in enumerate(circuit.operations):
        if operation.name in {"CX", "CNOT", "CZ", "SWAP"} and len(operation.modes) != 2:
            raise CircuitValidationError(
                f"PsiQuantum operation {operation.name} at index {index} must target two modes."
            )
        if operation.name in {"CCX", "Toffoli"} and len(operation.modes) != 3:
            raise CircuitValidationError(
                f"PsiQuantum operation {operation.name} at index {index} must target three modes."
            )
        if operation.name in {"H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ"}:
            if len(operation.modes) != 1:
                raise CircuitValidationError(
                    f"PsiQuantum operation {operation.name} at index {index} "
                    "must target one mode."
                )
    return model


def _build_workbench_execution(
    workbench: Any,
    circuit: PhotonicCircuit,
    config: BackendConfig,
) -> dict[str, Any]:
    logical_qubits = _logical_qubits(circuit, config)
    qpu = _instantiate_qpu(workbench, logical_qubits, circuit.metadata, config)
    registers = _instantiate_registers(workbench, qpu, logical_qubits, circuit.metadata)
    applied, skipped = _apply_operations(qpu, registers, circuit.operations, circuit.metadata)
    return {
        "qpu": qpu,
        "registers": registers,
        "logical_qubits": logical_qubits,
        "applied_operations": applied,
        "skipped_operations": skipped,
    }


def _instantiate_qpu(
    workbench: Any,
    logical_qubits: int,
    metadata: Mapping[str, Any],
    config: BackendConfig,
) -> Any:
    qpu_cls = getattr(workbench, "QPU", None)
    if qpu_cls is None:
        raise BackendExecutionError("PsiQDK Workbench does not expose QPU.")

    qpu_options = config.options.get("qpu_options", metadata.get("qpu_options", {}))
    if qpu_options is None:
        qpu_options = {}
    if not isinstance(qpu_options, Mapping):
        raise CircuitValidationError("PsiQuantum qpu_options must be a mapping.")

    attempts: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
        ((), {"num_qubits": logical_qubits, **dict(qpu_options)}),
        ((logical_qubits,), dict(qpu_options)),
        ((), dict(qpu_options)),
    )
    last_error: TypeError | None = None
    for args, kwargs in attempts:
        try:
            return qpu_cls(*args, **kwargs)
        except TypeError as exc:
            last_error = exc

    raise BackendExecutionError("Unable to construct PsiQDK Workbench QPU.") from last_error


def _instantiate_registers(
    workbench: Any,
    qpu: Any,
    logical_qubits: int,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    qubits_cls = getattr(workbench, "Qubits", None)
    if qubits_cls is None:
        return {}

    raw_registers = metadata.get("registers", [{"name": "q", "size": logical_qubits}])
    if not isinstance(raw_registers, Sequence) or isinstance(raw_registers, (str, bytes)):
        raise CircuitValidationError("PsiQuantum metadata.registers must be a sequence.")

    registers: dict[str, Any] = {}
    for index, raw_register in enumerate(raw_registers):
        if not isinstance(raw_register, Mapping):
            raise CircuitValidationError(
                f"PsiQuantum metadata.registers[{index}] must be a mapping."
            )
        name = str(raw_register.get("name", f"q{index}"))
        size = _positive_int(raw_register.get("size"), field_name=f"registers[{index}].size")
        registers[name] = qubits_cls(size, name, qpu)
    return registers


def _apply_operations(
    qpu: Any,
    registers: Mapping[str, Any],
    operations: Sequence[PhotonicOperation],
    metadata: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    strict = bool(metadata.get("strict_operation_mapping", False))
    apply_ir = bool(metadata.get("apply_ir", True))
    if not apply_ir:
        return [], [operation.name for operation in operations]

    applied: list[str] = []
    skipped: list[str] = []
    default_register = registers.get("q")
    for operation in operations:
        target = _operation_target(qpu, default_register, operation.name)
        if target is None:
            if strict:
                raise BackendExecutionError(
                    f"PsiQDK Workbench target does not expose operation '{operation.name}'."
                )
            skipped.append(operation.name)
            continue
        if _call_operation(target, operation):
            applied.append(operation.name)
        elif strict:
            raise BackendExecutionError(
                f"PsiQDK Workbench operation '{operation.name}' could not be applied."
            )
        else:
            skipped.append(operation.name)
    return applied, skipped


def _operation_target(qpu: Any, register: Any, operation_name: str) -> Any | None:
    candidates = _operation_method_names(operation_name)
    for owner in (qpu, register):
        if owner is None:
            continue
        for name in candidates:
            method = getattr(owner, name, None)
            if callable(method):
                return method
    return None


def _operation_method_names(operation_name: str) -> tuple[str, ...]:
    normalized = operation_name.strip()
    lower = normalized.lower()
    aliases = {
        "cnot": ("cnot", "cx"),
        "cx": ("cx", "cnot"),
        "toffoli": ("toffoli", "ccx"),
        "ccx": ("ccx", "toffoli"),
        "logical_measure": ("measure", "logical_measure"),
    }
    base_names = aliases.get(lower, (lower,))
    names: list[str] = []
    for name in base_names:
        names.extend((name, name.upper(), f"apply_{name}", f"{name}_gate"))
    return tuple(dict.fromkeys(names))


def _call_operation(method: Any, operation: PhotonicOperation) -> bool:
    modes = tuple(operation.modes)
    params = dict(operation.parameters)
    attempts = (
        (modes, params),
        ((list(modes),), params),
        (modes, {}),
        ((list(modes),), {}),
        ((), params),
        ((), {}),
    )
    for args, kwargs in attempts:
        try:
            method(*args, **kwargs)
            return True
        except TypeError:
            continue
    return False


def _estimate_resources(qre: Any, execution: Mapping[str, Any]) -> Any:
    estimator_factory = getattr(qre, "resource_estimator", None)
    if not callable(estimator_factory):
        raise BackendExecutionError("PsiQDK QRE module does not expose resource_estimator.")
    estimator = estimator_factory(execution["qpu"])
    for method_name in ("resources", "estimate", "run"):
        method = getattr(estimator, method_name, None)
        if callable(method):
            return method()
    if isinstance(estimator, Mapping):
        return estimator
    raise BackendExecutionError("PsiQDK resource estimator does not expose resources().")


def _run_simulation(workbench: Any, execution: Mapping[str, Any]) -> Any:
    qpu = execution["qpu"]
    for owner in (qpu, workbench):
        for method_name in ("simulate", "run", "execute"):
            method = getattr(owner, method_name, None)
            if not callable(method):
                continue
            try:
                return method(qpu) if owner is workbench else method()
            except TypeError:
                try:
                    return method()
                except TypeError:
                    continue
    raise BackendExecutionError("PsiQDK Workbench does not expose a simulation method.")


def _extract_counts(value: Any) -> dict[str, int] | None:
    data = _to_plain_data(value)
    if not isinstance(data, Mapping):
        return None
    for key in ("counts", "histogram", "sample_counts"):
        raw_counts = data.get(key)
        if raw_counts is not None:
            return _normalize_counts(raw_counts)
    result = data.get("result") or data.get("results") or data.get("output")
    if isinstance(result, Mapping):
        return _extract_counts(result)
    samples = data.get("samples")
    if samples is not None and not isinstance(samples, (int, float, str, bytes, bytearray)):
        return _count_samples(samples)
    return None


def _normalize_counts(value: Any) -> dict[str, int]:
    if isinstance(value, Mapping):
        counts: dict[str, int] = {}
        for state, count in value.items():
            if isinstance(count, bool):
                raise BackendExecutionError("PsiQDK count values must be integers.")
            counts[str(state)] = int(count)
        return counts
    return _count_samples(value)


def _count_samples(samples: Any) -> dict[str, int]:
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes, bytearray)):
        raise BackendExecutionError("PsiQDK samples must be a sequence.")
    counts: dict[str, int] = {}
    for sample in samples:
        state = _sample_state(sample)
        counts[state] = counts.get(state, 0) + 1
    return counts


def _sample_state(sample: Any) -> str:
    if isinstance(sample, Mapping):
        for key in ("state", "bitstring", "output", "sample"):
            value = sample.get(key)
            if value is not None:
                return str(value)
    if isinstance(sample, Sequence) and not isinstance(sample, (str, bytes, bytearray)):
        return "".join(str(value) for value in sample)
    return str(sample)


def _metadata_without_counts(value: Any) -> dict[str, Any]:
    data = _to_plain_data(value)
    if not isinstance(data, Mapping):
        return {"value": data}
    omitted = {"counts", "histogram", "sample_counts", "samples"}
    return {str(key): value for key, value in data.items() if str(key) not in omitted}


def _to_plain_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_plain_data(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_plain_data(item) for item in value]
    for method_name in ("to_dict", "model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return _to_plain_data(method())
            except TypeError:
                continue
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, Mapping):
        return {
            str(key): _to_plain_data(item)
            for key, item in attrs.items()
            if not str(key).startswith("_")
        }
    return value


def _model(circuit: PhotonicCircuit) -> str:
    return str(circuit.metadata.get("model", "resource_estimate")).strip().lower()


def _logical_qubits(circuit: PhotonicCircuit, config: BackendConfig) -> int:
    raw_value = (
        circuit.metadata.get("logical_qubits")
        or config.options.get("logical_qubits")
        or circuit.modes
    )
    return _positive_int(raw_value, field_name="logical_qubits")


def _positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CircuitValidationError(f"PsiQuantum {field_name} must be a positive integer.")
    return value


def _sdk_module_name(config: BackendConfig) -> str:
    return str(config.options.get("sdk_module", "psiqdk"))


def _workbench_module_name(config: BackendConfig, sdk_module_name: str) -> str:
    return str(config.options.get("workbench_module", f"{sdk_module_name}.workbench"))


def _qre_module_name(config: BackendConfig, workbench_module_name: str) -> str:
    return str(config.options.get("qre_module", f"{workbench_module_name}.qre"))
