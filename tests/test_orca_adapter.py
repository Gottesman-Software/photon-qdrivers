import json
import sys
import types
import urllib.request

import pytest

from photon_qdrivers import BackendConfig, BackendUnavailableError, JobStatus, PhotonDriver


def test_orca_backend_requires_credentials_before_sdk_or_endpoint(monkeypatch) -> None:
    _block_default_orca_sdk_modules(monkeypatch)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="credentials"):
        driver.load_backend("orca")


def test_orca_backend_with_credentials_requires_sdk_or_endpoint(monkeypatch) -> None:
    _block_default_orca_sdk_modules(monkeypatch)

    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="orca",
        credentials={"token": "secret-token"},
    )

    with pytest.raises(BackendUnavailableError, match="photon-qdrivers-orca"):
        driver.load_backend("orca", config=config)


def test_orca_adapter_runs_private_sdk_job(monkeypatch) -> None:
    fake_orca = types.ModuleType("orca_quantum")

    class Client:
        latest = None

        def __init__(self, token=None, endpoint=None, device=None, profile=None, **kwargs):
            self.token = token
            self.endpoint = endpoint
            self.device = device
            self.profile = profile
            self.kwargs = kwargs
            self.submitted_payloads = []
            self.closed = False
            Client.latest = self

        def submit_job(self, payload):
            self.submitted_payloads.append(payload)
            return {
                "job_id": "orca-sdk-job-1",
                "status": "queued",
                "metadata": {"queue": "pt-2", "token": "secret-token"},
            }

        def get_job(self, provider_job_id):
            return {
                "job_id": provider_job_id,
                "status": "completed",
                "result": {"counts": {"10": 6, "01": 4}},
                "shots": 10,
                "metadata": {"queue": "pt-2", "api_key": "secret-key"},
            }

        def cancel_job(self, provider_job_id):
            return True

        def close(self):
            self.closed = True

    fake_orca.Client = Client
    monkeypatch.setitem(sys.modules, "orca_quantum", fake_orca)

    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="orca",
        endpoint="https://orca.private.example/api",
        profile="lab",
        credentials={"token": "secret-token"},
        options={
            "sdk_module": "orca_quantum",
            "device": "pt-2-test",
            "application": "hybrid-optimization",
            "poll_interval_seconds": 0,
        },
    )
    backend = driver.load_backend("orca", config=config)
    job = driver.compile(_circuit(shots=10))

    result = driver.run(job)

    assert backend.name == "orca"
    assert result.status == JobStatus.COMPLETED
    assert result.counts == {"10": 6, "01": 4}
    assert result.metadata["provider_job_id"] == "orca-sdk-job-1"
    assert result.metadata["provider_metadata"]["adapter"] == "orca_sdk"
    assert result.metadata["provider_metadata"]["device"] == "pt-2-test"
    assert result.metadata["provider_metadata"]["queue"] == "pt-2"
    assert result.metadata["provider_metadata"]["api_key"] == "<redacted>"
    assert "secret-token" not in str(result.metadata)
    assert "secret-key" not in str(result.metadata)

    assert Client.latest.token == "secret-token"
    assert Client.latest.endpoint == "https://orca.private.example/api"
    assert Client.latest.device == "pt-2-test"
    payload = Client.latest.submitted_payloads[0]
    assert payload["orca"] == {
        "adapter": "orca_hardware",
        "device": "pt-2-test",
        "profile": "lab",
        "workload_type": "photonic_circuit",
        "application": "hybrid-optimization",
    }
    assert payload["metadata"]["adapter"] == "orca_hardware"
    assert "secret-token" not in str(payload)


def test_orca_adapter_runs_rest_endpoint_job(monkeypatch) -> None:
    _block_default_orca_sdk_modules(monkeypatch)
    calls = []

    class FakeHTTPResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        calls.append((request, timeout))
        assert isinstance(request, urllib.request.Request)
        assert request.full_url == "https://orca.private.example/api/jobs"
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer secret-token"
        body = json.loads(request.data.decode("utf-8"))
        assert body["orca"]["device"] == "pt-1-bench"
        return FakeHTTPResponse(
            {
                "id": "orca-rest-job-1",
                "status": "completed",
                "counts": {"00": 3, "11": 2},
                "shots": 5,
                "metadata": {"queue": "rest", "token": "secret-token"},
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="orca",
        endpoint="https://orca.private.example/api",
        credentials={"token": "secret-token"},
        options={
            "device": "pt-1-bench",
            "poll_interval_seconds": 0,
            "http_timeout_seconds": 3,
        },
    )
    driver.load_backend("orca", config=config)
    job = driver.compile(_circuit(shots=5))

    result = driver.run(job)

    assert result.status == JobStatus.COMPLETED
    assert result.counts == {"00": 3, "11": 2}
    assert result.metadata["provider_job_id"] == "orca-rest-job-1"
    assert result.metadata["provider_metadata"]["adapter"] == "orca_rest"
    assert result.metadata["provider_metadata"]["token"] == "<redacted>"
    assert calls[0][1] == 3.0


def _block_default_orca_sdk_modules(monkeypatch) -> None:
    for module_name in ("orca_quantum", "orca_computing", "orca_sdk"):
        monkeypatch.setitem(sys.modules, module_name, None)


def _circuit(*, shots):
    return {
        "type": "photonic_circuit",
        "modes": 2,
        "operations": [
            {"gate": "BS", "modes": [0, 1]},
            {"gate": "PS", "mode": 0, "theta": 0.2},
            {"measure": "photon_counting", "modes": [0, 1]},
        ],
        "shots": shots,
    }
