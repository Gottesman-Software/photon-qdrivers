"""Local emulator backend for exercising production backend contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.ir import PhotonicCircuit
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


class LocalEmulatorBackend:
    """Deterministic local emulator boundary.

    This backend is intentionally not a physics-complete photonic simulator. It
    validates the same IR and capability contracts real emulators and hardware
    adapters must honor, then returns reproducible structured counts.
    """

    name = "emulator"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.initialized = False
        self.config = config or BackendConfig(backend_name=self.name)
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("BS", "PS", "photon_counting"),
            max_modes=16,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={"model": "deterministic-contract-emulator"},
        )
        self.device = PhotonicDevice(
            name="local-contract-emulator",
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
                    "execution": "local_emulator",
                    "device": self.device.name,
                    "model": "deterministic-contract-emulator",
                    "real_hardware": False,
                    "cancelled": True,
                },
            )

        running_job = replace(job, status=JobStatus.RUNNING)
        counts = _emulated_counts(running_job.circuit, running_job.shots)
        return PhotonicResult(
            job_id=running_job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=running_job.shots,
            counts=counts,
            metadata={
                "backend": self.name,
                "execution": "local_emulator",
                "device": self.device.name,
                "model": "deterministic-contract-emulator",
                "real_hardware": False,
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True


def _emulated_counts(circuit: PhotonicCircuit, shots: int) -> dict[str, int]:
    state_count = min(16, 2 ** circuit.modes)
    states = [format(index, f"0{circuit.modes}b") for index in range(state_count)]
    payload = json.dumps(circuit.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(payload).digest()

    weights = [(digest[index % len(digest)] + 1) for index in range(state_count)]
    total_weight = sum(weights)
    counts = {
        state: (shots * weight) // total_weight
        for state, weight in zip(states, weights, strict=True)
    }

    remainder = shots - sum(counts.values())
    for index in range(remainder):
        counts[states[index % state_count]] += 1

    return counts
