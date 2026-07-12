"""Run the compiled C++ native runtime through the Python adapter."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photonic_driver import BackendUnavailableError, Driver


def main() -> None:
    try:
        driver = Driver.load("native")
    except BackendUnavailableError as exc:
        print(f"native runtime unavailable: {exc}")
        print("Build it first with: cmake -S . -B build && cmake --build build")
        return

    try:
        job = driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "operations": [
                    {"gate": "BS", "modes": [0, 1]},
                    {"gate": "PS", "mode": 0, "theta": 0.25},
                    {"measure": "photon_counting", "modes": [0, 1]},
                ],
                "shots": 16,
            }
        )
        result = driver.run(job)
        print(result.counts)
    finally:
        driver.shutdown()


if __name__ == "__main__":
    main()

