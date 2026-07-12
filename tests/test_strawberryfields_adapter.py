import sys
import types

import pytest

from photon_qdrivers import BackendUnavailableError, CircuitValidationError, PhotonDriver


def test_strawberryfields_missing_dependency_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "strawberryfields", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="strawberryfields"):
        driver.load_backend("strawberryfields")


def test_strawberryfields_compile_requires_measurement(monkeypatch) -> None:
    _install_fake_strawberryfields(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("strawberryfields")

    with pytest.raises(CircuitValidationError, match="photon_counting"):
        driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "operations": [{"gate": "BS", "modes": [0, 1]}],
                "shots": 10,
            }
        )


def test_strawberryfields_adapter_runs_against_optional_sdk_shape(monkeypatch) -> None:
    fake_sf = _install_fake_strawberryfields(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("strawberryfields", cutoff_dim=6, backend="fock")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1], "theta": 0.785, "phi": 0.1},
                {"gate": "PS", "mode": 0, "theta": 0.5},
                {"gate": "S", "mode": 1, "r": 0.2},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 4,
            "metadata": {"input_state": [1, 0]},
        }
    )

    result = driver.run(job)

    assert result.backend_name == "strawberryfields"
    assert result.counts == {"|1,0>": 3, "|0,1>": 1}
    assert result.metadata["adapter"] == "strawberryfields"
    assert result.metadata["backend_options"] == {"cutoff_dim": 6}
    assert fake_sf.last_engine.backend == "fock"
    assert fake_sf.last_engine.backend_options == {"cutoff_dim": 6}
    assert fake_sf.last_program.operations == [
        ("Fock", (1,), "q0"),
        ("BSgate", (0.785, 0.1), ("q0", "q1")),
        ("Rgate", (0.5,), "q0"),
        ("Sgate", (0.2, 0.0), "q1"),
        ("MeasureFock", (), ["q0", "q1"]),
    ]


def test_strawberryfields_repeats_single_shots_when_fock_backend_rejects_batched(
    monkeypatch,
) -> None:
    fake_sf = _install_fake_strawberryfields(monkeypatch, reject_batched_fock=True)
    driver = PhotonDriver()
    driver.load_backend("strawberryfields", cutoff_dim=6, backend="fock")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1]},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 3,
            "metadata": {"input_state": [1, 0]},
        }
    )

    result = driver.run(job)

    assert result.counts == {"|1,0>": 3}
    assert result.metadata["result_format"] == "strawberryfields_repeated_single_fock_samples"
    assert fake_sf.run_shots == [3, 1, 1, 1]


def _install_fake_strawberryfields(monkeypatch, *, reject_batched_fock=False):
    strawberryfields_module = types.ModuleType("strawberryfields")
    ops_module = types.ModuleType("strawberryfields.ops")
    strawberryfields_module.__path__ = []
    strawberryfields_module.last_engine = None
    strawberryfields_module.last_program = None
    strawberryfields_module.run_shots = []

    class FakeProgramContext:
        def __init__(self, program):
            self.program = program

        def __enter__(self):
            return self.program.registers

        def __exit__(self, exc_type, exc, traceback):
            return False

    class Program:
        def __init__(self, modes):
            self.modes = modes
            self.registers = [f"q{mode}" for mode in range(modes)]
            self.operations = []
            self.context = FakeProgramContext(self)
            strawberryfields_module.last_program = self

    class Operation:
        name = ""

        def __init__(self, *parameters):
            self.parameters = parameters

        def __or__(self, target):
            strawberryfields_module.last_program.operations.append(
                (self.name, self.parameters, target)
            )
            return self

    class Fock(Operation):
        name = "Fock"

    class BSgate(Operation):
        name = "BSgate"

    class Rgate(Operation):
        name = "Rgate"

    class Sgate(Operation):
        name = "Sgate"

    class Dgate(Operation):
        name = "Dgate"

    class MeasureFock(Operation):
        name = "MeasureFock"

    class Result:
        def __init__(self, shots):
            samples = [(1, 0), (1, 0), (0, 1), (1, 0)]
            self.samples = samples[:shots]

    class Engine:
        def __init__(self, backend, backend_options=None):
            self.backend = backend
            self.backend_options = backend_options
            strawberryfields_module.last_engine = self

        def run(self, program, shots=None):
            strawberryfields_module.run_shots.append(shots)
            assert program is strawberryfields_module.last_program
            if reject_batched_fock and self.backend == "fock" and shots and shots > 1:
                raise NotImplementedError("shots are not supported")
            return Result(shots or 1)

    strawberryfields_module.Program = Program
    strawberryfields_module.Engine = Engine
    ops_module.Fock = Fock
    ops_module.BSgate = BSgate
    ops_module.Rgate = Rgate
    ops_module.Sgate = Sgate
    ops_module.Dgate = Dgate
    ops_module.MeasureFock = MeasureFock

    monkeypatch.setitem(sys.modules, "strawberryfields", strawberryfields_module)
    monkeypatch.setitem(sys.modules, "strawberryfields.ops", ops_module)
    return strawberryfields_module
