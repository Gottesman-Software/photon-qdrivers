from photon_qdrivers import PhotonDriver


def test_run_job_returns_structured_counts() -> None:
    driver = PhotonDriver()
    driver.load_backend("mock")
    job = driver.compile({"type": "photonic_circuit", "modes": 2, "operations": [], "shots": 10})

    result = driver.run(job)

    assert result["backend_name"] == "mock"
    assert result["status"] == "completed"
    assert result["shots"] == 10
    assert sum(result["counts"].values()) == 10
    assert result["metadata"]["real_hardware"] is False


def test_local_emulator_backend_runs_validated_circuit() -> None:
    driver = PhotonDriver()
    driver.load_backend("emulator")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 3,
            "operations": [
                {"gate": "BS", "modes": [0, 1]},
                {"gate": "PS", "mode": 0, "theta": 0.25},
                {"measure": "photon_counting", "modes": [0, 1, 2]},
            ],
            "shots": 99,
        }
    )

    first_result = driver.run(job)
    second_result = driver.run(job)

    assert first_result["backend_name"] == "emulator"
    assert first_result["metadata"]["execution"] == "local_emulator"
    assert first_result["metadata"]["real_hardware"] is False
    assert sum(first_result["counts"].values()) == 99
    assert first_result["counts"] == second_result["counts"]
