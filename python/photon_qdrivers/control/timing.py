"""Deterministic clock quantization and resource accounting."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from math import isfinite, prod
from typing import Any, Mapping

from ..errors import ControlValidationError
from .acquisition import AcquisitionKind
from .profile import HardwareProfile, QuantizationRule
from .program import ControlEvent, ControlProgram, EventKind
from .sweep import ControlSweep, SweepTargetKind


COMPILED_CONTROL_SCHEMA_VERSION = "photon-qdrivers.control.compiled.v1"
CONTROL_COMPILER_ID = "photon_qdrivers.control.timing.v1"

_POSITIVE_DURATION_KINDS = {
    EventKind.SOURCE_TRIGGER,
    EventKind.MODULATOR_PULSE,
    EventKind.DELAY,
    EventKind.ACQUIRE,
}
_TIMING_SWEEP_PARAMETERS = {
    "start_ns": "start_tick",
    "duration_ns": "duration_ticks",
}


@dataclass(frozen=True)
class QuantizedTime:
    """One requested time mapped to an integer hardware tick."""

    requested_ns: float
    tick: int
    quantized_ns: float
    error_ns: float

    def __post_init__(self) -> None:
        _require_finite_number(self.requested_ns, "Quantized time requested_ns")
        _require_non_negative_int(self.tick, "Quantized time tick")
        _require_finite_number(self.quantized_ns, "Quantized time quantized_ns")
        _require_finite_number(self.error_ns, "Quantized time error_ns")

    def to_dict(self) -> dict[str, float | int]:
        return {
            "requested_ns": self.requested_ns,
            "tick": self.tick,
            "quantized_ns": self.quantized_ns,
            "error_ns": self.error_ns,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "QuantizedTime":
        _require_mapping(data, "Quantized time")
        try:
            return cls(
                requested_ns=data["requested_ns"],
                tick=data["tick"],
                quantized_ns=data["quantized_ns"],
                error_ns=data["error_ns"],
            )
        except KeyError as exc:
            raise _missing_field("Quantized time", exc) from exc


@dataclass(frozen=True)
class ResourceUsage:
    """Finite controller resources consumed by one compiled program."""

    instructions: int
    waveform_samples: int
    registers: int
    acquisition_ticks: int
    program_ticks: int
    sweep_points: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.instructions, "Resource instructions"),
            (self.waveform_samples, "Resource waveform_samples"),
            (self.registers, "Resource registers"),
            (self.acquisition_ticks, "Resource acquisition_ticks"),
            (self.program_ticks, "Resource program_ticks"),
            (self.sweep_points, "Resource sweep_points"),
        ):
            _require_non_negative_int(value, label)
        if self.program_ticks <= 0:
            raise ControlValidationError("Resource program_ticks must be positive.")
        if self.sweep_points <= 0:
            raise ControlValidationError("Resource sweep_points must be positive.")

    def to_dict(self) -> dict[str, int]:
        return {
            "instructions": self.instructions,
            "waveform_samples": self.waveform_samples,
            "registers": self.registers,
            "acquisition_ticks": self.acquisition_ticks,
            "program_ticks": self.program_ticks,
            "sweep_points": self.sweep_points,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ResourceUsage":
        _require_mapping(data, "Resource usage")
        try:
            return cls(
                instructions=data["instructions"],
                waveform_samples=data["waveform_samples"],
                registers=data["registers"],
                acquisition_ticks=data["acquisition_ticks"],
                program_ticks=data["program_ticks"],
                sweep_points=data["sweep_points"],
            )
        except KeyError as exc:
            raise _missing_field("Resource usage", exc) from exc


@dataclass(frozen=True)
class CompiledControlEvent:
    """A control event expressed entirely in device ticks."""

    event_id: str
    kind: EventKind
    channel: str
    start_tick: int
    duration_ticks: int
    start_error_ns: float
    duration_error_ns: float
    parameters: Mapping[str, Any]
    acquisition_id: str | None = None
    acquisition_kind: AcquisitionKind | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.event_id, "Compiled event id")
        _require_identifier(self.channel, "Compiled event channel")
        if not isinstance(self.kind, EventKind):
            try:
                object.__setattr__(self, "kind", EventKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported compiled event kind '{self.kind}'."
                ) from exc
        _require_non_negative_int(self.start_tick, "Compiled event start_tick")
        _require_non_negative_int(self.duration_ticks, "Compiled event duration_ticks")
        if self.kind in _POSITIVE_DURATION_KINDS and self.duration_ticks <= 0:
            raise ControlValidationError(
                f"Compiled event '{self.event_id}' requires a positive duration_ticks."
            )
        _require_finite_number(self.start_error_ns, "Compiled event start_error_ns")
        _require_finite_number(
            self.duration_error_ns, "Compiled event duration_error_ns"
        )
        _require_mapping(self.parameters, "Compiled event parameters")

        if self.kind is EventKind.ACQUIRE:
            _require_identifier(self.acquisition_id, "Acquisition id")
            if self.acquisition_kind is None:
                raise ControlValidationError(
                    f"Compiled acquire event '{self.event_id}' requires an "
                    "acquisition_kind."
                )
            if not isinstance(self.acquisition_kind, AcquisitionKind):
                try:
                    object.__setattr__(
                        self,
                        "acquisition_kind",
                        AcquisitionKind(self.acquisition_kind),
                    )
                except (TypeError, ValueError) as exc:
                    raise ControlValidationError(
                        f"Unsupported acquisition kind '{self.acquisition_kind}'."
                    ) from exc
        elif self.acquisition_id is not None or self.acquisition_kind is not None:
            raise ControlValidationError(
                "Only compiled acquire events may define acquisition metadata."
            )

    @property
    def end_tick(self) -> int:
        return self.start_tick + self.duration_ticks

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind.value,
            "channel": self.channel,
            "start_tick": self.start_tick,
            "duration_ticks": self.duration_ticks,
            "start_error_ns": self.start_error_ns,
            "duration_error_ns": self.duration_error_ns,
            "parameters": dict(self.parameters),
            "acquisition_id": self.acquisition_id,
            "acquisition_kind": (
                None if self.acquisition_kind is None else self.acquisition_kind.value
            ),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CompiledControlEvent":
        _require_mapping(data, "Compiled event")
        try:
            acquisition_kind = data.get("acquisition_kind")
            return cls(
                event_id=data["event_id"],
                kind=data["kind"],
                channel=data["channel"],
                start_tick=data["start_tick"],
                duration_ticks=data["duration_ticks"],
                start_error_ns=data["start_error_ns"],
                duration_error_ns=data["duration_error_ns"],
                parameters=data.get("parameters", {}),
                acquisition_id=data.get("acquisition_id"),
                acquisition_kind=acquisition_kind,
            )
        except KeyError as exc:
            raise _missing_field("Compiled event", exc) from exc


@dataclass(frozen=True)
class CompiledControlSweep:
    """An executable sweep whose timing values have already been quantized."""

    sweep_id: str
    target_kind: SweepTargetKind
    target_id: str
    source_parameter: str
    compiled_parameter: str
    requested_values: tuple[float, ...]
    compiled_values: tuple[float | int, ...]
    quantization_errors_ns: tuple[float, ...]
    real_time: bool = True

    def __post_init__(self) -> None:
        for value, label in (
            (self.sweep_id, "Compiled sweep id"),
            (self.target_id, "Compiled sweep target id"),
            (self.source_parameter, "Compiled sweep source_parameter"),
            (self.compiled_parameter, "Compiled sweep compiled_parameter"),
        ):
            _require_identifier(value, label)
        if not isinstance(self.target_kind, SweepTargetKind):
            try:
                object.__setattr__(
                    self, "target_kind", SweepTargetKind(self.target_kind)
                )
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported compiled sweep target kind '{self.target_kind}'."
                ) from exc
        for values, label in (
            (self.requested_values, "requested_values"),
            (self.compiled_values, "compiled_values"),
            (self.quantization_errors_ns, "quantization_errors_ns"),
        ):
            if not isinstance(values, tuple) or not values:
                raise ControlValidationError(
                    f"Compiled sweep {label} must be a non-empty tuple."
                )
        size = len(self.requested_values)
        if len(self.compiled_values) != size or len(self.quantization_errors_ns) != size:
            raise ControlValidationError(
                "Compiled sweep value and quantization-error arrays must have equal length."
            )
        for value in self.requested_values:
            _require_finite_number(value, "Compiled sweep requested value")
        for value in self.compiled_values:
            _require_finite_number(value, "Compiled sweep value")
        for value in self.quantization_errors_ns:
            _require_finite_number(value, "Compiled sweep quantization error")
        if self.source_parameter in _TIMING_SWEEP_PARAMETERS:
            if self.compiled_parameter != _TIMING_SWEEP_PARAMETERS[self.source_parameter]:
                raise ControlValidationError(
                    f"Timing sweep '{self.sweep_id}' must compile to "
                    f"'{_TIMING_SWEEP_PARAMETERS[self.source_parameter]}'."
                )
            for value in self.compiled_values:
                _require_non_negative_int(value, "Compiled timing sweep value")
            if self.source_parameter == "duration_ns" and any(
                value <= 0 for value in self.compiled_values
            ):
                raise ControlValidationError(
                    f"Duration sweep '{self.sweep_id}' contains a value that "
                    "quantizes to zero device ticks."
                )
        elif any(error != 0.0 for error in self.quantization_errors_ns):
            raise ControlValidationError(
                "Non-timing sweeps must have zero quantization error."
            )
        if not isinstance(self.real_time, bool):
            raise ControlValidationError("Compiled sweep real_time must be a boolean.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sweep_id": self.sweep_id,
            "target_kind": self.target_kind.value,
            "target_id": self.target_id,
            "source_parameter": self.source_parameter,
            "compiled_parameter": self.compiled_parameter,
            "requested_values": list(self.requested_values),
            "compiled_values": list(self.compiled_values),
            "quantization_errors_ns": list(self.quantization_errors_ns),
            "real_time": self.real_time,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CompiledControlSweep":
        _require_mapping(data, "Compiled sweep")
        try:
            requested_values = _require_sequence(
                data["requested_values"], "Compiled sweep requested_values"
            )
            compiled_values = _require_sequence(
                data["compiled_values"], "Compiled sweep compiled_values"
            )
            errors = _require_sequence(
                data["quantization_errors_ns"],
                "Compiled sweep quantization_errors_ns",
            )
            return cls(
                sweep_id=data["sweep_id"],
                target_kind=data["target_kind"],
                target_id=data["target_id"],
                source_parameter=data["source_parameter"],
                compiled_parameter=data["compiled_parameter"],
                requested_values=tuple(requested_values),
                compiled_values=tuple(compiled_values),
                quantization_errors_ns=tuple(errors),
                real_time=data.get("real_time", True),
            )
        except KeyError as exc:
            raise _missing_field("Compiled sweep", exc) from exc


@dataclass(frozen=True)
class CompiledControlProgram:
    """A deterministic, profile-bound control program ready for execution."""

    program_id: str
    profile_id: str
    profile_digest: str
    shots: int
    repetition_ticks: int
    events: tuple[CompiledControlEvent, ...]
    sweeps: tuple[CompiledControlSweep, ...]
    resource_usage: ResourceUsage
    provenance: Mapping[str, Any]
    schema_version: str = COMPILED_CONTROL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != COMPILED_CONTROL_SCHEMA_VERSION:
            raise ControlValidationError(
                f"Unsupported compiled control schema '{self.schema_version}'. "
                f"Expected '{COMPILED_CONTROL_SCHEMA_VERSION}'."
            )
        _require_identifier(self.program_id, "Compiled program id")
        _require_identifier(self.profile_id, "Compiled program profile id")
        if (
            not isinstance(self.profile_digest, str)
            or len(self.profile_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.profile_digest)
        ):
            raise ControlValidationError(
                "Compiled program profile_digest must be a lowercase SHA-256 digest."
            )
        _require_positive_int(self.shots, "Compiled program shots")
        _require_positive_int(
            self.repetition_ticks, "Compiled program repetition_ticks"
        )
        events = tuple(self.events)
        sweeps = tuple(self.sweeps)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "sweeps", sweeps)
        if not events:
            raise ControlValidationError(
                "Compiled control program must define at least one event."
            )
        if any(not isinstance(event, CompiledControlEvent) for event in events):
            raise ControlValidationError(
                "Compiled program events must contain CompiledControlEvent objects."
            )
        if any(not isinstance(sweep, CompiledControlSweep) for sweep in sweeps):
            raise ControlValidationError(
                "Compiled program sweeps must contain CompiledControlSweep objects."
            )
        if not isinstance(self.resource_usage, ResourceUsage):
            raise ControlValidationError(
                "Compiled program resource_usage must be a ResourceUsage object."
            )
        _require_mapping(self.provenance, "Compiled program provenance")
        _validate_unique(events, "event_id", "compiled event")
        _validate_unique(sweeps, "sweep_id", "compiled sweep")
        _validate_compiled_schedule(events, self.repetition_ticks)
        _validate_compiled_sweeps(events, sweeps, self.repetition_ticks)
        if self.resource_usage.instructions != len(events):
            raise ControlValidationError(
                "Compiled program instruction count does not match its events."
            )
        expected_sweep_points = (
            prod(len(sweep.compiled_values) for sweep in sweeps) if sweeps else 1
        )
        if self.resource_usage.sweep_points != expected_sweep_points:
            raise ControlValidationError(
                "Compiled program sweep_points does not match its sweeps."
            )
        if self.resource_usage.registers != sum(
            1 for sweep in sweeps if sweep.real_time
        ):
            raise ControlValidationError(
                "Compiled program register count does not match its real-time sweeps."
            )
        if self.resource_usage.program_ticks != self.repetition_ticks:
            raise ControlValidationError(
                "Compiled program resource program_ticks does not match repetition_ticks."
            )
        _canonical_json(self.to_dict(), "Compiled control program")

    @property
    def execution_iterations(self) -> int:
        """Number of repeated schedule executions across shots and sweep points."""

        return self.shots * self.resource_usage.sweep_points

    @property
    def total_device_ticks(self) -> int:
        """Logical device ticks represented by the complete execution."""

        return self.repetition_ticks * self.execution_iterations

    @property
    def canonical_json(self) -> str:
        """Canonical transport representation used for integrity checks."""

        return _canonical_json(self.to_dict(), "Compiled control program")

    @property
    def digest(self) -> str:
        """Stable SHA-256 digest of the canonical transport representation."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program_id,
            "profile_id": self.profile_id,
            "profile_digest": self.profile_digest,
            "shots": self.shots,
            "repetition_ticks": self.repetition_ticks,
            "events": [event.to_dict() for event in self.events],
            "sweeps": [sweep.to_dict() for sweep in self.sweeps],
            "resource_usage": self.resource_usage.to_dict(),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CompiledControlProgram":
        _require_mapping(data, "Compiled control program")
        try:
            events = _require_sequence(data["events"], "Compiled program events")
            sweeps = _require_sequence(
                data.get("sweeps", ()), "Compiled program sweeps"
            )
            return cls(
                schema_version=data.get(
                    "schema_version", COMPILED_CONTROL_SCHEMA_VERSION
                ),
                program_id=data["program_id"],
                profile_id=data["profile_id"],
                profile_digest=data["profile_digest"],
                shots=data["shots"],
                repetition_ticks=data["repetition_ticks"],
                events=tuple(CompiledControlEvent.from_mapping(item) for item in events),
                sweeps=tuple(CompiledControlSweep.from_mapping(item) for item in sweeps),
                resource_usage=ResourceUsage.from_mapping(data["resource_usage"]),
                provenance=data.get("provenance", {}),
            )
        except KeyError as exc:
            raise _missing_field("Compiled control program", exc) from exc


def quantize_time_ns(value_ns: float, profile: HardwareProfile) -> QuantizedTime:
    """Map nanoseconds to ticks with an explicit, reproducible rounding rule."""

    _require_non_negative_number(value_ns, "Requested time")
    requested = Decimal(str(value_ns))
    period = Decimal(str(profile.clock_period_ns))
    ratio = requested / period
    rounding = {
        QuantizationRule.NEAREST: ROUND_HALF_UP,
        QuantizationRule.FLOOR: ROUND_FLOOR,
        QuantizationRule.CEIL: ROUND_CEILING,
    }[profile.quantization_rule]
    tick = int(ratio.to_integral_value(rounding=rounding))
    quantized = Decimal(tick) * period
    error = quantized - requested
    return QuantizedTime(
        requested_ns=float(requested),
        tick=tick,
        quantized_ns=float(quantized),
        error_ns=float(error),
    )


def compile_control_program(
    program: ControlProgram, profile: HardwareProfile
) -> CompiledControlProgram:
    """Quantize, validate, and bind a control program to a hardware profile."""

    profile.validate_program(program)
    repetition = quantize_time_ns(program.repetition_period_ns, profile)
    if repetition.tick <= 0:
        raise ControlValidationError(
            "Control program repetition period quantizes to zero device ticks."
        )

    compiled_events = tuple(_compile_event(event, profile) for event in program.events)
    _validate_compiled_schedule(compiled_events, repetition.tick)
    compiled_sweeps = tuple(
        _compile_sweep(sweep, profile) for sweep in program.sweeps
    )

    waveform_samples = sum(
        event.duration_ticks
        for event in compiled_events
        if event.kind in (EventKind.SOURCE_TRIGGER, EventKind.MODULATOR_PULSE)
    )
    acquisition_ticks = sum(
        event.duration_ticks
        for event in compiled_events
        if event.kind is EventKind.ACQUIRE
    )
    sweep_points = (
        prod(len(sweep.compiled_values) for sweep in compiled_sweeps)
        if compiled_sweeps
        else 1
    )
    usage = ResourceUsage(
        instructions=len(compiled_events),
        waveform_samples=waveform_samples,
        registers=sum(1 for sweep in compiled_sweeps if sweep.real_time),
        acquisition_ticks=acquisition_ticks,
        program_ticks=repetition.tick,
        sweep_points=sweep_points,
    )
    profile.validate_resource_usage(usage.to_dict())

    return CompiledControlProgram(
        program_id=program.program_id,
        profile_id=profile.profile_id,
        profile_digest=profile.digest,
        shots=program.shots,
        repetition_ticks=repetition.tick,
        events=compiled_events,
        sweeps=compiled_sweeps,
        resource_usage=usage,
        provenance={
            "compiler": CONTROL_COMPILER_ID,
            "source_schema": program.schema_version,
            "clock_period_ns": profile.clock_period_ns,
            "quantization_rule": profile.quantization_rule.value,
            "source": dict(program.provenance),
        },
    )


def _compile_event(event: ControlEvent, profile: HardwareProfile) -> CompiledControlEvent:
    start = quantize_time_ns(event.start_ns, profile)
    duration = quantize_time_ns(event.duration_ns, profile)
    if event.duration_ns > 0 and duration.tick <= 0:
        raise ControlValidationError(
            f"Control event '{event.event_id}' duration quantizes to zero device ticks."
        )
    return CompiledControlEvent(
        event_id=event.event_id,
        kind=event.kind,
        channel=event.channel,
        start_tick=start.tick,
        duration_ticks=duration.tick,
        start_error_ns=start.error_ns,
        duration_error_ns=duration.error_ns,
        parameters=event.parameters,
        acquisition_id=event.acquisition_id,
        acquisition_kind=event.acquisition_kind,
    )


def _compile_sweep(
    sweep: ControlSweep, profile: HardwareProfile
) -> CompiledControlSweep:
    if sweep.parameter in _TIMING_SWEEP_PARAMETERS:
        quantized = tuple(quantize_time_ns(value, profile) for value in sweep.values)
        compiled_values: tuple[float | int, ...] = tuple(
            value.tick for value in quantized
        )
        errors = tuple(value.error_ns for value in quantized)
        if sweep.parameter == "duration_ns" and any(
            value <= 0 for value in compiled_values
        ):
            raise ControlValidationError(
                f"Duration sweep '{sweep.sweep_id}' contains a value that "
                "quantizes to zero device ticks."
            )
        compiled_parameter = _TIMING_SWEEP_PARAMETERS[sweep.parameter]
    else:
        compiled_values = tuple(float(value) for value in sweep.values)
        errors = tuple(0.0 for _ in sweep.values)
        compiled_parameter = sweep.parameter

    return CompiledControlSweep(
        sweep_id=sweep.sweep_id,
        target_kind=sweep.target_kind,
        target_id=sweep.target_id,
        source_parameter=sweep.parameter,
        compiled_parameter=compiled_parameter,
        requested_values=tuple(float(value) for value in sweep.values),
        compiled_values=compiled_values,
        quantization_errors_ns=errors,
        real_time=sweep.real_time,
    )


def _validate_compiled_schedule(
    events: tuple[CompiledControlEvent, ...], repetition_ticks: int
) -> None:
    by_channel: dict[str, list[CompiledControlEvent]] = {}
    for event in events:
        if event.end_tick > repetition_ticks:
            raise ControlValidationError(
                f"Control event '{event.event_id}' ends after the quantized "
                "repetition period."
            )
        by_channel.setdefault(event.channel, []).append(event)

    for channel_events in by_channel.values():
        previous: CompiledControlEvent | None = None
        for event in sorted(
            channel_events, key=lambda item: (item.start_tick, item.event_id)
        ):
            if (
                previous is not None
                and previous.duration_ticks > 0
                and event.duration_ticks > 0
                and event.start_tick < previous.end_tick
            ):
                raise ControlValidationError(
                    f"Control events '{previous.event_id}' and '{event.event_id}' "
                    f"overlap after timing quantization on channel '{event.channel}'."
                )
            if event.duration_ticks > 0 and (
                previous is None or event.end_tick > previous.end_tick
            ):
                previous = event


def _validate_compiled_sweeps(
    events: tuple[CompiledControlEvent, ...],
    sweeps: tuple[CompiledControlSweep, ...],
    repetition_ticks: int,
) -> None:
    """Reject sweep domains that can create an invalid executable schedule."""

    event_map = {event.event_id: event for event in events}
    channels = {event.channel for event in events}
    timing_sweeps: dict[tuple[str, str], CompiledControlSweep] = {}
    seen_targets: set[tuple[SweepTargetKind, str, str]] = set()
    for sweep in sweeps:
        target_key = (sweep.target_kind, sweep.target_id, sweep.source_parameter)
        if target_key in seen_targets:
            raise ControlValidationError(
                f"Multiple compiled sweeps target '{sweep.source_parameter}' on "
                f"'{sweep.target_id}'."
            )
        seen_targets.add(target_key)
        if sweep.target_kind is SweepTargetKind.EVENT:
            if sweep.target_id not in event_map:
                raise ControlValidationError(
                    f"Compiled sweep '{sweep.sweep_id}' references unknown event "
                    f"'{sweep.target_id}'."
                )
        elif sweep.target_id not in channels:
            raise ControlValidationError(
                f"Compiled sweep '{sweep.sweep_id}' references unknown channel "
                f"'{sweep.target_id}'."
            )
        if sweep.source_parameter in _TIMING_SWEEP_PARAMETERS:
            if sweep.target_kind is not SweepTargetKind.EVENT:
                raise ControlValidationError(
                    f"Timing sweep '{sweep.sweep_id}' must target an event."
                )
            timing_sweeps[(sweep.target_id, sweep.source_parameter)] = sweep

    intervals: dict[str, tuple[int, int, int]] = {}
    for event in events:
        start_sweep = timing_sweeps.get((event.event_id, "start_ns"))
        duration_sweep = timing_sweeps.get((event.event_id, "duration_ns"))
        starts = (
            tuple(int(value) for value in start_sweep.compiled_values)
            if start_sweep is not None
            else (event.start_tick,)
        )
        durations = (
            tuple(int(value) for value in duration_sweep.compiled_values)
            if duration_sweep is not None
            else (event.duration_ticks,)
        )
        min_start = min(starts)
        max_start = max(starts)
        min_duration = min(durations)
        max_duration = max(durations)
        if event.kind in _POSITIVE_DURATION_KINDS and min_duration <= 0:
            raise ControlValidationError(
                f"Timing sweeps can reduce event '{event.event_id}' to zero ticks."
            )
        if max_start + max_duration > repetition_ticks:
            raise ControlValidationError(
                f"Timing sweeps can move event '{event.event_id}' beyond the "
                "repetition period."
            )
        intervals[event.event_id] = (min_start, max_start + max_duration, max_duration)

    by_channel: dict[str, list[CompiledControlEvent]] = {}
    for event in events:
        if intervals[event.event_id][2] > 0:
            by_channel.setdefault(event.channel, []).append(event)
    for channel, channel_events in by_channel.items():
        ordered = sorted(
            channel_events,
            key=lambda event: (intervals[event.event_id][0], event.event_id),
        )
        for current, following in zip(ordered, ordered[1:]):
            current_max_end = intervals[current.event_id][1]
            following_min_start = intervals[following.event_id][0]
            if current_max_end > following_min_start:
                raise ControlValidationError(
                    f"Timing sweeps can overlap events '{current.event_id}' and "
                    f"'{following.event_id}' on channel '{channel}'."
                )


def _canonical_json(value: Any, label: str) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ControlValidationError(
            f"{label} must contain JSON-serializable finite values."
        ) from exc


def _require_mapping(value: Any, label: str) -> None:
    if not isinstance(value, MappingABC):
        raise ControlValidationError(f"{label} must be a mapping.")


def _require_sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise ControlValidationError(f"{label} must be a sequence.")
    return value


def _require_identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ControlValidationError(f"{label} must be a non-empty string.")


def _require_finite_number(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlValidationError(f"{label} must be numeric.")
    if not isfinite(float(value)):
        raise ControlValidationError(f"{label} must be finite.")


def _require_non_negative_number(value: Any, label: str) -> None:
    _require_finite_number(value, label)
    if value < 0:
        raise ControlValidationError(f"{label} must be non-negative.")


def _require_non_negative_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlValidationError(f"{label} must be a non-negative integer.")


def _require_positive_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ControlValidationError(f"{label} must be a positive integer.")


def _validate_unique(values: tuple[Any, ...], attribute: str, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        identifier = getattr(value, attribute)
        if identifier in seen:
            raise ControlValidationError(f"Duplicate {label} id '{identifier}'.")
        seen.add(identifier)


def _missing_field(label: str, exc: KeyError) -> ControlValidationError:
    return ControlValidationError(
        f"{label} is missing required field '{exc.args[0]}'."
    )
