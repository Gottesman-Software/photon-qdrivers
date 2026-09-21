#!/usr/bin/env python3
"""Generate or verify the immutable P5 compiled-program/RTL parity evidence."""

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
    ChannelRole,
    ControlChannel,
    ControlEvent,
    ControlProgram,
    EventKind,
    HardwareProfile,
    RTLProgram,
    compile_control_program,
)


SUITE_ID = "qdriverlab-rtl-reference-v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REFERENCE = Path(__file__).resolve().parent / "rtl_reference_v1"
FPGA_FIXTURE = (
    REPO_ROOT / "fpga" / "testbench" / "fixtures" / "p5_control_program.hex"
)
TESTBENCH = REPO_ROOT / "fpga" / "testbench" / "tb_control_schedule_engine.sv"
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


def _build_program() -> RTLProgram:
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
    source = ControlProgram(
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
                acquisition_kind=AcquisitionKind.COUNTS,
            ),
        ),
        shots=4,
        repetition_period_ns=12,
        provenance={"paper_suite": SUITE_ID},
    )
    return RTLProgram.from_compiled(compile_control_program(source, profile), CHANNEL_MAP)


def _run_simulator(program_hex: Path) -> tuple[list[dict[str, int]], dict[str, int], dict[str, int]]:
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if iverilog is None or vvp is None:
        raise RuntimeError("P5 evidence generation requires Icarus Verilog and vvp.")
    with tempfile.TemporaryDirectory(prefix="qdriverlab-rtl-") as temporary:
        executable = Path(temporary) / "tb_control_schedule_engine.vvp"
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
            [vvp, str(executable), f"+PROGRAM={program_hex}"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if run_result.returncode != 0 or "P5_PASS" not in run_result.stdout:
            raise RuntimeError(run_result.stdout + run_result.stderr)

    observations: list[dict[str, int]] = []
    final: dict[str, int] = {}
    faults: dict[str, int] = {}
    for line in run_result.stdout.splitlines():
        fields = line.split()
        if fields[:1] == ["P5_OBS"]:
            observations.append(
                {
                    "index": int(fields[1]),
                    "start_tick": int(fields[2]),
                    "opcode": int(fields[3]),
                    "channel_index": int(fields[4]),
                    "duration_ticks": int(fields[5]),
                    "argument_word": int(fields[6], 16),
                    "acquisition_code": int(fields[7]),
                }
            )
        elif fields[:1] == ["P5_RESULT"]:
            final = {
                "final_device_tick": int(fields[1]),
                "recorded_events": int(fields[2]),
                "overflow": int(fields[3]),
                "dropped_events": int(fields[4]),
            }
        elif fields[:1] == ["P5_FAULT"]:
            faults[fields[1]] = int(fields[2])
    return observations, final, faults


def _expected_observations(program: RTLProgram) -> list[dict[str, int]]:
    return [
        {
            "index": index,
            "start_tick": item.start_tick,
            "opcode": int(item.opcode),
            "channel_index": item.channel_index,
            "duration_ticks": item.duration_ticks,
            "argument_word": item.argument_word,
            "acquisition_code": int(item.acquisition_code),
        }
        for index, item in enumerate(program.instructions)
    ]


def generate(output: Path) -> str:
    output.mkdir(parents=True, exist_ok=False)
    program = _build_program()
    program_path = output / "program.hex"
    program_path.write_text(program.hex_lines, encoding="utf-8")
    if program_path.read_bytes() != FPGA_FIXTURE.read_bytes():
        raise RuntimeError("Generated P5 program differs from the FPGA fixture.")

    observed, final, faults = _run_simulator(program_path)
    expected = _expected_observations(program)
    if observed != expected:
        raise RuntimeError("RTL observations differ from the compiled instructions.")
    if final != {
        "final_device_tick": 11,
        "recorded_events": 3,
        "overflow": 1,
        "dropped_events": 1,
    }:
        raise RuntimeError("RTL acquisition summary differs from the P5 reference.")
    if faults != {
        "acquisition_kind": 5,
        "format_version": 1,
        "unsorted": 6,
    }:
        raise RuntimeError("RTL fault-injection summary differs from the P5 reference.")

    parity = {
        "schema_version": "qdriverlab.rtl-parity.v1",
        "suite_id": SUITE_ID,
        "rtl_program_digest": program.digest,
        "compiled_program_digest": program.compiled_program_digest,
        "profile_digest": program.profile_digest,
        "repetition_ticks": program.repetition_ticks,
        "instruction_count": len(program.instructions),
        "exact_schedule_match": True,
        "expected_observations": expected,
        "observed_observations": observed,
        "acquisition_summary": final,
        "fault_error_codes": faults,
        "claim_boundary": (
            "Instruction-level Icarus Verilog parity; not synthesis, place-and-route, "
            "board timing, or physical photonic validation."
        ),
    }
    parity_path = output / "rtl_parity.json"
    _write_json(parity_path, parity)

    files = {
        path.name: _sha256_bytes(path.read_bytes())
        for path in (program_path, parity_path)
    }
    manifest_base = {
        "schema_version": "qdriverlab.rtl-reference-manifest.v1",
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
        raise RuntimeError(f"P5 reference directory does not exist: {reference}")
    with tempfile.TemporaryDirectory(prefix="qdriverlab-rtl-verify-") as temporary:
        generated = Path(temporary) / "rtl_reference_v1"
        suite_digest = generate(generated)
        if _directory_bytes(generated) != _directory_bytes(reference):
            raise RuntimeError("P5 RTL reference does not regenerate byte-for-byte.")
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
