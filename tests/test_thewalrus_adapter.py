import sys
import types

import pytest

from photon_qdrivers import BackendUnavailableError, CircuitValidationError, PhotonDriver


def test_thewalrus_missing_dependency_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "thewalrus", None)

    driver = PhotonDriver()

    with pytest.raises(BackendUnavailableError, match="thewalrus"):
        driver.load_backend("thewalrus")


def test_thewalrus_compile_requires_kernel_matrix(monkeypatch) -> None:
    _install_fake_thewalrus(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("thewalrus")

    with pytest.raises(CircuitValidationError, match="matrix"):
        driver.compile(
            {
                "type": "photonic_circuit",
                "modes": 2,
                "operations": [{"measure": "photon_counting", "modes": [0, 1]}],
                "shots": 10,
                "metadata": {"kernel": "hafnian"},
            }
        )


def test_thewalrus_hafnian_kernel_runs_against_optional_sdk_shape(monkeypatch) -> None:
    fake_tw = _install_fake_thewalrus(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("thewalrus")
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [{"measure": "photon_counting", "modes": [0, 1]}],
            "shots": 10,
            "metadata": {
                "kernel": "hafnian",
                "matrix": [[0.0, 1.0], [1.0, 0.0]],
            },
        }
    )

    result = driver.run(job)

    assert result.backend_name == "thewalrus"
    assert result.counts == {}
    assert result.metadata["kernel"] == "hafnian"
    assert result.metadata["kernel_result"] == 2.0
    assert fake_tw.calls["hafnian"] == [([[0.0, 1.0], [1.0, 0.0]], {})]


def test_thewalrus_probabilities_kernel_returns_count_projection(monkeypatch) -> None:
    _install_fake_thewalrus(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("thewalrus", max_probability_entries=3)
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 1,
            "operations": [{"measure": "photon_counting", "modes": [0]}],
            "shots": 100,
            "metadata": {
                "kernel": "probabilities",
                "mu": [0.0, 0.0],
                "cov": [[1.0, 0.0], [0.0, 1.0]],
                "cutoff": 3,
            },
        }
    )

    result = driver.run(job)

    assert result.counts == {"|0>": 50, "|1>": 25, "|2>": 25}
    assert result.metadata["result_format"] == "fock_probability_tensor"
    assert result.metadata["top_probabilities"][0] == {"state": "|0>", "probability": 0.5}


def test_thewalrus_hafnian_sample_graph_returns_counts(monkeypatch) -> None:
    _install_fake_thewalrus(monkeypatch)
    driver = PhotonDriver()
    driver.load_backend("thewalrus", cutoff=4)
    job = driver.compile(
        {
            "type": "photonic_circuit",
            "modes": 2,
            "operations": [{"measure": "photon_counting", "modes": [0, 1]}],
            "shots": 4,
            "metadata": {
                "kernel": "hafnian_sample_graph",
                "adjacency_matrix": [[0.0, 1.0], [1.0, 0.0]],
                "n_mean": 2.0,
            },
        }
    )

    result = driver.run(job)

    assert result.counts == {"|1,0>": 3, "|0,1>": 1}
    assert result.metadata["result_format"] == "hafnian_graph_samples"
    assert result.metadata["sample_count"] == 4


def _install_fake_thewalrus(monkeypatch):
    thewalrus_module = types.ModuleType("thewalrus")
    thewalrus_module.__path__ = []
    quantum_module = types.ModuleType("thewalrus.quantum")
    samples_module = types.ModuleType("thewalrus.samples")
    thewalrus_module.calls = {"hafnian": [], "loop_hafnian": [], "tor": []}

    def hafnian(matrix, **kwargs):
        thewalrus_module.calls["hafnian"].append((_tolist(matrix), kwargs))
        return 2.0

    def loop_hafnian(matrix):
        thewalrus_module.calls["loop_hafnian"].append(_tolist(matrix))
        return 3.0

    def tor(matrix):
        thewalrus_module.calls["tor"].append(_tolist(matrix))
        return 4.0

    def probabilities(mu, cov, cutoff, **kwargs):
        assert _tolist(mu) == [0.0, 0.0]
        assert _tolist(cov) == [[1.0, 0.0], [0.0, 1.0]]
        assert cutoff == 3
        return [0.5, 0.25, 0.25]

    def hafnian_sample_graph(adjacency_matrix, n_mean, **kwargs):
        assert _tolist(adjacency_matrix) == [[0.0, 1.0], [1.0, 0.0]]
        assert n_mean == 2.0
        assert kwargs["samples"] == 4
        assert kwargs["cutoff"] == 4
        return [(1, 0), (1, 0), (0, 1), (1, 0)]

    thewalrus_module.hafnian = hafnian
    thewalrus_module.loop_hafnian = loop_hafnian
    thewalrus_module.tor = tor
    quantum_module.probabilities = probabilities
    samples_module.hafnian_sample_graph = hafnian_sample_graph

    monkeypatch.setitem(sys.modules, "thewalrus", thewalrus_module)
    monkeypatch.setitem(sys.modules, "thewalrus.quantum", quantum_module)
    monkeypatch.setitem(sys.modules, "thewalrus.samples", samples_module)
    return thewalrus_module


def _tolist(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    return value
