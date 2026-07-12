"""Run a one-mode oscillator dynamics job with QuTiP."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photonic_driver import BackendUnavailableError, Driver


def main() -> None:
    try:
        driver = Driver.load("qutip")
    except BackendUnavailableError as exc:
        print(f"qutip unavailable: {exc}")
        return

    try:
        job = driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 1,
                "operations": [{"measure": "photon_counting", "modes": [0]}],
                "shots": 1,
                "metadata": {
                    "cutoff": 4,
                    "times": [0.0, 0.5, 1.0],
                    "initial_state": {"kind": "fock", "n": 1},
                    "hamiltonian": [{"operator": "num", "coefficient": 1.0}],
                    "observables": [{"name": "n", "operator": "num"}],
                },
            }
        )
        result = driver.run(job)
        print(result.metadata["final_expectations"])
    finally:
        driver.shutdown()


if __name__ == "__main__":
    main()

