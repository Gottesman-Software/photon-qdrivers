import json
from math import pi

import pytest

from photon_qdrivers import (
    AcquisitionKind,
    AnalyticLoopbackConfig,
    AnalyticLoopbackPlant,
    ChannelRole,
    ControlChannel,
    ControlEvent,
    ControlProgram,
    ControlSweep,
    ControlValidationError,
    DetectorResponse,
    EventKind,
    HardwareProfile,
    LoopbackPath,
    SweepTargetKind,
    VirtualPhotonicController,
    compile_control_program,
)


def hardware(*, counter_bits: int = 32, include_second_detector: bool = False):
    roles = {
        "source/0": ChannelRole.SOURCE,
        "detector/0": ChannelRole.DETECTOR,
    }
    if include_second_detector:
        roles["detector/1"] = ChannelRole.DETECTOR
    return HardwareProfile(
        profile_id="analytic-loopback-profile",
        clock_period_ns=1.0,
        channel_roles=roles,
        counter_bits=counter_bits,
    )


def compiled_program(
    profile,
    *,
    kind: AcquisitionKind = AcquisitionKind.COUNTS,
    shots: int = 1,
    source_parameters=None,
    acquisition_parameters=None,
    sweeps=(),
    acquisition_start: int = 0,
    acquisition_duration: int = 8,
    repetition_period: int = 10,
):
    channels = [
        ControlChannel("source/0", ChannelRole.SOURCE),
        ControlChannel("detector/0", ChannelRole.DETECTOR),
    ]
    if "detector/1" in profile.channel_roles:
        channels.append(ControlChannel("detector/1", ChannelRole.DETECTOR))
    source = ControlProgram(
        program_id="analytic-loopback-program",
        channels=tuple(channels),
        events=(
            ControlEvent(
                "source-pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=0,
                duration_ns=1,
                parameters=source_parameters or {"amplitude": 1.0},
            ),
            ControlEvent(
                "detector-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=acquisition_start,
                duration_ns=acquisition_duration,
                parameters=acquisition_parameters or {},
                acquisition_id="acq-0",
                acquisition_kind=kind,
            ),
        ),
        sweeps=tuple(sweeps),
        shots=shots,
        repetition_period_ns=repetition_period,
    )
    return compile_control_program(source, profile)


def config(
    *,
    paths=None,
    detectors=None,
    seed: int = 17,
    coincidence_window_ticks: int = 0,
):
    return AnalyticLoopbackConfig(
        paths=tuple(
            paths
            or (
                LoopbackPath(
                    "path-0", "source/0", "detector/0", delay_ticks=3
                ),
            )
        ),
        detectors=tuple(
            detectors or (DetectorResponse("detector/0"),)
        ),
        seed=seed,
        coincidence_window_ticks=coincidence_window_ticks,
    )


def execute(program, profile, plant_config):
    controller = VirtualPhotonicController(
        profile, AnalyticLoopbackPlant(profile, plant_config)
    )
    controller.initialize()
    return controller.execute(program, job_id="analytic-loopback-job")


def test_loopback_config_round_trips_with_stable_digest() -> None:
    original = config()

    restored = AnalyticLoopbackConfig.from_mapping(
        json.loads(original.canonical_json)
    )

    assert restored.to_dict() == original.to_dict()
    assert restored.digest == original.digest
    assert len(original.digest) == 64


def test_amplitude_sweep_changes_deterministic_counts() -> None:
    profile = hardware()
    sweep = ControlSweep(
        "source-amplitude",
        SweepTargetKind.EVENT,
        "source-pulse",
        "amplitude",
        (0.0, 1.0),
    )
    program = compiled_program(profile, shots=2, sweeps=(sweep,))

    first = execute(program, profile, config())
    second = execute(program, profile, config())
    record = first.acquisitions[0]

    assert record.payload == {"detector/0": 2}
    assert record.metadata["execution_iterations"] == 4
    assert record.metadata["hardware_validated"] is False
    assert record.metadata["model_scope"] == "analytic_loopback"
    assert record.end_tick == 38
    assert first.to_dict() == second.to_dict()
    assert first.trace.digest == second.trace.digest


def test_seeded_sampler_is_repeatable_at_nontrivial_probability() -> None:
    profile = hardware()
    program = compiled_program(
        profile,
        shots=64,
        source_parameters={"amplitude": 0.5},
    )

    first = execute(program, profile, config(seed=2026)).acquisitions[0]
    second = execute(program, profile, config(seed=2026)).acquisitions[0]

    assert first.to_dict() == second.to_dict()
    assert 0 < first.payload["detector/0"] < 64
    assert first.metadata["sampler"] == "sha256_bernoulli_v1"


def test_time_tags_use_global_logical_device_ticks() -> None:
    profile = hardware()
    program = compiled_program(
        profile, kind=AcquisitionKind.TIME_TAGS, shots=3
    )

    record = execute(program, profile, config()).acquisitions[0]

    assert record.payload == (3, 13, 23)
    assert record.shape == (3,)
    assert record.unit == "ticks"
    assert record.start_tick == 0
    assert record.end_tick == 28


@pytest.mark.parametrize(
    ("kind", "expected_payload", "expected_shape"),
    (
        (
            AcquisitionKind.WAVEFORM,
            (
                (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0),
                (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0),
            ),
            (2, 8),
        ),
        (AcquisitionKind.THRESHOLDED_EVENTS, (1, 1), (2,)),
    ),
)
def test_waveform_and_threshold_records_follow_repeated_windows(
    kind, expected_payload, expected_shape
) -> None:
    profile = hardware()
    program = compiled_program(profile, kind=kind, shots=2)

    record = execute(program, profile, config()).acquisitions[0]

    assert record.payload == expected_payload
    assert record.shape == expected_shape


def test_coincidences_use_configured_detector_pair_and_window() -> None:
    profile = hardware(include_second_detector=True)
    program = compiled_program(
        profile,
        kind=AcquisitionKind.COINCIDENCES,
        shots=3,
        acquisition_parameters={
            "detectors": ["detector/0", "detector/1"],
            "coincidence_window_ticks": 1,
        },
    )
    plant_config = config(
        paths=(
            LoopbackPath("path-0", "source/0", "detector/0", delay_ticks=3),
            LoopbackPath("path-1", "source/0", "detector/1", delay_ticks=4),
        ),
        detectors=(
            DetectorResponse("detector/0"),
            DetectorResponse("detector/1"),
        ),
    )

    record = execute(program, profile, plant_config).acquisitions[0]

    assert record.payload == {"detector/0&detector/1": 3}
    assert record.metadata["coincidence_window_ticks"] == 1


def test_time_tag_buffer_overflow_is_explicit() -> None:
    profile = hardware()
    program = compiled_program(
        profile, kind=AcquisitionKind.TIME_TAGS, shots=5
    )
    plant_config = config(
        detectors=(DetectorResponse("detector/0", buffer_capacity=2),)
    )

    record = execute(program, profile, plant_config).acquisitions[0]

    assert record.payload == (3, 13)
    assert record.overflow is True
    assert record.dropped_events == 3
    assert record.metadata["unsaturated_event_count"] == 5


def test_count_register_saturates_at_profile_numeric_width() -> None:
    profile = hardware(counter_bits=2)
    program = compiled_program(profile, shots=5)

    record = execute(program, profile, config()).acquisitions[0]

    assert record.payload == {"detector/0": 3}
    assert record.overflow is True
    assert record.dropped_events == 2
    assert record.metadata["unsaturated_counts"] == {"detector/0": 5}


def test_equal_delay_paths_exhibit_constructive_and_destructive_interference() -> None:
    profile = hardware()
    program = compiled_program(profile, shots=4)
    detector = (DetectorResponse("detector/0"),)
    constructive = config(
        paths=(
            LoopbackPath(
                "arm-a", "source/0", "detector/0", 3, transmission=0.25
            ),
            LoopbackPath(
                "arm-b", "source/0", "detector/0", 3, transmission=0.25
            ),
        ),
        detectors=detector,
    )
    destructive = config(
        paths=(
            LoopbackPath(
                "arm-a", "source/0", "detector/0", 3, transmission=0.25
            ),
            LoopbackPath(
                "arm-b",
                "source/0",
                "detector/0",
                3,
                transmission=0.25,
                phase_offset_rad=pi,
            ),
        ),
        detectors=detector,
    )

    constructive_record = execute(program, profile, constructive).acquisitions[0]
    destructive_record = execute(program, profile, destructive).acquisitions[0]

    assert constructive_record.payload == {"detector/0": 4}
    assert destructive_record.payload == {"detector/0": 0}


def test_phase_update_event_controls_interference() -> None:
    profile = HardwareProfile(
        profile_id="phase-control-profile",
        clock_period_ns=1.0,
        channel_roles={
            "source/0": ChannelRole.SOURCE,
            "phase/0": ChannelRole.PHASE,
            "detector/0": ChannelRole.DETECTOR,
        },
    )
    source = ControlProgram(
        program_id="phase-control-program",
        channels=(
            ControlChannel("source/0", ChannelRole.SOURCE),
            ControlChannel("phase/0", ChannelRole.PHASE),
            ControlChannel("detector/0", ChannelRole.DETECTOR),
        ),
        events=(
            ControlEvent(
                "phase-arm-b",
                EventKind.PHASE_UPDATE,
                "phase/0",
                start_ns=0,
                parameters={"path_id": "arm-b", "phase": pi},
            ),
            ControlEvent(
                "source-pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=0,
                duration_ns=1,
            ),
            ControlEvent(
                "detector-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=0,
                duration_ns=8,
                acquisition_id="acq-0",
                acquisition_kind=AcquisitionKind.COUNTS,
            ),
        ),
        shots=4,
        repetition_period_ns=10,
    )
    program = compile_control_program(source, profile)
    plant_config = config(
        paths=(
            LoopbackPath(
                "arm-a", "source/0", "detector/0", 3, transmission=0.25
            ),
            LoopbackPath(
                "arm-b", "source/0", "detector/0", 3, transmission=0.25
            ),
        ),
    )

    record = execute(program, profile, plant_config).acquisitions[0]

    assert record.payload == {"detector/0": 0}


def test_modulator_event_controls_path_transmission() -> None:
    profile = HardwareProfile(
        profile_id="modulator-control-profile",
        clock_period_ns=1.0,
        channel_roles={
            "source/0": ChannelRole.SOURCE,
            "modulator/0": ChannelRole.MODULATOR,
            "detector/0": ChannelRole.DETECTOR,
        },
    )
    source = ControlProgram(
        program_id="modulator-control-program",
        channels=(
            ControlChannel("source/0", ChannelRole.SOURCE),
            ControlChannel("modulator/0", ChannelRole.MODULATOR),
            ControlChannel("detector/0", ChannelRole.DETECTOR),
        ),
        events=(
            ControlEvent(
                "block-path",
                EventKind.MODULATOR_PULSE,
                "modulator/0",
                start_ns=0,
                duration_ns=1,
                parameters={"path_id": "path-0", "amplitude": 0.0},
            ),
            ControlEvent(
                "source-pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=0,
                duration_ns=1,
            ),
            ControlEvent(
                "detector-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=0,
                duration_ns=8,
                acquisition_id="acq-0",
                acquisition_kind=AcquisitionKind.COUNTS,
            ),
        ),
        shots=4,
        repetition_period_ns=10,
    )
    program = compile_control_program(source, profile)

    record = execute(program, profile, config()).acquisitions[0]

    assert record.payload == {"detector/0": 0}


def test_dark_count_and_dead_time_are_recorded_separately_from_overflow() -> None:
    profile = hardware()
    program = compiled_program(
        profile,
        shots=3,
        acquisition_duration=1,
        repetition_period=2,
    )
    plant_config = config(
        paths=(LoopbackPath("path-0", "source/0", "detector/0", 0),),
        detectors=(
            DetectorResponse(
                "detector/0",
                dark_count_probability=1.0,
                dead_time_ticks=1,
            ),
        ),
    )

    record = execute(program, profile, plant_config).acquisitions[0]

    assert record.payload == {"detector/0": 3}
    assert record.metadata["dead_time_rejections"] == 3
    assert record.dropped_events == 0
    assert record.overflow is False


def test_detector_dead_time_persists_across_repetition_boundaries() -> None:
    profile = hardware()
    program = compiled_program(
        profile,
        shots=3,
        acquisition_duration=1,
        repetition_period=2,
    )
    plant_config = config(
        paths=(LoopbackPath("path-0", "source/0", "detector/0", 0),),
        detectors=(DetectorResponse("detector/0", dead_time_ticks=3),),
    )

    record = execute(program, profile, plant_config).acquisitions[0]

    assert record.payload == {"detector/0": 2}
    assert record.metadata["dead_time_rejections"] == 1


def test_coherent_paths_with_different_delays_are_rejected() -> None:
    with pytest.raises(ControlValidationError, match="same integer delay"):
        config(
            paths=(
                LoopbackPath("arm-a", "source/0", "detector/0", 3),
                LoopbackPath("arm-b", "source/0", "detector/0", 4),
            )
        )
