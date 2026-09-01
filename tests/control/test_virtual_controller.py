import pytest

from photon_qdrivers import (
    AcquisitionKind,
    BackendExecutionError,
    ChannelRole,
    ControlChannel,
    ControlEvent,
    ControlProgram,
    ControlSweep,
    ControlValidationError,
    EventKind,
    ExecutionTrace,
    HardwareProfile,
    JobStatus,
    SweepTargetKind,
    TraceEventKind,
    VirtualControllerState,
    VirtualExecutionResult,
    VirtualPhotonicController,
    compile_control_program,
)


def profile(*, clock_period_ns: float = 4.0) -> HardwareProfile:
    return HardwareProfile(
        profile_id="virtual-lab-profile",
        clock_period_ns=clock_period_ns,
        channel_roles={
            "source/0": ChannelRole.SOURCE,
            "detector/0": ChannelRole.DETECTOR,
        },
    )


def compiled_program(acquisition_kind: AcquisitionKind = AcquisitionKind.COUNTS):
    source = ControlProgram(
        program_id="virtual-lab-program",
        channels=(
            ControlChannel("source/0", ChannelRole.SOURCE),
            ControlChannel("detector/0", ChannelRole.DETECTOR),
        ),
        events=(
            ControlEvent(
                "pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=0,
                duration_ns=8,
                parameters={"amplitude": 0.5},
            ),
            ControlEvent(
                "detector-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=8,
                duration_ns=12,
                acquisition_id="acq-0",
                acquisition_kind=acquisition_kind,
            ),
        ),
        sweeps=(
            ControlSweep(
                "amplitude-sweep",
                SweepTargetKind.EVENT,
                "pulse",
                "amplitude",
                (0.25, 0.5),
            ),
        ),
        shots=2,
        repetition_period_ns=40,
        provenance={"experiment": "virtual-controller-test"},
    )
    hardware = profile()
    return compile_control_program(source, hardware), hardware


def test_controller_requires_initialization_and_has_terminal_shutdown() -> None:
    program, hardware = compiled_program()
    controller = VirtualPhotonicController(hardware)

    assert controller.state is VirtualControllerState.NEW
    with pytest.raises(BackendExecutionError, match="initialized"):
        controller.execute(program)

    controller.initialize()
    assert controller.state is VirtualControllerState.READY
    controller.shutdown()
    assert controller.state is VirtualControllerState.SHUTDOWN
    with pytest.raises(BackendExecutionError, match="cannot be reinitialized"):
        controller.initialize()


def test_execution_is_deterministic_in_device_ticks() -> None:
    program, hardware = compiled_program()
    controller = VirtualPhotonicController(hardware)
    controller.initialize()

    first = controller.execute(program, job_id="deterministic-job")
    second = controller.execute(program, job_id="deterministic-job")

    assert first.status is JobStatus.COMPLETED
    assert first.final_tick == 40
    assert first.trace.events[-1].kind is TraceEventKind.PROGRAM_COMPLETED
    assert first.trace.events[-1].tick == 40
    assert [event.tick for event in first.trace.events] == sorted(
        event.tick for event in first.trace.events
    )
    assert first.trace.to_dict() == second.trace.to_dict()
    assert first.trace.digest == second.trace.digest
    assert first.trace.metadata["wall_clock_timing"] is False
    assert first.trace.metadata["execution_iterations"] == 4
    assert controller.state is VirtualControllerState.READY


def test_zero_signal_acquisition_is_typed_and_explicitly_non_physical() -> None:
    program, hardware = compiled_program()
    controller = VirtualPhotonicController(hardware)
    controller.initialize()

    result = controller.execute(program, job_id="fixture-job")
    record = result.acquisitions[0]

    assert record.kind is AcquisitionKind.COUNTS
    assert record.payload == {"detected": 0}
    assert record.start_tick == 2
    assert record.end_tick == 5
    assert record.metadata["fixture"] == "zero_signal"
    assert record.metadata["physical_model"] is False
    assert record.metadata["execution_iterations"] == 4


def test_trace_and_result_round_trip_through_mappings() -> None:
    program, hardware = compiled_program()
    controller = VirtualPhotonicController(hardware)
    controller.initialize()
    result = controller.execute(program, job_id="round-trip-job")

    restored_trace = ExecutionTrace.from_mapping(result.trace.to_dict())
    restored_result = VirtualExecutionResult.from_mapping(result.to_dict())

    assert restored_trace.to_dict() == result.trace.to_dict()
    assert restored_trace.digest == result.trace.digest
    assert restored_result.to_dict() == result.to_dict()


def test_controller_rejects_program_compiled_for_different_profile_digest() -> None:
    program, _ = compiled_program()
    controller = VirtualPhotonicController(profile(clock_period_ns=2.0))
    controller.initialize()

    with pytest.raises(ControlValidationError, match="does not match"):
        controller.execute(program)


@pytest.mark.parametrize("kind", tuple(AcquisitionKind))
def test_zero_signal_provider_supports_all_acquisition_kinds(kind) -> None:
    program, hardware = compiled_program(kind)
    controller = VirtualPhotonicController(hardware)
    controller.initialize()

    record = controller.execute(program, job_id=f"kind-{kind.value}").acquisitions[0]

    assert record.kind is kind
    assert record.metadata["physical_model"] is False
