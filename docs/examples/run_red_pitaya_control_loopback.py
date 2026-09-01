"""Run a control request through the native Red Pitaya mailbox and P6 bridge."""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photon_qdrivers import (  # noqa: E402
    AcquisitionKind,
    BoardCapabilities,
    ChannelRole,
    ControlChannel,
    ControlEnvelope,
    ControlEvent,
    ControlProgram,
    EventKind,
    HardwareProfile,
    NativeRuntime,
    P6BoardBridge,
    compile_control_program,
)


CHANNEL_MAP = {
    "source/0": 0,
    "modulator/0": 1,
    "phase/0": 2,
    "sync/0": 3,
    "detector/0": 4,
}


def build_envelope() -> ControlEnvelope:
    profile = HardwareProfile(
        profile_id="red-pitaya-loopback",
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
    program = ControlProgram(
        program_id="red-pitaya-loopback-program",
        channels=tuple(
            ControlChannel(name, role)
            for name, role in profile.channel_roles.items()
        ),
        events=(
            ControlEvent(
                "source",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=1,
                duration_ns=2,
            ),
            ControlEvent(
                "modulator",
                EventKind.MODULATOR_PULSE,
                "modulator/0",
                start_ns=2,
                duration_ns=3,
                parameters={"amplitude": 0.5},
            ),
            ControlEvent(
                "phase",
                EventKind.PHASE_UPDATE,
                "phase/0",
                start_ns=2,
                parameters={"phase": math.pi},
            ),
            ControlEvent(
                "sync", EventKind.SYNC, "sync/0", start_ns=4
            ),
            ControlEvent(
                "delay", EventKind.DELAY, "sync/0", start_ns=5, duration_ns=1
            ),
            ControlEvent(
                "counts",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=7,
                duration_ns=4,
                acquisition_id="counts-0",
                acquisition_kind=AcquisitionKind.COUNTS,
            ),
        ),
        shots=1,
        repetition_period_ns=12,
        provenance={"example": "red-pitaya-control-loopback"},
    )
    return ControlEnvelope(
        job_id="red-pitaya-loopback-job",
        program=compile_control_program(program, profile),
    )


def main() -> None:
    envelope = build_envelope()
    capabilities = BoardCapabilities(max_instructions=16, count_width_bits=2)
    bridge = P6BoardBridge(capabilities, CHANNEL_MAP)

    with tempfile.TemporaryDirectory(prefix="photon-qdrivers-red-pitaya-") as tmp:
        command_path = Path(tmp) / "commands"
        result_path = Path(tmp) / "results"
        with NativeRuntime(
            transport="red_pitaya",
            command_path=command_path,
            result_path=result_path,
        ) as runtime:
            runtime.submit_control(envelope)
            _, image, board_result, result_frame = bridge.handle_control_frame(
                command_path.read_text(encoding="utf-8"),
                detector_event_ticks=(7, 8, 9, 10),
            )
            result_path.write_text(result_frame, encoding="utf-8")
            normalized = runtime.read_control_result(envelope.job_id)

    print(f"board image: {image.image_digest}")
    print(
        "board count: "
        f"{board_result.recorded_events}, overflow={board_result.overflow}, "
        f"dropped={board_result.dropped_events}"
    )
    print(f"normalized acquisitions: {normalized['acquisitions']}")


if __name__ == "__main__":
    main()
