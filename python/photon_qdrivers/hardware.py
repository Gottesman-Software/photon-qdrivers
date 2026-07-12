"""Reusable hardware backend foundations for vendor SDK adapters."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, ClassVar, Protocol

from photon_qdrivers.cloud import (
    CloudJobSnapshot,
    CloudJobState,
    normalize_cloud_job_state,
    redact_sensitive_mapping,
)
from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import (
    BackendExecutionError,
    BackendUnavailableError,
    CircuitValidationError,
    JobTimeoutError,
)
from photon_qdrivers.ir import PhotonicCircuit
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


class CloudJobClient(Protocol):
    """Minimal adapter around a provider SDK client."""

    def submit_job(self, payload: Mapping[str, Any]) -> CloudJobSnapshot | Mapping[str, Any]:
        """Submit a hardware job and return the first provider snapshot."""

    def get_job(self, provider_job_id: str) -> CloudJobSnapshot | Mapping[str, Any]:
        """Fetch the latest provider snapshot."""

    def cancel_job(self, provider_job_id: str) -> bool:
        """Request cancellation for a provider job."""

    def close(self) -> None:
        """Release network or SDK resources."""


class CloudHardwareBackend:
    """Base implementation for cloud photonic hardware adapters.

    Subclasses only need to provide vendor identity, capability limits, and a
    `_create_client()` implementation that wraps the provider SDK behind
    `CloudJobClient`.
    """

    name: ClassVar[str] = ""
    target_name: ClassVar[str] = ""
    package_hint: ClassVar[str] = ""
    credential_requirements: ClassVar[tuple[tuple[str, ...], ...]] = (("token", "api_key"),)
    supported_operations: ClassVar[tuple[str, ...]] = ("BS", "PS", "photon_counting")
    max_modes: ClassVar[int | None] = 128
    max_shots: ClassVar[int | None] = 1_000_000
    supports_realtime: ClassVar[bool] = True
    default_poll_interval_seconds: ClassVar[float] = 0.25

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._client: CloudJobClient | None = None
        self._cancelled_jobs: set[str] = set()
        self._provider_jobs: dict[str, str] = {}
        self.capabilities = BackendCapabilities(
            supported_operations=self.supported_operations,
            max_modes=self.max_modes,
            max_shots=self.max_shots,
            supports_emulation=False,
            supports_hardware=True,
            supports_realtime=self.supports_realtime,
            metadata={
                "adapter": self.name,
                "target": self.target_name,
                "execution": "cloud_hardware",
                "package_hint": self.package_hint,
            },
        )
        self.device = PhotonicDevice(
            name=f"{self.name}-cloud-hardware",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        self._validate_credentials()
        self._client = self._create_client()
        self.initialized = True

    def shutdown(self) -> None:
        if self._client is not None and callable(getattr(self._client, "close", None)):
            self._client.close()
        self._client = None
        self.initialized = False
        self._cancelled_jobs.clear()
        self._provider_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        self._validate_hardware_circuit(circuit)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "target": self.target_name,
                "device": self.device.as_dict(),
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
            return self._cancelled_result(job, provider_job_id=None)

        client = self._require_client()
        deadline = self._deadline()
        snapshot = self._coerce_snapshot(client.submit_job(self._build_payload(job)))
        self._provider_jobs[job.job_id] = snapshot.provider_job_id

        while True:
            if job.job_id in self._cancelled_jobs:
                self.cancel(job.job_id)
                return self._cancelled_result(job, provider_job_id=snapshot.provider_job_id)

            snapshot = self._refresh_snapshot(client, snapshot)
            if snapshot.state == CloudJobState.COMPLETED:
                return self._completed_result(job, snapshot)
            if snapshot.state == CloudJobState.FAILED:
                raise BackendExecutionError(
                    f"Hardware job '{job.job_id}' on backend '{self.name}' failed"
                    f"{': ' + snapshot.error if snapshot.error else '.'}"
                )
            if snapshot.state == CloudJobState.CANCELLED:
                return self._cancelled_result(job, provider_job_id=snapshot.provider_job_id)

            if deadline is not None and time.monotonic() >= deadline:
                self.cancel(job.job_id)
                raise JobTimeoutError(
                    f"Hardware job '{job.job_id}' on backend '{self.name}' timed out."
                )

            time.sleep(self._poll_interval_seconds())

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False

        self._cancelled_jobs.add(job_id)
        provider_job_id = self._provider_jobs.get(job_id)
        if provider_job_id is None or self._client is None:
            return True

        try:
            return bool(self._client.cancel_job(provider_job_id))
        except Exception:
            return False

    def _create_client(self) -> CloudJobClient:
        raise BackendUnavailableError(
            f"Backend '{self.name}' targets {self.target_name}, but no vendor SDK "
            f"adapter is installed. Expected adapter package: {self.package_hint}."
        )

    def _validate_hardware_circuit(self, circuit: PhotonicCircuit) -> None:
        if "photon_counting" not in circuit.operation_names():
            raise CircuitValidationError(
                f"Backend '{self.name}' hardware jobs must include photon_counting measurement."
            )

    def _build_payload(self, job: PhotonicJob) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "backend_name": self.name,
            "target": self.target_name,
            "shots": job.shots,
            "circuit": job.circuit.to_dict(),
            "metadata": {
                "device": self.device.as_dict(),
                "config": self.config.public_dict(),
            },
        }

    def _completed_result(self, job: PhotonicJob, snapshot: CloudJobSnapshot) -> PhotonicResult:
        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=snapshot.shots or job.shots,
            counts=snapshot.counts or {},
            metadata=self._result_metadata(snapshot),
        )

    def _cancelled_result(
        self,
        job: PhotonicJob,
        *,
        provider_job_id: str | None,
    ) -> PhotonicResult:
        metadata = {
            "backend": self.name,
            "target": self.target_name,
            "execution": "cloud_hardware",
            "provider_job_id": provider_job_id,
            "cancelled": True,
            "real_hardware": True,
        }
        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.CANCELLED,
            shots=job.shots,
            counts={},
            metadata=metadata,
        )

    def _result_metadata(self, snapshot: CloudJobSnapshot) -> dict[str, Any]:
        return {
            "backend": self.name,
            "target": self.target_name,
            "execution": "cloud_hardware",
            "provider_job_id": snapshot.provider_job_id,
            "provider_status": snapshot.raw_status,
            "provider_metadata": redact_sensitive_mapping(snapshot.metadata),
            "device": self.device.name,
            "real_hardware": True,
        }

    def _validate_credentials(self) -> None:
        credential_keys = {key.lower() for key in self.config.credentials}
        missing_groups = [
            group for group in self.credential_requirements
            if not credential_keys.intersection({key.lower() for key in group})
        ]
        if not missing_groups:
            return

        hints = []
        for group in missing_groups:
            env_names = [
                f"PHOTON_QDRIVERS_{self.name.upper().replace('-', '_')}_{key.upper()}"
                for key in group
            ]
            hints.append(" or ".join(env_names))

        raise BackendUnavailableError(
            f"Backend '{self.name}' requires hardware credentials for {self.target_name}. "
            f"Set {'; '.join(hints)} or pass BackendConfig(credentials=...)."
        )

    def _refresh_snapshot(
        self,
        client: CloudJobClient,
        snapshot: CloudJobSnapshot,
    ) -> CloudJobSnapshot:
        if snapshot.terminal:
            return snapshot
        return self._coerce_snapshot(client.get_job(snapshot.provider_job_id))

    def _coerce_snapshot(self, snapshot: CloudJobSnapshot | Mapping[str, Any]) -> CloudJobSnapshot:
        if isinstance(snapshot, CloudJobSnapshot):
            return snapshot
        return CloudJobSnapshot.from_mapping(snapshot)

    def _require_client(self) -> CloudJobClient:
        if self._client is None:
            raise BackendUnavailableError(f"Backend '{self.name}' is not initialized.")
        return self._client

    def _deadline(self) -> float | None:
        if self.config.timeout_seconds is None:
            return None
        return time.monotonic() + float(self.config.timeout_seconds)

    def _poll_interval_seconds(self) -> float:
        value = self.config.options.get(
            "poll_interval_seconds",
            self.default_poll_interval_seconds,
        )
        return max(0.0, float(value))


def coerce_cloud_snapshot(snapshot: CloudJobSnapshot | Mapping[str, Any]) -> CloudJobSnapshot:
    """Public helper for adapter packages that receive provider dictionaries."""

    if isinstance(snapshot, CloudJobSnapshot):
        return snapshot
    return CloudJobSnapshot.from_mapping(snapshot)


def coerce_cloud_state(status: Any) -> CloudJobState:
    """Public helper for adapter packages that only receive provider statuses."""

    return normalize_cloud_job_state(status)
