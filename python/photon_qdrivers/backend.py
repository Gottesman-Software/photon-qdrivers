"""Backend contracts shared by mock, emulator, and hardware adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .device import PhotonicDevice
from .ir import PhotonicCircuit
from .job import PhotonicJob, PhotonicResult


@runtime_checkable
class PhotonicBackend(Protocol):
    """Interface every backend must satisfy."""

    name: str
    device: PhotonicDevice

    def initialize(self) -> None:
        """Prepare the backend for compilation and execution."""

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        """Validate and lower a circuit into a backend-owned job."""

    def run(self, job: PhotonicJob) -> PhotonicResult:
        """Execute a compiled job and return normalized results."""

    def cancel(self, job_id: str) -> bool:
        """Request cancellation of a submitted job when the backend supports it."""

    def shutdown(self) -> None:
        """Release backend resources, network sessions, or device handles."""
