"""Public convenience API for Photon-QDrivers."""

from __future__ import annotations

from typing import Any

from photon_qdrivers import (
    BackendCapabilityError,
    BackendConfig,
    BackendExecutionError,
    BackendUnavailableError,
    CircuitValidationError,
    CloudHardwareBackend,
    CloudJobClient,
    CloudJobSnapshot,
    CloudJobState,
    coerce_cloud_snapshot,
    coerce_cloud_state,
    JobStatus,
    JobTimeoutError,
    LiDMaSPlugin,
    NativeRuntime,
    PhotonDriver,
    PhotonicCircuit,
    PhotonicJob,
    PhotonicResult,
    SchroSIMPlugin,
    redact_sensitive_mapping,
)


class Driver(PhotonDriver):
    """Concise public facade for emulator and hardware adapter workflows."""

    @classmethod
    def load(
        cls,
        backend_name: str,
        config: BackendConfig | None = None,
        **options: Any,
    ) -> "Driver":
        driver = cls()
        driver.load_backend(backend_name, config=config, **options)
        return driver

    def use_plugin(self, plugin_name: str) -> Any:
        normalized_name = _normalize_plugin_name(plugin_name)
        try:
            return self.plugins.get(normalized_name)
        except KeyError:
            pass

        plugins = {
            "schrosim": SchroSIMPlugin,
            "lidmas": LiDMaSPlugin,
        }

        try:
            plugin_factory = plugins[normalized_name]
        except KeyError as exc:
            available = ", ".join(sorted(plugins))
            raise KeyError(
                f"Unknown plugin '{normalized_name}'. Available plugins: {available}."
            ) from exc

        return self.register_plugin(plugin_factory())


def _normalize_plugin_name(plugin_name: str) -> str:
    if not isinstance(plugin_name, str):
        raise TypeError("Plugin name must be a string.")

    normalized_name = plugin_name.strip().lower()
    if not normalized_name:
        raise ValueError("Plugin name must be non-empty.")
    return normalized_name


__all__ = [
    "Driver",
    "BackendConfig",
    "CloudJobSnapshot",
    "CloudJobState",
    "CloudHardwareBackend",
    "CloudJobClient",
    "coerce_cloud_snapshot",
    "coerce_cloud_state",
    "redact_sensitive_mapping",
    "PhotonicCircuit",
    "PhotonicJob",
    "PhotonicResult",
    "JobStatus",
    "NativeRuntime",
    "CircuitValidationError",
    "BackendCapabilityError",
    "BackendExecutionError",
    "BackendUnavailableError",
    "JobTimeoutError",
]
