"""Run a small legacy Strawberry Fields Fock-backend sampling job."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photonic_driver import BackendUnavailableError, Driver


def main() -> None:
    try:
        driver = Driver.load("strawberryfields", cutoff_dim=5)
    except BackendUnavailableError as exc:
        print(f"strawberryfields unavailable: {exc}")
        return

    try:
        job = driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "operations": [
                    {"gate": "BS", "modes": [0, 1]},
                    {"measure": "photon_counting", "modes": [0, 1]},
                ],
                "shots": 4,
                "metadata": {"input_state": [1, 1]},
            }
        )
        result = driver.run(job)
        print(result.counts)
    finally:
        driver.shutdown()


if __name__ == "__main__":
    main()

