import sys
import types

import pytest

from photon_qdrivers import BackendUnavailableError, CircuitValidationError, PhotonDriver


def test_lightworks_missing_dependency_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "lightworks", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="lightworks"):
        driver.load_backend("lightworks")


def test_lightworks_compile_requires_input_state(monkeypatch) -> None:
    _install_fake_lightworks(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("lightworks")

    with pytest.raises(CircuitValidationError, match="metadata.input_state"):
        driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "operations": [
                    {"gate": "BS", "modes": [0, 1]},
                    {"measure": "photon_counting", "modes": [0, 1]},
                ],
                "shots": 25,
            }
        )


def test_lightworks_adapter_runs_against_optional_sdk_shape(monkeypatch) -> None:
    fake_lw = _install_fake_lightworks(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend(
        "lightworks",
        backend="permanent",
        random_seed=7,
        sampling_mode="input",
    )
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1], "reflectivity": 0.5},
                {"gate": "PS", "mode": 0, "theta": 0.5},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 25,
            "metadata": {"input_state": [1, 1]},
        }
    )

    result = driver.run(job)

    assert result.backend_name == "lightworks"
    assert result.counts == {"|1,0>": 25}
    assert result.metadata["adapter"] == "lightworks"
    assert result.metadata["emulator_backend"] == "permanent"
    assert fake_lw.last_backend.name == "permanent"


def _install_fake_lightworks(monkeypatch):
    lightworks_module = types.ModuleType("lightworks")
    emulator_module = types.ModuleType("lightworks.emulator")
    lightworks_module.last_backend = None

    class PhotonicCircuit:
        def __init__(self, n_modes):
            self.n_modes = n_modes
            self.operations = []

        def bs(self, mode_1, mode_2=None, reflectivity=0.5, loss=0, convention="Rx"):
            self.operations.append(
                ("bs", mode_1, mode_2, reflectivity, loss, convention)
            )

        def ps(self, mode, phi, loss=0):
            self.operations.append(("ps", mode, phi, loss))

    class State:
        def __init__(self, state):
            self.s = list(state)

        def __hash__(self):
            return hash(tuple(self.s))

        def __eq__(self, other):
            return isinstance(other, State) and self.s == other.s

        def __str__(self):
            return "|" + ",".join(str(value) for value in self.s) + ">"

    class Sampler:
        def __init__(self, circuit, input_state, n_samples, **options):
            self.circuit = circuit
            self.input_state = input_state
            self.n_samples = n_samples
            self.options = options

    class SamplingResult:
        def __init__(self, counts):
            self.counts = counts

    class Backend:
        def __init__(self, name):
            self.name = name
            lightworks_module.last_backend = self

        def run(self, sampler):
            assert sampler.circuit.n_modes == 2
            assert sampler.circuit.operations == [
                ("bs", 0, 1, 0.5, 0, "Rx"),
                ("ps", 0, 0.5, 0),
            ]
            assert sampler.input_state.s == [1, 1]
            assert sampler.n_samples == 25
            assert sampler.options == {"random_seed": 7, "sampling_mode": "input"}
            return SamplingResult({State([1, 0]): sampler.n_samples})

    lightworks_module.PhotonicCircuit = PhotonicCircuit
    lightworks_module.State = State
    lightworks_module.Sampler = Sampler
    lightworks_module.emulator = emulator_module
    emulator_module.Backend = Backend

    monkeypatch.setitem(sys.modules, "lightworks", lightworks_module)
    monkeypatch.setitem(sys.modules, "lightworks.emulator", emulator_module)
    return lightworks_module
