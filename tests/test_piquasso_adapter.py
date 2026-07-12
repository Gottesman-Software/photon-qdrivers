import sys
import types

import pytest

from photon_qdrivers import BackendUnavailableError, CircuitValidationError, PhotonDriver


def test_piquasso_missing_dependency_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "piquasso", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="piquasso"):
        driver.load_backend("piquasso")


def test_piquasso_compile_requires_input_state(monkeypatch) -> None:
    _install_fake_piquasso(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("piquasso")

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


def test_piquasso_adapter_runs_against_optional_sdk_shape(monkeypatch) -> None:
    fake_pq = _install_fake_piquasso(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("piquasso", cutoff=5)
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1], "theta": 0.785},
                {"gate": "PS", "mode": 0, "theta": 0.5},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 25,
            "metadata": {"input_state": [1, 1]},
        }
    )

    result = driver.run(job)

    assert result.backend_name == "piquasso"
    assert result.counts == {"|1,0>": 25}
    assert result.metadata["adapter"] == "piquasso"
    assert fake_pq.last_simulator.config.cutoff == 5


def _install_fake_piquasso(monkeypatch):
    piquasso_module = types.ModuleType("piquasso")
    piquasso_module.current_program = None
    piquasso_module.last_simulator = None

    class Program:
        def __init__(self):
            self.instructions = []

        def __enter__(self):
            piquasso_module.current_program = self
            return self

        def __exit__(self, exc_type, exc, traceback):
            piquasso_module.current_program = None
            return False

    class Q:
        def __init__(self, *modes):
            self.modes = modes

        def __or__(self, instruction):
            if piquasso_module.current_program is None:
                raise AssertionError("Piquasso instruction was applied outside a Program context.")
            piquasso_module.current_program.instructions.append((self.modes, instruction))
            return instruction

    class StateVector:
        def __init__(self, state):
            self.state = state

    class Beamsplitter:
        def __init__(self, **parameters):
            self.parameters = parameters

    class Phaseshifter:
        def __init__(self, phi):
            self.phi = phi

    class ParticleNumberMeasurement:
        pass

    class Config:
        def __init__(self, **options):
            self.__dict__.update(options)

    class FakeResult:
        def __init__(self, samples):
            self.samples = samples

    class SamplingSimulator:
        def __init__(self, d, config=None):
            self.d = d
            self.config = config
            piquasso_module.last_simulator = self

        def execute(self, program, shots):
            assert self.d == 2
            instruction_names = [
                type(instruction).__name__ for _, instruction in program.instructions
            ]
            assert instruction_names == [
                "StateVector",
                "Beamsplitter",
                "Phaseshifter",
                "ParticleNumberMeasurement",
            ]
            assert program.instructions[0][1].state == [1, 1]
            assert program.instructions[1][0] == (0, 1)
            assert program.instructions[2][0] == (0,)
            assert program.instructions[3][0] == (all,)
            return FakeResult([(1, 0)] * shots)

    piquasso_module.Program = Program
    piquasso_module.Q = Q
    piquasso_module.StateVector = StateVector
    piquasso_module.Beamsplitter = Beamsplitter
    piquasso_module.Phaseshifter = Phaseshifter
    piquasso_module.ParticleNumberMeasurement = ParticleNumberMeasurement
    piquasso_module.Config = Config
    piquasso_module.SamplingSimulator = SamplingSimulator

    monkeypatch.setitem(sys.modules, "piquasso", piquasso_module)
    return piquasso_module
