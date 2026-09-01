"""Fixed-width RTL instruction lowering for compiled photonic schedules."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping

from ..errors import ControlValidationError
from .acquisition import AcquisitionKind
from .program import EventKind
from .timing import CompiledControlEvent, CompiledControlProgram


RTL_INSTRUCTION_SCHEMA_VERSION = "photon-qdrivers.rtl-instruction.v1"
RTL_INSTRUCTION_FORMAT_VERSION = 1
RTL_INSTRUCTION_WIDTH_BITS = 128


class RTLOpcode(IntEnum):
    """Operations understood by the first control-schedule RTL engine."""

    SOURCE_TRIGGER = 1
    MODULATOR_PULSE = 2
    PHASE_UPDATE = 3
    SYNC = 4
    DELAY = 5
    ACQUIRE = 6


class RTLAcquisitionCode(IntEnum):
    """Eight-bit acquisition codes carried by ACQUIRE instructions."""

    NONE = 0
    WAVEFORM = 1
    TIME_TAGS = 2
    COUNTS = 3
    COINCIDENCES = 4
    THRESHOLDED_EVENTS = 5


_OPCODE_BY_EVENT_KIND = {
    EventKind.SOURCE_TRIGGER: RTLOpcode.SOURCE_TRIGGER,
    EventKind.MODULATOR_PULSE: RTLOpcode.MODULATOR_PULSE,
    EventKind.PHASE_UPDATE: RTLOpcode.PHASE_UPDATE,
    EventKind.SYNC: RTLOpcode.SYNC,
    EventKind.DELAY: RTLOpcode.DELAY,
    EventKind.ACQUIRE: RTLOpcode.ACQUIRE,
}

_ACQUISITION_CODE_BY_KIND = {
    None: RTLAcquisitionCode.NONE,
    AcquisitionKind.WAVEFORM: RTLAcquisitionCode.WAVEFORM,
    AcquisitionKind.TIME_TAGS: RTLAcquisitionCode.TIME_TAGS,
    AcquisitionKind.COUNTS: RTLAcquisitionCode.COUNTS,
    AcquisitionKind.COINCIDENCES: RTLAcquisitionCode.COINCIDENCES,
    AcquisitionKind.THRESHOLDED_EVENTS: RTLAcquisitionCode.THRESHOLDED_EVENTS,
}


@dataclass(frozen=True)
class RTLInstruction:
    """One 128-bit executable instruction in decoded form."""

    opcode: RTLOpcode
    channel_index: int
    start_tick: int
    duration_ticks: int
    argument_word: int = 0
    acquisition_code: RTLAcquisitionCode = RTLAcquisitionCode.NONE
    flags: int = 0
    format_version: int = RTL_INSTRUCTION_FORMAT_VERSION

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "opcode", RTLOpcode(self.opcode))
        except (TypeError, ValueError) as exc:
            raise ControlValidationError(
                f"Unsupported RTL opcode '{self.opcode}'."
            ) from exc
        try:
            object.__setattr__(
                self, "acquisition_code", RTLAcquisitionCode(self.acquisition_code)
            )
        except (TypeError, ValueError) as exc:
            raise ControlValidationError(
                f"Unsupported RTL acquisition code '{self.acquisition_code}'."
            ) from exc
        _require_uint(self.format_version, 4, "RTL format_version")
        if self.format_version != RTL_INSTRUCTION_FORMAT_VERSION:
            raise ControlValidationError(
                f"Unsupported RTL instruction format version {self.format_version}."
            )
        _require_uint(self.channel_index, 8, "RTL channel_index")
        _require_uint(self.start_tick, 32, "RTL start_tick")
        _require_uint(self.duration_ticks, 32, "RTL duration_ticks")
        _require_uint(self.argument_word, 32, "RTL argument_word")
        _require_uint(self.flags, 8, "RTL flags")
        if self.opcode in {
            RTLOpcode.SOURCE_TRIGGER,
            RTLOpcode.MODULATOR_PULSE,
            RTLOpcode.DELAY,
            RTLOpcode.ACQUIRE,
        } and self.duration_ticks == 0:
            raise ControlValidationError(
                f"RTL opcode '{self.opcode.name.lower()}' requires nonzero duration."
            )
        if self.opcode is RTLOpcode.ACQUIRE:
            if self.acquisition_code is RTLAcquisitionCode.NONE:
                raise ControlValidationError(
                    "RTL ACQUIRE instruction requires an acquisition code."
                )
        elif self.acquisition_code is not RTLAcquisitionCode.NONE:
            raise ControlValidationError(
                "Only RTL ACQUIRE instructions may carry an acquisition code."
            )

    @property
    def word(self) -> int:
        """Return the unsigned 128-bit packed instruction."""

        return (
            (self.format_version << 124)
            | (int(self.opcode) << 120)
            | (self.channel_index << 112)
            | (self.start_tick << 80)
            | (self.duration_ticks << 48)
            | (self.argument_word << 16)
            | (int(self.acquisition_code) << 8)
            | self.flags
        )

    @property
    def hex_word(self) -> str:
        """Return exactly 32 lowercase hexadecimal digits for `$readmemh`."""

        return f"{self.word:032x}"

    @classmethod
    def from_word(cls, word: int) -> "RTLInstruction":
        _require_uint(word, RTL_INSTRUCTION_WIDTH_BITS, "RTL instruction word")
        return cls(
            format_version=(word >> 124) & 0xF,
            opcode=RTLOpcode((word >> 120) & 0xF),
            channel_index=(word >> 112) & 0xFF,
            start_tick=(word >> 80) & 0xFFFFFFFF,
            duration_ticks=(word >> 48) & 0xFFFFFFFF,
            argument_word=(word >> 16) & 0xFFFFFFFF,
            acquisition_code=RTLAcquisitionCode((word >> 8) & 0xFF),
            flags=word & 0xFF,
        )

    def to_dict(self) -> dict[str, int | str]:
        return {
            "format_version": self.format_version,
            "opcode": self.opcode.name.lower(),
            "opcode_value": int(self.opcode),
            "channel_index": self.channel_index,
            "start_tick": self.start_tick,
            "duration_ticks": self.duration_ticks,
            "argument_word": self.argument_word,
            "acquisition_code": self.acquisition_code.name.lower(),
            "acquisition_code_value": int(self.acquisition_code),
            "flags": self.flags,
            "hex_word": self.hex_word,
        }


@dataclass(frozen=True)
class RTLProgram:
    """One compiled schedule template lowered to fixed-width RTL words."""

    program_id: str
    profile_id: str
    profile_digest: str
    compiled_program_digest: str
    repetition_ticks: int
    channel_map: Mapping[str, int]
    instructions: tuple[RTLInstruction, ...]
    schema_version: str = RTL_INSTRUCTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RTL_INSTRUCTION_SCHEMA_VERSION:
            raise ControlValidationError(
                f"Unsupported RTL program schema '{self.schema_version}'."
            )
        for value, label in (
            (self.program_id, "RTL program_id"),
            (self.profile_id, "RTL profile_id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ControlValidationError(f"{label} must be non-empty.")
        for digest, label in (
            (self.profile_digest, "RTL profile_digest"),
            (self.compiled_program_digest, "RTL compiled_program_digest"),
        ):
            _require_digest(digest, label)
        _require_uint(self.repetition_ticks, 32, "RTL repetition_ticks")
        if self.repetition_ticks == 0:
            raise ControlValidationError("RTL repetition_ticks must be nonzero.")
        if not isinstance(self.channel_map, MappingABC) or not self.channel_map:
            raise ControlValidationError("RTL channel_map must be a non-empty mapping.")
        normalized_map = dict(self.channel_map)
        indices: list[int] = []
        for channel, index in normalized_map.items():
            if not isinstance(channel, str) or not channel.strip():
                raise ControlValidationError(
                    "RTL channel_map keys must be non-empty strings."
                )
            _require_uint(index, 8, f"RTL channel index for '{channel}'")
            indices.append(index)
        if len(indices) != len(set(indices)):
            raise ControlValidationError("RTL channel_map indices must be unique.")
        object.__setattr__(self, "channel_map", normalized_map)

        instructions = tuple(self.instructions)
        if not instructions:
            raise ControlValidationError("RTL program must contain instructions.")
        if any(not isinstance(item, RTLInstruction) for item in instructions):
            raise ControlValidationError(
                "RTL program instructions must contain RTLInstruction objects."
            )
        object.__setattr__(self, "instructions", instructions)
        previous_tick = -1
        acquisition_end = -1
        for instruction in instructions:
            if instruction.start_tick < previous_tick:
                raise ControlValidationError(
                    "RTL instructions must be ordered by nondecreasing start_tick."
                )
            if instruction.start_tick + instruction.duration_ticks > self.repetition_ticks:
                raise ControlValidationError(
                    "RTL instruction extends beyond the repetition period."
                )
            if instruction.opcode is RTLOpcode.ACQUIRE:
                if instruction.start_tick < acquisition_end:
                    raise ControlValidationError(
                        "RTL v1 supports only one active acquisition window."
                    )
                acquisition_end = instruction.start_tick + instruction.duration_ticks
            previous_tick = instruction.start_tick
        _canonical_json(self.to_dict())

    @property
    def hex_lines(self) -> str:
        """Return a deterministic `$readmemh` file body."""

        return "\n".join(item.hex_word for item in self.instructions) + "\n"

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program_id,
            "profile_id": self.profile_id,
            "profile_digest": self.profile_digest,
            "compiled_program_digest": self.compiled_program_digest,
            "repetition_ticks": self.repetition_ticks,
            "channel_map": dict(sorted(self.channel_map.items())),
            "instructions": [item.to_dict() for item in self.instructions],
        }

    @classmethod
    def from_compiled(
        cls,
        program: CompiledControlProgram,
        channel_map: Mapping[str, int],
    ) -> "RTLProgram":
        """Lower a sweep-free compiled schedule template to RTL words."""

        if not isinstance(program, CompiledControlProgram):
            raise ControlValidationError(
                "RTL lowering requires a CompiledControlProgram."
            )
        if program.sweeps:
            raise ControlValidationError(
                "RTL instruction format v1 does not encode controller sweeps."
            )
        unsupported_acquisitions = sorted(
            event.event_id
            for event in program.events
            if event.kind is EventKind.ACQUIRE
            and event.acquisition_kind is not AcquisitionKind.COUNTS
        )
        if unsupported_acquisitions:
            raise ControlValidationError(
                "RTL schedule engine v1 supports count acquisitions only: "
                + ", ".join(unsupported_acquisitions)
            )
        normalized_map = dict(channel_map)
        missing = sorted({event.channel for event in program.events} - normalized_map.keys())
        if missing:
            raise ControlValidationError(
                "RTL channel_map is missing compiled channels: " + ", ".join(missing)
            )
        ordered_events = sorted(
            program.events, key=lambda event: (event.start_tick, event.event_id)
        )
        instructions = tuple(
            _lower_event(event, normalized_map[event.channel])
            for event in ordered_events
        )
        return cls(
            program_id=program.program_id,
            profile_id=program.profile_id,
            profile_digest=program.profile_digest,
            compiled_program_digest=program.digest,
            repetition_ticks=program.repetition_ticks,
            channel_map=normalized_map,
            instructions=instructions,
        )


def _lower_event(event: CompiledControlEvent, channel_index: int) -> RTLInstruction:
    return RTLInstruction(
        opcode=_OPCODE_BY_EVENT_KIND[event.kind],
        channel_index=channel_index,
        start_tick=event.start_tick,
        duration_ticks=event.duration_ticks,
        argument_word=_argument_word(event),
        acquisition_code=_ACQUISITION_CODE_BY_KIND[event.acquisition_kind],
    )


def _argument_word(event: CompiledControlEvent) -> int:
    if event.kind in (EventKind.SOURCE_TRIGGER, EventKind.MODULATOR_PULSE):
        amplitude = event.parameters.get("amplitude", 1.0)
        if isinstance(amplitude, bool) or not isinstance(amplitude, (int, float)):
            raise ControlValidationError(
                f"RTL amplitude for event '{event.event_id}' must be numeric."
            )
        amplitude = float(amplitude)
        if not math.isfinite(amplitude) or not 0.0 <= amplitude <= 1.0:
            raise ControlValidationError(
                f"RTL amplitude for event '{event.event_id}' must be in [0, 1]."
            )
        return int(round(amplitude * 0xFFFFFFFF))
    if event.kind is EventKind.PHASE_UPDATE:
        phase = event.parameters.get("phase", 0.0)
        if isinstance(phase, bool) or not isinstance(phase, (int, float)):
            raise ControlValidationError(
                f"RTL phase for event '{event.event_id}' must be numeric."
            )
        phase = float(phase)
        if not math.isfinite(phase):
            raise ControlValidationError(
                f"RTL phase for event '{event.event_id}' must be finite."
            )
        normalized = phase % (2.0 * math.pi)
        return int(round(normalized / (2.0 * math.pi) * (1 << 32))) & 0xFFFFFFFF
    if event.kind is EventKind.ACQUIRE:
        window = event.parameters.get("coincidence_window_ticks", 0)
        _require_uint(window, 32, f"RTL acquisition argument for '{event.event_id}'")
        return window
    return 0


def _require_uint(value: Any, bits: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ControlValidationError(f"{label} must be an integer.")
    if value < 0 or value >= (1 << bits):
        raise ControlValidationError(f"{label} must fit in {bits} unsigned bits.")


def _require_digest(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ControlValidationError(f"{label} must be a lowercase SHA-256 digest.")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ControlValidationError(
            "RTL program must contain finite JSON-compatible values."
        ) from exc
