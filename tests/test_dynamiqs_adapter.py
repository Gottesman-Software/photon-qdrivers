import sys
import types

import pytest

from photon_qdrivers import BackendUnavailableError, CircuitValidationError, PhotonDriver


def test_dynamiqs_missing_dependency_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "dynamiqs", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="dynamiqs"):
        driver.load_backend("dynamiqs")


def test_dynamiqs_compile_requires_times(monkeypatch) -> None:
    _install_fake_dynamiqs(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("dynamiqs")

    with pytest.raises(CircuitValidationError, match="metadata.times"):
        driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 1,
                "operations": [{"measure": "photon_counting", "modes": [0]}],
                "shots": 10,
                "metadata": {
                    "cutoff": 4,
                    "hamiltonian": [{"operator": "number", "coefficient": 1.0}],
                },
            }
        )


def test_dynamiqs_sesolve_runs_against_optional_sdk_shape(monkeypatch) -> None:
    fake_dq = _install_fake_dynamiqs(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("dynamiqs")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 1,
            "operations": [{"measure": "photon_counting", "modes": [0]}],
            "shots": 10,
            "metadata": {
                "model": "oscillator_dynamics",
                "cutoff": 4,
                "times": [0.0, 0.5, 1.0],
                "initial_state": {"kind": "fock", "n": 1},
                "hamiltonian": [{"operator": "number", "coefficient": 1.5}],
                "observables": [{"name": "n", "operator": "number"}],
            },
        }
    )

    result = driver.run(job)

    assert result.backend_name == "dynamiqs"
    assert result.counts == {}
    assert result.metadata["solver"] == "sesolve"
    assert result.metadata["expectation_values"] == {"n": [1.0, 1.25, 1.5]}
    assert result.metadata["final_expectations"] == {"n": 1.5}
    assert fake_dq.calls["sesolve"][0]["H"].label == "(1.5*number4)"
    assert fake_dq.calls["sesolve"][0]["psi0"].label == "fock(4,1)"


def test_dynamiqs_mesolve_uses_jump_operators_and_method(monkeypatch) -> None:
    fake_dq = _install_fake_dynamiqs(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("dynamiqs", method="Tsit5", solver_options={"save_states": False})
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 1,
            "operations": [{"measure": "photon_counting", "modes": [0]}],
            "shots": 10,
            "metadata": {
                "cutoff": 3,
                "times": [0.0, 1.0],
                "initial_state": {"kind": "coherent", "alpha": 0.2},
                "hamiltonian": [{"operator": "number", "coefficient": 1.0}],
                "jump_ops": [{"operator": "destroy", "rate": 0.25}],
                "observables": [{"name": "n", "operator": "number"}],
            },
        }
    )

    result = driver.run(job)

    assert result.metadata["solver"] == "mesolve"
    assert result.metadata["expectation_values"] == {"n": [2.0, 1.0]}
    call = fake_dq.calls["mesolve"][0]
    assert call["jump_ops"][0].label == "(0.5*destroy3)"
    assert call["method"].label == "Tsit5"
    assert call["kwargs"]["save_states"] is False
    assert call["kwargs"]["progress_meter"] is False


def _install_fake_dynamiqs(monkeypatch):
    dynamiqs_module = types.ModuleType("dynamiqs")
    dynamiqs_module.calls = {"sesolve": [], "mesolve": []}

    class FakeQArray:
        def __init__(self, label):
            self.label = label

        def __rmul__(self, value):
            return FakeQArray(f"({value}*{self.label})")

        def __add__(self, other):
            return FakeQArray(f"({self.label}+{other.label})")

        def __matmul__(self, other):
            return FakeQArray(f"({self.label}@{other.label})")

        def dag(self):
            return FakeQArray(f"{self.label}.dag")

    class FakeMethod:
        def __init__(self, label):
            self.label = label

        def __str__(self):
            return self.label

    class FakeMethodNamespace:
        @staticmethod
        def Tsit5():
            return FakeMethod("Tsit5")

    class FakeResult:
        def __init__(self, expects):
            self.expects = expects
            self.infos = {"steps": 3}
            self.method = FakeMethod("fake")

    def fock(cutoff, n):
        return FakeQArray(f"fock({cutoff},{n})")

    def coherent(cutoff, alpha):
        return FakeQArray(f"coherent({cutoff},{alpha})")

    def fock_dm(cutoff, n):
        return FakeQArray(f"fock_dm({cutoff},{n})")

    def coherent_dm(cutoff, alpha):
        return FakeQArray(f"coherent_dm({cutoff},{alpha})")

    def destroy(cutoff):
        return FakeQArray(f"destroy{cutoff}")

    def create(cutoff):
        return FakeQArray(f"create{cutoff}")

    def number(cutoff):
        return FakeQArray(f"number{cutoff}")

    def eye(cutoff):
        return FakeQArray(f"eye{cutoff}")

    def position(cutoff):
        return FakeQArray(f"position{cutoff}")

    def momentum(cutoff):
        return FakeQArray(f"momentum{cutoff}")

    def asqarray(matrix):
        return FakeQArray(f"asqarray({matrix})")

    def sesolve(H, psi0, tsave, **kwargs):
        dynamiqs_module.calls["sesolve"].append(
            {"H": H, "psi0": psi0, "tsave": tsave, "kwargs": kwargs}
        )
        return FakeResult([[1.0, 1.25, 1.5]])

    def mesolve(H, jump_ops, rho0, tsave, **kwargs):
        dynamiqs_module.calls["mesolve"].append(
            {
                "H": H,
                "jump_ops": jump_ops,
                "rho0": rho0,
                "tsave": tsave,
                "method": kwargs.get("method"),
                "kwargs": kwargs,
            }
        )
        return FakeResult([[2.0, 1.0]])

    dynamiqs_module.FakeQArray = FakeQArray
    dynamiqs_module.method = FakeMethodNamespace
    dynamiqs_module.fock = fock
    dynamiqs_module.coherent = coherent
    dynamiqs_module.fock_dm = fock_dm
    dynamiqs_module.coherent_dm = coherent_dm
    dynamiqs_module.destroy = destroy
    dynamiqs_module.create = create
    dynamiqs_module.number = number
    dynamiqs_module.eye = eye
    dynamiqs_module.position = position
    dynamiqs_module.momentum = momentum
    dynamiqs_module.asqarray = asqarray
    dynamiqs_module.sesolve = sesolve
    dynamiqs_module.mesolve = mesolve

    monkeypatch.setitem(sys.modules, "dynamiqs", dynamiqs_module)
    return dynamiqs_module
