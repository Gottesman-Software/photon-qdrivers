"""Run a small sampling circuit on installed optional photonic adapters."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photonic_driver import BackendUnavailableError, Driver


def main() -> None:
    circuit = {
        "type": "photonic_circuit",
        "modes": 2,
        "operations": [
            {"gate": "BS", "modes": [0, 1]},
            {"gate": "PS", "mode": 0, "theta": 0.25},
            {"measure": "photon_counting", "modes": [0, 1]},
        ],
        "shots": 8,
        "metadata": {"input_state": [1, 1]},
    }

    for backend_name in ("perceval", "piquasso", "lightworks"):
        try:
            driver = Driver.load(backend_name)
        except BackendUnavailableError as exc:
            print(f"{backend_name}: unavailable ({exc})")
            continue

        try:
            result = driver.run(driver.compile(circuit))
            print(f"{backend_name}: {result.counts}")
        finally:
            driver.shutdown()


if __name__ == "__main__":
    main()

