from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from photon_qdrivers import (
    AcquisitionKind,
    BOARD_REGISTER_MAP,
    PHYSICAL_REGISTER_MAP,
    BoardCapabilities,
    ChannelRole,
    ControlChannel,
    ControlEnvelope,
    ControlEvent,
    ControlProgram,
    ControlValidationError,
    DevMemRegisterIO,
    EventKind,
    HardwareProfile,
    P6BoardBridge,
    RedPitayaMMIOBoard,
    RED_PITAYA_PHYSICAL_LOOPBACK_CHANNEL_MAP,
    compile_control_program,
    red_pitaya_physical_loopback_envelope,
)


CHANNEL_MAP = {"source/0": 0, "detector/0": 4}


def physical_loopback_image():
    profile = HardwareProfile(
        profile_id="p61-red-pitaya-profile",
        clock_period_ns=8.0,
        channel_roles={
            "source/0": ChannelRole.SOURCE,
            "detector/0": ChannelRole.DETECTOR,
        },
        counter_bits=2,
    )
    program = ControlProgram(
        program_id="p61-physical-loopback",
        channels=(
            ControlChannel("source/0", ChannelRole.SOURCE),
            ControlChannel("detector/0", ChannelRole.DETECTOR),
        ),
        events=(
            ControlEvent(
                "loopback-pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=56,
                duration_ns=32,
                parameters={"amplitude": 1.0},
            ),
            ControlEvent(
                "loopback-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=56,
                duration_ns=32,
                acquisition_id="p61-loopback-counts",
                acquisition_kind=AcquisitionKind.COUNTS,
            ),
        ),
        shots=1,
        repetition_period_ns=96,
    )
    envelope = ControlEnvelope(
        job_id="p61-physical-loopback-job",
        program=compile_control_program(program, profile),
    )
    capabilities = BoardCapabilities(max_instructions=16, count_width_bits=2)
    return P6BoardBridge(capabilities, CHANNEL_MAP).prepare(envelope)


@dataclass
class FakeRegisterIO:
    registers: dict[int, int] = field(default_factory=dict)
    writes: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        values = {
            "identity": 0x50514452,
            "protocol_version": 0x00010000,
            "instruction_width": 128,
            "max_instructions": 16,
            "channel_count": 8,
            "count_width": 2,
            "status": 0x2,
            "instruction_count": 0,
            "device_tick": 11,
            "acquisition_count": 3,
            "dropped_events": 1,
            "result_flags": 1,
            "acquisition_start_tick": 7,
            "acquisition_end_tick": 11,
            "acquisition_channel": 4,
            "error_code": 0,
        }
        self.registers.update(
            {BOARD_REGISTER_MAP[name]: value for name, value in values.items()}
        )
        physical = {
            "physical_protocol_version": 0x00010000,
            "fpga_clock_hz": 125_000_000,
            "output_rise_tick": 7,
            "output_fall_tick": 11,
            "input_rise_tick": 7,
            "input_high_cycles": 4,
            "loopback_flags": 0x7,
        }
        self.registers.update(
            {PHYSICAL_REGISTER_MAP[name]: value for name, value in physical.items()}
        )

    def read32(self, offset: int) -> int:
        return self.registers.get(offset, 0)

    def write32(self, offset: int, value: int) -> None:
        self.writes.append((offset, value))
        self.registers[offset] = value
        if offset != BOARD_REGISTER_MAP["control"]:
            return
        if value & 0x1:
            self.registers[BOARD_REGISTER_MAP["status"]] = 0x2
            self.registers[BOARD_REGISTER_MAP["instruction_count"]] = 0
        if value & 0x2:
            count_address = BOARD_REGISTER_MAP["instruction_count"]
            self.registers[count_address] += 1
            self.registers[BOARD_REGISTER_MAP["status"]] = 0x2
            if value & 0x4:
                self.registers[BOARD_REGISTER_MAP["status"]] |= 0x1
        if value & 0x8:
            self.registers[BOARD_REGISTER_MAP["status"]] = 0x49


def test_devmem_register_io_maps_aligned_words(tmp_path) -> None:
    backing = tmp_path / "registers.bin"
    backing.write_bytes(bytes(4096))

    with DevMemRegisterIO(
        physical_address=0,
        span=4096,
        device_path=backing,
    ) as registers:
        registers.write32(0x24, 0x12345678)
        assert registers.read32(0x24) == 0x12345678
        with pytest.raises(ControlValidationError, match="aligned"):
            registers.read32(0x25)


def test_red_pitaya_mmio_executes_and_captures_physical_evidence() -> None:
    registers = FakeRegisterIO()
    ticks = iter((100, 110, 120, 130, 140, 150, 160, 170))
    board = RedPitayaMMIOBoard(
        registers,
        timeout_seconds=1,
        poll_interval_seconds=0,
        monotonic_ns=lambda: next(ticks),
    )
    image = physical_loopback_image()

    evidence = board.execute(
        image,
        bitstream_sha256="a" * 64,
        captured_at_utc="2026-09-20T00:00:00Z",
    )

    assert evidence.fpga_clock_hz == 125_000_000
    assert evidence.tick_period_ns == 8.0
    assert evidence.output_rise_tick == 7
    assert evidence.output_fall_tick == 11
    assert evidence.input_rise_tick == 7
    assert evidence.input_high_cycles == 4
    assert evidence.board_result.recorded_events == 3
    assert evidence.board_result.overflow is True
    assert evidence.board_result.dropped_events == 1
    assert len(evidence.evidence_digest) == 64

    controls = [
        value
        for offset, value in registers.writes
        if offset == BOARD_REGISTER_MAP["control"]
    ]
    assert controls == [0x1, 0x2, 0x6, 0x8]


def test_red_pitaya_mmio_rejects_wrong_live_identity() -> None:
    registers = FakeRegisterIO()
    registers.registers[BOARD_REGISTER_MAP["identity"]] = 0
    board = RedPitayaMMIOBoard(registers)

    with pytest.raises(ControlValidationError, match="identity mismatch"):
        board.inspect_capabilities()


def test_physical_loopback_fixture_matches_versioned_control_program() -> None:
    capabilities = BoardCapabilities(max_instructions=16, count_width_bits=2)
    image = P6BoardBridge(
        capabilities,
        RED_PITAYA_PHYSICAL_LOOPBACK_CHANNEL_MAP,
    ).prepare(red_pitaya_physical_loopback_envelope())
    fixture = Path(
        "fpga/testbench/fixtures/p61_physical_loopback_program.hex"
    ).read_text(encoding="utf-8").splitlines()

    assert list(image.instruction_words) == fixture
    assert image.repetition_ticks == 12
