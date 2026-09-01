"""Versioned photonic control-program intermediate representation."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Any, Mapping
from uuid import uuid4

from ..errors import ControlValidationError
from .acquisition import AcquisitionKind
from .sweep import ControlSweep, SweepTargetKind


CONTROL_SCHEMA_VERSION = "photon-qdrivers.control.v1"


class ChannelRole(str, Enum):
    """Roles understood by the initial photonic control-plane schema."""

    SOURCE = "source"
    MODULATOR = "modulator"
    PHASE = "phase"
    SYNC = "sync"
    DETECTOR = "detector"


class EventKind(str, Enum):
    """Instruction kinds supported by the initial control-program schema."""

    SOURCE_TRIGGER = "source_trigger"
    MODULATOR_PULSE = "modulator_pulse"
    PHASE_UPDATE = "phase_update"
    SYNC = "sync"
    DELAY = "delay"
    ACQUIRE = "acquire"


_EVENT_ROLES: dict[EventKind, ChannelRole | None] = {
    EventKind.SOURCE_TRIGGER: ChannelRole.SOURCE,
    EventKind.MODULATOR_PULSE: ChannelRole.MODULATOR,
    EventKind.PHASE_UPDATE: ChannelRole.PHASE,
    EventKind.SYNC: ChannelRole.SYNC,
    EventKind.DELAY: None,
    EventKind.ACQUIRE: ChannelRole.DETECTOR,
}


@dataclass(frozen=True)
class ControlChannel:
    """A logical channel routed by a control program."""

    name: str
    role: ChannelRole

    def __post_init__(self) -> None:
        _require_identifier(self.name, "Control channel name")
        if not isinstance(self.role, ChannelRole):
            try:
                object.__setattr__(self, "role", ChannelRole(self.role))
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported channel role '{self.role}'."
                ) from exc

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "role": self.role.value}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ControlChannel":
        if not isinstance(data, MappingABC):
            raise ControlValidationError("Control channel must be a mapping.")
        try:
            return cls(name=data["name"], role=ChannelRole(data["role"]))
        except KeyError as exc:
            raise ControlValidationError(
                f"Control channel is missing required field '{exc.args[0]}'."
            ) from exc
        except ValueError as exc:
            raise ControlValidationError(str(exc)) from exc


@dataclass(frozen=True)
class ControlEvent:
    """A timed operation on one logical control channel."""

    event_id: str
    kind: EventKind
    channel: str
    start_ns: float
    duration_ns: float = 0.0
    parameters: Mapping[str, Any] = field(default_factory=dict)
    acquisition_id: str | None = None
    acquisition_kind: AcquisitionKind | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.event_id, "Control event id")
        _require_identifier(self.channel, "Control event channel")
        if not isinstance(self.kind, EventKind):
            try:
                object.__setattr__(self, "kind", EventKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported control event kind '{self.kind}'."
                ) from exc

        _require_non_negative_number(self.start_ns, "Control event start_ns")
        _require_non_negative_number(self.duration_ns, "Control event duration_ns")
        if self.kind in (
            EventKind.SOURCE_TRIGGER,
            EventKind.MODULATOR_PULSE,
            EventKind.DELAY,
            EventKind.ACQUIRE,
        ) and self.duration_ns <= 0:
            raise ControlValidationError(
                f"Control event '{self.event_id}' of kind '{self.kind.value}' "
                "requires a positive duration_ns."
            )
        if not isinstance(self.parameters, MappingABC):
            raise ControlValidationError("Control event parameters must be a mapping.")

        if self.kind is EventKind.ACQUIRE:
            _require_identifier(self.acquisition_id, "Acquisition id")
            if self.acquisition_kind is None:
                raise ControlValidationError(
                    f"Acquire event '{self.event_id}' requires an acquisition_kind."
                )
            if not isinstance(self.acquisition_kind, AcquisitionKind):
                try:
                    object.__setattr__(
                        self, "acquisition_kind", AcquisitionKind(self.acquisition_kind)
                    )
                except (TypeError, ValueError) as exc:
                    raise ControlValidationError(
                        f"Unsupported acquisition kind '{self.acquisition_kind}'."
                    ) from exc
        elif self.acquisition_id is not None or self.acquisition_kind is not None:
            raise ControlValidationError(
                "Only acquire events may define acquisition_id or acquisition_kind."
            )

    @property
    def end_ns(self) -> float:
        return float(self.start_ns) + float(self.duration_ns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind.value,
            "channel": self.channel,
            "start_ns": self.start_ns,
            "duration_ns": self.duration_ns,
            "parameters": dict(self.parameters),
            "acquisition_id": self.acquisition_id,
            "acquisition_kind": (
                None if self.acquisition_kind is None else self.acquisition_kind.value
            ),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ControlEvent":
        if not isinstance(data, MappingABC):
            raise ControlValidationError("Control event must be a mapping.")
        try:
            acquisition_kind = data.get("acquisition_kind")
            return cls(
                event_id=data["event_id"],
                kind=EventKind(data["kind"]),
                channel=data["channel"],
                start_ns=data["start_ns"],
                duration_ns=data.get("duration_ns", 0.0),
                parameters=data.get("parameters", {}),
                acquisition_id=data.get("acquisition_id"),
                acquisition_kind=(
                    None
                    if acquisition_kind is None
                    else AcquisitionKind(acquisition_kind)
                ),
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Control event is missing required field '{exc.args[0]}'."
            ) from exc
        except ValueError as exc:
            if isinstance(exc, ControlValidationError):
                raise
            raise ControlValidationError(str(exc)) from exc


@dataclass(frozen=True)
class ControlProgram:
    """Vendor-neutral timed program for photonic control electronics."""

    channels: tuple[ControlChannel, ...]
    events: tuple[ControlEvent, ...]
    shots: int = 1
    repetition_period_ns: float = 1_000.0
    sweeps: tuple[ControlSweep, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    program_id: str = field(default_factory=lambda: uuid4().hex)
    schema_version: str = CONTROL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONTROL_SCHEMA_VERSION:
            raise ControlValidationError(
                f"Unsupported control schema '{self.schema_version}'. "
                f"Expected '{CONTROL_SCHEMA_VERSION}'."
            )
        _require_identifier(self.program_id, "Control program id")
        if isinstance(self.shots, bool) or not isinstance(self.shots, int) or self.shots <= 0:
            raise ControlValidationError("Control program shots must be a positive integer.")
        _require_positive_number(
            self.repetition_period_ns, "Control program repetition_period_ns"
        )
        if not isinstance(self.provenance, MappingABC):
            raise ControlValidationError("Control program provenance must be a mapping.")

        channels = tuple(self.channels)
        events = tuple(self.events)
        sweeps = tuple(self.sweeps)
        object.__setattr__(self, "channels", channels)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "sweeps", sweeps)

        if not channels:
            raise ControlValidationError("Control program must define at least one channel.")
        if not events:
            raise ControlValidationError("Control program must define at least one event.")
        if any(not isinstance(channel, ControlChannel) for channel in channels):
            raise ControlValidationError(
                "Control program channels must contain ControlChannel objects."
            )
        if any(not isinstance(event, ControlEvent) for event in events):
            raise ControlValidationError(
                "Control program events must contain ControlEvent objects."
            )
        if any(not isinstance(sweep, ControlSweep) for sweep in sweeps):
            raise ControlValidationError(
                "Control program sweeps must contain ControlSweep objects."
            )

        channel_map = _unique_by(channels, "name", "control channel")
        event_map = _unique_by(events, "event_id", "control event")
        _unique_by(sweeps, "sweep_id", "control sweep")

        acquisition_ids: set[str] = set()
        events_by_channel: dict[str, list[ControlEvent]] = {}
        for event in events:
            try:
                channel = channel_map[event.channel]
            except KeyError as exc:
                raise ControlValidationError(
                    f"Control event '{event.event_id}' references unknown channel "
                    f"'{event.channel}'."
                ) from exc
            expected_role = _EVENT_ROLES[event.kind]
            if expected_role is not None and channel.role is not expected_role:
                raise ControlValidationError(
                    f"Control event '{event.event_id}' of kind '{event.kind.value}' "
                    f"requires a '{expected_role.value}' channel, but '{event.channel}' "
                    f"is '{channel.role.value}'."
                )
            if event.end_ns > float(self.repetition_period_ns):
                raise ControlValidationError(
                    f"Control event '{event.event_id}' ends after the repetition period."
                )
            if event.acquisition_id is not None:
                if event.acquisition_id in acquisition_ids:
                    raise ControlValidationError(
                        f"Duplicate acquisition id '{event.acquisition_id}'."
                    )
                acquisition_ids.add(event.acquisition_id)
            events_by_channel.setdefault(event.channel, []).append(event)

        for channel_events in events_by_channel.values():
            _validate_no_overlap(channel_events)

        for sweep in sweeps:
            targets = event_map if sweep.target_kind is SweepTargetKind.EVENT else channel_map
            if sweep.target_id not in targets:
                raise ControlValidationError(
                    f"Control sweep '{sweep.sweep_id}' references unknown "
                    f"{sweep.target_kind.value} '{sweep.target_id}'."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program_id,
            "shots": self.shots,
            "repetition_period_ns": self.repetition_period_ns,
            "channels": [channel.to_dict() for channel in self.channels],
            "events": [event.to_dict() for event in self.events],
            "sweeps": [sweep.to_dict() for sweep in self.sweeps],
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ControlProgram":
        if not isinstance(data, MappingABC):
            raise ControlValidationError("Control program must be a mapping.")
        try:
            raw_channels = _require_sequence(data["channels"], "Control program channels")
            raw_events = _require_sequence(data["events"], "Control program events")
            raw_sweeps = _require_sequence(
                data.get("sweeps", ()), "Control program sweeps"
            )
            return cls(
                schema_version=data.get("schema_version", CONTROL_SCHEMA_VERSION),
                program_id=data.get("program_id", uuid4().hex),
                shots=data.get("shots", 1),
                repetition_period_ns=data.get("repetition_period_ns", 1_000.0),
                channels=tuple(ControlChannel.from_mapping(item) for item in raw_channels),
                events=tuple(ControlEvent.from_mapping(item) for item in raw_events),
                sweeps=tuple(ControlSweep.from_mapping(item) for item in raw_sweeps),
                provenance=data.get("provenance", {}),
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Control program is missing required field '{exc.args[0]}'."
            ) from exc


def _validate_no_overlap(events: Sequence[ControlEvent]) -> None:
    ordered = sorted(events, key=lambda event: (event.start_ns, event.event_id))
    previous: ControlEvent | None = None
    for event in ordered:
        if previous is not None and previous.duration_ns > 0:
            if event.duration_ns > 0 and event.start_ns < previous.end_ns:
                raise ControlValidationError(
                    f"Control events '{previous.event_id}' and '{event.event_id}' "
                    f"overlap on channel '{event.channel}'."
                )
        if event.duration_ns > 0 and (
            previous is None or event.end_ns > previous.end_ns
        ):
            previous = event


def _unique_by(items: Sequence[Any], attribute: str, label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        key = getattr(item, attribute)
        if key in result:
            raise ControlValidationError(f"Duplicate {label} id '{key}'.")
        result[key] = item
    return result


def _require_sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ControlValidationError(f"{label} must be a sequence.")
    return value


def _require_identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ControlValidationError(f"{label} must be a non-empty string.")


def _require_non_negative_number(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlValidationError(f"{label} must be numeric.")
    if not isfinite(float(value)) or value < 0:
        raise ControlValidationError(f"{label} must be finite and non-negative.")


def _require_positive_number(value: Any, label: str) -> None:
    _require_non_negative_number(value, label)
    if value <= 0:
        raise ControlValidationError(f"{label} must be positive.")
