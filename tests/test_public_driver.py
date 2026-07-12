import sys

import pytest

from photonic_driver import BackendUnavailableError, Driver, PhotonicResult


def test_public_driver_load_compile_run() -> None:
    driver = Driver.load("emulator")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1]},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 12,
        }
    )

    result = driver.run(job)

    assert isinstance(result, PhotonicResult)
    assert result["backend_name"] == "emulator"
    assert sum(result["counts"].values()) == 12


def test_public_driver_use_plugin_by_name() -> None:
    driver = Driver.load("mock")

    driver.use_plugin("schrosim")
    driver.use_plugin("lidmas")
    driver.use_plugin(" SCHROSIM ")

    assert driver.list_plugins() == ["lidmas", "schrosim"]


def test_public_driver_rejects_unknown_plugin() -> None:
    driver = Driver.load("mock")

    with pytest.raises(KeyError):
        driver.use_plugin("missing")


def test_public_driver_known_hardware_target_is_unavailable_until_dependency_installed(
    monkeypatch,
) -> None:
    monkeypatch.setitem(sys.modules, "psiqdk", None)
    monkeypatch.setitem(sys.modules, "psiqdk.workbench", None)
    monkeypatch.setitem(sys.modules, "psiqdk.workbench.qre", None)

    with pytest.raises(BackendUnavailableError):
        Driver.load("psiquantum")


def test_public_driver_known_emulator_target_is_unavailable_until_configured() -> None:
    with pytest.raises(BackendUnavailableError):
        Driver.load("pennylane-sf")
