"""Sketch of where a SchroSIM integration will attach."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photonic_driver import Driver


driver = Driver.load("emulator")
driver.use_plugin("schrosim")

print(driver.list_plugins())
print("SchroSIM plugin registered; real simulator calls are not wired yet.")
