"""Configuration objects for emulator and hardware backends."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class BackendConfig:
    """Runtime configuration passed to backend adapter factories.

    Credentials are intentionally kept separate from metadata returned to users.
    Backends may use them to initialize SDK clients, but should not echo secret
    values into jobs, results, logs, or exceptions.
    """

    backend_name: str
    profile: str | None = None
    endpoint: str | None = None
    timeout_seconds: float | None = None
    credentials: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, backend_name: str) -> "BackendConfig":
        normalized_name = _normalize_backend_name(backend_name)
        env_prefix = f"PHOTON_QDRIVERS_{normalized_name.upper().replace('-', '_')}"

        credentials: dict[str, str] = {}
        for key in (
            "TOKEN",
            "API_KEY",
            "ACCESS_TOKEN",
            "CLIENT_ID",
            "CLIENT_SECRET",
            "REFRESH_TOKEN",
        ):
            value = os.environ.get(f"{env_prefix}_{key}")
            if value:
                credentials[key.lower()] = value

        timeout_seconds: float | None = None
        raw_timeout = os.environ.get(f"{env_prefix}_TIMEOUT_SECONDS")
        if raw_timeout:
            timeout_seconds = float(raw_timeout)

        options: dict[str, Any] = {}
        for key in ("DEVICE", "DEVICE_ID", "PROJECT_ID", "ORGANIZATION", "REGION"):
            value = os.environ.get(f"{env_prefix}_{key}")
            if value:
                options[key.lower()] = value

        return cls(
            backend_name=normalized_name,
            profile=os.environ.get(f"{env_prefix}_PROFILE"),
            endpoint=os.environ.get(f"{env_prefix}_ENDPOINT"),
            timeout_seconds=timeout_seconds,
            credentials=credentials,
            options=options,
        )

    def with_options(self, **options: Any) -> "BackendConfig":
        merged_options = {**dict(self.options), **options}
        timeout_seconds = merged_options.pop("timeout_seconds", self.timeout_seconds)
        profile = merged_options.pop("profile", self.profile)
        endpoint = merged_options.pop("endpoint", self.endpoint)
        return replace(
            self,
            profile=profile,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            options=merged_options,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "backend_name": self.backend_name,
            "profile": self.profile,
            "endpoint_configured": self.endpoint is not None,
            "timeout_seconds": self.timeout_seconds,
            "credentials_configured": sorted(self.credentials),
            "options": dict(self.options),
        }


def _normalize_backend_name(backend_name: str) -> str:
    if not isinstance(backend_name, str):
        raise TypeError("Backend name must be a string.")

    normalized_name = backend_name.strip().lower()
    if not normalized_name:
        raise ValueError("Backend name must be non-empty.")
    return normalized_name
