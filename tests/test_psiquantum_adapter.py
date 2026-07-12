import sys
import types

import pytest

from photon_qdrivers import BackendConfig, BackendUnavailableError, JobStatus, PhotonDriver


def test_psiquantum_backend_requires_psiqdk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "psiqdk", None)
    monkeypatch.setitem(sys.modules, "psiqdk.workbench", None)
    monkeypatch.setitem(sys.modules, "psiqdk.workbench.qre", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="psiqdk"):
        driver.load_backend("psiquantum")


def test_psiquantum_adapter_runs_resource_estimate(monkeypatch) -> None:
    fake = _install_fake_psiqdk(monkeypatch)

    driver = PhotonDriver()
    backend = driver.load_backend("psiquantum")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "H", "mode": 0},
                {"gate": "CNOT", "modes": [0, 1]},
                {"measure": "logical_measure", "modes": [0, 1]},
            ],
            "shots": 10,
            "metadata": {
                "model": "resource_estimate",
                "logical_qubits": 2,
                "strict_operation_mapping": True,
            },
        }
    )

    result = driver.run(job)

    assert backend.name == "psiquantum"
    assert result.status == JobStatus.COMPLETED
    assert result.counts == {}
    assert result.metadata["adapter"] == "psiqdk"
    assert result.metadata["execution"] == "ftqc_software"
    assert result.metadata["real_hardware"] is False
    assert result.metadata["provider_metadata"]["resources"] == {
        "logical_qubits": 2,
        "operation_count": 3,
        "t_count": 12,
        "surface_code_cycles": 96,
    }
    assert result.metadata["operation_mapping"] == {
        "applied": ["H", "CNOT", "logical_measure"],
        "skipped": [],
    }
    assert fake.last_qpu.operations == [
        ("h", (0,), {}),
        ("cnot", (0, 1), {}),
        ("measure", (0, 1), {}),
    ]


def test_psiquantum_adapter_runs_simulation(monkeypatch) -> None:
    _install_fake_psiqdk(monkeypatch)

    driver = PhotonDriver()
    driver.load_backend("psiquantum")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 1,
            "operations": [
                {"gate": "X", "mode": 0},
                {"measure": "measure", "mode": 0},
            ],
            "shots": 4,
            "metadata": {"model": "simulate", "strict_operation_mapping": True},
        }
    )

    result = driver.run(job)

    assert result.status == JobStatus.COMPLETED
    assert result.counts == {"1": 4}
    assert result.metadata["result_kind"] == "simulation"
    assert result.metadata["provider_metadata"] == {
        "logical_qubits": 1,
        "operation_count": 2,
    }


def test_psiquantum_adapter_accepts_custom_module_names(monkeypatch) -> None:
    _install_fake_psiqdk(
        monkeypatch,
        sdk_module="custom_psiq",
        workbench_module="custom_psiq.wb",
        qre_module="custom_psiq.wb.resources",
    )

    driver = PhotonDriver()
    driver.load_backend(
        "psiquantum",
        config=BackendConfig(
            backend_name="psiquantum",
            options={
                "sdk_module": "custom_psiq",
                "workbench_module": "custom_psiq.wb",
                "qre_module": "custom_psiq.wb.resources",
            },
        ),
    )
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 1,
            "operations": [{"gate": "T", "mode": 0}],
            "shots": 1,
            "metadata": {"model": "resource_estimate"},
        }
    )

    result = driver.run(job)

    assert result.status == JobStatus.COMPLETED
    assert result.metadata["sdk_module"] == "custom_psiq"


def _install_fake_psiqdk(
    monkeypatch,
    *,
    sdk_module="psiqdk",
    workbench_module="psiqdk.workbench",
    qre_module="psiqdk.workbench.qre",
):
    fake = types.SimpleNamespace(last_qpu=None)
    sdk = types.ModuleType(sdk_module)
    workbench = types.ModuleType(workbench_module)
    qre = types.ModuleType(qre_module)

    class QPU:
        def __init__(self, num_qubits=None, **kwargs):
            self.num_qubits = num_qubits
            self.kwargs = kwargs
            self.operations = []
            fake.last_qpu = self

        def h(self, *args, **kwargs):
            self.operations.append(("h", args, kwargs))

        def x(self, *args, **kwargs):
            self.operations.append(("x", args, kwargs))

        def t(self, *args, **kwargs):
            self.operations.append(("t", args, kwargs))

        def cnot(self, *args, **kwargs):
            self.operations.append(("cnot", args, kwargs))

        def measure(self, *args, **kwargs):
            self.operations.append(("measure", args, kwargs))

        def simulate(self):
            return {
                "counts": {"1": 4},
                "logical_qubits": self.num_qubits,
                "operation_count": len(self.operations),
            }

    class Qubits:
        def __init__(self, size, name, qpu):
            self.size = size
            self.name = name
            self.qpu = qpu

    class ResourceEstimator:
        def __init__(self, qpu):
            self.qpu = qpu

        def resources(self):
            return {
                "logical_qubits": self.qpu.num_qubits,
                "operation_count": len(self.qpu.operations),
                "t_count": 12,
                "surface_code_cycles": 96,
            }

    def resource_estimator(qpu):
        return ResourceEstimator(qpu)

    workbench.QPU = QPU
    workbench.Qubits = Qubits
    qre.resource_estimator = resource_estimator

    monkeypatch.setitem(sys.modules, sdk_module, sdk)
    monkeypatch.setitem(sys.modules, workbench_module, workbench)
    monkeypatch.setitem(sys.modules, qre_module, qre)
    return fake
