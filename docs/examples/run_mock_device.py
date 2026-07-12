"""Run a symbolic photonic circuit on the local mock backend."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photonic_driver import Driver


driver = Driver.load("mock")

job = driver.compile(
    {
        "type": "photonic_circuit",
        "modes": 4,
        "operations": [
            {"gate": "BS", "modes": [0, 1]},
            {"gate": "PS", "mode": 0, "theta": 0.5},
            {"measure": "photon_counting", "modes": [0, 1, 2, 3]},
        ],
        "shots": 1000,
    }
)

result = driver.run(job)
print(result.as_dict())
