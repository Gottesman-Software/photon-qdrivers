import sys
import types

import pytest

from photon_qdrivers import BackendUnavailableError, PhotonDriver


def test_perceval_missing_dependency_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "perceval", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="perceval-quandela"):
        driver.load_backend("perceval")


def test_perceval_adapter_runs_against_optional_sdk_shape(monkeypatch) -> None:
    perceval_module = types.ModuleType("perceval")
    algorithm_module = types.ModuleType("perceval.algorithm")

    class FakeBasicState:
        def __init__(self, state):
            self.state = state

        def __str__(self):
            if isinstance(self.state, str):
                return self.state
            return "|" + ",".join(str(value) for value in self.state) + ">"

        def __hash__(self):
            return hash(str(self))

        def __eq__(self, other):
            return str(self) == str(other)

    class FakeCircuit:
        def __init__(self, modes):
            self.modes = modes
            self.operations = []

        def add(self, target, component):
            self.operations.append((target, component))

    class FakeBS:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakePS:
        def __init__(self, theta):
            self.theta = theta

    class FakeProcessor:
        def __init__(self, backend_name, circuit):
            self.backend_name = backend_name
            self.circuit = circuit
            self.input_state = None
            self.min_detected_photons = None

        def min_detected_photons_filter(self, value):
            self.min_detected_photons = value

        def with_input(self, input_state):
            self.input_state = input_state

    class FakeSampler:
        def __init__(self, processor):
            self.processor = processor

        def sample_count(self, shots):
            return {"results": {FakeBasicState([1, 0]): shots}}

    perceval_module.BasicState = FakeBasicState
    perceval_module.BS = FakeBS
    perceval_module.Circuit = FakeCircuit
    perceval_module.PS = FakePS
    perceval_module.Processor = FakeProcessor
    algorithm_module.Sampler = FakeSampler
    monkeypatch.setitem(sys.modules, "perceval", perceval_module)
    monkeypatch.setitem(sys.modules, "perceval.algorithm", algorithm_module)

    driver = PhotonDriver()
    driver.load_backend("perceval", processor_backend="SLOS", min_detected_photons=1)
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1]},
                {"gate": "PS", "mode": 0, "theta": 0.5},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 25,
            "metadata": {"input_state": [1, 1]},
        }
    )

    result = driver.run(job)

    assert result.backend_name == "perceval"
    assert result.counts == {"|1,0>": 25}
    assert result.metadata["adapter"] == "perceval"
