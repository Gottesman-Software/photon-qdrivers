"""Deterministic mock backend for local development and tests."""

from __future__ import annotations

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.ir import PhotonicCircuit
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


class MockPhotonicBackend:
    """Backend that accepts symbolic photonic circuits and returns fake counts."""

    name = "mock"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.initialized = False
        self.config = config or BackendConfig(backend_name=self.name)
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("BS", "PS", "photon_counting"),
            max_modes=32,
            max_shots=10_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={"model": "deterministic-mock"},
        )
        self.device = PhotonicDevice(
            name="mock-photonic-device",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "operation_count": len(circuit.operations),
                "modes": circuit.modes,
                "schema_version": circuit.schema_version,
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
                    "execution": "mock",
                    "device": self.device.name,
                    "real_hardware": False,
                    "cancelled": True,
                },
            )

        counts = _deterministic_counts(modes=job.circuit.modes, shots=job.shots)
        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts=counts,
            metadata={
                "backend": self.name,
                "execution": "mock",
                "device": self.device.name,
                "real_hardware": False,
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True


def _deterministic_counts(modes: int, shots: int) -> dict[str, int]:
    state_count = min(4, 2 ** min(modes, 16))
    states = [format(index, f"0{modes}b") for index in range(state_count)]
    base = shots // state_count
    remainder = shots % state_count

    counts: dict[str, int] = {}
    for index, state in enumerate(states):
        counts[state] = base + (1 if index < remainder else 0)
    return counts
