"""Sketch of where a LiDMaS+ decoder integration will attach."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from photonic_driver import Driver


driver = Driver.load("emulator")
driver.use_plugin("lidmas")

print(driver.list_plugins())
print("LiDMaS+ plugin registered; real decoder calls are not wired yet.")
