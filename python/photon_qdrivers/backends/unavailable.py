"""Backend adapters that are known targets but not installed locally."""

from __future__ import annotations

from typing import ClassVar

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import BackendUnavailableError
from photon_qdrivers.ir import PhotonicCircuit
from photon_qdrivers.job import PhotonicJob, PhotonicResult


class UnavailableBackend:
    """Contract-compliant backend for adapters that are not configured."""

    name: ClassVar[str] = ""
    target_name: ClassVar[str] = ""
    target_kind: ClassVar[str] = "target"
    package_hint: ClassVar[str] = ""
    docs_hint: ClassVar[str] = ""
    supports_emulation: ClassVar[bool] = False
    supports_hardware: ClassVar[bool] = False
    supports_realtime: ClassVar[bool] = False

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.capabilities = BackendCapabilities(
            supported_operations=(),
            supports_emulation=self.supports_emulation,
            supports_hardware=self.supports_hardware,
            supports_realtime=self.supports_realtime,
            metadata={
                "adapter_available": False,
                "target": self.target_name,
                "target_kind": self.target_kind,
                "package_hint": self.package_hint,
                "docs_hint": self.docs_hint,
            },
        )
        self.device = PhotonicDevice(
            name=f"{self.name}-adapter-unconfigured",
            backend_name=self.name,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        raise BackendUnavailableError(self._message())

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        raise BackendUnavailableError(self._message())

    def run(self, job: PhotonicJob) -> PhotonicResult:
        raise BackendUnavailableError(self._message())

    def cancel(self, job_id: str) -> bool:
        return False

    def shutdown(self) -> None:
        return None

    def _message(self) -> str:
        details = [
            f"Backend '{self.name}' targets {self.target_name}, "
            "but no configured adapter is available.",
        ]
        if self.package_hint:
            details.append(f"Expected adapter package: {self.package_hint}.")
        if self.docs_hint:
            details.append(f"Configuration hint: {self.docs_hint}.")
        return " ".join(details)


class UnavailableHardwareBackend(UnavailableBackend):
    """Known hardware adapter target that is not configured."""

    target_kind = "hardware"
    supports_hardware = True
    supports_realtime = True


class UnavailableEmulatorBackend(UnavailableBackend):
    """Known emulator adapter target that is not configured."""

    target_kind = "emulator"
    supports_emulation = True
