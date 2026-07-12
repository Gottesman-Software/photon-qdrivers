import pytest

from photon_qdrivers import (
    BackendConfig,
    BackendExecutionError,
    BackendUnavailableError,
    CloudHardwareBackend,
    CloudJobSnapshot,
    CloudJobState,
    JobStatus,
    JobTimeoutError,
    PhotonDriver,
)
from photon_qdrivers.cloud import normalize_cloud_job_state, redact_sensitive_mapping


def test_cloud_status_normalization_accepts_common_provider_terms() -> None:
    assert normalize_cloud_job_state("submitted") == CloudJobState.QUEUED
    assert normalize_cloud_job_state("executing") == CloudJobState.RUNNING
    assert normalize_cloud_job_state("succeeded") == CloudJobState.COMPLETED
    assert normalize_cloud_job_state("canceled") == CloudJobState.CANCELLED


def test_cloud_metadata_redaction_removes_secret_values() -> None:
    redacted = redact_sensitive_mapping(
        {
            "token": "secret-token",
            "nested": {"api_key": "secret-key", "device": "qpu-1"},
            "shots": 100,
        }
    )

    assert redacted == {
        "token": "<redacted>",
        "nested": {"api_key": "<redacted>", "device": "qpu-1"},
        "shots": 100,
    }


def test_backend_config_reads_hardware_env_without_public_secret_leak(monkeypatch) -> None:
    monkeypatch.setenv("PHOTON_QDRIVERS_XANADU_CLIENT_ID", "client-id")
    monkeypatch.setenv("PHOTON_QDRIVERS_XANADU_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PHOTON_QDRIVERS_XANADU_DEVICE_ID", "device-1")
    monkeypatch.setenv("PHOTON_QDRIVERS_XANADU_PROJECT_ID", "project-1")

    config = BackendConfig.from_env("xanadu")

    assert config.credentials == {
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
    assert config.options == {"device_id": "device-1", "project_id": "project-1"}
    assert config.public_dict()["credentials_configured"] == ["client_id", "client_secret"]
    assert "client-secret" not in str(config.public_dict())


def test_vendor_backend_requires_credentials_before_sdk_adapter() -> None:
    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="credentials"):
        driver.load_backend("xanadu")


def test_vendor_backend_with_credentials_reports_missing_adapter_package() -> None:
    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="orca",
        credentials={"token": "secret-token"},
    )

    with pytest.raises(BackendUnavailableError, match="photon-qdrivers-orca"):
        driver.load_backend("orca", config=config)


def test_cloud_hardware_backend_runs_fake_provider_job() -> None:
    client = FakeCloudClient(
        submit_snapshot={"job_id": "provider-1", "status": "queued"},
        poll_snapshots=[
            {
                "job_id": "provider-1",
                "status": "succeeded",
                "counts": {"|1,0>": 5},
                "shots": 5,
                "metadata": {"provider": "fake", "token": "secret-token"},
            }
        ],
    )
    driver = PhotonDriver()
    driver.register_backend("fakehardware", lambda config: FakeHardwareBackend(config, client))
    driver.load_backend(
        "fakehardware",
        config=BackendConfig(
            backend_name="fakehardware",
            credentials={"api_key": "secret-key"},
            options={"poll_interval_seconds": 0},
        ),
    )
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [{"measure": "photon_counting", "modes": [0, 1]}],
            "shots": 5,
        }
    )

    result = driver.run(job)

    assert result.status == JobStatus.COMPLETED
    assert result.counts == {"|1,0>": 5}
    assert result.metadata["provider_job_id"] == "provider-1"
    assert result.metadata["provider_metadata"]["token"] == "<redacted>"
    assert client.submitted_payloads[0]["metadata"]["config"]["credentials_configured"] == [
        "api_key"
    ]
    assert "secret-key" not in str(client.submitted_payloads[0])


def test_cloud_hardware_backend_failed_provider_job_raises() -> None:
    client = FakeCloudClient(
        submit_snapshot={
            "job_id": "provider-1",
            "status": "failed",
            "error": "calibration window closed",
        },
        poll_snapshots=[],
    )
    driver = PhotonDriver()
    driver.register_backend("fakehardware", lambda config: FakeHardwareBackend(config, client))
    driver.load_backend(
        "fakehardware",
        config=BackendConfig(
            backend_name="fakehardware",
            credentials={"token": "secret-token"},
            options={"poll_interval_seconds": 0},
        ),
    )
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [{"measure": "photon_counting", "modes": [0, 1]}],
            "shots": 5,
        }
    )

    with pytest.raises(BackendExecutionError, match="calibration window closed"):
        driver.run(job)


def test_cloud_hardware_backend_timeout_requests_provider_cancel() -> None:
    client = FakeCloudClient(
        submit_snapshot={"job_id": "provider-1", "status": "queued"},
        poll_snapshots=[{"job_id": "provider-1", "status": "running"}],
    )
    driver = PhotonDriver()
    driver.register_backend("fakehardware", lambda config: FakeHardwareBackend(config, client))
    driver.load_backend(
        "fakehardware",
        config=BackendConfig(
            backend_name="fakehardware",
            timeout_seconds=0,
            credentials={"token": "secret-token"},
            options={"poll_interval_seconds": 0},
        ),
    )
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [{"measure": "photon_counting", "modes": [0, 1]}],
            "shots": 5,
        }
    )

    with pytest.raises(JobTimeoutError):
        driver.run(job)

    assert client.cancelled_provider_jobs == ["provider-1"]


def test_cloud_snapshot_from_mapping_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="Unknown cloud job status"):
        CloudJobSnapshot.from_mapping({"job_id": "provider-1", "status": "mystery"})


class FakeHardwareBackend(CloudHardwareBackend):
    name = "fakehardware"
    target_name = "Fake Hardware"
    package_hint = "photon-qdrivers-fakehardware"
    supported_operations = ("photon_counting",)

    def __init__(self, config, client):
        self.fake_client = client
        super().__init__(config)

    def _create_client(self):
        return self.fake_client


class FakeCloudClient:
    def __init__(self, *, submit_snapshot, poll_snapshots):
        self.submit_snapshot = submit_snapshot
        self.poll_snapshots = list(poll_snapshots)
        self.submitted_payloads = []
        self.cancelled_provider_jobs = []
        self.closed = False

    def submit_job(self, payload):
        self.submitted_payloads.append(payload)
        return self.submit_snapshot

    def get_job(self, provider_job_id):
        if self.poll_snapshots:
            return self.poll_snapshots.pop(0)
        return {"job_id": provider_job_id, "status": "running"}

    def cancel_job(self, provider_job_id):
        self.cancelled_provider_jobs.append(provider_job_id)
        return True

    def close(self):
        self.closed = True
