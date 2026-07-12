"""Optional QuTiP backend adapter for quantum-optics dynamics."""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import BackendUnavailableError, CircuitValidationError
from photon_qdrivers.ir import PhotonicCircuit
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


_SUPPORTED_MODELS = {"oscillator_dynamics"}
_SUPPORTED_SOLVERS = {"sesolve", "mesolve"}


class QuTiPBackend:
    """Adapter for QuTiP single-mode oscillator dynamics."""

    name = "qutip"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._qt: Any | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("photon_counting",),
            max_modes=1,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "qutip",
                "dependency": "qutip",
                "execution": "local",
                "supported_models": sorted(_SUPPORTED_MODELS),
                "supported_solvers": sorted(_SUPPORTED_SOLVERS),
            },
        )
        self.device = PhotonicDevice(
            name="qutip-oscillator-dynamics",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        try:
            self._qt = importlib.import_module("qutip")
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'qutip' requires the optional dependency 'qutip'. "
                "Install with `pip install photon-qdrivers[qutip]` or `pip install qutip`."
            ) from exc

        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        model = _validate_qutip_request(circuit)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "qutip",
                "model": model,
                "operation_count": len(circuit.operations),
                "modes": circuit.modes,
                "schema_version": circuit.schema_version,
                "config": self.config.public_dict(),
            },
        )

    def run(self, job: PhotonicJob) -> PhotonicResult:
        if not self.initialized:
            self.initialize()

        if job.job_id in self._cancelled_jobs:
            return PhotonicResult(
                job_id=job.job_id,
                backend_name=self.name,
                status=JobStatus.CANCELLED,
                shots=job.shots,
                counts={},
                metadata={"backend": self.name, "adapter": "qutip", "cancelled": True},
            )

        qt = self._require_qutip()
        execution = _build_execution(qt, job.circuit.metadata, self.config)
        result = _run_solver(qt, execution)
        metadata = _result_metadata(execution, result)

        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts={},
            metadata={
                "backend": self.name,
                "adapter": "qutip",
                "execution": "local_quantum_optics_dynamics",
                "device": self.device.name,
                "real_hardware": False,
                **metadata,
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True

    def _require_qutip(self) -> Any:
        if self._qt is None:
            raise BackendUnavailableError("QuTiP backend is not initialized.")
        return self._qt


def _validate_qutip_request(circuit: PhotonicCircuit) -> str:
    model = _normalize_model(circuit.metadata.get("model", "oscillator_dynamics"))
    if circuit.modes != 1:
        raise CircuitValidationError("QuTiP oscillator_dynamics currently supports exactly one mode.")

    cutoff = _positive_int(circuit.metadata.get("cutoff"), field_name="metadata.cutoff")
    if cutoff < 2:
        raise CircuitValidationError("QuTiP metadata.cutoff must be at least 2.")

    _parse_times(circuit.metadata.get("times"))
    _parse_initial_state(circuit.metadata.get("initial_state", {"kind": "fock", "n": 0}), cutoff)
    _parse_hamiltonian(circuit.metadata.get("hamiltonian"), cutoff)
    _parse_observables(circuit.metadata.get("observables", [{"name": "n", "operator": "num"}]), cutoff)
    _parse_collapse_operators(circuit.metadata.get("collapse_operators", []), cutoff)
    _normalize_solver(circuit.metadata.get("solver", "auto"))
    return model


def _build_execution(qt: Any, metadata: Mapping[str, Any], config: BackendConfig) -> dict[str, Any]:
    cutoff = _positive_int(metadata.get("cutoff"), field_name="metadata.cutoff")
    c_ops = [
        _build_collapse_operator(qt, collapse, cutoff)
        for collapse in _parse_collapse_operators(metadata.get("collapse_operators", []), cutoff)
    ]
    solver = _select_solver(metadata, config, has_collapse=bool(c_ops))
    observables = _parse_observables(
        metadata.get("observables", [{"name": "n", "operator": "num"}]),
        cutoff,
    )

    return {
        "model": _normalize_model(metadata.get("model", "oscillator_dynamics")),
        "solver": solver,
        "cutoff": cutoff,
        "times": _parse_times(metadata.get("times")),
        "hamiltonian": _build_hamiltonian(qt, metadata.get("hamiltonian"), cutoff),
        "initial_state": _build_initial_state(
            qt,
            _parse_initial_state(metadata.get("initial_state", {"kind": "fock", "n": 0}), cutoff),
            cutoff,
        ),
        "collapse_operators": c_ops,
        "observables": [
            (observable["name"], _build_operator(qt, observable["operator"], cutoff))
            for observable in observables
        ],
        "args": _parse_mapping(metadata.get("args", {}), field_name="metadata.args"),
        "solver_options": _solver_options(metadata, config),
    }


def _run_solver(qt: Any, execution: Mapping[str, Any]) -> Any:
    e_ops = [operator for _, operator in execution["observables"]]
    if execution["solver"] == "sesolve":
        return qt.sesolve(
            execution["hamiltonian"],
            execution["initial_state"],
            execution["times"],
            e_ops=e_ops,
            args=execution["args"],
            options=execution["solver_options"],
        )

    return qt.mesolve(
        execution["hamiltonian"],
        execution["initial_state"],
        execution["times"],
        c_ops=execution["collapse_operators"],
        e_ops=e_ops,
        args=execution["args"],
        options=execution["solver_options"],
    )


def _result_metadata(execution: Mapping[str, Any], result: Any) -> dict[str, Any]:
    observable_names = [name for name, _ in execution["observables"]]
    expectations = _expectations_by_name(observable_names, getattr(result, "expect", []))
    metadata: dict[str, Any] = {
        "model": execution["model"],
        "solver": execution["solver"],
        "cutoff": execution["cutoff"],
        "times": list(execution["times"]),
        "observables": observable_names,
        "expectation_values": expectations,
        "final_expectations": {
            name: values[-1] for name, values in expectations.items() if values
        },
        "result_format": "qutip_expectation_values",
    }

    stats = getattr(result, "stats", None)
    if isinstance(stats, Mapping):
        metadata["solver_stats"] = {str(key): _to_public_value(value) for key, value in stats.items()}
    return metadata


def _normalize_model(raw_model: Any) -> str:
    if not isinstance(raw_model, str) or not raw_model.strip():
        raise CircuitValidationError("QuTiP metadata.model must be a non-empty string.")
    normalized = raw_model.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in _SUPPORTED_MODELS:
        supported = ", ".join(sorted(_SUPPORTED_MODELS))
        raise CircuitValidationError(
            f"Unsupported QuTiP model '{raw_model}'. Supported models: {supported}."
        )
    return normalized


def _normalize_solver(raw_solver: Any) -> str:
    if raw_solver is None:
        return "auto"
    if not isinstance(raw_solver, str) or not raw_solver.strip():
        raise CircuitValidationError("QuTiP metadata.solver must be a non-empty string.")
    normalized = raw_solver.strip().lower()
    if normalized == "auto" or normalized in _SUPPORTED_SOLVERS:
        return normalized
    supported = ", ".join(["auto", *sorted(_SUPPORTED_SOLVERS)])
    raise CircuitValidationError(
        f"Unsupported QuTiP solver '{raw_solver}'. Supported solvers: {supported}."
    )


def _select_solver(metadata: Mapping[str, Any], config: BackendConfig, *, has_collapse: bool) -> str:
    raw_solver = metadata.get("solver", config.options.get("solver", "auto"))
    solver = _normalize_solver(raw_solver)
    if solver != "auto":
        return solver
    if has_collapse:
        return "mesolve"
    return "sesolve"


def _parse_times(raw_times: Any) -> list[float]:
    if not isinstance(raw_times, Sequence) or isinstance(raw_times, (str, bytes)):
        raise CircuitValidationError("QuTiP metadata.times must be a sequence of time points.")
    if len(raw_times) < 2:
        raise CircuitValidationError("QuTiP metadata.times must contain at least two values.")

    times: list[float] = []
    for value in raw_times:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise CircuitValidationError("QuTiP metadata.times values must be numeric.")
        times.append(float(value))

    for previous, current in zip(times, times[1:]):
        if current <= previous:
            raise CircuitValidationError("QuTiP metadata.times values must be strictly increasing.")
    return times


def _parse_initial_state(raw_state: Any, cutoff: int) -> Mapping[str, Any]:
    state = _parse_mapping(raw_state, field_name="metadata.initial_state")
    kind = str(state.get("kind", "fock")).strip().lower().replace("-", "_")
    if kind == "fock":
        n = _nonnegative_int(state.get("n", 0), field_name="metadata.initial_state.n")
        if n >= cutoff:
            raise CircuitValidationError("QuTiP initial Fock state n must be below cutoff.")
        return {"kind": kind, "n": n}
    if kind == "coherent":
        return {"kind": kind, "alpha": _number(state.get("alpha", 0.0), field_name="metadata.initial_state.alpha")}
    if kind == "fock_dm":
        n = _nonnegative_int(state.get("n", 0), field_name="metadata.initial_state.n")
        if n >= cutoff:
            raise CircuitValidationError("QuTiP initial Fock density state n must be below cutoff.")
        return {"kind": kind, "n": n}
    raise CircuitValidationError(f"Unsupported QuTiP initial_state kind '{kind}'.")


def _build_initial_state(qt: Any, state: Mapping[str, Any], cutoff: int) -> Any:
    if state["kind"] == "fock":
        if hasattr(qt, "basis"):
            return qt.basis(cutoff, state["n"])
        return qt.fock(cutoff, state["n"])
    if state["kind"] == "coherent":
        return qt.coherent(cutoff, state["alpha"])
    if state["kind"] == "fock_dm":
        return qt.fock_dm(cutoff, state["n"])
    raise CircuitValidationError(f"Unsupported QuTiP initial_state kind '{state['kind']}'.")


def _parse_hamiltonian(raw_hamiltonian: Any, cutoff: int) -> list[Mapping[str, Any]]:
    if not isinstance(raw_hamiltonian, Sequence) or isinstance(raw_hamiltonian, (str, bytes)):
        raise CircuitValidationError("QuTiP metadata.hamiltonian must be a non-empty sequence.")
    if not raw_hamiltonian:
        raise CircuitValidationError("QuTiP metadata.hamiltonian must not be empty.")

    terms: list[Mapping[str, Any]] = []
    for index, raw_term in enumerate(raw_hamiltonian):
        term = _parse_mapping(raw_term, field_name=f"metadata.hamiltonian[{index}]")
        coefficient = _number(term.get("coefficient", 1.0), field_name=f"metadata.hamiltonian[{index}].coefficient")
        operator = _parse_operator_spec(term.get("operator", "num"), cutoff)
        terms.append({"operator": operator, "coefficient": coefficient})
    return terms


def _build_hamiltonian(qt: Any, raw_hamiltonian: Any, cutoff: int) -> Any:
    terms = _parse_hamiltonian(raw_hamiltonian, cutoff)
    hamiltonian = None
    for term in terms:
        term_operator = term["coefficient"] * _build_operator(qt, term["operator"], cutoff)
        hamiltonian = term_operator if hamiltonian is None else hamiltonian + term_operator
    return hamiltonian


def _parse_observables(raw_observables: Any, cutoff: int) -> list[Mapping[str, Any]]:
    if not isinstance(raw_observables, Sequence) or isinstance(raw_observables, (str, bytes)):
        raise CircuitValidationError("QuTiP metadata.observables must be a non-empty sequence.")
    if not raw_observables:
        raise CircuitValidationError("QuTiP metadata.observables must not be empty.")

    observables: list[Mapping[str, Any]] = []
    for index, raw_observable in enumerate(raw_observables):
        observable = _parse_mapping(raw_observable, field_name=f"metadata.observables[{index}]")
        name = observable.get("name", f"observable_{index}")
        if not isinstance(name, str) or not name.strip():
            raise CircuitValidationError("QuTiP observable names must be non-empty strings.")
        observables.append(
            {
                "name": name.strip(),
                "operator": _parse_operator_spec(observable.get("operator", "num"), cutoff),
            }
        )
    return observables


def _parse_collapse_operators(raw_collapse_operators: Any, cutoff: int) -> list[Mapping[str, Any]]:
    if raw_collapse_operators is None:
        return []
    if not isinstance(raw_collapse_operators, Sequence) or isinstance(raw_collapse_operators, (str, bytes)):
        raise CircuitValidationError("QuTiP metadata.collapse_operators must be a sequence.")

    collapse_operators: list[Mapping[str, Any]] = []
    for index, raw_collapse in enumerate(raw_collapse_operators):
        collapse = _parse_mapping(raw_collapse, field_name=f"metadata.collapse_operators[{index}]")
        rate = _nonnegative_number(collapse.get("rate", 1.0), field_name=f"metadata.collapse_operators[{index}].rate")
        collapse_operators.append(
            {
                "operator": _parse_operator_spec(collapse.get("operator", "destroy"), cutoff),
                "rate": rate,
            }
        )
    return collapse_operators


def _build_collapse_operator(qt: Any, collapse: Mapping[str, Any], cutoff: int) -> Any:
    return math.sqrt(float(collapse["rate"])) * _build_operator(qt, collapse["operator"], cutoff)


def _parse_operator_spec(raw_operator: Any, cutoff: int) -> Mapping[str, Any]:
    if isinstance(raw_operator, str):
        name = raw_operator.strip().lower().replace("-", "_")
        if name not in {"identity", "destroy", "create", "num", "number", "position", "momentum"}:
            raise CircuitValidationError(f"Unsupported QuTiP operator '{raw_operator}'.")
        return {"kind": name}

    operator = _parse_mapping(raw_operator, field_name="operator")
    if "matrix" in operator:
        return {"kind": "matrix", "matrix": _coerce_square_matrix(operator["matrix"], cutoff=cutoff)}
    if "kind" in operator:
        return _parse_operator_spec(str(operator["kind"]), cutoff)
    raise CircuitValidationError("QuTiP operator specs must be strings or contain a matrix.")


def _build_operator(qt: Any, operator: Mapping[str, Any], cutoff: int) -> Any:
    kind = operator["kind"]
    if kind == "identity":
        return qt.qeye(cutoff)
    if kind == "destroy":
        return qt.destroy(cutoff)
    if kind == "create":
        if hasattr(qt, "create"):
            return qt.create(cutoff)
        return qt.destroy(cutoff).dag()
    if kind in {"num", "number"}:
        if hasattr(qt, "num"):
            return qt.num(cutoff)
        destroy = qt.destroy(cutoff)
        return destroy.dag() * destroy
    if kind == "position":
        return qt.position(cutoff)
    if kind == "momentum":
        return qt.momentum(cutoff)
    if kind == "matrix":
        return qt.Qobj(operator["matrix"])
    raise CircuitValidationError(f"Unsupported QuTiP operator '{kind}'.")


def _solver_options(metadata: Mapping[str, Any], config: BackendConfig) -> dict[str, Any]:
    options = dict(config.options.get("solver_options", {}))
    options.update(dict(metadata.get("solver_options", {})))
    options.setdefault("progress_bar", "")
    return options


def _parse_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CircuitValidationError(f"QuTiP {field_name} must be a mapping.")
    return value


def _positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CircuitValidationError(f"QuTiP {field_name} must be a positive integer.")
    return value


def _nonnegative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CircuitValidationError(f"QuTiP {field_name} must be a non-negative integer.")
    return value


def _number(value: Any, *, field_name: str) -> int | float | complex:
    if isinstance(value, bool) or not isinstance(value, int | float | complex):
        raise CircuitValidationError(f"QuTiP {field_name} must be numeric.")
    return value


def _nonnegative_number(value: Any, *, field_name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise CircuitValidationError(f"QuTiP {field_name} must be a non-negative number.")
    return value


def _coerce_square_matrix(raw_matrix: Any, *, cutoff: int) -> list[list[Any]]:
    if not isinstance(raw_matrix, Sequence) or isinstance(raw_matrix, (str, bytes)):
        raise CircuitValidationError("QuTiP matrix operators must be square matrices.")
    if len(raw_matrix) != cutoff:
        raise CircuitValidationError("QuTiP matrix operators must match metadata.cutoff.")

    matrix: list[list[Any]] = []
    for row in raw_matrix:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != cutoff:
            raise CircuitValidationError("QuTiP matrix operators must be square matrices.")
        matrix.append([_number(value, field_name="matrix") for value in row])
    return matrix


def _expectations_by_name(names: Sequence[str], expectation_series: Any) -> dict[str, list[Any]]:
    if hasattr(expectation_series, "tolist"):
        expectation_series = expectation_series.tolist()

    expectations: dict[str, list[Any]] = {}
    for index, name in enumerate(names):
        if index >= len(expectation_series):
            expectations[name] = []
            continue
        expectations[name] = [_to_public_value(value) for value in _as_sequence(expectation_series[index])]
    return expectations


def _as_sequence(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return [value]


def _to_public_value(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, complex):
        if abs(value.imag) < 1e-12:
            return float(value.real)
        return {"real": float(value.real), "imag": float(value.imag)}
    if isinstance(value, int | float | str | bool) or value is None:
        return value
    if hasattr(value, "tolist"):
        return _to_public_value(value.tolist())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_to_public_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _to_public_value(item) for key, item in value.items()}
    return str(value)
