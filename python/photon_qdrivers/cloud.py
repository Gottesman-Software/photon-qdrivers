"""Cloud job normalization shared by hardware vendor adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CloudJobState(str, Enum):
    """Normalized lifecycle states for remote hardware jobs."""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_CLOUD_STATES = {
    CloudJobState.COMPLETED,
    CloudJobState.FAILED,
    CloudJobState.CANCELLED,
}

_STATUS_ALIASES = {
    "created": CloudJobState.CREATED,
    "new": CloudJobState.CREATED,
    "pending": CloudJobState.QUEUED,
    "queued": CloudJobState.QUEUED,
    "queue": CloudJobState.QUEUED,
    "submitted": CloudJobState.QUEUED,
    "accepted": CloudJobState.QUEUED,
    "running": CloudJobState.RUNNING,
    "active": CloudJobState.RUNNING,
    "executing": CloudJobState.RUNNING,
    "processing": CloudJobState.RUNNING,
    "complete": CloudJobState.COMPLETED,
    "completed": CloudJobState.COMPLETED,
    "done": CloudJobState.COMPLETED,
    "success": CloudJobState.COMPLETED,
    "succeeded": CloudJobState.COMPLETED,
    "failed": CloudJobState.FAILED,
    "failure": CloudJobState.FAILED,
    "error": CloudJobState.FAILED,
    "errored": CloudJobState.FAILED,
    "cancelled": CloudJobState.CANCELLED,
    "canceled": CloudJobState.CANCELLED,
    "aborted": CloudJobState.CANCELLED,
}

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class CloudJobSnapshot:
    """Provider-neutral view of a remote hardware job."""

    provider_job_id: str
    state: CloudJobState
    counts: Mapping[str, int] | None = None
    shots: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    raw_status: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CloudJobSnapshot":
        provider_job_id = _first_present(
            data,
            ("provider_job_id", "remote_job_id", "job_id", "id"),
        )
        if provider_job_id is None:
            raise ValueError("Cloud job snapshot is missing a provider job id.")

        raw_status = _first_present(data, ("state", "status", "job_status"))
        state = normalize_cloud_job_state(raw_status)

        counts = data.get("counts")
        if counts is not None:
            counts = normalize_count_mapping(counts)

        shots = data.get("shots")
        if shots is not None:
            shots = int(shots)

        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            metadata = {"value": metadata}

        error = data.get("error") or data.get("message")
        return cls(
            provider_job_id=str(provider_job_id),
            state=state,
            counts=counts,
            shots=shots,
            metadata=redact_sensitive_mapping(metadata),
            error=str(error) if error else None,
            raw_status=str(raw_status) if raw_status is not None else None,
        )

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_CLOUD_STATES


def normalize_cloud_job_state(status: Any) -> CloudJobState:
    """Convert provider-specific status values into `CloudJobState`."""

    if isinstance(status, CloudJobState):
        return status
    if status is None:
        return CloudJobState.CREATED

    normalized = str(status).strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return _STATUS_ALIASES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown cloud job status '{status}'.") from exc


def normalize_count_mapping(counts: Any) -> dict[str, int]:
    """Normalize count-like mappings without accepting lossy result shapes."""

    if not isinstance(counts, Mapping):
        raise TypeError("Cloud job counts must be a mapping of state to count.")

    normalized_counts: dict[str, int] = {}
    for state, count in counts.items():
        if isinstance(count, bool):
            raise TypeError("Cloud job count values must be integers.")
        normalized_counts[str(state)] = int(count)
    return normalized_counts


def redact_sensitive_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of metadata with obvious secret values removed."""

    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        key_text = str(key)
        if _is_sensitive_key(key_text):
            redacted[key_text] = "<redacted>"
        elif isinstance(value, Mapping):
            redacted[key_text] = redact_sensitive_mapping(value)
        else:
            redacted[key_text] = value
    return redacted


def _first_present(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
