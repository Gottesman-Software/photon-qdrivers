import time

import pytest

from photon_qdrivers import BackendConfig, JobStatus, JobTimeoutError, PhotonDriver
from photon_qdrivers.backends.mock_backend import MockPhotonicBackend


def test_load_backend_accepts_config_options() -> None:
    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="mock",
        profile="local",
        timeout_seconds=5.0,
        options={"label": "test"},
    )

    backend = driver.load_backend("mock", config=config, min_detected_photons=1)

    assert backend.config.profile == "local"
    assert backend.config.timeout_seconds == 5.0
    assert backend.config.options == {"label": "test", "min_detected_photons": 1}


def test_load_backend_still_supports_zero_argument_factories() -> None:
    class NoConfigBackend(MockPhotonicBackend):
        name = "noconfig"

        def __init__(self):
            super().__init__()

    driver = PhotonDriver()
    driver.register_backend("noconfig", NoConfigBackend)

    backend = driver.load_backend("noconfig")

    assert backend.name == "noconfig"


def test_submit_returns_async_handle() -> None:
    driver = PhotonDriver()
    driver.load_backend("mock")
    job = driver.compile({"type": "photonic_circuit", "modes": 2, "operations": [], "shots": 10})

    handle = driver.submit(job)
    result = handle.result(timeout=1.0)

    assert handle.done() is True
    assert handle.status == JobStatus.COMPLETED
    assert result.total_counts == 10


def test_cancel_marks_job_for_backend() -> None:
    driver = PhotonDriver()
    driver.load_backend("mock")
    job = driver.compile({"type": "photonic_circuit", "modes": 2, "operations": [], "shots": 10})

    assert driver.cancel(job.job_id) is True
    result = driver.run(job)

    assert result.status == JobStatus.CANCELLED
    assert result["metadata"]["cancelled"] is True


def test_run_timeout_raises_and_requests_cancel() -> None:
    class SlowBackend(MockPhotonicBackend):
        name = "slow"

        def run(self, job):
            time.sleep(0.05)
            return super().run(job)

    driver = PhotonDriver()
    driver.register_backend("slow", SlowBackend)
    driver.load_backend("slow")
    job = driver.compile({"type": "photonic_circuit", "modes": 2, "operations": [], "shots": 10})

    with pytest.raises(JobTimeoutError):
        driver.run(job, timeout=0.001)

    assert driver.cancel(job.job_id) is True
