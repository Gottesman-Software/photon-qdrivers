"""Physical Red Pitaya MMIO execution and P6.1 evidence capture."""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import struct
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ..errors import ControlValidationError
from .board import (
    BOARD_REGISTER_MAP,
    BoardCapabilities,
    BoardExecutionResult,
    BoardProgramImage,
)
from .rtl import RTLInstruction, RTLOpcode


RED_PITAYA_DEFAULT_BASE_ADDRESS = 0x4034_0000
RED_PITAYA_DEFAULT_MAP_SIZE = 0x1000
RED_PITAYA_BOARD_IDENTITY = 0x5051_4452
RED_PITAYA_BOARD_PROTOCOL_VERSION = 0x0001_0000
RED_PITAYA_PHYSICAL_PROTOCOL_VERSION = 0x0001_0000
RED_PITAYA_LOOPBACK_OUTPUT_CHANNEL = 0
RED_PITAYA_LOOPBACK_INPUT_CHANNEL = 4
PHYSICAL_EVIDENCE_PROTOCOL = "PQDR_PHYSICAL_EVIDENCE_V1"

PHYSICAL_REGISTER_MAP = {
    "physical_protocol_version": 0x5C,
    "fpga_clock_hz": 0x60,
    "output_rise_tick": 0x64,
    "output_fall_tick": 0x68,
    "input_rise_tick": 0x6C,
    "input_high_cycles": 0x70,
    "loopback_flags": 0x74,
}


class RegisterIO(Protocol):
    """Minimal little-endian 32-bit register access contract."""

    def read32(self, offset: int) -> int: ...

    def write32(self, offset: int, value: int) -> None: ...


class DevMemRegisterIO:
    """Page-aligned ``mmap`` access to a physical register aperture.

    The Red Pitaya process normally needs root or an equivalent capability to
    open ``/dev/mem``.  Device deployment should grant only the minimum access
    needed for the configured FPGA aperture.
    """

    def __init__(
        self,
        physical_address: int = RED_PITAYA_DEFAULT_BASE_ADDRESS,
        span: int = RED_PITAYA_DEFAULT_MAP_SIZE,
        *,
        device_path: str | os.PathLike[str] = "/dev/mem",
    ) -> None:
        _require_non_negative_int(physical_address, "Physical address")
        _require_positive_int(span, "Register span")
        page_size = mmap.PAGESIZE
        page_base = physical_address - (physical_address % page_size)
        self._page_offset = physical_address - page_base
        self._span = span
        map_length = self._page_offset + span
        descriptor = os.open(os.fspath(device_path), os.O_RDWR | os.O_SYNC)
        try:
            self._mapping = mmap.mmap(
                descriptor,
                map_length,
                flags=mmap.MAP_SHARED,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
                offset=page_base,
            )
        finally:
            os.close(descriptor)
        self._closed = False

    def __enter__(self) -> "DevMemRegisterIO":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._mapping.close()
            self._closed = True

    def read32(self, offset: int) -> int:
        position = self._position(offset)
        return struct.unpack_from("<I", self._mapping, position)[0]

    def write32(self, offset: int, value: int) -> None:
        position = self._position(offset)
        _require_uint32(value, "Register value")
        struct.pack_into("<I", self._mapping, position, value)

    def _position(self, offset: int) -> int:
        if self._closed:
            raise ControlValidationError("Register mapping is closed.")
        _require_non_negative_int(offset, "Register offset")
        if offset % 4:
            raise ControlValidationError("Register offset must be 32-bit aligned.")
        if offset + 4 > self._span:
            raise ControlValidationError("Register offset exceeds the mapped span.")
        return self._page_offset + offset


@dataclass(frozen=True)
class PhysicalExecutionEvidence:
    """Digestible physical-loopback evidence kept separate from P6.0 frames."""

    captured_at_utc: str
    bitstream_sha256: str
    board_result: BoardExecutionResult
    register_base_address: int
    fpga_clock_hz: int
    host_round_trip_ns: int
    loopback_output_channel: int
    loopback_input_channel: int
    output_rise_tick: int
    output_fall_tick: int
    input_rise_tick: int
    input_high_cycles: int
    loopback_flags: int
    protocol: str = PHYSICAL_EVIDENCE_PROTOCOL

    def __post_init__(self) -> None:
        if self.protocol != PHYSICAL_EVIDENCE_PROTOCOL:
            raise ControlValidationError(
                f"Unsupported physical-evidence protocol '{self.protocol}'."
            )
        if not isinstance(self.captured_at_utc, str) or not self.captured_at_utc:
            raise ControlValidationError("captured_at_utc must be non-empty text.")
        _require_digest(self.bitstream_sha256, "Bitstream SHA-256")
        if not isinstance(self.board_result, BoardExecutionResult):
            raise ControlValidationError(
                "Physical evidence requires a BoardExecutionResult."
            )
        for value, label in (
            (self.register_base_address, "Register base address"),
            (self.host_round_trip_ns, "Host round-trip time"),
            (self.loopback_output_channel, "Loopback output channel"),
            (self.loopback_input_channel, "Loopback input channel"),
            (self.output_rise_tick, "Output rise tick"),
            (self.output_fall_tick, "Output fall tick"),
            (self.input_rise_tick, "Input rise tick"),
            (self.input_high_cycles, "Input high cycles"),
            (self.loopback_flags, "Loopback flags"),
        ):
            _require_non_negative_int(value, label)
        _require_positive_int(self.fpga_clock_hz, "FPGA clock frequency")
        if self.output_fall_tick < self.output_rise_tick:
            raise ControlValidationError("Observed output interval is invalid.")
        if self.loopback_flags & 0x7 != 0x7:
            raise ControlValidationError(
                "Physical loopback did not observe output rise/fall and input rise."
            )

    @property
    def evidence_digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    @property
    def tick_period_ns(self) -> float:
        return 1_000_000_000 / self.fpga_clock_hz

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self._digest_fields(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    def _digest_fields(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "captured_at_utc": self.captured_at_utc,
            "bitstream_sha256": self.bitstream_sha256,
            "board_result": self.board_result.to_dict(),
            "register_base_address": self.register_base_address,
            "fpga_clock_hz": self.fpga_clock_hz,
            "tick_period_ns": self.tick_period_ns,
            "host_round_trip_ns": self.host_round_trip_ns,
            "loopback_output_channel": self.loopback_output_channel,
            "loopback_input_channel": self.loopback_input_channel,
            "output_rise_tick": self.output_rise_tick,
            "output_fall_tick": self.output_fall_tick,
            "input_rise_tick": self.input_rise_tick,
            "input_high_cycles": self.input_high_cycles,
            "loopback_flags": self.loopback_flags,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._digest_fields(), "evidence_digest": self.evidence_digest}


class RedPitayaMMIOBoard:
    """Execute a P6 image through a deployed Red Pitaya register aperture."""

    def __init__(
        self,
        registers: RegisterIO,
        *,
        base_address: int = RED_PITAYA_DEFAULT_BASE_ADDRESS,
        timeout_seconds: float = 1.0,
        poll_interval_seconds: float = 0.000_001,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not hasattr(registers, "read32") or not hasattr(registers, "write32"):
            raise ControlValidationError("Red Pitaya board requires RegisterIO.")
        _require_non_negative_int(base_address, "Register base address")
        if timeout_seconds <= 0:
            raise ControlValidationError("MMIO timeout must be positive.")
        if poll_interval_seconds < 0:
            raise ControlValidationError("MMIO poll interval cannot be negative.")
        self.registers = registers
        self.base_address = base_address
        self.timeout_ns = int(timeout_seconds * 1_000_000_000)
        self.poll_interval_seconds = poll_interval_seconds
        self._monotonic_ns = monotonic_ns
        self._sleep = sleep

    def inspect_capabilities(self) -> BoardCapabilities:
        identity = self._read("identity")
        protocol_version = self._read("protocol_version")
        instruction_width = self._read("instruction_width")
        if identity != RED_PITAYA_BOARD_IDENTITY:
            raise ControlValidationError(
                f"Red Pitaya identity mismatch: 0x{identity:08x}."
            )
        if protocol_version != RED_PITAYA_BOARD_PROTOCOL_VERSION:
            raise ControlValidationError(
                f"Unsupported board protocol 0x{protocol_version:08x}."
            )
        if instruction_width != 128:
            raise ControlValidationError(
                f"Unsupported instruction width {instruction_width}."
            )
        physical_protocol = self.registers.read32(
            PHYSICAL_REGISTER_MAP["physical_protocol_version"]
        )
        if physical_protocol != RED_PITAYA_PHYSICAL_PROTOCOL_VERSION:
            raise ControlValidationError(
                f"Unsupported physical protocol 0x{physical_protocol:08x}."
            )
        return BoardCapabilities(
            max_instructions=self._read("max_instructions"),
            channel_count=self._read("channel_count"),
            count_width_bits=self._read("count_width"),
        )

    def execute(
        self,
        image: BoardProgramImage,
        *,
        bitstream_sha256: str,
        captured_at_utc: str,
        loopback_output_channel: int = RED_PITAYA_LOOPBACK_OUTPUT_CHANNEL,
        loopback_input_channel: int = RED_PITAYA_LOOPBACK_INPUT_CHANNEL,
    ) -> PhysicalExecutionEvidence:
        _require_digest(bitstream_sha256, "Bitstream SHA-256")
        capabilities = self.inspect_capabilities()
        image = BoardProgramImage.from_frame(image.to_frame(), capabilities)
        if loopback_output_channel != RED_PITAYA_LOOPBACK_OUTPUT_CHANNEL:
            raise ControlValidationError(
                "Physical protocol v1 observes loopback output channel 0."
            )
        if loopback_input_channel != RED_PITAYA_LOOPBACK_INPUT_CHANNEL:
            raise ControlValidationError(
                "Physical protocol v1 observes loopback input channel 4."
            )
        if loopback_output_channel >= capabilities.channel_count:
            raise ControlValidationError("Loopback output channel exceeds capacity.")
        if loopback_input_channel >= capabilities.channel_count:
            raise ControlValidationError("Loopback input channel exceeds capacity.")
        instructions = tuple(
            RTLInstruction.from_word(int(word, 16))
            for word in image.instruction_words
        )
        acquisition = next(
            instruction
            for instruction in instructions
            if instruction.opcode is RTLOpcode.ACQUIRE
        )
        matching_pulses = tuple(
            instruction
            for instruction in instructions
            if instruction.opcode
            in (RTLOpcode.SOURCE_TRIGGER, RTLOpcode.MODULATOR_PULSE)
            and instruction.channel_index == loopback_output_channel
            and instruction.start_tick == acquisition.start_tick
            and instruction.duration_ticks == acquisition.duration_ticks
        )
        if acquisition.channel_index != loopback_input_channel:
            raise ControlValidationError(
                "P6.1 acquisition must target loopback input channel 4."
            )
        if len(matching_pulses) != 1:
            raise ControlValidationError(
                "P6.1 requires one output-channel-0 pulse exactly matching "
                "the acquisition window."
            )

        host_start = self._monotonic_ns()
        self._write("control", 0x1)
        self._write("repetition_ticks", image.repetition_ticks)

        for index, hexadecimal_word in enumerate(image.instruction_words):
            self._wait_for_status(
                lambda status: bool(status & (1 << 1)),
                "instruction-ready",
            )
            word = int(hexadecimal_word, 16)
            self._write("instruction_word_3", (word >> 96) & 0xFFFF_FFFF)
            self._write("instruction_word_2", (word >> 64) & 0xFFFF_FFFF)
            self._write("instruction_word_1", (word >> 32) & 0xFFFF_FFFF)
            self._write("instruction_word_0", word & 0xFFFF_FFFF)
            is_last = index == len(image.instruction_words) - 1
            self._write("control", 0x2 | (0x4 if is_last else 0x0))

        status = self._read("status")
        if not status & 0x1:
            raise ControlValidationError("Board did not latch a complete program.")
        if self._read("instruction_count") != len(image.instruction_words):
            raise ControlValidationError("Board instruction count does not match image.")

        self._write("control", 0x8)
        status = self._wait_for_status(
            lambda value: bool(value & ((1 << 3) | (1 << 4))),
            "execution-complete",
        )
        host_end = self._monotonic_ns()
        error_code = self._read("error_code")
        if status & (1 << 4) or error_code:
            raise ControlValidationError(
                f"Red Pitaya execution failed with error 0x{error_code:02x}."
            )
        if not status & (1 << 6):
            raise ControlValidationError("Board did not complete its acquisition.")

        result = BoardExecutionResult(
            job_id=image.job_id,
            board_id=image.board_id,
            capability_digest=image.capability_digest,
            image_digest=image.image_digest,
            rtl_program_digest=image.rtl_program_digest,
            instruction_count=self._read("instruction_count"),
            final_device_tick=self._read("device_tick"),
            error_code=error_code,
            acquisition_id=image.acquisition_id,
            acquisition_channel=self._read("acquisition_channel"),
            acquisition_start_tick=self._read("acquisition_start_tick"),
            acquisition_end_tick=self._read("acquisition_end_tick"),
            recorded_events=self._read("acquisition_count"),
            overflow=bool(self._read("result_flags") & 0x1),
            dropped_events=self._read("dropped_events"),
            execution_target="red-pitaya-stemlab-125-14-mmio",
        )
        restored = BoardExecutionResult.from_frame(
            result.to_frame(), image, capabilities
        )
        physical = {
            name: self.registers.read32(offset)
            for name, offset in PHYSICAL_REGISTER_MAP.items()
        }
        expected_end_tick = acquisition.start_tick + acquisition.duration_ticks
        expected_maximum = (1 << capabilities.count_width_bits) - 1
        expected_recorded = min(acquisition.duration_ticks, expected_maximum)
        expected_dropped = max(0, acquisition.duration_ticks - expected_maximum)
        if physical["fpga_clock_hz"] != 125_000_000:
            raise ControlValidationError("P6.1 requires the 125 MHz fabric clock.")
        if (
            physical["output_rise_tick"] != acquisition.start_tick
            or physical["output_fall_tick"] != expected_end_tick
            or physical["input_rise_tick"] != acquisition.start_tick
            or physical["input_high_cycles"] != acquisition.duration_ticks
        ):
            raise ControlValidationError(
                "Physical loopback edge timing does not match the board image."
            )
        if (
            restored.final_device_tick != image.repetition_ticks - 1
            or restored.acquisition_channel != acquisition.channel_index
            or restored.acquisition_start_tick != acquisition.start_tick
            or restored.acquisition_end_tick != expected_end_tick
            or restored.recorded_events != expected_recorded
            or restored.dropped_events != expected_dropped
            or restored.overflow != (expected_dropped > 0)
        ):
            raise ControlValidationError(
                "Physical loopback result does not match the P6.1 acceptance values."
            )
        return PhysicalExecutionEvidence(
            captured_at_utc=captured_at_utc,
            bitstream_sha256=bitstream_sha256,
            board_result=restored,
            register_base_address=self.base_address,
            fpga_clock_hz=physical["fpga_clock_hz"],
            host_round_trip_ns=host_end - host_start,
            loopback_output_channel=loopback_output_channel,
            loopback_input_channel=loopback_input_channel,
            output_rise_tick=physical["output_rise_tick"],
            output_fall_tick=physical["output_fall_tick"],
            input_rise_tick=physical["input_rise_tick"],
            input_high_cycles=physical["input_high_cycles"],
            loopback_flags=physical["loopback_flags"],
        )

    def _read(self, name: str) -> int:
        return self.registers.read32(BOARD_REGISTER_MAP[name])

    def _write(self, name: str, value: int) -> None:
        self.registers.write32(BOARD_REGISTER_MAP[name], value)

    def _wait_for_status(
        self,
        predicate: Callable[[int], bool],
        label: str,
    ) -> int:
        deadline = self._monotonic_ns() + self.timeout_ns
        while True:
            status = self._read("status")
            if predicate(status):
                return status
            if self._monotonic_ns() >= deadline:
                raise ControlValidationError(
                    f"Timed out waiting for Red Pitaya {label}."
                )
            if self.poll_interval_seconds:
                self._sleep(self.poll_interval_seconds)


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Return a streaming SHA-256 digest for a deployed bitstream."""

    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def _require_uint32(value: Any, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value >= 1 << 32
    ):
        raise ControlValidationError(f"{label} must fit in 32 unsigned bits.")
