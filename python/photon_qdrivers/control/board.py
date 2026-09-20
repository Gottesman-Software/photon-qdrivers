"""P6 board-program framing and pre-hardware Red Pitaya bridge."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping as MappingABC
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..errors import ControlValidationError
from .acquisition import AcquisitionKind, AcquisitionRecord
from .native_protocol import CONTROL_RESULT_PROTOCOL, ControlEnvelope
from .program import EventKind
from .rtl import (
    RTL_INSTRUCTION_FORMAT_VERSION,
    RTL_INSTRUCTION_WIDTH_BITS,
    RTLAcquisitionCode,
    RTLInstruction,
    RTLOpcode,
    RTLProgram,
)
from .timing import CompiledControlProgram


BOARD_CAPABILITIES_PROTOCOL = "PQDR_BOARD_CAPABILITIES_V1"
BOARD_PROGRAM_PROTOCOL = "PQDR_BOARD_PROGRAM_V1"
BOARD_RESULT_PROTOCOL = "PQDR_BOARD_RESULT_V1"

BOARD_REGISTER_MAP = {
    "identity": 0x00,
    "protocol_version": 0x04,
    "instruction_width": 0x08,
    "max_instructions": 0x0C,
    "channel_count": 0x10,
    "count_width": 0x14,
    "control": 0x18,
    "status": 0x1C,
    "error_code": 0x20,
    "repetition_ticks": 0x24,
    "instruction_count": 0x28,
    "device_tick": 0x2C,
    "acquisition_count": 0x30,
    "dropped_events": 0x34,
    "result_flags": 0x38,
    "pulse_active_mask": 0x3C,
    "instruction_word_3": 0x40,
    "instruction_word_2": 0x44,
    "instruction_word_1": 0x48,
    "instruction_word_0": 0x4C,
    "acquisition_start_tick": 0x50,
    "acquisition_end_tick": 0x54,
    "acquisition_channel": 0x58,
}


@dataclass(frozen=True)
class BoardCapabilities:
    """Digestible capabilities for the P6 register/FIFO boundary."""

    board_id: str = "red-pitaya-stemlab-125-14"
    instruction_format_version: int = RTL_INSTRUCTION_FORMAT_VERSION
    instruction_width_bits: int = RTL_INSTRUCTION_WIDTH_BITS
    max_instructions: int = 64
    channel_count: int = 8
    count_width_bits: int = 32
    register_map: Mapping[str, int] = field(
        default_factory=lambda: dict(BOARD_REGISTER_MAP)
    )
    protocol: str = BOARD_CAPABILITIES_PROTOCOL

    def __post_init__(self) -> None:
        _require_identifier(self.board_id, "Board id")
        if self.protocol != BOARD_CAPABILITIES_PROTOCOL:
            raise ControlValidationError(
                f"Unsupported board capabilities protocol '{self.protocol}'."
            )
        if self.instruction_format_version != RTL_INSTRUCTION_FORMAT_VERSION:
            raise ControlValidationError(
                "Board instruction format does not match RTL format v1."
            )
        if self.instruction_width_bits != RTL_INSTRUCTION_WIDTH_BITS:
            raise ControlValidationError("Board instruction width must be 128 bits.")
        _require_positive_int(self.max_instructions, "Board max_instructions")
        _require_positive_int(self.channel_count, "Board channel_count")
        _require_positive_int(self.count_width_bits, "Board count_width_bits")
        if self.channel_count > 256:
            raise ControlValidationError("Board channel_count must fit in eight bits.")
        if self.count_width_bits > 32:
            raise ControlValidationError(
                "P6 result registers support at most 32 counter bits."
            )
        if not isinstance(self.register_map, MappingABC):
            raise ControlValidationError("Board register_map must be a mapping.")
        normalized = dict(self.register_map)
        if normalized != BOARD_REGISTER_MAP:
            raise ControlValidationError(
                "Board capabilities must use the P6 register-map v1 addresses."
            )
        object.__setattr__(self, "register_map", normalized)

    @property
    def digest(self) -> str:
        return _sha256(self.canonical_json)

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "board_id": self.board_id,
            "instruction_format_version": self.instruction_format_version,
            "instruction_width_bits": self.instruction_width_bits,
            "max_instructions": self.max_instructions,
            "channel_count": self.channel_count,
            "count_width_bits": self.count_width_bits,
            "register_map": dict(sorted(self.register_map.items())),
            "count_acquisition": True,
            "shots_in_rtl": False,
            "sweeps_in_rtl": False,
        }

    def validate_rtl_program(self, program: RTLProgram) -> None:
        if len(program.instructions) > self.max_instructions:
            raise ControlValidationError(
                f"Board accepts at most {self.max_instructions} instructions."
            )
        for instruction in program.instructions:
            if instruction.channel_index >= self.channel_count:
                raise ControlValidationError(
                    f"RTL channel {instruction.channel_index} exceeds board capacity."
                )


@dataclass(frozen=True)
class BoardProgramImage:
    """P4-correlated P5 words ready for the board instruction FIFO."""

    job_id: str
    program_id: str
    profile_id: str
    profile_digest: str
    compiled_program_digest: str
    control_envelope_digest: str
    rtl_program_digest: str
    board_id: str
    capability_digest: str
    repetition_ticks: int
    channel_map: Mapping[str, int]
    acquisition_id: str
    instruction_words: tuple[str, ...]
    protocol: str = BOARD_PROGRAM_PROTOCOL

    def __post_init__(self) -> None:
        if self.protocol != BOARD_PROGRAM_PROTOCOL:
            raise ControlValidationError(
                f"Unsupported board-program protocol '{self.protocol}'."
            )
        for value, label in (
            (self.job_id, "Board job_id"),
            (self.program_id, "Board program_id"),
            (self.profile_id, "Board profile_id"),
            (self.board_id, "Board board_id"),
            (self.acquisition_id, "Board acquisition_id"),
        ):
            _require_identifier(value, label)
        for value, label in (
            (self.profile_digest, "Board profile_digest"),
            (self.compiled_program_digest, "Board compiled_program_digest"),
            (self.control_envelope_digest, "Board control_envelope_digest"),
            (self.rtl_program_digest, "Board rtl_program_digest"),
            (self.capability_digest, "Board capability_digest"),
        ):
            _require_digest(value, label)
        _require_positive_int(self.repetition_ticks, "Board repetition_ticks")
        if not isinstance(self.channel_map, MappingABC) or not self.channel_map:
            raise ControlValidationError("Board channel_map must be non-empty.")
        channel_map = dict(self.channel_map)
        for name, index in channel_map.items():
            _require_identifier(name, "Board channel name")
            _require_uint(index, 8, f"Board channel index for '{name}'")
        if len(set(channel_map.values())) != len(channel_map):
            raise ControlValidationError("Board channel indices must be unique.")
        object.__setattr__(self, "channel_map", channel_map)

        words = tuple(self.instruction_words)
        if not words:
            raise ControlValidationError("Board program must contain instructions.")
        decoded: list[RTLInstruction] = []
        for word in words:
            if (
                not isinstance(word, str)
                or len(word) != 32
                or any(character not in "0123456789abcdef" for character in word)
            ):
                raise ControlValidationError(
                    "Board instructions must be 32 lowercase hexadecimal digits."
                )
            try:
                decoded.append(RTLInstruction.from_word(int(word, 16)))
            except (TypeError, ValueError) as exc:
                raise ControlValidationError("Board instruction decoding failed.") from exc
        object.__setattr__(self, "instruction_words", words)
        previous_tick = -1
        acquisitions = 0
        for instruction in decoded:
            if instruction.start_tick < previous_tick:
                raise ControlValidationError(
                    "Board instructions must have nondecreasing start ticks."
                )
            if instruction.start_tick + instruction.duration_ticks > self.repetition_ticks:
                raise ControlValidationError(
                    "Board instruction extends beyond repetition_ticks."
                )
            if instruction.opcode is RTLOpcode.ACQUIRE:
                acquisitions += 1
                if instruction.acquisition_code is not RTLAcquisitionCode.COUNTS:
                    raise ControlValidationError(
                        "P6 board program supports count acquisition only."
                    )
            previous_tick = instruction.start_tick
        if acquisitions != 1:
            raise ControlValidationError(
                "P6 board program requires exactly one count acquisition."
            )

    @property
    def image_digest(self) -> str:
        return _sha256(_canonical_json(self._digest_fields()))

    def _digest_fields(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "job_id": self.job_id,
            "program_id": self.program_id,
            "profile_id": self.profile_id,
            "profile_digest": self.profile_digest,
            "compiled_program_digest": self.compiled_program_digest,
            "control_envelope_digest": self.control_envelope_digest,
            "rtl_program_digest": self.rtl_program_digest,
            "board_id": self.board_id,
            "capability_digest": self.capability_digest,
            "repetition_ticks": self.repetition_ticks,
            "channel_map": dict(sorted(self.channel_map.items())),
            "acquisition_id": self.acquisition_id,
            "instruction_words": list(self.instruction_words),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._digest_fields(), "image_digest": self.image_digest}

    def to_frame(self) -> str:
        lines = [
            self.protocol,
            f"job_id={self.job_id}",
            f"program_id={self.program_id}",
            f"profile_id={self.profile_id}",
            f"profile_digest={self.profile_digest}",
            f"compiled_program_digest={self.compiled_program_digest}",
            f"control_envelope_digest={self.control_envelope_digest}",
            f"rtl_program_digest={self.rtl_program_digest}",
            f"board_id={self.board_id}",
            f"capability_digest={self.capability_digest}",
            f"repetition_ticks={self.repetition_ticks}",
            f"instruction_count={len(self.instruction_words)}",
            f"channel_map={_canonical_json(dict(sorted(self.channel_map.items())))}",
            f"acquisition_id={self.acquisition_id}",
        ]
        lines.extend(f"instruction={word}" for word in self.instruction_words)
        lines.extend((f"image_digest={self.image_digest}", "END", ""))
        return "\n".join(lines)

    @classmethod
    def from_control_envelope(
        cls,
        envelope: ControlEnvelope,
        channel_map: Mapping[str, int],
        capabilities: BoardCapabilities,
    ) -> "BoardProgramImage":
        if not isinstance(envelope, ControlEnvelope):
            raise ControlValidationError(
                "Board lowering requires a ControlEnvelope."
            )
        if envelope.program.shots != 1:
            raise ControlValidationError(
                "P6 board execution v1 requires exactly one shot."
            )
        if envelope.program.resource_usage.sweep_points != 1:
            raise ControlValidationError(
                "P6 board execution v1 does not execute sweeps."
            )
        rtl_program = RTLProgram.from_compiled(envelope.program, channel_map)
        capabilities.validate_rtl_program(rtl_program)
        acquisitions = [
            event
            for event in envelope.program.events
            if event.kind is EventKind.ACQUIRE
        ]
        if len(acquisitions) != 1 or acquisitions[0].acquisition_id is None:
            raise ControlValidationError(
                "P6 board execution requires one identified acquisition."
            )
        return cls(
            job_id=envelope.job_id,
            program_id=envelope.program.program_id,
            profile_id=envelope.program.profile_id,
            profile_digest=envelope.program.profile_digest,
            compiled_program_digest=envelope.program_digest,
            control_envelope_digest=envelope.envelope_digest,
            rtl_program_digest=rtl_program.digest,
            board_id=capabilities.board_id,
            capability_digest=capabilities.digest,
            repetition_ticks=rtl_program.repetition_ticks,
            channel_map=channel_map,
            acquisition_id=acquisitions[0].acquisition_id,
            instruction_words=tuple(
                instruction.hex_word for instruction in rtl_program.instructions
            ),
        )

    @classmethod
    def from_frame(
        cls,
        frame: str,
        capabilities: BoardCapabilities,
    ) -> "BoardProgramImage":
        fields, instructions = _parse_board_program_frame(frame)
        try:
            channel_map = json.loads(fields["channel_map"])
            image = cls(
                job_id=fields["job_id"],
                program_id=fields["program_id"],
                profile_id=fields["profile_id"],
                profile_digest=fields["profile_digest"],
                compiled_program_digest=fields["compiled_program_digest"],
                control_envelope_digest=fields["control_envelope_digest"],
                rtl_program_digest=fields["rtl_program_digest"],
                board_id=fields["board_id"],
                capability_digest=fields["capability_digest"],
                repetition_ticks=_parse_non_negative_int(
                    fields["repetition_ticks"], "repetition_ticks"
                ),
                channel_map=channel_map,
                acquisition_id=fields["acquisition_id"],
                instruction_words=tuple(instructions),
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Board program frame is missing '{exc.args[0]}'."
            ) from exc
        except json.JSONDecodeError as exc:
            raise ControlValidationError(
                "Board program channel_map is not valid JSON."
            ) from exc
        expected_count = _parse_non_negative_int(
            fields.get("instruction_count", ""), "instruction_count"
        )
        if expected_count != len(image.instruction_words):
            raise ControlValidationError(
                "Board program instruction_count does not match its words."
            )
        if fields.get("image_digest") != image.image_digest:
            raise ControlValidationError("Board program image SHA-256 mismatch.")
        if image.board_id != capabilities.board_id:
            raise ControlValidationError("Board program targets a different board.")
        if image.capability_digest != capabilities.digest:
            raise ControlValidationError(
                "Board program capability digest does not match the board."
            )
        _validate_image_capabilities(image, capabilities)
        return image


@dataclass(frozen=True)
class BoardExecutionResult:
    """Correlated result produced by the P6 board boundary."""

    job_id: str
    board_id: str
    capability_digest: str
    image_digest: str
    rtl_program_digest: str
    instruction_count: int
    final_device_tick: int
    error_code: int
    acquisition_id: str
    acquisition_channel: int
    acquisition_start_tick: int
    acquisition_end_tick: int
    recorded_events: int
    overflow: bool
    dropped_events: int
    execution_target: str
    protocol: str = BOARD_RESULT_PROTOCOL

    def __post_init__(self) -> None:
        if self.protocol != BOARD_RESULT_PROTOCOL:
            raise ControlValidationError(
                f"Unsupported board-result protocol '{self.protocol}'."
            )
        for value, label in (
            (self.job_id, "Board-result job_id"),
            (self.board_id, "Board-result board_id"),
            (self.acquisition_id, "Board-result acquisition_id"),
            (self.execution_target, "Board-result execution_target"),
        ):
            _require_identifier(value, label)
        for value, label in (
            (self.capability_digest, "Board-result capability_digest"),
            (self.image_digest, "Board-result image_digest"),
            (self.rtl_program_digest, "Board-result rtl_program_digest"),
        ):
            _require_digest(value, label)
        for value, label in (
            (self.instruction_count, "Board-result instruction_count"),
            (self.final_device_tick, "Board-result final_device_tick"),
            (self.error_code, "Board-result error_code"),
            (self.acquisition_channel, "Board-result acquisition_channel"),
            (self.acquisition_start_tick, "Board-result acquisition_start_tick"),
            (self.acquisition_end_tick, "Board-result acquisition_end_tick"),
            (self.recorded_events, "Board-result recorded_events"),
            (self.dropped_events, "Board-result dropped_events"),
        ):
            _require_non_negative_int(value, label)
        if self.acquisition_end_tick < self.acquisition_start_tick:
            raise ControlValidationError(
                "Board-result acquisition interval is invalid."
            )
        if not isinstance(self.overflow, bool):
            raise ControlValidationError("Board-result overflow must be boolean.")

    @property
    def result_digest(self) -> str:
        return _sha256(_canonical_json(self._digest_fields()))

    def _digest_fields(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "job_id": self.job_id,
            "board_id": self.board_id,
            "capability_digest": self.capability_digest,
            "image_digest": self.image_digest,
            "rtl_program_digest": self.rtl_program_digest,
            "instruction_count": self.instruction_count,
            "final_device_tick": self.final_device_tick,
            "error_code": self.error_code,
            "acquisition_id": self.acquisition_id,
            "acquisition_channel": self.acquisition_channel,
            "acquisition_start_tick": self.acquisition_start_tick,
            "acquisition_end_tick": self.acquisition_end_tick,
            "recorded_events": self.recorded_events,
            "overflow": self.overflow,
            "dropped_events": self.dropped_events,
            "execution_target": self.execution_target,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._digest_fields(), "result_digest": self.result_digest}

    def to_frame(self) -> str:
        values = self.to_dict()
        ordered = (
            "job_id",
            "board_id",
            "capability_digest",
            "image_digest",
            "rtl_program_digest",
            "instruction_count",
            "final_device_tick",
            "error_code",
            "acquisition_id",
            "acquisition_channel",
            "acquisition_start_tick",
            "acquisition_end_tick",
            "recorded_events",
            "overflow",
            "dropped_events",
            "execution_target",
            "result_digest",
        )
        lines = [self.protocol]
        for name in ordered:
            value = values[name]
            if isinstance(value, bool):
                value = int(value)
            lines.append(f"{name}={value}")
        lines.extend(("END", ""))
        return "\n".join(lines)

    @classmethod
    def from_frame(
        cls,
        frame: str,
        image: BoardProgramImage,
        capabilities: BoardCapabilities,
    ) -> "BoardExecutionResult":
        fields = _parse_single_value_frame(frame, BOARD_RESULT_PROTOCOL)
        try:
            result = cls(
                job_id=fields["job_id"],
                board_id=fields["board_id"],
                capability_digest=fields["capability_digest"],
                image_digest=fields["image_digest"],
                rtl_program_digest=fields["rtl_program_digest"],
                instruction_count=_parse_non_negative_int(
                    fields["instruction_count"], "instruction_count"
                ),
                final_device_tick=_parse_non_negative_int(
                    fields["final_device_tick"], "final_device_tick"
                ),
                error_code=_parse_non_negative_int(
                    fields["error_code"], "error_code"
                ),
                acquisition_id=fields["acquisition_id"],
                acquisition_channel=_parse_non_negative_int(
                    fields["acquisition_channel"], "acquisition_channel"
                ),
                acquisition_start_tick=_parse_non_negative_int(
                    fields["acquisition_start_tick"], "acquisition_start_tick"
                ),
                acquisition_end_tick=_parse_non_negative_int(
                    fields["acquisition_end_tick"], "acquisition_end_tick"
                ),
                recorded_events=_parse_non_negative_int(
                    fields["recorded_events"], "recorded_events"
                ),
                overflow=_parse_bool(fields["overflow"], "overflow"),
                dropped_events=_parse_non_negative_int(
                    fields["dropped_events"], "dropped_events"
                ),
                execution_target=fields["execution_target"],
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Board result frame is missing '{exc.args[0]}'."
            ) from exc
        if fields.get("result_digest") != result.result_digest:
            raise ControlValidationError("Board result SHA-256 mismatch.")
        _validate_result_correlation(result, image, capabilities)
        return result

    def acquisition_record(self) -> AcquisitionRecord:
        return AcquisitionRecord(
            acquisition_id=self.acquisition_id,
            kind=AcquisitionKind.COUNTS,
            payload={f"channel_{self.acquisition_channel}": self.recorded_events},
            unit="events",
            shape=(1,),
            start_tick=self.acquisition_start_tick,
            end_tick=self.acquisition_end_tick,
            overflow=self.overflow,
            dropped_events=self.dropped_events,
            metadata={
                "board_id": self.board_id,
                "capability_digest": self.capability_digest,
                "board_image_digest": self.image_digest,
                "rtl_program_digest": self.rtl_program_digest,
                "board_result_digest": self.result_digest,
                "execution_target": self.execution_target,
                "error_code": self.error_code,
                "final_device_tick": self.final_device_tick,
            },
        )


class SoftwareBoard:
    """Deterministic P6.0 register-level model; never physical evidence."""

    def __init__(self, capabilities: BoardCapabilities) -> None:
        if not isinstance(capabilities, BoardCapabilities):
            raise ControlValidationError(
                "SoftwareBoard requires BoardCapabilities."
            )
        self.capabilities = capabilities

    def execute(
        self,
        image: BoardProgramImage,
        *,
        detector_event_ticks: Iterable[int] = (),
    ) -> BoardExecutionResult:
        if not isinstance(image, BoardProgramImage):
            raise ControlValidationError(
                "SoftwareBoard execute requires a BoardProgramImage."
            )
        _validate_image_capabilities(image, self.capabilities)
        instructions = tuple(
            RTLInstruction.from_word(int(word, 16))
            for word in image.instruction_words
        )
        acquisition = next(
            instruction
            for instruction in instructions
            if instruction.opcode is RTLOpcode.ACQUIRE
        )
        ticks = tuple(detector_event_ticks)
        for tick in ticks:
            _require_non_negative_int(tick, "Detector event tick")
        accepted = sum(
            1
            for tick in ticks
            if acquisition.start_tick
            <= tick
            < acquisition.start_tick + acquisition.duration_ticks
        )
        maximum = (1 << self.capabilities.count_width_bits) - 1
        recorded = min(accepted, maximum)
        dropped = accepted - recorded
        return BoardExecutionResult(
            job_id=image.job_id,
            board_id=image.board_id,
            capability_digest=image.capability_digest,
            image_digest=image.image_digest,
            rtl_program_digest=image.rtl_program_digest,
            instruction_count=len(image.instruction_words),
            final_device_tick=image.repetition_ticks - 1,
            error_code=0,
            acquisition_id=image.acquisition_id,
            acquisition_channel=acquisition.channel_index,
            acquisition_start_tick=acquisition.start_tick,
            acquisition_end_tick=(
                acquisition.start_tick + acquisition.duration_ticks
            ),
            recorded_events=recorded,
            overflow=dropped > 0,
            dropped_events=dropped,
            execution_target="p6-software-board-model",
        )


class P6BoardBridge:
    """Translate an existing P4 mailbox frame into P5 board evidence."""

    def __init__(
        self,
        capabilities: BoardCapabilities,
        channel_map: Mapping[str, int],
    ) -> None:
        self.capabilities = capabilities
        self.channel_map = dict(channel_map)
        self.software_board = SoftwareBoard(capabilities)

    def prepare(self, envelope: ControlEnvelope) -> BoardProgramImage:
        return BoardProgramImage.from_control_envelope(
            envelope,
            self.channel_map,
            self.capabilities,
        )

    def handle_control_frame(
        self,
        frame: str,
        *,
        detector_event_ticks: Iterable[int] = (),
    ) -> tuple[ControlEnvelope, BoardProgramImage, BoardExecutionResult, str]:
        envelope = decode_control_request_frame(frame)
        image = self.prepare(envelope)
        restored = BoardProgramImage.from_frame(
            image.to_frame(), self.capabilities
        )
        result = self.software_board.execute(
            restored,
            detector_event_ticks=detector_event_ticks,
        )
        restored_result = BoardExecutionResult.from_frame(
            result.to_frame(), restored, self.capabilities
        )
        control_result = encode_control_result_frame(
            envelope, restored, restored_result
        )
        return envelope, restored, restored_result, control_result


def encode_control_request_frame(envelope: ControlEnvelope) -> str:
    """Render exactly the P4 line frame consumed by a board-side bridge."""

    values = envelope.to_dict()
    lines = [
        values["protocol"],
        f"job_id={values['job_id']}",
        f"program_id={values['program_id']}",
        f"profile_id={values['profile_id']}",
        f"profile_digest={values['profile_digest']}",
        f"program_digest={values['program_digest']}",
        f"envelope_digest={values['envelope_digest']}",
        f"shots={values['shots']}",
        f"repetition_ticks={values['repetition_ticks']}",
        f"sweep_points={values['sweep_points']}",
        f"event_count={values['event_count']}",
        "compiled_payload_length="
        f"{len(values['compiled_payload'].encode('utf-8'))}",
        f"compiled_payload={values['compiled_payload']}",
        "END",
        "",
    ]
    return "\n".join(lines)


def decode_control_request_frame(frame: str) -> ControlEnvelope:
    """Reconstruct and integrity-check a P4 mailbox request."""

    from .native_protocol import CONTROL_TRANSPORT_PROTOCOL

    fields = _parse_single_value_frame(frame, CONTROL_TRANSPORT_PROTOCOL)
    try:
        payload = fields["compiled_payload"]
        payload_length = _parse_non_negative_int(
            fields["compiled_payload_length"], "compiled_payload_length"
        )
        if len(payload.encode("utf-8")) != payload_length:
            raise ControlValidationError(
                "P4 compiled_payload length does not match its frame."
            )
        raw_program = json.loads(payload)
        program = CompiledControlProgram.from_mapping(raw_program)
        envelope = ControlEnvelope(job_id=fields["job_id"], program=program)
    except KeyError as exc:
        raise ControlValidationError(
            f"P4 control frame is missing '{exc.args[0]}'."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ControlValidationError(
            "P4 compiled_payload is not valid JSON."
        ) from exc
    expected = envelope.to_dict()
    for name in (
        "job_id",
        "program_id",
        "profile_id",
        "profile_digest",
        "program_digest",
        "envelope_digest",
        "shots",
        "repetition_ticks",
        "sweep_points",
        "event_count",
        "compiled_payload",
    ):
        if fields.get(name) != str(expected[name]):
            raise ControlValidationError(
                f"P4 control frame field '{name}' does not match its payload."
            )
    return envelope


def encode_control_result_frame(
    envelope: ControlEnvelope,
    image: BoardProgramImage,
    result: BoardExecutionResult,
    *,
    message: str = "completed by P6.0 software board bridge",
) -> str:
    """Return a P4 result frame accepted by the existing native mailbox."""

    _validate_result_correlation(result, image, None)
    if result.error_code != 0:
        raise ControlValidationError(
            "Failed board executions cannot be encoded as completed P4 results."
        )
    if envelope.job_id != image.job_id:
        raise ControlValidationError("Board image does not correlate with P4 job.")
    if envelope.program_digest != image.compiled_program_digest:
        raise ControlValidationError(
            "Board image does not correlate with P4 compiled program."
        )
    if envelope.envelope_digest != image.control_envelope_digest:
        raise ControlValidationError(
            "Board image does not correlate with P4 envelope."
        )
    _require_identifier(message, "Control-result message")
    record = result.acquisition_record()
    acquisition_payload = _canonical_json([record.to_dict()])
    acquisition_digest = _sha256(acquisition_payload)
    lines = [
        CONTROL_RESULT_PROTOCOL,
        f"job_id={envelope.job_id}",
        f"program_id={envelope.program.program_id}",
        f"profile_id={envelope.program.profile_id}",
        f"profile_digest={envelope.program.profile_digest}",
        f"program_digest={envelope.program_digest}",
        f"envelope_digest={envelope.envelope_digest}",
        f"acquisition_digest={acquisition_digest}",
        "status=completed",
        f"shots={envelope.program.shots}",
        f"repetition_ticks={envelope.program.repetition_ticks}",
        f"sweep_points={envelope.program.resource_usage.sweep_points}",
        f"event_count={len(envelope.program.events)}",
        "acquisition_count=1",
        f"total_device_ticks={envelope.program.total_device_ticks}",
        f"overflowed_acquisitions={int(result.overflow)}",
        f"dropped_events={result.dropped_events}",
        f"acquisition_payload_length={len(acquisition_payload.encode('utf-8'))}",
        f"acquisition_payload={acquisition_payload}",
        f"message={message}",
        "END",
        "",
    ]
    return "\n".join(lines)


def _rtl_program_from_image(image: BoardProgramImage) -> RTLProgram:
    return RTLProgram(
        program_id=image.program_id,
        profile_id=image.profile_id,
        profile_digest=image.profile_digest,
        compiled_program_digest=image.compiled_program_digest,
        repetition_ticks=image.repetition_ticks,
        channel_map=image.channel_map,
        instructions=tuple(
            RTLInstruction.from_word(int(word, 16))
            for word in image.instruction_words
        ),
    )


def _validate_image_capabilities(
    image: BoardProgramImage,
    capabilities: BoardCapabilities,
) -> None:
    if image.board_id != capabilities.board_id:
        raise ControlValidationError("Board image targets a different board.")
    if image.capability_digest != capabilities.digest:
        raise ControlValidationError("Board capability digest mismatch.")
    rtl_program = _rtl_program_from_image(image)
    if rtl_program.digest != image.rtl_program_digest:
        raise ControlValidationError("Board RTL program SHA-256 mismatch.")
    capabilities.validate_rtl_program(rtl_program)


def _validate_result_correlation(
    result: BoardExecutionResult,
    image: BoardProgramImage,
    capabilities: BoardCapabilities | None,
) -> None:
    if (
        result.job_id != image.job_id
        or result.board_id != image.board_id
        or result.capability_digest != image.capability_digest
        or result.image_digest != image.image_digest
        or result.rtl_program_digest != image.rtl_program_digest
        or result.instruction_count != len(image.instruction_words)
        or result.acquisition_id != image.acquisition_id
    ):
        raise ControlValidationError(
            "Board result does not correlate with its program image."
        )
    if capabilities is not None:
        _validate_image_capabilities(image, capabilities)


def _parse_board_program_frame(frame: str) -> tuple[dict[str, str], list[str]]:
    lines = _frame_lines(frame, BOARD_PROGRAM_PROTOCOL)
    fields: dict[str, str] = {}
    instructions: list[str] = []
    for line in lines:
        name, value = _split_field(line)
        if name == "instruction":
            instructions.append(value)
        elif name in fields:
            raise ControlValidationError(
                f"Board program frame repeats field '{name}'."
            )
        else:
            fields[name] = value
    return fields, instructions


def _parse_single_value_frame(frame: str, protocol: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in _frame_lines(frame, protocol):
        name, value = _split_field(line)
        if name in fields:
            raise ControlValidationError(f"Frame repeats field '{name}'.")
        fields[name] = value
    return fields


def _frame_lines(frame: str, protocol: str) -> list[str]:
    if not isinstance(frame, str):
        raise ControlValidationError("Protocol frame must be text.")
    lines = frame.splitlines()
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) < 2 or lines[0] != protocol or lines[-1] != "END":
        raise ControlValidationError(
            f"Malformed or unsupported protocol frame; expected '{protocol}'."
        )
    return lines[1:-1]


def _split_field(line: str) -> tuple[str, str]:
    if "=" not in line:
        raise ControlValidationError("Protocol frame contains a malformed field.")
    name, value = line.split("=", 1)
    if not name or "\n" in value or "\r" in value:
        raise ControlValidationError("Protocol frame contains an invalid field.")
    return name, value


def _parse_non_negative_int(value: str, label: str) -> int:
    try:
        parsed = int(value, 10)
    except (TypeError, ValueError) as exc:
        raise ControlValidationError(f"{label} must be a decimal integer.") from exc
    _require_non_negative_int(parsed, label)
    return parsed


def _parse_bool(value: str, label: str) -> bool:
    if value == "0":
        return False
    if value == "1":
        return True
    raise ControlValidationError(f"{label} must be 0 or 1.")


def _require_identifier(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise ControlValidationError(f"{label} must be a non-empty line value.")


def _require_digest(value: Any, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ControlValidationError(f"{label} must be a lowercase SHA-256 digest.")


def _require_positive_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ControlValidationError(f"{label} must be a positive integer.")


def _require_non_negative_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlValidationError(f"{label} must be a non-negative integer.")


def _require_uint(value: Any, bits: int, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value >= 1 << bits
    ):
        raise ControlValidationError(f"{label} must fit in {bits} unsigned bits.")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ControlValidationError(
            "Board protocol data must be canonical JSON-compatible."
        ) from exc


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
