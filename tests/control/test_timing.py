import json

import pytest

from photon_qdrivers import (
    ChannelRole,
    CompiledControlProgram,
    ControlChannel,
    ControlEvent,
    ControlProgram,
    ControlResourceError,
    ControlSweep,
    ControlValidationError,
    EventKind,
    HardwareProfile,
    QuantizationRule,
    SweepTargetKind,
    compile_control_program,
    quantize_time_ns,
)


def profile(**updates) -> HardwareProfile:
    values = {
        "profile_id": "timing-test-profile",
        "clock_period_ns": 4.0,
        "channel_roles": {"source/0": ChannelRole.SOURCE},
    }
    values.update(updates)
    return HardwareProfile(**values)


def program(*events: ControlEvent) -> ControlProgram:
    return ControlProgram(
        program_id="timing-program",
        channels=(ControlChannel("source/0", ChannelRole.SOURCE),),
        events=events,
        repetition_period_ns=40.0,
        provenance={"calibration_digest": "abc123"},
    )


def test_quantization_uses_explicit_half_up_rule() -> None:
    quantized = quantize_time_ns(6.0, profile())

    assert quantized.tick == 2
    assert quantized.quantized_ns == 8.0
    assert quantized.error_ns == 2.0


def test_compile_control_program_records_timing_and_resource_provenance() -> None:
    source = program(
        ControlEvent(
            "pulse",
            EventKind.SOURCE_TRIGGER,
            "source/0",
            start_ns=6.0,
            duration_ns=10.0,
        )
    )

    compiled = compile_control_program(source, profile())

    event = compiled.events[0]
    assert event.start_tick == 2
    assert event.duration_ticks == 3
    assert event.start_error_ns == 2.0
    assert event.duration_error_ns == 2.0
    assert compiled.resource_usage.waveform_samples == 3
    assert compiled.resource_usage.instructions == 1
    assert compiled.provenance["source"] == {"calibration_digest": "abc123"}
    assert compiled.profile_digest == profile().digest
    assert compiled.to_dict() == compile_control_program(source, profile()).to_dict()


def test_compile_rejects_overlap_created_by_quantization() -> None:
    source = program(
        ControlEvent(
            "pulse-0",
            EventKind.SOURCE_TRIGGER,
            "source/0",
            start_ns=2.1,
            duration_ns=6.0,
        ),
        ControlEvent(
            "pulse-1",
            EventKind.SOURCE_TRIGGER,
            "source/0",
            start_ns=8.2,
            duration_ns=4.0,
        ),
    )

    with pytest.raises(ControlValidationError, match="after timing quantization"):
        compile_control_program(source, profile())


def test_compile_rejects_waveform_memory_overflow() -> None:
    source = program(
        ControlEvent(
            "pulse",
            EventKind.SOURCE_TRIGGER,
            "source/0",
            start_ns=0,
            duration_ns=8,
        )
    )

    with pytest.raises(ControlResourceError, match="waveform_samples"):
        compile_control_program(source, profile(max_waveform_samples=1))


def test_floor_and_ceil_profiles_produce_different_ticks() -> None:
    floor_time = quantize_time_ns(
        5.0, profile(quantization_rule=QuantizationRule.FLOOR)
    )
    ceil_time = quantize_time_ns(
        5.0, profile(quantization_rule=QuantizationRule.CEIL)
    )

    assert floor_time.tick == 1
    assert ceil_time.tick == 2


def test_compiled_program_round_trips_through_canonical_json() -> None:
    source = program(
        ControlEvent(
            "pulse",
            EventKind.SOURCE_TRIGGER,
            "source/0",
            start_ns=6.0,
            duration_ns=10.0,
        )
    )
    compiled = compile_control_program(source, profile())

    restored = CompiledControlProgram.from_mapping(json.loads(compiled.canonical_json))

    assert restored.to_dict() == compiled.to_dict()
    assert restored.canonical_json == compiled.canonical_json
    assert restored.digest == compiled.digest
    assert len(compiled.digest) == 64


def test_timing_sweep_is_preserved_as_executable_ticks() -> None:
    source = ControlProgram(
        program_id="timing-sweep-program",
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
                "duration-sweep",
                SweepTargetKind.EVENT,
                "pulse",
                "duration_ns",
                (6.0, 10.0),
            ),
        ),
        shots=3,
        repetition_period_ns=40,
    )

    compiled = compile_control_program(source, profile())
    sweep = compiled.sweeps[0]

    assert sweep.source_parameter == "duration_ns"
    assert sweep.compiled_parameter == "duration_ticks"
    assert sweep.requested_values == (6.0, 10.0)
    assert sweep.compiled_values == (2, 3)
    assert sweep.quantization_errors_ns == (2.0, 2.0)
    assert compiled.resource_usage.registers == 1
    assert compiled.resource_usage.sweep_points == 2
    assert compiled.execution_iterations == 6
    assert compiled.total_device_ticks == 60


def test_compile_rejects_duration_sweep_that_quantizes_to_zero() -> None:
    source = ControlProgram(
        program_id="invalid-duration-sweep",
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
                "duration-sweep",
                SweepTargetKind.EVENT,
                "pulse",
                "duration_ns",
                (1.0,),
            ),
        ),
        repetition_period_ns=40,
    )

    with pytest.raises(ControlValidationError, match="quantizes to zero"):
        compile_control_program(source, profile())


def test_compile_rejects_timing_sweep_beyond_repetition_period() -> None:
    source = ControlProgram(
        program_id="out-of-bounds-sweep",
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
                "start-sweep",
                SweepTargetKind.EVENT,
                "pulse",
                "start_ns",
                (0.0, 36.0),
            ),
        ),
        repetition_period_ns=40,
    )

    with pytest.raises(ControlValidationError, match="beyond the repetition period"):
        compile_control_program(source, profile())
