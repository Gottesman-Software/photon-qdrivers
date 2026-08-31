"""Deterministic, transport-safe execution traces for virtual control runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from ..errors import ControlValidationError


EXECUTION_TRACE_SCHEMA_VERSION = "photon-qdrivers.control.trace.v1"


class TraceEventKind(str, Enum):
    """Observable transitions emitted by the schedule-level virtual executor."""

    PROGRAM_STARTED = "program_started"
    EVENT_STARTED = "event_started"
    ACQUISITION_CREATED = "acquisition_created"
    EVENT_COMPLETED = "event_completed"
    PROGRAM_COMPLETED = "program_completed"


@dataclass(frozen=True)
class TraceEvent:
    """One ordered execution transition at an integer device tick."""

    sequence_no: int
    tick: int
    kind: TraceEventKind
    event_id: str | None = None
    channel: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_negative_int(self.sequence_no, "Trace event sequence_no")
        _require_non_negative_int(self.tick, "Trace event tick")
        if not isinstance(self.kind, TraceEventKind):
            try:
                object.__setattr__(self, "kind", TraceEventKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported trace event kind '{self.kind}'."
                ) from exc
        if self.event_id is not None:
            _require_identifier(self.event_id, "Trace event id")
        if self.channel is not None:
            _require_identifier(self.channel, "Trace event channel")
        if not isinstance(self.details, MappingABC):
            raise ControlValidationError("Trace event details must be a mapping.")
        _canonical_json(self.to_dict(), "Trace event")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence_no": self.sequence_no,
            "tick": self.tick,
            "kind": self.kind.value,
            "event_id": self.event_id,
            "channel": self.channel,
            "details": dict(self.details),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TraceEvent":
        if not isinstance(data, MappingABC):
            raise ControlValidationError("Trace event must be a mapping.")
        try:
            return cls(
                sequence_no=data["sequence_no"],
                tick=data["tick"],
                kind=data["kind"],
                event_id=data.get("event_id"),
                channel=data.get("channel"),
                details=data.get("details", {}),
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Trace event is missing required field '{exc.args[0]}'."
            ) from exc


@dataclass(frozen=True)
class ExecutionTrace:
    """An ordered, profile-bound record of a virtual schedule execution."""

    trace_id: str
    job_id: str
    program_id: str
    profile_id: str
    program_digest: str
    events: tuple[TraceEvent, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EXECUTION_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_TRACE_SCHEMA_VERSION:
            raise ControlValidationError(
                f"Unsupported trace schema '{self.schema_version}'. Expected "
                f"'{EXECUTION_TRACE_SCHEMA_VERSION}'."
            )
        for value, label in (
            (self.trace_id, "Execution trace id"),
            (self.job_id, "Execution trace job id"),
            (self.program_id, "Execution trace program id"),
            (self.profile_id, "Execution trace profile id"),
        ):
            _require_identifier(value, label)
        _require_sha256(self.program_digest, "Execution trace program_digest")
        events = tuple(self.events)
        object.__setattr__(self, "events", events)
        if not events:
            raise ControlValidationError("Execution trace must contain events.")
        if any(not isinstance(event, TraceEvent) for event in events):
            raise ControlValidationError(
                "Execution trace events must contain TraceEvent objects."
            )
        expected_sequence = tuple(range(len(events)))
        actual_sequence = tuple(event.sequence_no for event in events)
        if actual_sequence != expected_sequence:
            raise ControlValidationError(
                "Execution trace sequence numbers must be contiguous and ordered from zero."
            )
        if any(current.tick > following.tick for current, following in zip(events, events[1:])):
            raise ControlValidationError(
                "Execution trace event ticks must be monotonically non-decreasing."
            )
        if events[0].kind is not TraceEventKind.PROGRAM_STARTED:
            raise ControlValidationError(
                "Execution trace must begin with a program_started event."
            )
        if events[-1].kind is not TraceEventKind.PROGRAM_COMPLETED:
            raise ControlValidationError(
                "Execution trace must end with a program_completed event."
            )
        if not isinstance(self.metadata, MappingABC):
            raise ControlValidationError("Execution trace metadata must be a mapping.")
        _canonical_json(self.to_dict(), "Execution trace")

    @property
    def canonical_json(self) -> str:
        """Canonical JSON used to compare or transmit a trace."""

        return _canonical_json(self.to_dict(), "Execution trace")

    @property
    def digest(self) -> str:
        """Stable SHA-256 digest of the trace contents."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "job_id": self.job_id,
            "program_id": self.program_id,
            "profile_id": self.profile_id,
            "program_digest": self.program_digest,
            "events": [event.to_dict() for event in self.events],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ExecutionTrace":
        if not isinstance(data, MappingABC):
            raise ControlValidationError("Execution trace must be a mapping.")
        try:
            raw_events = data["events"]
            if not isinstance(raw_events, Sequence) or isinstance(
                raw_events, (str, bytes, bytearray)
            ):
                raise ControlValidationError(
                    "Execution trace events must be a sequence."
                )
            return cls(
                schema_version=data.get(
                    "schema_version", EXECUTION_TRACE_SCHEMA_VERSION
                ),
                trace_id=data["trace_id"],
                job_id=data["job_id"],
                program_id=data["program_id"],
                profile_id=data["profile_id"],
                program_digest=data["program_digest"],
                events=tuple(TraceEvent.from_mapping(item) for item in raw_events),
                metadata=data.get("metadata", {}),
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Execution trace is missing required field '{exc.args[0]}'."
            ) from exc


def _canonical_json(value: Any, label: str) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ControlValidationError(
            f"{label} must contain JSON-serializable finite values."
        ) from exc


def _require_identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ControlValidationError(f"{label} must be a non-empty string.")


def _require_non_negative_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlValidationError(f"{label} must be a non-negative integer.")


def _require_sha256(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ControlValidationError(f"{label} must be a lowercase SHA-256 digest.")
