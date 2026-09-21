from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest


def test_paper_reference_suite_regenerates_exactly() -> None:
    repository = Path(__file__).resolve().parents[3]
    script = (
        repository
        / "examples"
        / "paper_01"
        / "experiments"
        / "run_reference_experiments.py"
    )
    reference = script.parent / "reference_v1"
    manifest = json.loads((reference / "manifest.json").read_text(encoding="utf-8"))

    completed = subprocess.run(
        [sys.executable, str(script), "--verify"],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
    )

    assert manifest["suite_digest"] in completed.stdout


def test_paper_rtl_reference_suite_regenerates_exactly() -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("Icarus Verilog and vvp are required for RTL evidence.")
    repository = Path(__file__).resolve().parents[3]
    script = (
        repository
        / "examples"
        / "paper_01"
        / "experiments"
        / "run_rtl_reference.py"
    )
    reference = script.parent / "rtl_reference_v1"
    manifest = json.loads((reference / "manifest.json").read_text(encoding="utf-8"))

    completed = subprocess.run(
        [sys.executable, str(script), "--verify"],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    )

    assert manifest["suite_digest"] in completed.stdout


def test_paper_p6_board_reference_suite_regenerates_exactly() -> None:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("Icarus Verilog and vvp are required for P6 evidence.")
    repository = Path(__file__).resolve().parents[3]
    script = (
        repository
        / "examples"
        / "paper_01"
        / "experiments"
        / "run_p6_board_reference.py"
    )
    reference = script.parent / "p6_board_reference_v1"
    manifest = json.loads((reference / "manifest.json").read_text(encoding="utf-8"))

    completed = subprocess.run(
        [sys.executable, str(script), "--verify"],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    )

    assert manifest["suite_digest"] in completed.stdout
