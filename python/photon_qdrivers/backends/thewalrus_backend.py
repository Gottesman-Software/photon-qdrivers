"""Optional The Walrus backend adapter for GBS validation kernels."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any

from photon_qdrivers.config import BackendConfig
from photon_qdrivers.device import BackendCapabilities, PhotonicDevice
from photon_qdrivers.errors import BackendUnavailableError, CircuitValidationError
from photon_qdrivers.ir import PhotonicCircuit
from photon_qdrivers.job import JobStatus, PhotonicJob, PhotonicResult


_SUPPORTED_KERNELS = {
    "hafnian",
    "loop_hafnian",
    "torontonian",
    "probabilities",
    "hafnian_sample_graph",
}

_KERNEL_ALIASES = {
    "loop-hafnian": "loop_hafnian",
    "loop hafnian": "loop_hafnian",
    "tor": "torontonian",
    "torontonian": "torontonian",
    "hafnian-sample-graph": "hafnian_sample_graph",
    "hafnian sample graph": "hafnian_sample_graph",
}


class TheWalrusBackend:
    """Adapter for The Walrus hafnian, torontonian, and GBS kernels."""

    name = "thewalrus"

    def __init__(self, config: BackendConfig | None = None) -> None:
        self.config = config or BackendConfig(backend_name=self.name)
        self.initialized = False
        self._tw: Any | None = None
        self._quantum: Any | None = None
        self._samples: Any | None = None
        self._cancelled_jobs: set[str] = set()
        self.capabilities = BackendCapabilities(
            supported_operations=("photon_counting",),
            max_modes=64,
            max_shots=1_000_000,
            supports_emulation=True,
            supports_hardware=False,
            supports_realtime=False,
            metadata={
                "adapter": "thewalrus",
                "dependency": "thewalrus",
                "execution": "local",
                "supported_kernels": sorted(_SUPPORTED_KERNELS),
            },
        )
        self.device = PhotonicDevice(
            name="thewalrus-gbs-kernels",
            backend_name=self.name,
            modes=self.capabilities.max_modes,
            capabilities=self.capabilities,
        )

    def initialize(self) -> None:
        try:
            self._tw = importlib.import_module("thewalrus")
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'thewalrus' requires the optional dependency 'thewalrus'. "
                "Install with `pip install photon-qdrivers[thewalrus]` or "
                "`pip install thewalrus`."
            ) from exc

        self._quantum = _optional_import("thewalrus.quantum")
        self._samples = _optional_import("thewalrus.samples")
        self.initialized = True

    def shutdown(self) -> None:
        self.initialized = False
        self._cancelled_jobs.clear()

    def compile(self, circuit: PhotonicCircuit) -> PhotonicJob:
        if not self.initialized:
            self.initialize()

        self.capabilities.validate_circuit(circuit, backend_name=self.name)
        kernel = _validate_thewalrus_request(circuit)

        return PhotonicJob(
            circuit=circuit,
            backend_name=self.name,
            shots=circuit.shots,
            metadata={
                "compiled_by": self.name,
                "device": self.device.as_dict(),
                "adapter": "thewalrus",
                "kernel": kernel,
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
                metadata={"backend": self.name, "adapter": "thewalrus", "cancelled": True},
            )

        kernel = _normalize_kernel(job.circuit.metadata.get("kernel", "hafnian"))
        counts, metadata = self._execute_kernel(kernel, job)

        return PhotonicResult(
            job_id=job.job_id,
            backend_name=self.name,
            status=JobStatus.COMPLETED,
            shots=job.shots,
            counts=counts,
            metadata={
                "backend": self.name,
                "adapter": "thewalrus",
                "execution": "local_gbs_kernel",
                "device": self.device.name,
                "kernel": kernel,
                "real_hardware": False,
                **metadata,
            },
        )

    def cancel(self, job_id: str) -> bool:
        if not job_id:
            return False
        self._cancelled_jobs.add(job_id)
        return True

    def _execute_kernel(
        self,
        kernel: str,
        job: PhotonicJob,
    ) -> tuple[dict[str, int], dict[str, Any]]:
        tw = self._require_thewalrus()
        metadata = job.circuit.metadata

        if kernel == "hafnian":
            value = tw.hafnian(_backend_array(_matrix_from_metadata(metadata)))
            return {}, {"kernel_result": _to_public_value(value)}

        if kernel == "loop_hafnian":
            matrix = _backend_array(_matrix_from_metadata(metadata))
            if hasattr(tw, "loop_hafnian"):
                value = tw.loop_hafnian(matrix)
            else:
                value = tw.hafnian(matrix, loop=True)
            return {}, {"kernel_result": _to_public_value(value)}

        if kernel == "torontonian":
            value = tw.tor(_backend_array(_matrix_from_metadata(metadata)))
            return {}, {"kernel_result": _to_public_value(value)}

        if kernel == "probabilities":
            quantum = self._require_quantum()
            probabilities = quantum.probabilities(
                _backend_array(_vector_from_metadata(metadata, "mu")),
                _backend_array(_matrix_from_metadata(metadata, key="cov")),
                _positive_int_from_metadata(metadata, "cutoff"),
                parallel=bool(metadata.get("parallel", self.config.options.get("parallel", False))),
                hbar=float(metadata.get("hbar", self.config.options.get("hbar", 2.0))),
            )
            counts, top_probabilities = _probabilities_to_counts_and_metadata(
                probabilities,
                shots=job.shots,
                max_entries=int(self.config.options.get("max_probability_entries", 256)),
            )
            return counts, {
                "result_format": "fock_probability_tensor",
                "top_probabilities": top_probabilities,
            }

        if kernel == "hafnian_sample_graph":
            samples = self._require_samples()
            output_samples = samples.hafnian_sample_graph(
                _backend_array(_matrix_from_metadata(metadata, key="adjacency_matrix")),
                _positive_float_from_metadata(metadata, "n_mean"),
                samples=job.shots,
                cutoff=int(metadata.get("cutoff", self.config.options.get("cutoff", 5))),
                max_photons=int(
                    metadata.get("max_photons", self.config.options.get("max_photons", 30))
                ),
                parallel=bool(metadata.get("parallel", self.config.options.get("parallel", False))),
            )
            counts = _samples_to_counts(output_samples)
            return counts, {
                "result_format": "hafnian_graph_samples",
                "sample_count": sum(counts.values()),
            }

        raise CircuitValidationError(f"Unsupported The Walrus kernel '{kernel}'.")

    def _require_thewalrus(self) -> Any:
        if self._tw is None:
            raise BackendUnavailableError("The Walrus backend is not initialized.")
        return self._tw

    def _require_quantum(self) -> Any:
        if self._quantum is None:
            raise BackendUnavailableError(
                "The Walrus quantum submodule is required for the selected kernel."
            )
        return self._quantum

    def _require_samples(self) -> Any:
        if self._samples is None:
            raise BackendUnavailableError(
                "The Walrus samples submodule is required for the selected kernel."
            )
        return self._samples


def _optional_import(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


def _validate_thewalrus_request(circuit: PhotonicCircuit) -> str:
    kernel = _normalize_kernel(circuit.metadata.get("kernel", "hafnian"))

    if kernel in {"hafnian", "loop_hafnian", "torontonian"}:
        matrix = _matrix_from_metadata(circuit.metadata)
        if kernel == "torontonian" and len(matrix) % 2 != 0:
            raise CircuitValidationError("The Walrus torontonian matrix dimension must be even.")
        return kernel

    if kernel == "probabilities":
        mu = _vector_from_metadata(circuit.metadata, "mu")
        cov = _matrix_from_metadata(circuit.metadata, key="cov")
        cutoff = _positive_int_from_metadata(circuit.metadata, "cutoff")
        if len(mu) != len(cov):
            raise CircuitValidationError("The Walrus probabilities require len(mu) == len(cov).")
        if len(mu) != 2 * circuit.modes:
            raise CircuitValidationError(
                "The Walrus probabilities require mu and cov in 2N-dimensional phase space."
            )
        if cutoff < 2:
            raise CircuitValidationError("The Walrus probabilities cutoff must be at least 2.")
        return kernel

    if kernel == "hafnian_sample_graph":
        _matrix_from_metadata(circuit.metadata, key="adjacency_matrix")
        _positive_float_from_metadata(circuit.metadata, "n_mean")
        return kernel

    raise CircuitValidationError(f"Unsupported The Walrus kernel '{kernel}'.")


def _normalize_kernel(raw_kernel: Any) -> str:
    if not isinstance(raw_kernel, str) or not raw_kernel.strip():
        raise CircuitValidationError("The Walrus metadata.kernel must be a non-empty string.")

    normalized = raw_kernel.strip().lower()
    normalized = _KERNEL_ALIASES.get(normalized, normalized.replace("-", "_").replace(" ", "_"))
    if normalized not in _SUPPORTED_KERNELS:
        supported = ", ".join(sorted(_SUPPORTED_KERNELS))
        raise CircuitValidationError(
            f"Unsupported The Walrus kernel '{raw_kernel}'. Supported kernels: {supported}."
        )
    return normalized


def _matrix_from_metadata(metadata: Mapping[str, Any], *, key: str | None = None) -> list[list[Any]]:
    candidate_keys = (key,) if key is not None else ("matrix", "adjacency_matrix", "A")
    raw_matrix = None
    for candidate_key in candidate_keys:
        if candidate_key in metadata:
            raw_matrix = metadata[candidate_key]
            break

    if raw_matrix is None:
        names = ", ".join(candidate_keys)
        raise CircuitValidationError(f"The Walrus kernel requires metadata matrix key: {names}.")

    return _coerce_square_matrix(raw_matrix, field_name=f"metadata.{candidate_key}")


def _coerce_square_matrix(raw_matrix: Any, *, field_name: str) -> list[list[Any]]:
    if not isinstance(raw_matrix, Sequence) or isinstance(raw_matrix, (str, bytes)):
        raise CircuitValidationError(f"The Walrus {field_name} must be a square matrix.")
    if not raw_matrix:
        raise CircuitValidationError(f"The Walrus {field_name} must not be empty.")

    matrix: list[list[Any]] = []
    row_count = len(raw_matrix)
    for row in raw_matrix:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            raise CircuitValidationError(f"The Walrus {field_name} rows must be sequences.")
        if len(row) != row_count:
            raise CircuitValidationError(f"The Walrus {field_name} must be square.")
        matrix.append([_coerce_number(value, field_name=field_name) for value in row])
    return matrix


def _vector_from_metadata(metadata: Mapping[str, Any], key: str) -> list[Any]:
    if key not in metadata:
        raise CircuitValidationError(f"The Walrus kernel requires metadata.{key}.")

    raw_vector = metadata[key]
    if not isinstance(raw_vector, Sequence) or isinstance(raw_vector, (str, bytes)):
        raise CircuitValidationError(f"The Walrus metadata.{key} must be a vector.")
    if not raw_vector:
        raise CircuitValidationError(f"The Walrus metadata.{key} must not be empty.")
    return [_coerce_number(value, field_name=f"metadata.{key}") for value in raw_vector]


def _backend_array(value: Any) -> Any:
    try:
        np = importlib.import_module("numpy")
    except ImportError:
        return value
    return np.asarray(value)


def _coerce_number(value: Any, *, field_name: str) -> Any:
    if isinstance(value, bool) or not isinstance(value, int | float | complex):
        raise CircuitValidationError(f"The Walrus {field_name} values must be numeric.")
    return value


def _positive_int_from_metadata(metadata: Mapping[str, Any], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CircuitValidationError(f"The Walrus metadata.{key} must be a positive integer.")
    return value


def _positive_float_from_metadata(metadata: Mapping[str, Any], key: str) -> float:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise CircuitValidationError(f"The Walrus metadata.{key} must be a positive number.")
    return float(value)


def _samples_to_counts(samples: Any) -> dict[str, int]:
    if hasattr(samples, "tolist"):
        samples = samples.tolist()

    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        raise CircuitValidationError("The Walrus sampler returned an unsupported sample shape.")

    counts: dict[str, int] = {}
    for sample in samples:
        key = _format_state(sample)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _probabilities_to_counts_and_metadata(
    probabilities: Any,
    *,
    shots: int,
    max_entries: int,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    entries = _flatten_probability_entries(probabilities)
    entries = [entry for entry in entries if entry[1] > 0]
    entries.sort(key=lambda entry: entry[1], reverse=True)

    top_entries = entries[:max(1, max_entries)]
    counts = {
        _format_state(state): int(round(probability * shots))
        for state, probability in top_entries
        if int(round(probability * shots)) > 0
    }
    top_probabilities = [
        {"state": _format_state(state), "probability": probability}
        for state, probability in top_entries
    ]
    return counts, top_probabilities


def _flatten_probability_entries(probabilities: Any) -> list[tuple[tuple[int, ...], float]]:
    if hasattr(probabilities, "tolist"):
        probabilities = probabilities.tolist()

    entries: list[tuple[tuple[int, ...], float]] = []

    def visit(node: Any, prefix: tuple[int, ...]) -> None:
        if isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for index, value in enumerate(node):
                visit(value, (*prefix, index))
            return
        entries.append((prefix, float(_real_scalar(node))))

    visit(probabilities, ())
    return entries


def _format_state(state: Any) -> str:
    if hasattr(state, "tolist"):
        state = state.tolist()
    if isinstance(state, Sequence) and not isinstance(state, (str, bytes)):
        return "|" + ",".join(str(int(value)) for value in state) + ">"
    return str(state)


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


def _real_scalar(value: Any) -> float:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, complex):
        return float(value.real)
    return float(value)
