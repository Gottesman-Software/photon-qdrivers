import hashlib
import json
from pathlib import Path

import pytest

from photon_qdrivers import (
    AcquisitionKind,
    AcquisitionRecord,
    BackendExecutionError,
    ChannelRole,
    ControlChannel,
    ControlEnvelope,
    ControlEvent,
    ControlProgram,
    EventKind,
    HardwareProfile,
    NativeRuntime,
    compile_control_program,
    decode_acquisition_payload,
)


def _require_native_library() -> None:
    if not any(path.exists() for path in NativeRuntime.candidate_library_paths()):
        pytest.skip("Native runtime shared library has not been built yet.")


def _reference_counter_case(requested_events: int = 384):
    capacity = (1 << 8) - 1
    recorded_events = min(requested_events, capacity)
    dropped_events = max(0, requested_events - capacity)
    row = {
        "resource": "counter",
        "capacity": str(capacity),
        "requested_events": str(requested_events),
        "recorded_events": str(recorded_events),
        "overflow": str(dropped_events > 0).lower(),
        "dropped_events": str(dropped_events),
    }

    profile = HardwareProfile(
        profile_id="paper-counter-profile",
        clock_period_ns=1.0,
        channel_roles={
            "source/0": ChannelRole.SOURCE,
            "detector/0": ChannelRole.DETECTOR,
        },
        counter_bits=8,
    )
    program = ControlProgram(
        program_id=f"paper-counter-{requested_events}",
        channels=(
            ControlChannel("source/0", ChannelRole.SOURCE),
            ControlChannel("detector/0", ChannelRole.DETECTOR),
        ),
        events=(
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
                duration_ns=12,
                acquisition_id="acq-0",
                acquisition_kind=AcquisitionKind.COUNTS,
            ),
        ),
        shots=requested_events,
        repetition_period_ns=20,
        provenance={"paper_suite": "qdriverlab-reference-v1"},
    )
    compiled = compile_control_program(program, profile)
    acquisition = AcquisitionRecord(
        acquisition_id="acq-0",
        kind=AcquisitionKind.COUNTS,
        payload={"detector/0": int(row["recorded_events"])},
        unit="counts",
        start_tick=0,
        end_tick=requested_events * compiled.repetition_ticks,
        overflow=row["overflow"] == "true",
        dropped_events=int(row["dropped_events"]),
        metadata={
            "fixture": "native-protocol-counter-boundary",
            "capacity": int(row["capacity"]),
            "requested_events": requested_events,
        },
    )
    return compiled, acquisition, row


def test_control_envelope_hashes_and_decodes_normalized_acquisitions() -> None:
    compiled, acquisition, _ = _reference_counter_case()
    envelope = ControlEnvelope(
        job_id="paper-native-envelope",
        program=compiled,
    )
    acquisition_payload = json.dumps(
        [acquisition.to_dict()], sort_keys=True, separators=(",", ":")
    )

    assert envelope.program_digest == hashlib.sha256(
        envelope.compiled_payload.encode("utf-8")
    ).hexdigest()
    assert len(envelope.envelope_digest) == 64
    assert envelope.to_dict()["envelope_digest"] == envelope.envelope_digest
    assert "acquisition_payload" not in envelope.to_dict()
    assert decode_acquisition_payload(acquisition_payload) == (acquisition,)


def test_native_control_in_memory_reports_compiled_execution_metadata() -> None:
    _require_native_library()
    compiled, _, _ = _reference_counter_case()

    with NativeRuntime() as runtime:
        reply = runtime.run_control_program(
            compiled,
            job_id="paper-native-saturation-384",
        )

    assert reply["protocol"] == "PQDR_CONTROL_RESULT_V1"
    assert reply["status"] == "completed"
    assert reply["program_digest"] == compiled.digest
    assert len(reply["envelope_digest"]) == 64
    assert reply["profile_digest"] == compiled.profile_digest
    assert reply["total_device_ticks"] == compiled.total_device_ticks
    assert reply["event_count"] == len(compiled.events)
    assert reply["acquisition_count"] == 0
    assert reply["overflowed_acquisitions"] == 0
    assert reply["dropped_events"] == 0
    assert reply["acquisitions"] == []


def test_native_control_mailbox_uses_versioned_frames(tmp_path: Path) -> None:
    _require_native_library()
    compiled, acquisition, _ = _reference_counter_case(256)
    envelope = ControlEnvelope(
        job_id="paper-native-mailbox-256",
        program=compiled,
    )
    acquisition_payload = json.dumps(
        [acquisition.to_dict()], sort_keys=True, separators=(",", ":")
    )
    acquisition_digest = hashlib.sha256(
        acquisition_payload.encode("utf-8")
    ).hexdigest()
    command_path = tmp_path / "control.commands"
    result_path = tmp_path / "control.results"
    result_frame = "\n".join(
        [
            "PQDR_CONTROL_RESULT_V1",
            f"job_id={envelope.job_id}",
            f"program_id={compiled.program_id}",
            f"profile_id={compiled.profile_id}",
            f"profile_digest={compiled.profile_digest}",
            f"program_digest={compiled.digest}",
            f"envelope_digest={envelope.envelope_digest}",
            f"acquisition_digest={acquisition_digest}",
            "status=completed",
            f"shots={compiled.shots}",
            f"repetition_ticks={compiled.repetition_ticks}",
            f"sweep_points={compiled.resource_usage.sweep_points}",
            f"event_count={len(compiled.events)}",
            "acquisition_count=1",
            f"total_device_ticks={compiled.total_device_ticks}",
            "overflowed_acquisitions=1",
            f"dropped_events={acquisition.dropped_events}",
            f"acquisition_payload_length={len(acquisition_payload)}",
            f"acquisition_payload={acquisition_payload}",
            "message=completed by pytest control mailbox",
            "END",
            "",
        ]
    )
    result_path.write_text(result_frame, encoding="utf-8")

    with NativeRuntime(
        transport="fpga_mailbox",
        command_path=command_path,
        result_path=result_path,
    ) as runtime:
        runtime.submit_control(envelope)
        reply = runtime.read_control_result(envelope.job_id)
        result_path.write_text(
            result_frame.replace(
                f"envelope_digest={envelope.envelope_digest}",
                f"envelope_digest={'0' * 64}",
            ),
            encoding="utf-8",
        )
        with pytest.raises(BackendExecutionError, match="does not correlate"):
            runtime.read_control_result(envelope.job_id)

    command = command_path.read_text(encoding="utf-8")
    assert command.startswith("PQDR_CONTROL_V1\n")
    assert f"program_digest={compiled.digest}\n" in command
    assert f"envelope_digest={envelope.envelope_digest}\n" in command
    assert f"compiled_payload_length={len(compiled.canonical_json)}\n" in command
    assert "acquisition_payload=" not in command
    assert reply["acquisitions"] == [acquisition.to_dict()]
