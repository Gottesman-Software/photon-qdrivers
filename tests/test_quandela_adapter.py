import sys
import types

import pytest

from photon_qdrivers import BackendConfig, BackendUnavailableError, JobStatus, PhotonDriver


def test_quandela_backend_requires_credentials_before_sdk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "perceval", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="credentials"):
        driver.load_backend("quandela")


def test_quandela_backend_with_credentials_requires_perceval_sdk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "perceval", None)

    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="quandela",
        credentials={"token": "secret-token"},
    )

    with pytest.raises(BackendUnavailableError, match="perceval-quandela"):
        driver.load_backend("quandela", config=config)


def test_quandela_adapter_runs_remote_perceval_job(monkeypatch) -> None:
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

    class FakeRemoteProcessor:
        latest = None

        def __init__(self, name, token=None, url=None, m=None, proxies=None):
            self.name = name
            self.token = token
            self.url = url
            self.m = m
            self.proxies = proxies
            self.circuit = None
            self.input_state = None
            self.min_detected_photons = None
            FakeRemoteProcessor.latest = self

        def set_circuit(self, circuit):
            self.circuit = circuit
            return self

        def min_detected_photons_filter(self, value):
            self.min_detected_photons = value

        def with_input(self, input_state):
            self.input_state = input_state

    class FakeStatus:
        def __init__(self, status):
            self.status = status
            self.progress = 1.0 if status == "success" else 0.0
            self.stop_message = None

    class FakeRemoteJob:
        def __init__(self):
            self.id = "provider-quandela-1"
            self.shots = None
            self.status_calls = 0
            self.cancelled = False

        def execute_async(self, shots):
            self.shots = shots
            return self

        @property
        def status(self):
            self.status_calls += 1
            if self.cancelled:
                return FakeStatus("canceled")
            if self.status_calls == 1:
                return FakeStatus("waiting")
            return FakeStatus("success")

        def get_results(self):
            return {
                "results": {FakeBasicState([1, 0]): self.shots},
                "physical_perf": 0.91,
            }

        def cancel(self):
            self.cancelled = True

    class FakeSampler:
        latest = None

        def __init__(self, processor, **kwargs):
            self.processor = processor
            self.kwargs = kwargs
            self.remote_job = FakeRemoteJob()
            FakeSampler.latest = self

        @property
        def sample_count(self):
            return self.remote_job

    perceval_module.BasicState = FakeBasicState
    perceval_module.BS = FakeBS
    perceval_module.Circuit = FakeCircuit
    perceval_module.PS = FakePS
    perceval_module.RemoteProcessor = FakeRemoteProcessor
    algorithm_module.Sampler = FakeSampler
    monkeypatch.setitem(sys.modules, "perceval", perceval_module)
    monkeypatch.setitem(sys.modules, "perceval.algorithm", algorithm_module)

    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="quandela",
        endpoint="https://cloud.quandela.example",
        credentials={"token": "secret-token"},
        options={
            "device": "qpu:test",
            "max_shots_per_call": 100,
            "min_detected_photons": 1,
            "poll_interval_seconds": 0,
        },
    )
    backend = driver.load_backend("quandela", config=config)
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

    assert backend.name == "quandela"
    assert result.status == JobStatus.COMPLETED
    assert result.counts == {"|1,0>": 25}
    assert result.metadata["provider_job_id"] == "provider-quandela-1"
    assert result.metadata["provider_metadata"]["adapter"] == "perceval_remote_processor"
    assert result.metadata["provider_metadata"]["physical_perf"] == 0.91
    assert result.metadata["real_hardware"] is True
    assert "secret-token" not in str(result.metadata)

    assert FakeRemoteProcessor.latest.name == "qpu:test"
    assert FakeRemoteProcessor.latest.token == "secret-token"
    assert FakeRemoteProcessor.latest.url == "https://cloud.quandela.example"
    assert FakeRemoteProcessor.latest.m == 2
    assert FakeRemoteProcessor.latest.min_detected_photons == 1
    assert str(FakeRemoteProcessor.latest.input_state) == "|1,1>"
    assert FakeSampler.latest.kwargs["max_shots_per_call"] == 100
