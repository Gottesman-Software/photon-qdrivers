import sys
import types

import pytest

from photon_qdrivers import BackendUnavailableError, CircuitValidationError, PhotonDriver


def test_qutip_missing_dependency_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "qutip", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="qutip"):
        driver.load_backend("qutip")


def test_qutip_compile_requires_times(monkeypatch) -> None:
    _install_fake_qutip(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("qutip")

    with pytest.raises(CircuitValidationError, match="metadata.times"):
        driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 1,
                "operations": [{"measure": "photon_counting", "modes": [0]}],
                "shots": 10,
                "metadata": {
                    "cutoff": 4,
                    "hamiltonian": [{"operator": "num", "coefficient": 1.0}],
                },
            }
        )


def test_qutip_sesolve_runs_against_optional_sdk_shape(monkeypatch) -> None:
    fake_qt = _install_fake_qutip(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("qutip")
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
                "hamiltonian": [{"operator": "num", "coefficient": 1.5}],
                "observables": [{"name": "n", "operator": "num"}],
            },
        }
    )

    result = driver.run(job)

    assert result.backend_name == "qutip"
    assert result.counts == {}
    assert result.metadata["solver"] == "sesolve"
    assert result.metadata["expectation_values"] == {"n": [1.0, 1.25, 1.5]}
    assert result.metadata["final_expectations"] == {"n": 1.5}
    assert fake_qt.calls["sesolve"][0]["H"].label == "(1.5*num4)"
    assert fake_qt.calls["sesolve"][0]["psi0"].label == "basis(4,1)"


def test_qutip_mesolve_uses_collapse_operators(monkeypatch) -> None:
    fake_qt = _install_fake_qutip(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("qutip", solver_options={"method": "bdf"})
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
                "hamiltonian": [{"operator": "num", "coefficient": 1.0}],
                "collapse_operators": [{"operator": "destroy", "rate": 0.25}],
                "observables": [{"name": "n", "operator": "num"}],
            },
        }
    )

    result = driver.run(job)

    assert result.metadata["solver"] == "mesolve"
    assert result.metadata["expectation_values"] == {"n": [2.0, 1.0]}
    call = fake_qt.calls["mesolve"][0]
    assert call["c_ops"][0].label == "(0.5*destroy3)"
    assert call["options"] == {"method": "bdf", "progress_bar": ""}


def _install_fake_qutip(monkeypatch):
    qutip_module = types.ModuleType("qutip")
    qutip_module.calls = {"sesolve": [], "mesolve": []}

    class FakeQobj:
        def __init__(self, label):
            self.label = label

        def __rmul__(self, value):
            return FakeQobj(f"({value}*{self.label})")

        def __mul__(self, other):
            if isinstance(other, FakeQobj):
                return FakeQobj(f"({self.label}*{other.label})")
            return FakeQobj(f"({self.label}*{other})")

        def __add__(self, other):
            return FakeQobj(f"({self.label}+{other.label})")

        def dag(self):
            return FakeQobj(f"{self.label}.dag")

    class FakeResult:
        def __init__(self, expect):
            self.expect = expect
            self.stats = {"solver": "fake"}

    def basis(cutoff, n):
        return FakeQobj(f"basis({cutoff},{n})")

    def coherent(cutoff, alpha):
        return FakeQobj(f"coherent({cutoff},{alpha})")

    def fock_dm(cutoff, n):
        return FakeQobj(f"fock_dm({cutoff},{n})")

    def destroy(cutoff):
        return FakeQobj(f"destroy{cutoff}")

    def create(cutoff):
        return FakeQobj(f"create{cutoff}")

    def num(cutoff):
        return FakeQobj(f"num{cutoff}")

    def qeye(cutoff):
        return FakeQobj(f"qeye{cutoff}")

    def position(cutoff):
        return FakeQobj(f"position{cutoff}")

    def momentum(cutoff):
        return FakeQobj(f"momentum{cutoff}")

    def Qobj(matrix):
        return FakeQobj(f"Qobj({matrix})")

    def sesolve(H, psi0, tlist, *, e_ops=None, args=None, options=None):
        qutip_module.calls["sesolve"].append(
            {"H": H, "psi0": psi0, "tlist": tlist, "e_ops": e_ops, "args": args, "options": options}
        )
        return FakeResult([[1.0, 1.25, 1.5]])

    def mesolve(H, rho0, tlist, *, c_ops=None, e_ops=None, args=None, options=None):
        qutip_module.calls["mesolve"].append(
            {
                "H": H,
                "rho0": rho0,
                "tlist": tlist,
                "c_ops": c_ops,
                "e_ops": e_ops,
                "args": args,
                "options": options,
            }
        )
        return FakeResult([[2.0, 1.0]])

    qutip_module.FakeQobj = FakeQobj
    qutip_module.Qobj = Qobj
    qutip_module.basis = basis
    qutip_module.coherent = coherent
    qutip_module.fock_dm = fock_dm
    qutip_module.destroy = destroy
    qutip_module.create = create
    qutip_module.num = num
    qutip_module.qeye = qeye
    qutip_module.position = position
    qutip_module.momentum = momentum
    qutip_module.sesolve = sesolve
    qutip_module.mesolve = mesolve

    monkeypatch.setitem(sys.modules, "qutip", qutip_module)
    return qutip_module
