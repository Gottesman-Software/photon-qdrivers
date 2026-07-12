"""Backend adapter that executes through the native C++ runtime binding."""

from __future__ import annotations

from typing import Any

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import BackendExecutionError, CircuitValidationError
from photon_qdrivers.ir import PhotonicCircuit
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult
from photon_qdrivers.native import NativeRuntime


class NativeRuntimeBackend:
    """Execute jobs through the compiled C++ Runtime/HAL/Transport stack."""

    name = "native"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._runtime: NativeRuntime | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("BS", "PS", "photon_counting"),
            max_modes=32,
            max_shots=10_000_000,
            supports_emulation=False,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "native_runtime",
                "execution": "cpp_runtime",
                "transport": "in_memory",
            },
        )
        self.device = PhotonicDevice(
            name="native-cpp-runtime",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        library_path = self.config.options.get("library_path")
        transport = str(self.config.options.get("transport", "in_memory"))
        command_path = self.config.options.get("command_path")
        result_path = self.config.options.get("result_path")
        self._runtime = NativeRuntime(
            str(library_path) if library_path else None,
            transport=transport,
            command_path=str(command_path) if command_path is not None else None,
            result_path=str(result_path) if result_path is not None else None,
        )
        native_capabilities = self._runtime.capabilities()
        self.capabilities = _capabilities_from_native(native_capabilities)
        self.device = PhotonicDevice(
            name=str(native_capabilities.get("device_id", "native-cpp-runtime")),
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )
        self._runtime.initialize()
        self.initialized = True

    def shutdown(self) -> None:
        if self._runtime is not None:
            try:
                self._runtime.shutdown()
            finally:
                self._runtime.close()
        self._runtime = None
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        _validate_native_circuit(circuit)
        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "native_runtime",
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
                metadata={"backend": self.name, "adapter": "native_runtime", "cancelled": True},
            )

        runtime = self._require_runtime()
        native_result = runtime.run_job(job)
        status = _job_status(native_result.get("status"))
        if status == JobStatus.FAILED:
            raise BackendExecutionError(
                str(native_result.get("message") or "Native C++ runtime job failed.")
            )

        return PhotonicResult(
            job_id=str(native_result.get("job_id") or job.job_id),
            backend_name=self.name,
            status=status,
            shots=int(native_result.get("shots") or job.shots),
            counts=_counts(native_result.get("counts", {})),
            metadata={
                "backend": self.name,
                "adapter": "native_runtime",
                "execution": "cpp_runtime",
                "device": self.device.name,
                "message": native_result.get("message"),
                "real_hardware": False,
                "transport": self.capabilities.metadata.get("transport", "unknown"),
                "hardware_backed": self.capabilities.supports_hardware,
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True

    def _require_runtime(self) -> NativeRuntime:
        if self._runtime is None:
            raise BackendExecutionError("Native runtime backend is not initialized.")
        return self._runtime


def _validate_native_circuit(circuit: PhotonicCircuit) -> None:
    if "photon_counting" not in circuit.operation_names():
        raise CircuitValidationError("Native runtime jobs must include photon_counting measurement.")
    for index, operation in enumerate(circuit.operations):
        if operation.name == "BS" and len(operation.modes) != 2:
            raise CircuitValidationError(f"Native runtime BS operation {index} must target two modes.")
        if operation.name == "PS" and len(operation.modes) != 1:
            raise CircuitValidationError(f"Native runtime PS operation {index} must target one mode.")


def _capabilities_from_native(data: dict[str, Any]) -> BackendCapabilities:
    operations = data.get("supported_operations", [])
    if not isinstance(operations, list):
        operations = []
    device_id = str(data.get("device_id") or "")
    transport = "in_memory"
    if data.get("hardware_backed"):
        transport = (
            "red_pitaya"
            if device_id == "red-pitaya-stemlab-125-14"
            else "fpga_mailbox"
        )
    return BackendCapabilities(
        supported_operations=tuple(str(operation) for operation in operations),
        max_modes=int(data.get("max_modes") or 0) or None,
        max_shots=int(data.get("max_shots") or 0) or None,
        supports_emulation=False,
        supports_hardware=bool(data.get("hardware_backed", False)),
        supports_realtime=bool(data.get("realtime", False)),
        metadata={
            "adapter": "native_runtime",
            "execution": "cpp_runtime",
            "transport": transport,
            "native_capabilities": data,
        },
    )


def _job_status(value: Any) -> JobStatus:
    normalized = str(value or "").strip().lower()
    if normalized == "completed":
        return JobStatus.COMPLETED
    if normalized == "submitted":
        return JobStatus.SUBMITTED
    if normalized == "created":
        return JobStatus.CREATED
    if normalized == "cancelled":
        return JobStatus.CANCELLED
    if normalized == "failed":
        return JobStatus.FAILED
    raise BackendExecutionError(f"Unknown native runtime status '{value}'.")


def _counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise BackendExecutionError("Native runtime counts must be a JSON object.")
    return {str(state): int(count) for state, count in value.items()}
