"""Run a The Walrus hafnian kernel through the driver adapter."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photonic_driver import BackendUnavailableError, Driver


def main() -> None:
    try:
        driver = Driver.load("thewalrus")
    except BackendUnavailableError as exc:
        print(f"thewalrus unavailable: {exc}")
        return

    try:
        job = driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "operations": [{"measure": "photon_counting", "modes": [0, 1]}],
                "shots": 1,
                "metadata": {
                    "kernel": "hafnian",
                    "matrix": [[0.0, 1.0], [1.0, 0.0]],
                },
            }
        )
        result = driver.run(job)
        print(result.metadata["kernel_result"])
    finally:
        driver.shutdown()


if __name__ == "__main__":
    main()

