#!/usr/bin/env python3
"""Generate or verify immutable P6.0 board-bridge evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from photon_qdrivers import (
    AcquisitionKind,
    BoardCapabilities,
    ChannelRole,
    ControlChannel,
    ControlEnvelope,
    ControlEvent,
    ControlProgram,
    EventKind,
    HardwareProfile,
    P6BoardBridge,
    compile_control_program,
    decode_acquisition_payload,
    encode_control_request_frame,
)


SUITE_ID = "qdriverlab-p6-board-reference-v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REFERENCE = Path(__file__).resolve().parent / "p6_board_reference_v1"
FPGA_FIXTURE = (
    REPO_ROOT / "fpga" / "testbench" / "fixtures" / "p5_control_program.hex"
)
TESTBENCH = REPO_ROOT / "fpga" / "testbench" / "tb_red_pitaya_control_bridge.sv"
CHANNEL_MAP = {
    "source/0": 0,
    "modulator/0": 1,
    "phase/0": 2,
    "sync/0": 3,
    "detector/0": 4,
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _build_envelope() -> ControlEnvelope:
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
        shots=1,
        repetition_period_ns=12,
        provenance={"paper_suite": SUITE_ID},
    )
    return ControlEnvelope(
        job_id="p6-board-reference-job",
        program=compile_control_program(source, profile),
    )


def _run_rtl() -> dict[str, Any]:
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if iverilog is None or vvp is None:
        raise RuntimeError("P6 evidence generation requires Icarus Verilog and vvp.")
    with tempfile.TemporaryDirectory(prefix="qdriverlab-p6-board-") as temporary:
        executable = Path(temporary) / "tb_red_pitaya_control_bridge.vvp"
        compile_result = subprocess.run(
            [
                iverilog,
                "-g2012",
                "-I",
                str(REPO_ROOT / "fpga" / "systemverilog"),
                "-o",
                str(executable),
                str(TESTBENCH),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(compile_result.stderr)
        run_result = subprocess.run(
            [vvp, str(executable), f"+PROGRAM={FPGA_FIXTURE}"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if run_result.returncode != 0 or "P6_PASS" not in run_result.stdout:
            raise RuntimeError(run_result.stdout + run_result.stderr)

    observed: dict[str, Any] = {}
    for line in run_result.stdout.splitlines():
        fields = line.split()
        if fields[:1] == ["P6_CAPS"]:
            observed["capabilities"] = {
                "instruction_width_bits": int(fields[1]),
                "max_instructions": int(fields[2]),
                "channel_count": int(fields[3]),
                "count_width_bits": int(fields[4]),
            }
        elif fields[:1] == ["P6_RESULT"]:
            observed["result"] = {
                "final_device_tick": int(fields[1]),
                "instruction_count": int(fields[2]),
                "acquisition_channel": int(fields[3]),
                "acquisition_start_tick": int(fields[4]),
                "acquisition_end_tick": int(fields[5]),
                "recorded_events": int(fields[6]),
                "overflow": int(fields[7]),
                "dropped_events": int(fields[8]),
            }
        elif fields[:1] == ["P6_FAULT"]:
            observed["fault"] = {fields[1]: int(fields[2])}
    return observed


def generate(output: Path) -> str:
    output.mkdir(parents=True, exist_ok=False)
    envelope = _build_envelope()
    capabilities = BoardCapabilities(
        max_instructions=16,
        count_width_bits=2,
    )
    bridge = P6BoardBridge(capabilities, CHANNEL_MAP)
    control_request = encode_control_request_frame(envelope)
    _, image, software_result, control_result = bridge.handle_control_frame(
        control_request,
        detector_event_ticks=(7, 8, 9, 10),
    )
    expected_hex = "\n".join(image.instruction_words) + "\n"
    if expected_hex.encode("utf-8") != FPGA_FIXTURE.read_bytes():
        raise RuntimeError("P6 board image differs from the immutable P5 fixture.")

    acquisition_line = next(
        line
        for line in control_result.splitlines()
        if line.startswith("acquisition_payload=")
    )
    acquisitions = decode_acquisition_payload(acquisition_line.split("=", 1)[1])
    if len(acquisitions) != 1:
        raise RuntimeError("P6 control result did not preserve one acquisition.")

    rtl = _run_rtl()
    expected_capabilities = {
        "instruction_width_bits": 128,
        "max_instructions": 16,
        "channel_count": 8,
        "count_width_bits": 2,
    }
    expected_result = {
        "final_device_tick": 11,
        "instruction_count": 6,
        "acquisition_channel": 4,
        "acquisition_start_tick": 7,
        "acquisition_end_tick": 11,
        "recorded_events": 3,
        "overflow": 1,
        "dropped_events": 1,
    }
    if rtl != {
        "capabilities": expected_capabilities,
        "result": expected_result,
        "fault": {"read_only_write": 128},
    }:
        raise RuntimeError("P6 register-interface observations differ from reference.")
    software_comparable = {
        key: int(value) if isinstance(value, bool) else value
        for key, value in software_result.to_dict().items()
        if key in expected_result
    }
    if software_comparable != expected_result:
        raise RuntimeError("P6 software and register-interface results differ.")

    frame_files = {
        "control_request.frame": control_request,
        "board_program.frame": image.to_frame(),
        "board_result.frame": software_result.to_frame(),
        "control_result.frame": control_result,
    }
    for name, payload in frame_files.items():
        (output / name).write_text(payload, encoding="utf-8")

    summary = {
        "schema_version": "qdriverlab.p6-board-bridge.v1",
        "suite_id": SUITE_ID,
        "control_envelope_digest": envelope.envelope_digest,
        "compiled_program_digest": envelope.program_digest,
        "rtl_program_digest": image.rtl_program_digest,
        "capability_digest": capabilities.digest,
        "board_image_digest": image.image_digest,
        "board_result_digest": software_result.result_digest,
        "capabilities": capabilities.to_dict(),
        "software_result": software_result.to_dict(),
        "rtl_register_observations": rtl,
        "exact_software_rtl_result_match": True,
        "p4_result_acquisition": acquisitions[0].to_dict(),
        "claim_boundary": (
            "P6.0 software/native framing and Icarus register-interface parity; "
            "not synthesis, deployed Red Pitaya IO, measured timing, or optical evidence."
        ),
    }
    summary_path = output / "bridge_summary.json"
    _write_json(summary_path, summary)

    files = {
        path.name: _sha256_bytes(path.read_bytes())
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    manifest_base = {
        "schema_version": "qdriverlab.p6-board-reference-manifest.v1",
        "suite_id": SUITE_ID,
        "generator_sha256": _sha256_bytes(Path(__file__).read_bytes()),
        "fpga_fixture_sha256": _sha256_bytes(FPGA_FIXTURE.read_bytes()),
        "files": files,
    }
    suite_digest = _sha256_bytes(_canonical_json(manifest_base).encode("utf-8"))
    _write_json(output / "manifest.json", {**manifest_base, "suite_digest": suite_digest})
    return suite_digest


def _directory_bytes(path: Path) -> dict[str, bytes]:
    return {
        str(item.relative_to(path)): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def verify(reference: Path) -> str:
    if not reference.is_dir():
        raise RuntimeError(f"P6 reference directory does not exist: {reference}")
    with tempfile.TemporaryDirectory(prefix="qdriverlab-p6-board-verify-") as temporary:
        generated = Path(temporary) / "p6_board_reference_v1"
        suite_digest = generate(generated)
        if _directory_bytes(generated) != _directory_bytes(reference):
            raise RuntimeError("P6 board reference does not regenerate byte-for-byte.")
    return suite_digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.verify == (arguments.output is not None):
        parser.error("choose exactly one of --verify or --output")
    if arguments.verify:
        digest = verify(DEFAULT_REFERENCE)
        print(f"verified {SUITE_ID} {digest}")
    else:
        digest = generate(arguments.output.resolve())
        print(f"generated {SUITE_ID} {digest}")


if __name__ == "__main__":
    main()
