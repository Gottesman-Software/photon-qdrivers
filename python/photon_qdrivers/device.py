"""Device descriptions and capability checks for photonic backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import BackendCapabilityError
from .ir import PhotonicCircuit


@dataclass(frozen=True)
class BackendCapabilities:
    """Backend limits that must be checked before job execution."""

    supported_operations: tuple[str, ...]
    max_modes: int | None = None
    max_shots: int | None = None
    supports_emulation: bool = False
    supports_hardware: bool = False
    supports_realtime: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate_circuit(self, circuit: PhotonicCircuit, *, backend_name: str) -> None:
        if self.max_modes is not None and circuit.modes > self.max_modes:
            raise BackendCapabilityError(
                f"Backend '{backend_name}' supports at most {self.max_modes} modes; "
                f"circuit requested {circuit.modes}."
            )

        if self.max_shots is not None and circuit.shots > self.max_shots:
            raise BackendCapabilityError(
                f"Backend '{backend_name}' supports at most {self.max_shots} shots; "
                f"circuit requested {circuit.shots}."
            )

        unsupported = sorted(circuit.operation_names() - set(self.supported_operations))
        if unsupported:
            supported = ", ".join(self.supported_operations) or "none"
            raise BackendCapabilityError(
                f"Backend '{backend_name}' does not support operation(s): "
                f"{', '.join(unsupported)}. Supported operations: {supported}."
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "supported_operations": list(self.supported_operations),
            "max_modes": self.max_modes,
            "max_shots": self.max_shots,
            "supports_emulation": self.supports_emulation,
            "supports_hardware": self.supports_hardware,
            "supports_realtime": self.supports_realtime,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PhotonicDevice:
    """Static metadata for a target photonic quantum device."""

    name: str
    backend_name: str
    modes: int | None = None
    capabilities: BackendCapabilities | Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        capabilities: dict[str, Any]
        if isinstance(self.capabilities, BackendCapabilities):
            capabilities = self.capabilities.as_dict()
        else:
            capabilities = dict(self.capabilities)

        return {
            "name": self.name,
            "backend_name": self.backend_name,
            "modes": self.modes,
            "capabilities": capabilities,
        }
