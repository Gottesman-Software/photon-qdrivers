"""Deterministic virtual execution of compiled photonic control schedules."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol
from uuid import uuid4

from ..errors import BackendExecutionError, ControlValidationError
from ..job import JobStatus
from .acquisition import AcquisitionKind, AcquisitionRecord
from .profile import HardwareProfile
from .timing import CompiledControlEvent, CompiledControlProgram
from .trace import ExecutionTrace, TraceEvent, TraceEventKind


class VirtualControllerState(str, Enum):
    """Lifecycle states for the in-process controller."""

    NEW = "new"
    READY = "ready"
    RUNNING = "running"
    SHUTDOWN = "shutdown"


class AcquisitionProvider(Protocol):
    """Provider contract for producing one acquisition from a compiled event."""

    def acquire(
        self, event: CompiledControlEvent, program: CompiledControlProgram
    ) -> AcquisitionRecord:
        """Return a typed record for one compiled acquire event."""


class ZeroAcquisitionProvider:
    """Produce structural zero-signal fixtures without modelling photonic physics."""

    def acquire(
        self, event: CompiledControlEvent, program: CompiledControlProgram
    ) -> AcquisitionRecord:
        if event.acquisition_id is None or event.acquisition_kind is None:
            raise ControlValidationError(
                f"Event '{event.event_id}' is not a compiled acquisition event."
            )

        kind = event.acquisition_kind
        if kind is AcquisitionKind.WAVEFORM:
            payload: Any = tuple(0.0 for _ in range(event.duration_ticks))
            unit = "normalized"
            shape = (event.duration_ticks,)
        elif kind is AcquisitionKind.TIME_TAGS:
            payload = ()
            unit = "ticks"
            shape = ()
        elif kind is AcquisitionKind.COUNTS:
            payload = {"detected": 0}
            unit = "counts"
            shape = ()
        elif kind is AcquisitionKind.COINCIDENCES:
            payload = {"coincidence": 0}
            unit = "counts"
            shape = ()
        else:
            payload = ()
            unit = "binary"
            shape = ()

        return AcquisitionRecord(
            acquisition_id=event.acquisition_id,
            kind=kind,
            payload=payload,
            unit=unit,
            shape=shape,
            start_tick=event.start_tick,
            end_tick=event.end_tick,
            metadata={
                "fixture": "zero_signal",
                "physical_model": False,
                "schedule_template": True,
                "execution_iterations": program.execution_iterations,
                "shots": program.shots,
                "sweep_points": program.resource_usage.sweep_points,
            },
        )


@dataclass(frozen=True)
class VirtualExecutionResult:
    """Completed virtual execution plus acquisitions and an out-of-band trace."""

    job_id: str
    program_id: str
    status: JobStatus
    acquisitions: tuple[AcquisitionRecord, ...]
    trace: ExecutionTrace
    final_tick: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.job_id, "Virtual result job id"),
            (self.program_id, "Virtual result program id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ControlValidationError(f"{label} must be a non-empty string.")
        if not isinstance(self.status, JobStatus):
            try:
                object.__setattr__(self, "status", JobStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported virtual result status '{self.status}'."
                ) from exc
        acquisitions = tuple(self.acquisitions)
        object.__setattr__(self, "acquisitions", acquisitions)
        if any(not isinstance(item, AcquisitionRecord) for item in acquisitions):
            raise ControlValidationError(
                "Virtual result acquisitions must contain AcquisitionRecord objects."
            )
        if not isinstance(self.trace, ExecutionTrace):
            raise ControlValidationError(
                "Virtual result trace must be an ExecutionTrace object."
            )
        if self.trace.job_id != self.job_id or self.trace.program_id != self.program_id:
            raise ControlValidationError(
                "Virtual result identifiers must match its execution trace."
            )
        if isinstance(self.final_tick, bool) or not isinstance(self.final_tick, int):
            raise ControlValidationError(
                "Virtual result final_tick must be a non-negative integer."
            )
        if self.final_tick < 0 or self.trace.events[-1].tick != self.final_tick:
            raise ControlValidationError(
                "Virtual result final_tick must match the trace completion tick."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "program_id": self.program_id,
            "status": self.status.value,
            "acquisitions": [item.to_dict() for item in self.acquisitions],
            "trace": self.trace.to_dict(),
            "final_tick": self.final_tick,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "VirtualExecutionResult":
        if not isinstance(data, MappingABC):
            raise ControlValidationError("Virtual result must be a mapping.")
        try:
            acquisitions = data["acquisitions"]
            if not isinstance(acquisitions, Sequence) or isinstance(
                acquisitions, (str, bytes, bytearray)
            ):
                raise ControlValidationError(
                    "Virtual result acquisitions must be a sequence."
                )
            return cls(
                job_id=data["job_id"],
                program_id=data["program_id"],
                status=data["status"],
                acquisitions=tuple(
                    AcquisitionRecord.from_mapping(item) for item in acquisitions
                ),
                trace=ExecutionTrace.from_mapping(data["trace"]),
                final_tick=data["final_tick"],
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Virtual result is missing required field '{exc.args[0]}'."
            ) from exc


class VirtualPhotonicController:
    """Run a compiled schedule in logical device time, without wall-clock sleeps."""

    def __init__(
        self,
        profile: HardwareProfile,
        acquisition_provider: AcquisitionProvider | None = None,
    ) -> None:
        if not isinstance(profile, HardwareProfile):
            raise ControlValidationError(
                "Virtual controller profile must be a HardwareProfile object."
            )
        self._profile = profile
        self._provider = acquisition_provider or ZeroAcquisitionProvider()
        self._state = VirtualControllerState.NEW

    @property
    def profile(self) -> HardwareProfile:
        return self._profile

    @property
    def state(self) -> VirtualControllerState:
        return self._state

    def initialize(self) -> None:
        """Make the controller ready; repeated initialization is idempotent."""

        if self._state is VirtualControllerState.SHUTDOWN:
            raise BackendExecutionError(
                "A shutdown virtual controller cannot be reinitialized."
            )
        if self._state is VirtualControllerState.RUNNING:
            raise BackendExecutionError(
                "A running virtual controller cannot be initialized."
            )
        self._state = VirtualControllerState.READY

    def shutdown(self) -> None:
        """Enter the terminal shutdown state."""

        if self._state is VirtualControllerState.RUNNING:
            raise BackendExecutionError(
                "A running virtual controller cannot be shut down."
            )
        self._state = VirtualControllerState.SHUTDOWN

    def execute(
        self, program: CompiledControlProgram, *, job_id: str | None = None
    ) -> VirtualExecutionResult:
        """Execute a schedule deterministically in logical device ticks."""

        if self._state is not VirtualControllerState.READY:
            raise BackendExecutionError(
                "Virtual controller must be initialized before execution."
            )
        if not isinstance(program, CompiledControlProgram):
            raise ControlValidationError(
                "Virtual controller requires a CompiledControlProgram object."
            )
        if (
            program.profile_id != self._profile.profile_id
            or program.profile_digest != self._profile.digest
        ):
            raise ControlValidationError(
                "Compiled program does not match the virtual controller hardware profile."
            )
        resolved_job_id = uuid4().hex if job_id is None else job_id
        if not isinstance(resolved_job_id, str) or not resolved_job_id.strip():
            raise ControlValidationError("Virtual execution job_id must be non-empty.")

        self._state = VirtualControllerState.RUNNING
        try:
            acquisitions = tuple(
                self._provider.acquire(event, program)
                for event in program.events
                if event.acquisition_kind is not None
            )
            _validate_acquisitions(program, acquisitions)
            trace = _build_trace(program, resolved_job_id, acquisitions)
            return VirtualExecutionResult(
                job_id=resolved_job_id,
                program_id=program.program_id,
                status=JobStatus.COMPLETED,
                acquisitions=acquisitions,
                trace=trace,
                final_tick=program.total_device_ticks,
            )
        finally:
            self._state = VirtualControllerState.READY


def _validate_acquisitions(
    program: CompiledControlProgram,
    acquisitions: tuple[AcquisitionRecord, ...],
) -> None:
    expected = {
        event.acquisition_id: event.acquisition_kind
        for event in program.events
        if event.acquisition_id is not None
    }
    actual: dict[str, AcquisitionKind] = {}
    for record in acquisitions:
        if not isinstance(record, AcquisitionRecord):
            raise ControlValidationError(
                "Acquisition provider must return AcquisitionRecord objects."
            )
        if record.acquisition_id in actual:
            raise ControlValidationError(
                f"Acquisition provider returned duplicate id '{record.acquisition_id}'."
            )
        actual[record.acquisition_id] = record.kind
    if actual != expected:
        raise ControlValidationError(
            "Acquisition provider output does not match the compiled acquisition events."
        )


def _build_trace(
    program: CompiledControlProgram,
    job_id: str,
    acquisitions: tuple[AcquisitionRecord, ...],
) -> ExecutionTrace:
    acquisition_by_id = {record.acquisition_id: record for record in acquisitions}
    transitions: list[
        tuple[int, str, int, TraceEventKind, CompiledControlEvent, Mapping[str, Any]]
    ] = []
    for event in program.events:
        transitions.append(
            (
                event.start_tick,
                event.event_id,
                0,
                TraceEventKind.EVENT_STARTED,
                event,
                {
                    "event_kind": event.kind.value,
                    "duration_ticks": event.duration_ticks,
                    "parameters": dict(event.parameters),
                },
            )
        )
        if event.acquisition_id is not None:
            record = acquisition_by_id[event.acquisition_id]
            transitions.append(
                (
                    event.end_tick,
                    event.event_id,
                    1,
                    TraceEventKind.ACQUISITION_CREATED,
                    event,
                    {
                        "acquisition_id": record.acquisition_id,
                        "acquisition_kind": record.kind.value,
                        "fixture": record.metadata.get("fixture"),
                        "model": record.metadata.get("model"),
                        "overflow": record.overflow,
                        "dropped_events": record.dropped_events,
                    },
                )
            )
        transitions.append(
            (
                event.end_tick,
                event.event_id,
                2,
                TraceEventKind.EVENT_COMPLETED,
                event,
                {"event_kind": event.kind.value},
            )
        )

    trace_events = [
        TraceEvent(
            sequence_no=0,
            tick=0,
            kind=TraceEventKind.PROGRAM_STARTED,
            details={
                "execution_iterations": program.execution_iterations,
                "schedule_template": True,
            },
        )
    ]
    for tick, _, _, kind, event, details in sorted(
        transitions, key=lambda item: (item[0], item[1], item[2])
    ):
        trace_events.append(
            TraceEvent(
                sequence_no=len(trace_events),
                tick=tick,
                kind=kind,
                event_id=event.event_id,
                channel=event.channel,
                details=details,
            )
        )
    trace_events.append(
        TraceEvent(
            sequence_no=len(trace_events),
            tick=program.total_device_ticks,
            kind=TraceEventKind.PROGRAM_COMPLETED,
            details={
                "execution_iterations": program.execution_iterations,
                "logical_device_ticks": program.total_device_ticks,
            },
        )
    )

    trace_seed = f"{job_id}:{program.digest}".encode("utf-8")
    trace_id = f"trace-{hashlib.sha256(trace_seed).hexdigest()[:32]}"
    return ExecutionTrace(
        trace_id=trace_id,
        job_id=job_id,
        program_id=program.program_id,
        profile_id=program.profile_id,
        program_digest=program.digest,
        events=tuple(trace_events),
        metadata={
            "clock_period_ns": program.provenance.get("clock_period_ns"),
            "schedule_template": True,
            "event_transitions_are_not_expanded_per_iteration": True,
            "execution_iterations": program.execution_iterations,
            "shots": program.shots,
            "sweep_points": program.resource_usage.sweep_points,
            "wall_clock_timing": False,
        },
    )
