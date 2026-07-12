import pytest

from photon_qdrivers import (
    BackendCapabilityError,
    BackendUnavailableError,
    CircuitValidationError,
    PhotonDriver,
    PhotonicJob,
    PhotonicResult,
)


def test_load_mock_backend() -> None:
    driver = PhotonDriver()

    backend = driver.load_backend("mock")

    assert backend.name == "mock"
    assert backend.initialized is True
    assert driver.list_backends() == [
        "dynamiqs",
        "emulator",
        "lightworks",
        "mock",
        "native",
        "orca",
        "pennylane-sf",
        "perceval",
        "piquasso",
        "psiquantum",
        "quandela",
        "qutip",
        "strawberryfields",
        "thewalrus",
        "xanadu",
    ]


def test_compile_job() -> None:
    driver = PhotonDriver()
    driver.load_backend("mock")

    job = driver.compile({"type": "photonic_circuit", "modes": 2, "operations": [], "shots": 25})

    assert isinstance(job, PhotonicJob)
    assert job.backend_name == "mock"
    assert job.shots == 25
    assert job.circuit.modes == 2
    assert job.metadata["modes"] == 2


def test_backend_names_are_normalized() -> None:
    driver = PhotonDriver()

    backend = driver.load_backend(" MOCK ")

    assert backend.name == "mock"


def test_run_returns_typed_mapping_result() -> None:
    driver = PhotonDriver()
    driver.load_backend("mock")
    job = driver.compile({"type": "photonic_circuit", "modes": 2, "operations": [], "shots": 25})

    result = driver.run(job)

    assert isinstance(result, PhotonicResult)
    assert result["backend_name"] == "mock"
    assert result.total_counts == 25


def test_compile_rejects_invalid_mode_reference() -> None:
    driver = PhotonDriver()
    driver.load_backend("mock")

    with pytest.raises(CircuitValidationError):
        driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "operations": [{"gate": "BS", "modes": [0, 2]}],
                "shots": 25,
            }
        )


def test_compile_rejects_unsupported_operation() -> None:
    driver = PhotonDriver()
    driver.load_backend("mock")

    with pytest.raises(BackendCapabilityError):
        driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "operations": [{"gate": "UNKNOWN", "modes": [0, 1]}],
                "shots": 25,
            }
        )


def test_registered_vendor_backend_reports_unavailable() -> None:
    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="xanadu"):
        driver.load_backend("xanadu")


def test_registered_emulator_backend_reports_unavailable() -> None:
    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="pennylane-sf"):
        driver.load_backend("pennylane-sf")
