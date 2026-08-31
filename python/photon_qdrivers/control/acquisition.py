"""Normalized acquisition records for photonic control hardware."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Any, Mapping

from ..errors import ControlValidationError


class AcquisitionKind(str, Enum):
    """Payload kinds produced by photonic acquisition hardware."""

    WAVEFORM = "waveform"
    TIME_TAGS = "time_tags"
    COUNTS = "counts"
    COINCIDENCES = "coincidences"
    THRESHOLDED_EVENTS = "thresholded_events"


@dataclass(frozen=True)
class AcquisitionRecord:
    """One typed acquisition payload with device-time and overflow metadata."""

    acquisition_id: str
    kind: AcquisitionKind
    payload: Any
    unit: str
    shape: tuple[int, ...] = ()
    start_tick: int = 0
    end_tick: int = 0
    overflow: bool = False
    dropped_events: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.acquisition_id, "Acquisition id")
        _require_identifier(self.unit, "Acquisition unit")
        if not isinstance(self.kind, AcquisitionKind):
            try:
                object.__setattr__(self, "kind", AcquisitionKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported acquisition kind '{self.kind}'."
                ) from exc

        _require_non_negative_int(self.start_tick, "Acquisition start_tick")
        _require_non_negative_int(self.end_tick, "Acquisition end_tick")
        if self.end_tick < self.start_tick:
            raise ControlValidationError(
                "Acquisition end_tick must be greater than or equal to start_tick."
            )
        if not isinstance(self.overflow, bool):
            raise ControlValidationError("Acquisition overflow must be a boolean.")
        _require_non_negative_int(self.dropped_events, "Acquisition dropped_events")

        for dimension in self.shape:
            if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
                raise ControlValidationError(
                    "Acquisition shape dimensions must be positive integers."
                )
        if not isinstance(self.metadata, MappingABC):
            raise ControlValidationError("Acquisition metadata must be a mapping.")

        _validate_payload(self.kind, self.payload)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "acquisition_id": self.acquisition_id,
            "kind": self.kind.value,
            "payload": _jsonable(self.payload),
            "unit": self.unit,
            "shape": list(self.shape),
            "start_tick": self.start_tick,
            "end_tick": self.end_tick,
            "overflow": self.overflow,
            "dropped_events": self.dropped_events,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AcquisitionRecord":
        """Build a record from its serialized representation."""

        if not isinstance(data, MappingABC):
            raise ControlValidationError("Acquisition record must be a mapping.")
        try:
            shape = tuple(data.get("shape", ()))
            return cls(
                acquisition_id=data["acquisition_id"],
                kind=AcquisitionKind(data["kind"]),
                payload=data["payload"],
                unit=data["unit"],
                shape=shape,
                start_tick=data.get("start_tick", 0),
                end_tick=data.get("end_tick", 0),
                overflow=data.get("overflow", False),
                dropped_events=data.get("dropped_events", 0),
                metadata=data.get("metadata", {}),
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Acquisition record is missing required field '{exc.args[0]}'."
            ) from exc
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ControlValidationError):
                raise
            raise ControlValidationError(str(exc)) from exc


def _validate_payload(kind: AcquisitionKind, payload: Any) -> None:
    if kind in (AcquisitionKind.COUNTS, AcquisitionKind.COINCIDENCES):
        if not isinstance(payload, MappingABC):
            raise ControlValidationError(f"{kind.value} payload must be a mapping.")
        for label, count in payload.items():
            if not isinstance(label, str) or not label:
                raise ControlValidationError(
                    f"{kind.value} payload labels must be non-empty strings."
                )
            _require_non_negative_int(count, f"{kind.value} count")
        return

    if not _is_sequence(payload):
        raise ControlValidationError(f"{kind.value} payload must be a sequence.")

    values = list(_scalars(payload))
    if kind is AcquisitionKind.TIME_TAGS:
        for value in values:
            _require_non_negative_int(value, "Time tag")
    elif kind is AcquisitionKind.THRESHOLDED_EVENTS:
        if any(value not in (0, 1, False, True) for value in values):
            raise ControlValidationError(
                "thresholded_events payload values must be binary."
            )
    elif kind is AcquisitionKind.WAVEFORM:
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ControlValidationError("Waveform samples must be numeric.")
            if not isfinite(float(value)):
                raise ControlValidationError("Waveform samples must be finite.")


def _scalars(value: Any):
    if _is_sequence(value):
        for item in value:
            yield from _scalars(item)
    else:
        yield value


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _jsonable(value: Any) -> Any:
    if isinstance(value, MappingABC):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if _is_sequence(value):
        return [_jsonable(item) for item in value]
    return value


def _require_identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ControlValidationError(f"{label} must be a non-empty string.")


def _require_non_negative_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlValidationError(f"{label} must be a non-negative integer.")
