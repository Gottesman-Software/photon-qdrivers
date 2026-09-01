import math

import pytest

from photon_qdrivers import (
    AcquisitionKind,
    BOARD_PROGRAM_PROTOCOL,
    BOARD_REGISTER_MAP,
    BoardCapabilities,
    BoardExecutionResult,
    BoardProgramImage,
    ChannelRole,
    ControlChannel,
    ControlEnvelope,
    ControlEvent,
    ControlProgram,
    ControlValidationError,
    EventKind,
    HardwareProfile,
    NativeRuntime,
    P6BoardBridge,
    compile_control_program,
    decode_acquisition_payload,
    decode_control_request_frame,
    encode_control_request_frame,
)


CHANNEL_MAP = {
    "source/0": 0,
    "modulator/0": 1,
    "phase/0": 2,
    "sync/0": 3,
    "detector/0": 4,
}


def board_reference_envelope(*, shots: int = 1) -> ControlEnvelope:
    profile = HardwareProfile(
        profile_id="p6-board-profile",
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
    source = ControlProgram(
        program_id="p6-board-reference-program",
        channels=tuple(
            ControlChannel(name, role)
            for name, role in profile.channel_roles.items()
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
                acquisition_id="p6-counts",
                acquisition_kind=AcquisitionKind.COUNTS,
            ),
        ),
        shots=shots,
        repetition_period_ns=12,
        provenance={"test_suite": "p6-board-bridge-v1"},
    )
    return ControlEnvelope(
        job_id="p6-board-reference-job",
        program=compile_control_program(source, profile),
    )


def reference_capabilities() -> BoardCapabilities:
    return BoardCapabilities(max_instructions=16, count_width_bits=2)


def _require_native_library() -> None:
    if not any(path.exists() for path in NativeRuntime.candidate_library_paths()):
        pytest.skip("Native runtime shared library has not been built yet.")


def test_board_capability_register_map_and_digest_are_stable() -> None:
    capabilities = reference_capabilities()

    assert capabilities.register_map == BOARD_REGISTER_MAP
    assert capabilities.instruction_width_bits == 128
    assert capabilities.count_width_bits == 2
    assert len(capabilities.digest) == 64
    assert capabilities.digest == BoardCapabilities(
        max_instructions=16,
        count_width_bits=2,
    ).digest


def test_p4_frame_lowers_to_correlated_p5_board_image() -> None:
    envelope = board_reference_envelope()
    bridge = P6BoardBridge(reference_capabilities(), CHANNEL_MAP)
    frame = encode_control_request_frame(envelope)

    restored_envelope = decode_control_request_frame(frame)
    image = bridge.prepare(restored_envelope)
    restored_image = BoardProgramImage.from_frame(
        image.to_frame(), bridge.capabilities
    )

    assert restored_envelope.envelope_digest == envelope.envelope_digest
    assert restored_image.protocol == BOARD_PROGRAM_PROTOCOL
    assert restored_image.compiled_program_digest == envelope.program_digest
    assert restored_image.control_envelope_digest == envelope.envelope_digest
    assert restored_image.capability_digest == bridge.capabilities.digest
    assert len(restored_image.instruction_words) == 6
    assert len(restored_image.image_digest) == 64


def test_software_board_round_trip_preserves_p4_acquisition_evidence() -> None:
    envelope = board_reference_envelope()
    bridge = P6BoardBridge(reference_capabilities(), CHANNEL_MAP)

    restored, image, result, control_result = bridge.handle_control_frame(
        encode_control_request_frame(envelope),
        detector_event_ticks=(7, 8, 9, 10),
    )

    restored_result = BoardExecutionResult.from_frame(
        result.to_frame(), image, bridge.capabilities
    )
    acquisition_line = next(
        line
        for line in control_result.splitlines()
        if line.startswith("acquisition_payload=")
    )
    records = decode_acquisition_payload(acquisition_line.split("=", 1)[1])

    assert restored.envelope_digest == envelope.envelope_digest
    assert restored_result.recorded_events == 3
    assert restored_result.overflow is True
    assert restored_result.dropped_events == 1
    assert restored_result.final_device_tick == 11
    assert records[0].payload == {"channel_4": 3}
    assert records[0].overflow is True
    assert records[0].dropped_events == 1
    assert records[0].metadata["board_image_digest"] == image.image_digest
    assert control_result.startswith("PQDR_CONTROL_RESULT_V1\n")


def test_p6_board_execution_rejects_multi_shot_programs() -> None:
    bridge = P6BoardBridge(reference_capabilities(), CHANNEL_MAP)

    with pytest.raises(ControlValidationError, match="exactly one shot"):
        bridge.prepare(board_reference_envelope(shots=2))


def test_p6_rejects_tampered_p4_and_board_frames() -> None:
    envelope = board_reference_envelope()
    bridge = P6BoardBridge(reference_capabilities(), CHANNEL_MAP)
    frame = encode_control_request_frame(envelope)

    with pytest.raises(ControlValidationError, match="program_digest"):
        decode_control_request_frame(
            frame.replace(
                f"program_digest={envelope.program_digest}",
                "program_digest=" + "0" * 64,
            )
        )

    image = bridge.prepare(envelope)
    with pytest.raises(ControlValidationError, match="image SHA-256 mismatch"):
        BoardProgramImage.from_frame(
            image.to_frame().replace("instruction=1100", "instruction=1101", 1),
            bridge.capabilities,
        )


def test_native_red_pitaya_mailbox_round_trips_through_p6_bridge(
    tmp_path,
) -> None:
    _require_native_library()
    command_path = tmp_path / "p6-red-pitaya.commands"
    result_path = tmp_path / "p6-red-pitaya.results"
    envelope = board_reference_envelope()
    bridge = P6BoardBridge(reference_capabilities(), CHANNEL_MAP)

    with NativeRuntime(
        transport="red_pitaya",
        command_path=command_path,
        result_path=result_path,
    ) as runtime:
        runtime.submit_control(envelope)
        command_frame = command_path.read_text(encoding="utf-8")
        restored, image, board_result, control_result = bridge.handle_control_frame(
            command_frame,
            detector_event_ticks=(7, 8, 9, 10),
        )
        result_path.write_text(control_result, encoding="utf-8")
        native_result = runtime.read_control_result(envelope.job_id)

    assert restored.envelope_digest == envelope.envelope_digest
    assert image.control_envelope_digest == envelope.envelope_digest
    assert board_result.recorded_events == 3
    assert native_result["status"] == "completed"
    assert native_result["acquisition_count"] == 1
    assert native_result["overflowed_acquisitions"] == 1
    assert native_result["dropped_events"] == 1
    assert native_result["acquisitions"][0]["payload"] == {"channel_4": 3}
    assert (
        native_result["acquisitions"][0]["metadata"]["board_image_digest"]
        == image.image_digest
    )
