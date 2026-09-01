import math
from pathlib import Path

import pytest

from photon_qdrivers import (
    AcquisitionKind,
    ChannelRole,
    ControlChannel,
    ControlEvent,
    ControlProgram,
    ControlSweep,
    ControlValidationError,
    EventKind,
    HardwareProfile,
    RTLAcquisitionCode,
    RTLInstruction,
    RTLOpcode,
    RTLProgram,
    SweepTargetKind,
    compile_control_program,
)


CHANNEL_MAP = {
    "source/0": 0,
    "modulator/0": 1,
    "phase/0": 2,
    "sync/0": 3,
    "detector/0": 4,
}
RTL_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fpga"
    / "testbench"
    / "fixtures"
    / "p5_control_program.hex"
)


def rtl_reference_source(
    *,
    sweeps=(),
    acquisition_kind=AcquisitionKind.COUNTS,
) -> ControlProgram:
    return ControlProgram(
        program_id="p5-rtl-reference-program",
        channels=(
            ControlChannel("source/0", ChannelRole.SOURCE),
            ControlChannel("modulator/0", ChannelRole.MODULATOR),
            ControlChannel("phase/0", ChannelRole.PHASE),
            ControlChannel("sync/0", ChannelRole.SYNC),
            ControlChannel("detector/0", ChannelRole.DETECTOR),
        ),
        events=(
            ControlEvent(
                "source-trigger",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=1,
                duration_ns=2,
                parameters={"amplitude": 1.0},
            ),
            ControlEvent(
                "modulator-pulse",
                EventKind.MODULATOR_PULSE,
                "modulator/0",
                start_ns=2,
                duration_ns=3,
                parameters={"amplitude": 0.5},
            ),
            ControlEvent(
                "phase-update",
                EventKind.PHASE_UPDATE,
                "phase/0",
                start_ns=2,
                parameters={"phase": math.pi},
            ),
            ControlEvent("sync-event", EventKind.SYNC, "sync/0", start_ns=4),
            ControlEvent(
                "delay-event",
                EventKind.DELAY,
                "sync/0",
                start_ns=5,
                duration_ns=1,
            ),
            ControlEvent(
                "detector-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=7,
                duration_ns=4,
                acquisition_id="acq-0",
                acquisition_kind=acquisition_kind,
            ),
        ),
        sweeps=sweeps,
        shots=4,
        repetition_period_ns=12,
        provenance={"paper_suite": "qdriverlab-rtl-reference-v1"},
    )


def rtl_reference_compiled(
    *,
    sweeps=(),
    acquisition_kind=AcquisitionKind.COUNTS,
):
    profile = HardwareProfile(
        profile_id="p5-rtl-profile",
        clock_period_ns=1.0,
        channel_roles={
            "source/0": ChannelRole.SOURCE,
            "modulator/0": ChannelRole.MODULATOR,
            "phase/0": ChannelRole.PHASE,
            "sync/0": ChannelRole.SYNC,
            "detector/0": ChannelRole.DETECTOR,
        },
        counter_bits=2,
    )
    return compile_control_program(
        rtl_reference_source(
            sweeps=sweeps,
            acquisition_kind=acquisition_kind,
        ),
        profile,
    )


def test_rtl_instruction_packing_round_trip() -> None:
    instruction = RTLInstruction(
        opcode=RTLOpcode.ACQUIRE,
        channel_index=4,
        start_tick=7,
        duration_ticks=4,
        acquisition_code=RTLAcquisitionCode.COUNTS,
    )

    restored = RTLInstruction.from_word(instruction.word)

    assert restored == instruction
    assert len(instruction.hex_word) == 32
    assert instruction.hex_word == "16040000000700000004000000000300"


def test_compiled_program_lowers_to_deterministic_rtl_schedule() -> None:
    compiled = rtl_reference_compiled()
    program = RTLProgram.from_compiled(compiled, CHANNEL_MAP)

    assert [item.opcode for item in program.instructions] == [
        RTLOpcode.SOURCE_TRIGGER,
        RTLOpcode.MODULATOR_PULSE,
        RTLOpcode.PHASE_UPDATE,
        RTLOpcode.SYNC,
        RTLOpcode.DELAY,
        RTLOpcode.ACQUIRE,
    ]
    assert [item.start_tick for item in program.instructions] == [1, 2, 2, 4, 5, 7]
    assert program.instructions[0].argument_word == 0xFFFFFFFF
    assert program.instructions[1].argument_word == 0x80000000
    assert program.instructions[2].argument_word == 0x80000000
    assert program.instructions[-1].acquisition_code is RTLAcquisitionCode.COUNTS
    assert program.hex_lines.endswith("\n")
    assert program.hex_lines == RTL_FIXTURE.read_text(encoding="utf-8")
    assert len(program.digest) == 64


def test_rtl_lowering_requires_complete_explicit_channel_map() -> None:
    with pytest.raises(ControlValidationError, match="missing compiled channels"):
        RTLProgram.from_compiled(
            rtl_reference_compiled(), {"source/0": 0, "detector/0": 1}
        )


def test_rtl_v1_rejects_controller_sweeps() -> None:
    sweep = ControlSweep(
        "amplitude-sweep",
        SweepTargetKind.EVENT,
        "modulator-pulse",
        "amplitude",
        (0.25, 0.75),
    )

    with pytest.raises(ControlValidationError, match="does not encode.*sweeps"):
        RTLProgram.from_compiled(
            rtl_reference_compiled(sweeps=(sweep,)), CHANNEL_MAP
        )


def test_rtl_v1_rejects_non_count_acquisitions() -> None:
    with pytest.raises(ControlValidationError, match="count acquisitions only"):
        RTLProgram.from_compiled(
            rtl_reference_compiled(acquisition_kind=AcquisitionKind.TIME_TAGS),
            CHANNEL_MAP,
        )


def test_rtl_program_rejects_overlapping_acquisition_windows() -> None:
    compiled = rtl_reference_compiled()
    first = RTLInstruction(
        RTLOpcode.ACQUIRE,
        4,
        2,
        5,
        acquisition_code=RTLAcquisitionCode.COUNTS,
    )
    second = RTLInstruction(
        RTLOpcode.ACQUIRE,
        5,
        4,
        2,
        acquisition_code=RTLAcquisitionCode.COUNTS,
    )

    with pytest.raises(ControlValidationError, match="one active acquisition"):
        RTLProgram(
            program_id=compiled.program_id,
            profile_id=compiled.profile_id,
            profile_digest=compiled.profile_digest,
            compiled_program_digest=compiled.digest,
            repetition_ticks=compiled.repetition_ticks,
            channel_map={"detector/0": 4, "detector/1": 5},
            instructions=(first, second),
        )
