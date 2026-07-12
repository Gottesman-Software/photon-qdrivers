import pytest

from photon_qdrivers import BackendUnavailableError, JobStatus, NativeRuntime, PhotonDriver


def _require_native_library() -> None:
    if not any(path.exists() for path in NativeRuntime.candidate_library_paths()):
        pytest.skip("Native runtime shared library has not been built yet.")


def test_native_runtime_wrapper_runs_compiled_cpp_runtime() -> None:
    _require_native_library()
    driver = PhotonDriver()
    driver.load_backend("native")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1]},
                {"gate": "PS", "mode": 0, "theta": 0.5},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 10,
        }
    )

    result = driver.run(job)

    assert result.backend_name == "native"
    assert result.status == JobStatus.COMPLETED
    assert result.shots == 10
    assert sum(result.counts.values()) == 10
    assert result.metadata["adapter"] == "native_runtime"
    assert result.metadata["execution"] == "cpp_runtime"


def test_native_runtime_fpga_mailbox_transport(tmp_path) -> None:
    _require_native_library()
    command_path = tmp_path / "fpga.commands"
    result_path = tmp_path / "fpga.results"

    driver = PhotonDriver()
    driver.load_backend(
        "native",
        transport="fpga_mailbox",
        command_path=str(command_path),
        result_path=str(result_path),
    )
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1]},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 12,
        }
    )
    result_path.write_text(
        "\n".join(
            [
                "PQDR_RESULT_V1",
                f"job_id={job.job_id}",
                "status=completed",
                "shots=12",
                "message=completed by pytest mailbox",
                "count=00:7",
                "count=11:5",
                "END",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = driver.run(job)

    assert result.status == JobStatus.COMPLETED
    assert result.counts == {"00": 7, "11": 5}
    assert result.metadata["transport"] == "fpga_mailbox"
    assert result.metadata["hardware_backed"] is True
    assert "job_id=" + job.job_id in command_path.read_text(encoding="utf-8")
    assert "operations=BS,photon_counting" in command_path.read_text(encoding="utf-8")


def test_native_runtime_red_pitaya_transport(tmp_path) -> None:
    _require_native_library()
    command_path = tmp_path / "red-pitaya.commands"
    result_path = tmp_path / "red-pitaya.results"

    driver = PhotonDriver()
    driver.load_backend(
        "native",
        transport="redpitaya",
        command_path=str(command_path),
        result_path=str(result_path),
    )
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "BS", "modes": [0, 1]},
                {"gate": "PS", "mode": 0, "theta": 0.25},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 16,
        }
    )
    result_path.write_text(
        "\n".join(
            [
                "PQDR_RESULT_V1",
                f"job_id={job.job_id}",
                "status=completed",
                "shots=16",
                "message=completed by pytest Red Pitaya mailbox",
                "count=00:9",
                "count=11:7",
                "END",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = driver.run(job)

    assert result.status == JobStatus.COMPLETED
    assert result.counts == {"00": 9, "11": 7}
    assert result.metadata["device"] == "red-pitaya-stemlab-125-14"
    assert result.metadata["transport"] == "red_pitaya"
    assert result.metadata["hardware_backed"] is True
    command_frame = command_path.read_text(encoding="utf-8")
    assert "job_id=" + job.job_id in command_frame
    assert "operations=BS,PS,photon_counting" in command_frame


def test_native_runtime_reports_missing_explicit_library() -> None:
    with pytest.raises(BackendUnavailableError, match="not found"):
        NativeRuntime("/missing/libphoton_qdrivers_capi.so")
