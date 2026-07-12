"""High-level Python facade for photonic quantum drivers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from inspect import Parameter, signature
from typing import Any

from .backend import PhotonicBackend
from .backends.emulator_backend import LocalEmulatorBackend
from .backends.emulator_targets import (
    DynamiqsBackend,
    LightworksBackend,
    PennyLaneSFBackend,
    PercevalBackend,
    PiquassoBackend,
    QuTiPBackend,
    StrawberryFieldsBackend,
    TheWalrusBackend,
)
from .backends.mock_backend import MockPhotonicBackend
from .backends.native_runtime_backend import NativeRuntimeBackend
from .backends.orca_backend import OrcaBackend
from .backends.psiquantum_backend import PsiQuantumBackend
from .backends.quandela_backend import QuandelaBackend
from .backends.xanadu_backend import XanaduBackend
from .config import BackendConfig
from .errors import CircuitValidationError, JobTimeoutError
from .ir import PhotonicCircuit
from .job import JobStatus, PhotonicJob, PhotonicResult, SubmittedPhotonicJob
from .plugins import PluginRegistry


BackendFactory = Callable[..., PhotonicBackend]


class PhotonDriver:
    """User-facing entry point for compiling and running photonic jobs."""

    def __init__(self, *, max_workers: int = 4) -> None:
        self._backend_factories: dict[str, BackendFactory] = {}
        self._backend: PhotonicBackend | None = None
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._submitted_jobs: dict[str, SubmittedPhotonicJob] = {}
        self.plugins = PluginRegistry()
        self.register_backend("emulator", LocalEmulatorBackend)
        self.register_backend("mock", MockPhotonicBackend)
        self.register_backend("native", NativeRuntimeBackend)
        self.register_backend("dynamiqs", DynamiqsBackend)
        self.register_backend("lightworks", LightworksBackend)
        self.register_backend("orca", OrcaBackend)
        self.register_backend("pennylane-sf", PennyLaneSFBackend)
        self.register_backend("perceval", PercevalBackend)
        self.register_backend("piquasso", PiquassoBackend)
        self.register_backend("psiquantum", PsiQuantumBackend)
        self.register_backend("qutip", QuTiPBackend)
        self.register_backend("quandela", QuandelaBackend)
        self.register_backend("strawberryfields", StrawberryFieldsBackend)
        self.register_backend("thewalrus", TheWalrusBackend)
        self.register_backend("xanadu", XanaduBackend)

    def register_backend(
        self,
        name: str,
        factory: BackendFactory,
        *,
        replace: bool = False,
    ) -> None:
        normalized_name = _normalize_name(name, field_name="Backend name")
        if not callable(factory):
            raise TypeError("Backend factory must be callable.")
        if normalized_name in self._backend_factories and not replace:
            raise ValueError(
                f"Backend '{normalized_name}' is already registered. "
                "Pass replace=True to override it."
            )
        self._backend_factories[normalized_name] = factory

    def load_backend(
        self,
        name: str,
        config: BackendConfig | None = None,
        **options: Any,
    ) -> PhotonicBackend:
        """Load a backend by name and make it the active execution target."""

        normalized_name = _normalize_name(name, field_name="Backend name")
        backend_config = _coerce_config(normalized_name, config, options)
        try:
            factory = self._backend_factories[normalized_name]
        except KeyError as exc:
            available = ", ".join(self.list_backends()) or "none"
            raise KeyError(
                f"Unknown backend '{normalized_name}'. Available backends: {available}."
            ) from exc

        backend = _create_backend(factory, backend_config)
        _validate_backend(backend, expected_name=normalized_name)
        backend.initialize()
        self._backend = backend
        return backend

    def compile(self, circuit: Mapping[str, Any] | PhotonicCircuit) -> PhotonicJob:
        """Compile a symbolic circuit into a backend-specific job object."""

        backend = self._require_backend()
        try:
            normalized_circuit = PhotonicCircuit.from_mapping(circuit)
        except CircuitValidationError:
            raise
        except Exception as exc:
            raise CircuitValidationError(str(exc)) from exc

        return backend.compile(normalized_circuit)

    def run(self, job: PhotonicJob, *, timeout: float | None = None) -> PhotonicResult:
        """Run a compiled job and return a structured result object."""

        backend = self._require_backend()
        if job.backend_name != backend.name:
            raise ValueError(
                f"Job targets backend '{job.backend_name}', but active backend is '{backend.name}'."
            )
        if timeout is None:
            return backend.run(job)

        submitted_job = self.submit(job)
        try:
            return submitted_job.result(timeout=timeout)
        except JobTimeoutError:
            submitted_job.cancel()
            raise

    def submit(self, job: PhotonicJob) -> SubmittedPhotonicJob:
        """Submit a compiled job to the active backend and return an async handle."""

        backend = self._require_backend()
        if job.backend_name != backend.name:
            raise ValueError(
                f"Job targets backend '{job.backend_name}', but active backend is '{backend.name}'."
            )

        submitted_job = replace(job, status=JobStatus.SUBMITTED)
        future = self._executor.submit(backend.run, submitted_job)
        handle = SubmittedPhotonicJob(
            job_id=submitted_job.job_id,
            backend_name=backend.name,
            _future=future,
            _cancel_backend=backend.cancel,
        )
        self._submitted_jobs[submitted_job.job_id] = handle
        return handle

    def cancel(self, job_id: str) -> bool:
        """Cancel a submitted job when possible."""

        handle = self._submitted_jobs.get(job_id)
        if handle is not None:
            return handle.cancel()

        backend = self._require_backend()
        return backend.cancel(job_id)

    def register_plugin(self, plugin: Any, *, replace: bool = False) -> Any:
        """Register an optional simulator, decoder, or hardware adapter plugin."""

        return self.plugins.register(plugin, replace=replace)

    def list_backends(self) -> list[str]:
        return sorted(self._backend_factories)

    def list_plugins(self) -> list[str]:
        return self.plugins.list()

    def shutdown(self) -> None:
        if self._backend is not None:
            self._backend.shutdown()
            self._backend = None
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _require_backend(self) -> PhotonicBackend:
        if self._backend is None:
            raise RuntimeError("No backend loaded. Call load_backend(name) first.")
        return self._backend


def _validate_backend(backend: Any, *, expected_name: str) -> None:
    required_methods = ("initialize", "compile", "run", "cancel", "shutdown")
    missing = [method for method in required_methods if not callable(getattr(backend, method, None))]
    if missing:
        raise TypeError(f"Backend '{expected_name}' is missing method(s): {', '.join(missing)}.")

    name = getattr(backend, "name", None)
    if name != expected_name:
        raise ValueError(f"Backend factory for '{expected_name}' returned backend named '{name}'.")

    if getattr(backend, "device", None) is None:
        raise TypeError(f"Backend '{expected_name}' must expose a device description.")


def _normalize_name(name: str, *, field_name: str) -> str:
    if not isinstance(name, str):
        raise TypeError(f"{field_name} must be a string.")

    normalized = name.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty.")
    return normalized


def _coerce_config(
    backend_name: str,
    config: BackendConfig | None,
    options: Mapping[str, Any],
) -> BackendConfig:
    backend_config = config or BackendConfig.from_env(backend_name)
    if backend_config.backend_name != backend_name:
        raise ValueError(
            f"BackendConfig targets '{backend_config.backend_name}', "
            f"but load_backend requested '{backend_name}'."
        )
    if options:
        backend_config = backend_config.with_options(**dict(options))
    return backend_config


def _create_backend(factory: BackendFactory, config: BackendConfig) -> PhotonicBackend:
    try:
        factory_signature = signature(factory)
    except (TypeError, ValueError):
        return factory(config)

    parameters = list(factory_signature.parameters.values())
    accepts_config = any(
        parameter.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
        for parameter in parameters
    ) or any(parameter.kind == Parameter.VAR_POSITIONAL for parameter in parameters)

    if accepts_config:
        return factory(config)
    return factory()
