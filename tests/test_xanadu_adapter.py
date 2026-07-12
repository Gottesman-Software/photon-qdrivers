import sys
import types

import pytest

from photon_qdrivers import BackendConfig, BackendUnavailableError, JobStatus, PhotonDriver


def test_xanadu_backend_requires_credentials_before_legacy_sdk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "strawberryfields", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="credentials"):
        driver.load_backend("xanadu")


def test_xanadu_backend_with_credentials_requires_legacy_sdk(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "strawberryfields", None)

    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="xanadu",
        credentials={"api_key": "secret-token"},
    )

    with pytest.raises(BackendUnavailableError, match="strawberryfields"):
        driver.load_backend("xanadu", config=config)


def test_xanadu_adapter_runs_legacy_remote_engine_job(monkeypatch) -> None:
    fake_sf, fake_xcc = _install_fake_xanadu_sdk(monkeypatch)
    driver = PhotonDriver()
    config = BackendConfig(
        backend_name="xanadu",
        endpoint="https://platform.test.xanadu.ai:443",
        credentials={"api_key": "secret-token"},
        options={
            "target": "X8_01",
            "backend_options": {"chip": "legacy-test"},
            "compile_options": {"compiler": "Xunitary"},
            "poll_interval_seconds": 0,
        },
    )
    backend = driver.load_backend("xanadu", config=config)
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [
                {"gate": "S", "mode": 0, "r": 0.2},
                {"gate": "BS", "modes": [0, 1], "theta": 0.785, "phi": 0.1},
                {"gate": "PS", "mode": 1, "theta": 0.3},
                {"measure": "photon_counting", "modes": [0, 1]},
            ],
            "shots": 4,
            "metadata": {
                "input_state": [1, 0],
                "compile_options": {"shots_compiler_hint": 4},
                "recompile": True,
            },
        }
    )

    result = driver.run(job)

    assert backend.name == "xanadu"
    assert result.status == JobStatus.COMPLETED
    assert result.counts == {"|1,0>": 3, "|0,1>": 1}
    assert result.metadata["provider_job_id"] == "xanadu-job-1"
    assert result.metadata["provider_status"] == "complete"
    assert result.metadata["provider_metadata"]["adapter"] == "strawberryfields_remote_engine"
    assert result.metadata["provider_metadata"]["legacy_cloud"] is True
    assert result.metadata["provider_metadata"]["provider_metadata"]["queue"] == "test"
    assert "secret-token" not in str(result.metadata)

    assert fake_xcc.last_connection.refresh_token == "secret-token"
    assert fake_xcc.last_connection.host == "platform.test.xanadu.ai"
    assert fake_xcc.last_connection.port == 443
    assert fake_xcc.last_connection.tls is True
    assert fake_sf.last_engine.target == "X8_01"
    assert fake_sf.last_engine.backend_options == {"chip": "legacy-test"}
    assert fake_sf.last_engine.last_run_kwargs == {
        "shots": 4,
        "compile_options": {"compiler": "Xunitary", "shots_compiler_hint": 4},
        "recompile": True,
    }
    assert fake_sf.last_program.operations == [
        ("Fock", (1,), "q0"),
        ("Sgate", (0.2, 0.0), "q0"),
        ("BSgate", (0.785, 0.1), ("q0", "q1")),
        ("Rgate", (0.3,), "q1"),
        ("MeasureFock", (), ["q0", "q1"]),
    ]


def _install_fake_xanadu_sdk(monkeypatch):
    strawberryfields_module = types.ModuleType("strawberryfields")
    ops_module = types.ModuleType("strawberryfields.ops")
    xcc_module = types.ModuleType("xcc")
    strawberryfields_module.__path__ = []
    strawberryfields_module.last_engine = None
    strawberryfields_module.last_program = None
    xcc_module.last_connection = None

    class FakeProgramContext:
        def __init__(self, program):
            self.program = program

        def __enter__(self):
            return self.program.registers

        def __exit__(self, exc_type, exc, traceback):
            return False

    class Program:
        def __init__(self, modes):
            self.modes = modes
            self.registers = [f"q{mode}" for mode in range(modes)]
            self.operations = []
            self.context = FakeProgramContext(self)
            strawberryfields_module.last_program = self

    class Operation:
        name = ""

        def __init__(self, *parameters):
            self.parameters = parameters

        def __or__(self, target):
            strawberryfields_module.last_program.operations.append(
                (self.name, self.parameters, target)
            )
            return self

    class Fock(Operation):
        name = "Fock"

    class BSgate(Operation):
        name = "BSgate"

    class Rgate(Operation):
        name = "Rgate"

    class Sgate(Operation):
        name = "Sgate"

    class Dgate(Operation):
        name = "Dgate"

    class MeasureFock(Operation):
        name = "MeasureFock"

    class Connection:
        def __init__(
            self,
            refresh_token=None,
            access_token=None,
            host="platform.xanadu.ai",
            port=443,
            tls=True,
            headers=None,
        ):
            self.refresh_token = refresh_token
            self.access_token = access_token
            self.host = host
            self.port = port
            self.tls = tls
            self.headers = headers
            xcc_module.last_connection = self

    class Job:
        def __init__(self, id_, connection):
            self.id = id_
            self.connection = connection
            self.status_calls = 0
            self.metadata = {"queue": "test"}
            self.target = "X8_01"
            self.cancelled = False

        def clear(self):
            return None

        @property
        def status(self):
            self.status_calls += 1
            if self.cancelled:
                return "cancelled"
            if self.status_calls == 1:
                return "queued"
            return "complete"

        @property
        def result(self):
            return {
                "output": [[(1, 0), (1, 0), (0, 1), (1, 0)]],
                "meta": "complete",
            }

        def cancel(self):
            self.cancelled = True

    class RemoteEngine:
        def __init__(self, target, connection=None, backend_options=None):
            self.target = target
            self.connection = connection
            self.backend_options = backend_options
            self.last_run_kwargs = None
            strawberryfields_module.last_engine = self

        def run_async(self, program, **kwargs):
            assert program is strawberryfields_module.last_program
            self.last_run_kwargs = kwargs
            return Job("xanadu-job-1", self.connection)

    strawberryfields_module.Program = Program
    strawberryfields_module.RemoteEngine = RemoteEngine
    ops_module.Fock = Fock
    ops_module.BSgate = BSgate
    ops_module.Rgate = Rgate
    ops_module.Sgate = Sgate
    ops_module.Dgate = Dgate
    ops_module.MeasureFock = MeasureFock
    xcc_module.Connection = Connection
    xcc_module.Job = Job

    monkeypatch.setitem(sys.modules, "strawberryfields", strawberryfields_module)
    monkeypatch.setitem(sys.modules, "strawberryfields.ops", ops_module)
    monkeypatch.setitem(sys.modules, "xcc", xcc_module)
    return strawberryfields_module, xcc_module
