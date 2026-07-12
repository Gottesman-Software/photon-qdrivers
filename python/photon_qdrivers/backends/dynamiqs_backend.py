"""Optional Dynamiqs backend adapter for JAX quantum dynamics."""

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


class DynamiqsBackend:
    """Adapter for Dynamiqs single-mode oscillator dynamics."""

    name = "dynamiqs"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._dq: Any | None = None
        self._jnp: Any | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("photon_counting",),
            max_modes=1,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "dynamiqs",
                "dependency": "dynamiqs",
                "execution": "local_jax",
                "supported_models": sorted(_SUPPORTED_MODELS),
                "supported_solvers": sorted(_SUPPORTED_SOLVERS),
            },
        )
        self.device = PhotonicDevice(
            name="dynamiqs-oscillator-dynamics",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        try:
            self._dq = importlib.import_module("dynamiqs")
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'dynamiqs' requires the optional dependency 'dynamiqs'. "
                "Install with `pip install photon-qdrivers[dynamiqs]` or "
                "`pip install dynamiqs`."
            ) from exc

        self._jnp = _optional_import("jax.numpy")
        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        model = _validate_dynamiqs_request(circuit)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "dynamiqs",
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
                metadata={"backend": self.name, "adapter": "dynamiqs", "cancelled": True},
            )

        dq = self._require_dynamiqs()
        execution = _build_execution(dq, self._jnp, job.circuit.metadata, self.config)
        result = _run_solver(dq, execution)
        metadata = _result_metadata(execution, result)

        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts={},
            metadata={
                "backend": self.name,
                "adapter": "dynamiqs",
                "execution": "local_jax_quantum_dynamics",
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

    def _require_dynamiqs(self) -> Any:
        if self._dq is None:
            raise BackendUnavailableError("Dynamiqs backend is not initialized.")
        return self._dq


def _optional_import(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


def _validate_dynamiqs_request(circuit: PhotonicCircuit) -> str:
    model = _normalize_model(circuit.metadata.get("model", "oscillator_dynamics"))
    if circuit.modes != 1:
        raise CircuitValidationError(
            "Dynamiqs oscillator_dynamics currently supports exactly one mode."
        )

    cutoff = _positive_int(circuit.metadata.get("cutoff"), field_name="metadata.cutoff")
    if cutoff < 2:
        raise CircuitValidationError("Dynamiqs metadata.cutoff must be at least 2.")

    _parse_times(circuit.metadata.get("times"))
    _parse_initial_state(circuit.metadata.get("initial_state", {"kind": "fock", "n": 0}), cutoff)
    _parse_hamiltonian(circuit.metadata.get("hamiltonian"), cutoff)
    _parse_observables(circuit.metadata.get("observables", [{"name": "n", "operator": "number"}]), cutoff)
    _parse_jump_operators(circuit.metadata.get("jump_ops", circuit.metadata.get("collapse_operators", [])), cutoff)
    _normalize_solver(circuit.metadata.get("solver", "auto"))
    return model


def _build_execution(
    dq: Any,
    jnp: Any | None,
    metadata: Mapping[str, Any],
    config: BackendConfig,
) -> dict[str, Any]:
    cutoff = _positive_int(metadata.get("cutoff"), field_name="metadata.cutoff")
    jump_ops = [
        _build_jump_operator(dq, jump_op, cutoff)
        for jump_op in _parse_jump_operators(
            metadata.get("jump_ops", metadata.get("collapse_operators", [])),
            cutoff,
        )
    ]
    solver = _select_solver(metadata, config, has_jump_ops=bool(jump_ops))
    observables = _parse_observables(
        metadata.get("observables", [{"name": "n", "operator": "number"}]),
        cutoff,
    )

    return {
        "model": _normalize_model(metadata.get("model", "oscillator_dynamics")),
        "solver": solver,
        "cutoff": cutoff,
        "times": _array(jnp, _parse_times(metadata.get("times"))),
        "public_times": _parse_times(metadata.get("times")),
        "hamiltonian": _build_hamiltonian(dq, metadata.get("hamiltonian"), cutoff),
        "initial_state": _build_initial_state(
            dq,
            _parse_initial_state(metadata.get("initial_state", {"kind": "fock", "n": 0}), cutoff),
            cutoff,
        ),
        "jump_ops": jump_ops,
        "observables": [
            (observable["name"], _build_operator(dq, observable["operator"], cutoff))
            for observable in observables
        ],
        "method": _build_method(dq, metadata.get("method", config.options.get("method"))),
        "solver_options": _solver_options(metadata, config),
    }


def _run_solver(dq: Any, execution: Mapping[str, Any]) -> Any:
    exp_ops = [operator for _, operator in execution["observables"]]
    kwargs = {"exp_ops": exp_ops}
    solver_options = dict(execution["solver_options"])
    if hasattr(dq, "Options"):
        solver_options.setdefault("progress_meter", False)
        kwargs["options"] = dq.Options(**solver_options)
    else:
        kwargs["progress_meter"] = False
        kwargs.update(solver_options)

    if execution["method"] is not None:
        kwargs["method"] = execution["method"]

    if execution["solver"] == "sesolve":
        return dq.sesolve(
            execution["hamiltonian"],
            execution["initial_state"],
            execution["times"],
            **kwargs,
        )

    return dq.mesolve(
        execution["hamiltonian"],
        execution["jump_ops"],
        execution["initial_state"],
        execution["times"],
        **kwargs,
    )


def _result_metadata(execution: Mapping[str, Any], result: Any) -> dict[str, Any]:
    observable_names = [name for name, _ in execution["observables"]]
    expectations = _expectations_by_name(observable_names, getattr(result, "expects", []))
    metadata: dict[str, Any] = {
        "model": execution["model"],
        "solver": execution["solver"],
        "cutoff": execution["cutoff"],
        "times": list(execution["public_times"]),
        "observables": observable_names,
        "expectation_values": expectations,
        "final_expectations": {
            name: values[-1] for name, values in expectations.items() if values
        },
        "result_format": "dynamiqs_expectation_values",
    }

    infos = getattr(result, "infos", None)
    if infos is not None:
        metadata["solver_infos"] = _to_public_value(infos)

    method = getattr(result, "method", None)
    if method is not None:
        metadata["method"] = _to_public_value(method)
    return metadata


def _normalize_model(raw_model: Any) -> str:
    if not isinstance(raw_model, str) or not raw_model.strip():
        raise CircuitValidationError("Dynamiqs metadata.model must be a non-empty string.")
    normalized = raw_model.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in _SUPPORTED_MODELS:
        supported = ", ".join(sorted(_SUPPORTED_MODELS))
        raise CircuitValidationError(
            f"Unsupported Dynamiqs model '{raw_model}'. Supported models: {supported}."
        )
    return normalized


def _normalize_solver(raw_solver: Any) -> str:
    if raw_solver is None:
        return "auto"
    if not isinstance(raw_solver, str) or not raw_solver.strip():
        raise CircuitValidationError("Dynamiqs metadata.solver must be a non-empty string.")
    normalized = raw_solver.strip().lower()
    if normalized == "auto" or normalized in _SUPPORTED_SOLVERS:
        return normalized
    supported = ", ".join(["auto", *sorted(_SUPPORTED_SOLVERS)])
    raise CircuitValidationError(
        f"Unsupported Dynamiqs solver '{raw_solver}'. Supported solvers: {supported}."
    )


def _select_solver(metadata: Mapping[str, Any], config: BackendConfig, *, has_jump_ops: bool) -> str:
    raw_solver = metadata.get("solver", config.options.get("solver", "auto"))
    solver = _normalize_solver(raw_solver)
    if solver != "auto":
        return solver
    if has_jump_ops:
        return "mesolve"
    return "sesolve"


def _parse_times(raw_times: Any) -> list[float]:
    if not isinstance(raw_times, Sequence) or isinstance(raw_times, (str, bytes)):
        raise CircuitValidationError("Dynamiqs metadata.times must be a sequence of time points.")
    if len(raw_times) < 2:
        raise CircuitValidationError("Dynamiqs metadata.times must contain at least two values.")

    times: list[float] = []
    for value in raw_times:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise CircuitValidationError("Dynamiqs metadata.times values must be numeric.")
        times.append(float(value))

    for previous, current in zip(times, times[1:]):
        if current <= previous:
            raise CircuitValidationError("Dynamiqs metadata.times values must be strictly increasing.")
    return times


def _parse_initial_state(raw_state: Any, cutoff: int) -> Mapping[str, Any]:
    state = _parse_mapping(raw_state, field_name="metadata.initial_state")
    kind = str(state.get("kind", "fock")).strip().lower().replace("-", "_")
    if kind == "fock":
        n = _nonnegative_int(state.get("n", 0), field_name="metadata.initial_state.n")
        if n >= cutoff:
            raise CircuitValidationError("Dynamiqs initial Fock state n must be below cutoff.")
        return {"kind": kind, "n": n}
    if kind == "coherent":
        return {"kind": kind, "alpha": _number(state.get("alpha", 0.0), field_name="metadata.initial_state.alpha")}
    if kind == "fock_dm":
        n = _nonnegative_int(state.get("n", 0), field_name="metadata.initial_state.n")
        if n >= cutoff:
            raise CircuitValidationError("Dynamiqs initial Fock density state n must be below cutoff.")
        return {"kind": kind, "n": n}
    if kind == "coherent_dm":
        return {"kind": kind, "alpha": _number(state.get("alpha", 0.0), field_name="metadata.initial_state.alpha")}
    raise CircuitValidationError(f"Unsupported Dynamiqs initial_state kind '{kind}'.")


def _build_initial_state(dq: Any, state: Mapping[str, Any], cutoff: int) -> Any:
    if state["kind"] == "fock":
        return dq.fock(cutoff, state["n"])
    if state["kind"] == "coherent":
        return dq.coherent(cutoff, state["alpha"])
    if state["kind"] == "fock_dm":
        return dq.fock_dm(cutoff, state["n"])
    if state["kind"] == "coherent_dm":
        return dq.coherent_dm(cutoff, state["alpha"])
    raise CircuitValidationError(f"Unsupported Dynamiqs initial_state kind '{state['kind']}'.")


def _parse_hamiltonian(raw_hamiltonian: Any, cutoff: int) -> list[Mapping[str, Any]]:
    if not isinstance(raw_hamiltonian, Sequence) or isinstance(raw_hamiltonian, (str, bytes)):
        raise CircuitValidationError("Dynamiqs metadata.hamiltonian must be a non-empty sequence.")
    if not raw_hamiltonian:
        raise CircuitValidationError("Dynamiqs metadata.hamiltonian must not be empty.")

    terms: list[Mapping[str, Any]] = []
    for index, raw_term in enumerate(raw_hamiltonian):
        term = _parse_mapping(raw_term, field_name=f"metadata.hamiltonian[{index}]")
        coefficient = _number(term.get("coefficient", 1.0), field_name=f"metadata.hamiltonian[{index}].coefficient")
        operator = _parse_operator_spec(term.get("operator", "number"), cutoff)
        terms.append({"operator": operator, "coefficient": coefficient})
    return terms


def _build_hamiltonian(dq: Any, raw_hamiltonian: Any, cutoff: int) -> Any:
    terms = _parse_hamiltonian(raw_hamiltonian, cutoff)
    hamiltonian = None
    for term in terms:
        term_operator = term["coefficient"] * _build_operator(dq, term["operator"], cutoff)
        hamiltonian = term_operator if hamiltonian is None else hamiltonian + term_operator
    return hamiltonian


def _parse_observables(raw_observables: Any, cutoff: int) -> list[Mapping[str, Any]]:
    if not isinstance(raw_observables, Sequence) or isinstance(raw_observables, (str, bytes)):
        raise CircuitValidationError("Dynamiqs metadata.observables must be a non-empty sequence.")
    if not raw_observables:
        raise CircuitValidationError("Dynamiqs metadata.observables must not be empty.")

    observables: list[Mapping[str, Any]] = []
    for index, raw_observable in enumerate(raw_observables):
        observable = _parse_mapping(raw_observable, field_name=f"metadata.observables[{index}]")
        name = observable.get("name", f"observable_{index}")
        if not isinstance(name, str) or not name.strip():
            raise CircuitValidationError("Dynamiqs observable names must be non-empty strings.")
        observables.append(
            {
                "name": name.strip(),
                "operator": _parse_operator_spec(observable.get("operator", "number"), cutoff),
            }
        )
    return observables


def _parse_jump_operators(raw_jump_ops: Any, cutoff: int) -> list[Mapping[str, Any]]:
    if raw_jump_ops is None:
        return []
    if not isinstance(raw_jump_ops, Sequence) or isinstance(raw_jump_ops, (str, bytes)):
        raise CircuitValidationError("Dynamiqs metadata.jump_ops must be a sequence.")

    jump_ops: list[Mapping[str, Any]] = []
    for index, raw_jump_op in enumerate(raw_jump_ops):
        jump_op = _parse_mapping(raw_jump_op, field_name=f"metadata.jump_ops[{index}]")
        rate = _nonnegative_number(jump_op.get("rate", 1.0), field_name=f"metadata.jump_ops[{index}].rate")
        jump_ops.append(
            {
                "operator": _parse_operator_spec(jump_op.get("operator", "destroy"), cutoff),
                "rate": rate,
            }
        )
    return jump_ops


def _build_jump_operator(dq: Any, jump_op: Mapping[str, Any], cutoff: int) -> Any:
    return math.sqrt(float(jump_op["rate"])) * _build_operator(dq, jump_op["operator"], cutoff)


def _parse_operator_spec(raw_operator: Any, cutoff: int) -> Mapping[str, Any]:
    if isinstance(raw_operator, str):
        name = raw_operator.strip().lower().replace("-", "_")
        aliases = {"num": "number", "identity": "eye"}
        name = aliases.get(name, name)
        if name not in {"eye", "destroy", "create", "number", "position", "momentum"}:
            raise CircuitValidationError(f"Unsupported Dynamiqs operator '{raw_operator}'.")
        return {"kind": name}

    operator = _parse_mapping(raw_operator, field_name="operator")
    if "matrix" in operator:
        return {"kind": "matrix", "matrix": _coerce_square_matrix(operator["matrix"], cutoff=cutoff)}
    if "kind" in operator:
        return _parse_operator_spec(str(operator["kind"]), cutoff)
    raise CircuitValidationError("Dynamiqs operator specs must be strings or contain a matrix.")


def _build_operator(dq: Any, operator: Mapping[str, Any], cutoff: int) -> Any:
    kind = operator["kind"]
    if kind == "eye":
        return dq.eye(cutoff)
    if kind == "destroy":
        return dq.destroy(cutoff)
    if kind == "create":
        return dq.create(cutoff)
    if kind == "number":
        return dq.number(cutoff)
    if kind == "position":
        return dq.position(cutoff)
    if kind == "momentum":
        return dq.momentum(cutoff)
    if kind == "matrix":
        if hasattr(dq, "asqarray"):
            return dq.asqarray(operator["matrix"])
        return operator["matrix"]
    raise CircuitValidationError(f"Unsupported Dynamiqs operator '{kind}'.")


def _build_method(dq: Any, raw_method: Any) -> Any | None:
    if raw_method is None:
        return None
    if not isinstance(raw_method, str) or not raw_method.strip():
        raise CircuitValidationError("Dynamiqs method must be a non-empty string.")

    method_name = raw_method.strip()
    method_namespace = getattr(dq, "method", None)
    if method_namespace is None or not hasattr(method_namespace, method_name):
        raise CircuitValidationError(f"Unsupported Dynamiqs method '{raw_method}'.")
    method_factory = getattr(method_namespace, method_name)
    return method_factory()


def _solver_options(metadata: Mapping[str, Any], config: BackendConfig) -> dict[str, Any]:
    options = dict(config.options.get("solver_options", {}))
    options.update(dict(metadata.get("solver_options", {})))
    return options


def _array(jnp: Any | None, values: Sequence[float]) -> Any:
    if jnp is None:
        return list(values)
    return jnp.asarray(values)


def _parse_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CircuitValidationError(f"Dynamiqs {field_name} must be a mapping.")
    return value


def _positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CircuitValidationError(f"Dynamiqs {field_name} must be a positive integer.")
    return value


def _nonnegative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CircuitValidationError(f"Dynamiqs {field_name} must be a non-negative integer.")
    return value


def _number(value: Any, *, field_name: str) -> int | float | complex:
    if isinstance(value, bool) or not isinstance(value, int | float | complex):
        raise CircuitValidationError(f"Dynamiqs {field_name} must be numeric.")
    return value


def _nonnegative_number(value: Any, *, field_name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise CircuitValidationError(f"Dynamiqs {field_name} must be a non-negative number.")
    return value


def _coerce_square_matrix(raw_matrix: Any, *, cutoff: int) -> list[list[Any]]:
    if not isinstance(raw_matrix, Sequence) or isinstance(raw_matrix, (str, bytes)):
        raise CircuitValidationError("Dynamiqs matrix operators must be square matrices.")
    if len(raw_matrix) != cutoff:
        raise CircuitValidationError("Dynamiqs matrix operators must match metadata.cutoff.")

    matrix: list[list[Any]] = []
    for row in raw_matrix:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != cutoff:
            raise CircuitValidationError("Dynamiqs matrix operators must be square matrices.")
        matrix.append([_number(value, field_name="matrix") for value in row])
    return matrix


def _expectations_by_name(names: Sequence[str], expectation_series: Any) -> dict[str, list[Any]]:
    if hasattr(expectation_series, "tolist"):
        expectation_series = expectation_series.tolist()

    if expectation_series is None:
        expectation_series = []

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
