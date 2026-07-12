"""Job and result models used by the Python driver facade."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping as MappingABC
from concurrent.futures import CancelledError, Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from .errors import BackendExecutionError, JobTimeoutError
from .ir import PhotonicCircuit


class JobStatus(str, Enum):
    """Execution states common to mock, simulator, and hardware backends."""

    CREATED = "created"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PhotonicJob:
    """A compiled photonic quantum job.

    The circuit remains symbolic at this stage. Future compiler passes can
    lower it into simulator input, runtime IR, or FPGA command streams.
    """

    circuit: PhotonicCircuit
    backend_name: str
    shots: int
    metadata: Mapping[str, Any] = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: uuid4().hex)
    status: JobStatus = JobStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not self.backend_name:
            raise ValueError("Job backend_name must be non-empty.")
        if isinstance(self.shots, bool) or not isinstance(self.shots, int) or self.shots <= 0:
            raise ValueError("Job shots must be a positive integer.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "backend_name": self.backend_name,
            "shots": self.shots,
            "status": self.status.value,
            "created_at": self.created_at,
            "circuit": self.circuit.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PhotonicResult(MappingABC[str, Any]):
    """Structured execution result returned by a backend."""

    job_id: str
    backend_name: str
    status: JobStatus
    shots: int
    counts: Mapping[str, int]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    completed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not self.job_id:
            raise ValueError("Result job_id must be non-empty.")
        if not self.backend_name:
            raise ValueError("Result backend_name must be non-empty.")
        if isinstance(self.shots, bool) or not isinstance(self.shots, int) or self.shots <= 0:
            raise ValueError("Result shots must be a positive integer.")

        for state, count in self.counts.items():
            if not isinstance(state, str) or not state:
                raise ValueError("Result count states must be non-empty strings.")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("Result counts must be non-negative integers.")

    @property
    def total_counts(self) -> int:
        return sum(self.counts.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "backend_name": self.backend_name,
            "status": self.status.value,
            "shots": self.shots,
            "counts": dict(self.counts),
            "completed_at": self.completed_at,
            "metadata": dict(self.metadata),
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


@dataclass(frozen=True)
class SubmittedPhotonicJob:
    """Handle for a job running through the driver's async submission path."""

    job_id: str
    backend_name: str
    _future: Future[PhotonicResult] = field(repr=False)
    _cancel_backend: Callable[[str], bool] = field(repr=False)

    @property
    def status(self) -> JobStatus:
        if self._future.cancelled():
            return JobStatus.CANCELLED
        if self._future.running():
            return JobStatus.RUNNING
        if not self._future.done():
            return JobStatus.SUBMITTED

        try:
            result = self._future.result(timeout=0)
        except CancelledError:
            return JobStatus.CANCELLED
        except Exception:
            return JobStatus.FAILED
        return result.status

    def done(self) -> bool:
        return self._future.done()

    def cancel(self) -> bool:
        cancelled_future = self._future.cancel()
        cancelled_backend = self._cancel_backend(self.job_id)
        return cancelled_future or cancelled_backend

    def result(self, timeout: float | None = None) -> PhotonicResult:
        try:
            return self._future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            raise JobTimeoutError(
                f"Job '{self.job_id}' on backend '{self.backend_name}' timed out."
            ) from exc
        except CancelledError as exc:
            raise BackendExecutionError(
                f"Job '{self.job_id}' on backend '{self.backend_name}' was cancelled."
            ) from exc
