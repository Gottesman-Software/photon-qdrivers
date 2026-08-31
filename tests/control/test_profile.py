import pytest

from photon_qdrivers import (
    ChannelRole,
    ControlChannel,
    ControlEvent,
    ControlProgram,
    ControlValidationError,
    EventKind,
    HardwareProfile,
    QuantizationRule,
)


def test_hardware_profile_round_trip_has_stable_digest() -> None:
    profile = HardwareProfile(
        profile_id="generic-photonic-fpga",
        clock_period_ns=4.0,
        channel_roles={
            "source/0": ChannelRole.SOURCE,
            "detector/0": ChannelRole.DETECTOR,
        },
        quantization_rule=QuantizationRule.CEIL,
        metadata={"board": "simulation"},
    )

    restored = HardwareProfile.from_mapping(profile.to_dict())

    assert restored == profile
    assert restored.digest == profile.digest
    assert len(profile.digest) == 64


def test_profile_rejects_program_channel_role_drift() -> None:
    program = ControlProgram(
        channels=(ControlChannel("source/0", ChannelRole.SOURCE),),
        events=(
            ControlEvent(
                "pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=0,
                duration_ns=4,
            ),
        ),
    )
    profile = HardwareProfile(
        profile_id="bad-routing",
        clock_period_ns=4,
        channel_roles={"source/0": ChannelRole.MODULATOR},
    )

    with pytest.raises(ControlValidationError, match="in the program"):
        profile.validate_program(program)


def test_profile_rejects_unsupported_event_kind() -> None:
    program = ControlProgram(
        channels=(ControlChannel("source/0", ChannelRole.SOURCE),),
        events=(
            ControlEvent(
                "pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=0,
                duration_ns=4,
            ),
        ),
    )
    profile = HardwareProfile(
        profile_id="acquisition-only",
        clock_period_ns=4,
        channel_roles={"source/0": ChannelRole.SOURCE},
        supported_event_kinds=(EventKind.ACQUIRE,),
    )

    with pytest.raises(ControlValidationError, match="does not support event"):
        profile.validate_program(program)


def test_profile_digest_rejects_non_serializable_metadata() -> None:
    profile = HardwareProfile(
        profile_id="bad-metadata",
        clock_period_ns=4,
        channel_roles={"source/0": ChannelRole.SOURCE},
        metadata={"not_json": {1, 2}},
    )

    with pytest.raises(ControlValidationError, match="JSON-serializable"):
        _ = profile.digest
