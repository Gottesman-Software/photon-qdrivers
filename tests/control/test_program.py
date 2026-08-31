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
    SweepTargetKind,
)


def valid_program() -> ControlProgram:
    return ControlProgram(
        program_id="control-program-001",
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
                start_ns=0.0,
                duration_ns=8.0,
                parameters={"amplitude": 0.8},
            ),
            ControlEvent(
                "modulator-pulse",
                EventKind.MODULATOR_PULSE,
                "modulator/0",
                start_ns=12.0,
                duration_ns=8.0,
                parameters={"amplitude": 0.5},
            ),
            ControlEvent(
                "phase-update",
                EventKind.PHASE_UPDATE,
                "phase/0",
                start_ns=12.0,
                parameters={"phase": 0.25},
            ),
            ControlEvent(
                "sync",
                EventKind.SYNC,
                "sync/0",
                start_ns=20.0,
            ),
            ControlEvent(
                "detector-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=24.0,
                duration_ns=16.0,
                acquisition_id="acq-0",
                acquisition_kind=AcquisitionKind.TIME_TAGS,
            ),
        ),
        sweeps=(
            ControlSweep(
                sweep_id="amplitude-sweep",
                target_kind=SweepTargetKind.EVENT,
                target_id="modulator-pulse",
                parameter="amplitude",
                values=(0.2, 0.4, 0.6),
            ),
        ),
        shots=100,
        repetition_period_ns=100.0,
        provenance={
            "circuit_schema": "photon-qdrivers.ir.v1",
            "calibration_digest": "calibration-sha256",
        },
    )


def test_control_program_round_trip() -> None:
    program = valid_program()

    restored = ControlProgram.from_mapping(program.to_dict())

    assert restored == program
    assert restored.events[-1].acquisition_id == "acq-0"
    assert restored.sweeps[0].values == (0.2, 0.4, 0.6)


def test_control_program_rejects_unknown_channels() -> None:
    with pytest.raises(ControlValidationError, match="unknown channel"):
        ControlProgram(
            channels=(ControlChannel("source/0", ChannelRole.SOURCE),),
            events=(
                ControlEvent(
                    "pulse",
                    EventKind.SOURCE_TRIGGER,
                    "missing",
                    start_ns=0,
                    duration_ns=4,
                ),
            ),
        )


def test_control_program_rejects_role_mismatches() -> None:
    with pytest.raises(ControlValidationError, match="requires a 'detector' channel"):
        ControlProgram(
            channels=(ControlChannel("source/0", ChannelRole.SOURCE),),
            events=(
                ControlEvent(
                    "acquire",
                    EventKind.ACQUIRE,
                    "source/0",
                    start_ns=0,
                    duration_ns=4,
                    acquisition_id="acq",
                    acquisition_kind=AcquisitionKind.COUNTS,
                ),
            ),
        )


def test_control_program_rejects_overlapping_events() -> None:
    with pytest.raises(ControlValidationError, match="overlap"):
        ControlProgram(
            channels=(ControlChannel("source/0", ChannelRole.SOURCE),),
            events=(
                ControlEvent(
                    "pulse-0",
                    EventKind.SOURCE_TRIGGER,
                    "source/0",
                    start_ns=0,
                    duration_ns=8,
                ),
                ControlEvent(
                    "pulse-1",
                    EventKind.SOURCE_TRIGGER,
                    "source/0",
                    start_ns=4,
                    duration_ns=8,
                ),
            ),
        )


def test_control_program_rejects_unknown_sweep_targets() -> None:
    with pytest.raises(ControlValidationError, match="unknown event"):
        ControlProgram(
            channels=(ControlChannel("source/0", ChannelRole.SOURCE),),
            events=(
                ControlEvent(
                    "pulse",
                    EventKind.SOURCE_TRIGGER,
                    "source/0",
                    start_ns=0,
                    duration_ns=8,
                ),
            ),
            sweeps=(
                ControlSweep(
                    "sweep",
                    SweepTargetKind.EVENT,
                    "missing",
                    "amplitude",
                    (0.1, 0.2),
                ),
            ),
        )


def test_control_program_rejects_untyped_events() -> None:
    with pytest.raises(ControlValidationError, match="ControlEvent objects"):
        ControlProgram(
            channels=(ControlChannel("source/0", ChannelRole.SOURCE),),
            events=({"event_id": "pulse"},),
        )
