import shutil
import subprocess
from pathlib import Path

import pytest

from photon_qdrivers import RTLInstruction


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    REPO_ROOT / "fpga" / "testbench" / "fixtures" / "p5_control_program.hex"
)
TESTBENCH_PATH = REPO_ROOT / "fpga" / "testbench" / "tb_control_schedule_engine.sv"


def _require_simulator() -> tuple[str, str]:
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if iverilog is None or vvp is None:
        pytest.skip("Icarus Verilog and vvp are required for RTL parity.")
    return iverilog, vvp


def test_compiled_instruction_fixture_matches_rtl_observations(tmp_path: Path) -> None:
    iverilog, vvp = _require_simulator()
    simulation = tmp_path / "tb_control_schedule_engine.vvp"
    compile_result = subprocess.run(
        [
            iverilog,
            "-g2012",
            "-I",
            str(REPO_ROOT / "fpga" / "systemverilog"),
            "-o",
            str(simulation),
            str(TESTBENCH_PATH),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    run_result = subprocess.run(
        [vvp, str(simulation), f"+PROGRAM={FIXTURE_PATH}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    assert "P5_PASS" in run_result.stdout

    instructions = [
        RTLInstruction.from_word(int(line, 16))
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observed = []
    for line in run_result.stdout.splitlines():
        if not line.startswith("P5_OBS "):
            continue
        fields = line.split()
        observed.append(
            {
                "index": int(fields[1]),
                "start_tick": int(fields[2]),
                "opcode": int(fields[3]),
                "channel": int(fields[4]),
                "duration_ticks": int(fields[5]),
                "argument_word": int(fields[6], 16),
                "acquisition_code": int(fields[7]),
            }
        )

    expected = [
        {
            "index": index,
            "start_tick": instruction.start_tick,
            "opcode": int(instruction.opcode),
            "channel": instruction.channel_index,
            "duration_ticks": instruction.duration_ticks,
            "argument_word": instruction.argument_word,
            "acquisition_code": int(instruction.acquisition_code),
        }
        for index, instruction in enumerate(instructions)
    ]
    assert observed == expected
    assert "P5_RESULT 11 3 1 1" in run_result.stdout
    assert "P5_FAULT format_version 1" in run_result.stdout
    assert "P5_FAULT unsorted 6" in run_result.stdout
    assert "P5_FAULT acquisition_kind 5" in run_result.stdout
