"""Xanadu legacy hardware adapter through Strawberry Fields RemoteEngine."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from photon_qdrivers.cloud import CloudJobSnapshot, CloudJobState, redact_sensitive_mapping
from photon_qdrivers.config import BackendConfig
from photon_qdrivers.errors import BackendExecutionError, BackendUnavailableError
from photon_qdrivers.hardware import CloudHardwareBackend
from photon_qdrivers.ir import PhotonicCircuit

from .strawberryfields_backend import (
    _build_program,
    _samples_to_counts,
    _validate_strawberryfields_circuit,
)


class XanaduBackend(CloudHardwareBackend):
    """Legacy Xanadu Cloud adapter backed by Strawberry Fields RemoteEngine.

    Xanadu Quantum Cloud is no longer a public service. This adapter is retained
    for private deployments, archived environments, and labs that still expose a
    Strawberry Fields/XCC-compatible endpoint.
    """

    name = "xanadu"
    target_name = "Xanadu Cloud (legacy)"
    package_hint = "strawberryfields and xanadu-cloud-client"
    credential_requirements = (("refresh_token", "api_key", "token", "access_token"),)
    supported_operations = ("BS", "PS", "S", "D", "photon_counting")
    max_modes = None
    max_shots = 500_000

    def _create_client(self) -> "XanaduRemoteEngineClient":
        try:
            sf = importlib.import_module("strawberryfields")
            ops = importlib.import_module("strawberryfields.ops")
            xcc = importlib.import_module("xcc")
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'xanadu' requires the legacy optional dependencies "
                "'strawberryfields' and 'xanadu-cloud-client'. Install in a "
                "compatible Python environment with `pip install "
                "photon-qdrivers[xanadu]`."
            ) from exc

        remote_engine_cls = getattr(sf, "RemoteEngine", None)
        if remote_engine_cls is None:
            raise BackendUnavailableError(
                "Backend 'xanadu' requires strawberryfields.RemoteEngine."
            )

        connection_cls = getattr(xcc, "Connection", None)
        job_cls = getattr(xcc, "Job", None)
        if connection_cls is None or job_cls is None:
            raise BackendUnavailableError(
                "Backend 'xanadu' requires xcc.Connection and xcc.Job from "
                "'xanadu-cloud-client'."
            )

        return XanaduRemoteEngineClient(
            sf=sf,
            ops=ops,
            remote_engine_cls=remote_engine_cls,
            connection_cls=connection_cls,
            job_cls=job_cls,
            config=self.config,
        )

    def _validate_hardware_circuit(self, circuit: PhotonicCircuit) -> None:
        super()._validate_hardware_circuit(circuit)
        _validate_strawberryfields_circuit(circuit)

    def _build_payload(self, job):
        payload = super()._build_payload(job)
        payload["xanadu"] = {
            "adapter": "strawberryfields_remote_engine",
            "target": _xanadu_target(self.config),
            "compile_options": _compile_options(job.circuit, self.config),
            "recompile": _recompile(job.circuit, self.config),
            "legacy_cloud": True,
        }
        payload["metadata"]["adapter"] = "strawberryfields_remote_engine"
        payload["metadata"]["legacy_cloud"] = True
        return payload


class XanaduRemoteEngineClient:
    """CloudJobClient implementation for Strawberry Fields RemoteEngine."""

    def __init__(
        self,
        *,
        sf: Any,
        ops: Any,
        remote_engine_cls: Any,
        connection_cls: Any,
        job_cls: Any,
        config: BackendConfig,
    ) -> None:
        self._sf = sf
        self._ops = ops
        self._remote_engine_cls = remote_engine_cls
        self._connection_cls = connection_cls
        self._job_cls = job_cls
        self._config = config
        self._connection = self._build_connection()
        self._jobs: dict[str, Any] = {}

    def submit_job(self, payload: Mapping[str, Any]) -> CloudJobSnapshot:
        circuit = PhotonicCircuit.from_mapping(payload["circuit"])
        program = _build_program(self._sf, self._ops, circuit)
        engine = self._build_engine(payload)

        run_kwargs: dict[str, Any] = {
            "shots": int(payload["shots"]),
            "compile_options": _compile_options(circuit, self._config),
            "recompile": _recompile(circuit, self._config),
        }
        run_async = getattr(engine, "run_async", None)
        if not callable(run_async):
            raise BackendExecutionError("strawberryfields.RemoteEngine lacks run_async().")

        provider_job = run_async(program, **run_kwargs)
        provider_job_id = _provider_job_id(provider_job)
        self._jobs[provider_job_id] = provider_job
        return self._snapshot_from_job(provider_job, shots=int(payload["shots"]))

    def get_job(self, provider_job_id: str) -> CloudJobSnapshot:
        provider_job = self._jobs.get(provider_job_id)
        if provider_job is None:
            provider_job = self._job_cls(provider_job_id, self._connection)
            self._jobs[provider_job_id] = provider_job

        clear = getattr(provider_job, "clear", None)
        if callable(clear):
            clear()
        return self._snapshot_from_job(provider_job)

    def cancel_job(self, provider_job_id: str) -> bool:
        provider_job = self._jobs.get(provider_job_id)
        if provider_job is None:
            provider_job = self._job_cls(provider_job_id, self._connection)
            self._jobs[provider_job_id] = provider_job

        cancel = getattr(provider_job, "cancel", None)
        if not callable(cancel):
            return False
        cancel()
        return True

    def close(self) -> None:
        self._jobs.clear()

    def _build_connection(self) -> Any:
        refresh_token = _credential(self._config, "refresh_token", "api_key", "token")
        access_token = _credential(self._config, "access_token")
        host, port, tls = _connection_endpoint(self._config)
        headers = self._config.options.get("headers")

        kwargs: dict[str, Any] = {}
        if refresh_token:
            kwargs["refresh_token"] = refresh_token
        if access_token:
            kwargs["access_token"] = access_token
        if host:
            kwargs["host"] = host
        if port is not None:
            kwargs["port"] = port
        if tls is not None:
            kwargs["tls"] = tls
        if isinstance(headers, Mapping):
            kwargs["headers"] = dict(headers)

        try:
            return self._connection_cls(**kwargs)
        except TypeError:
            return self._connection_cls(
                refresh_token=refresh_token or None,
                access_token=access_token or None,
            )

    def _build_engine(self, payload: Mapping[str, Any]) -> Any:
        target = _xanadu_target(self._config)
        xanadu_config = payload.get("xanadu", {})
        if isinstance(xanadu_config, Mapping):
            target = str(xanadu_config.get("target", target))

        backend_options = _backend_options(self._config)
        try:
            return self._remote_engine_cls(
                target,
                connection=self._connection,
                backend_options=backend_options or None,
            )
        except TypeError:
            return self._remote_engine_cls(target, connection=self._connection)

    def _snapshot_from_job(self, provider_job: Any, *, shots: int | None = None) -> CloudJobSnapshot:
        state, raw_status, error = _job_state(provider_job)
        counts = None
        result_metadata: dict[str, Any] = {}
        if state == CloudJobState.COMPLETED:
            raw_result = _job_result(provider_job)
            counts = _extract_counts(raw_result)
            result_metadata = _result_metadata(raw_result)

        job_metadata = _job_metadata(provider_job)
        metadata = {
            "adapter": "strawberryfields_remote_engine",
            "target": _job_attr(provider_job, "target") or _xanadu_target(self._config),
            "legacy_cloud": True,
            "provider_metadata": job_metadata,
            **result_metadata,
        }

        return CloudJobSnapshot(
            provider_job_id=_provider_job_id(provider_job),
            state=state,
            counts=counts,
            shots=shots,
            metadata=redact_sensitive_mapping(metadata),
            error=error,
            raw_status=raw_status,
        )


def _xanadu_target(config: BackendConfig) -> str:
    for key in ("target", "device", "device_id", "processor_name"):
        value = config.options.get(key)
        if value:
            return str(value)
    return "X8_01"


def _credential(config: BackendConfig, *names: str) -> str:
    for name in names:
        value = config.credentials.get(name)
        if value:
            return str(value)
    return ""


def _connection_endpoint(config: BackendConfig) -> tuple[str | None, int | None, bool | None]:
    host = config.options.get("host")
    port = config.options.get("port")
    tls = config.options.get("tls")

    if config.endpoint:
        parsed = urlparse(config.endpoint if "://" in config.endpoint else f"https://{config.endpoint}")
        host = parsed.hostname or host
        port = parsed.port or port
        tls = parsed.scheme != "http"

    parsed_port = int(port) if port is not None else None
    parsed_tls = bool(tls) if tls is not None else None
    return str(host) if host else None, parsed_port, parsed_tls


def _compile_options(circuit: PhotonicCircuit, config: BackendConfig) -> dict[str, Any]:
    options: dict[str, Any] = {}
    configured = config.options.get("compile_options")
    if isinstance(configured, Mapping):
        options.update(dict(configured))
    circuit_options = circuit.metadata.get("compile_options")
    if isinstance(circuit_options, Mapping):
        options.update(dict(circuit_options))
    return options


def _recompile(circuit: PhotonicCircuit, config: BackendConfig) -> bool:
    value = circuit.metadata.get("recompile", config.options.get("recompile", False))
    return bool(value)


def _backend_options(config: BackendConfig) -> dict[str, Any]:
    configured = config.options.get("backend_options")
    if isinstance(configured, Mapping):
        return dict(configured)
    return {}


def _provider_job_id(provider_job: Any) -> str:
    return str(
        _job_attr(provider_job, "id")
        or _job_attr(provider_job, "job_id")
        or f"xanadu-{uuid4().hex}"
    )


def _job_attr(provider_job: Any, name: str) -> Any:
    if isinstance(provider_job, Mapping):
        return provider_job.get(name)
    value = getattr(provider_job, name, None)
    if callable(value):
        try:
            return value()
        except TypeError:
            return value
    return value


def _job_state(provider_job: Any) -> tuple[CloudJobState, str, str | None]:
    raw_status = str(_job_attr(provider_job, "status") or "open")
    metadata = _job_metadata(provider_job)
    error = _metadata_error(metadata)

    normalized = raw_status.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"complete", "completed", "done", "success", "succeeded"}:
        return CloudJobState.COMPLETED, raw_status, error
    if normalized in {"failed", "failure", "error", "errored"}:
        return CloudJobState.FAILED, raw_status, error
    if normalized in {"cancelled", "canceled"}:
        return CloudJobState.CANCELLED, raw_status, error
    if normalized in {"running", "active", "executing", "processing", "cancel_pending"}:
        return CloudJobState.RUNNING, raw_status, error
    if normalized in {"open", "queued", "pending", "submitted", "accepted"}:
        return CloudJobState.QUEUED, raw_status, error
    return CloudJobState.CREATED, raw_status, error


def _job_metadata(provider_job: Any) -> dict[str, Any]:
    metadata = _job_attr(provider_job, "metadata")
    if isinstance(metadata, Mapping):
        return dict(metadata)
    overview = _job_attr(provider_job, "overview")
    if isinstance(overview, Mapping):
        return dict(overview)
    return {}


def _metadata_error(metadata: Mapping[str, Any]) -> str | None:
    for key in ("error", "errors", "message", "detail", "details"):
        value = metadata.get(key)
        if value:
            return str(value)
    return None


def _job_result(provider_job: Any) -> Any:
    result = _job_attr(provider_job, "result")
    if result is not None:
        return result

    get_result = getattr(provider_job, "get_result", None)
    if callable(get_result):
        return get_result()

    raise BackendExecutionError("Completed Xanadu Cloud job does not expose a result.")


def _extract_counts(raw_result: Any) -> dict[str, int]:
    samples = _result_samples(raw_result)
    if samples is not None:
        return _samples_to_counts(samples)

    if isinstance(raw_result, Mapping) and "counts" in raw_result:
        return {str(state): int(count) for state, count in raw_result["counts"].items()}

    raise BackendExecutionError("Xanadu Cloud result does not contain samples or counts.")


def _result_samples(raw_result: Any) -> Any | None:
    if hasattr(raw_result, "samples"):
        return raw_result.samples

    if not isinstance(raw_result, Mapping):
        return None

    if "samples" in raw_result:
        return raw_result["samples"]
    if "output" not in raw_result:
        return None

    output = raw_result["output"]
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes, bytearray)):
        if len(output) == 1:
            return output[0]
        return _flatten_output_batches(output)
    return output


def _flatten_output_batches(output: Sequence[Any]) -> list[Any]:
    flattened: list[Any] = []
    for batch in output:
        if hasattr(batch, "tolist"):
            batch = batch.tolist()
        if (
            isinstance(batch, Sequence)
            and not isinstance(batch, (str, bytes, bytearray))
            and batch
            and not _is_flat_numeric_sample(batch)
        ):
            flattened.extend(batch)
        else:
            flattened.append(batch)
    return flattened


def _is_flat_numeric_sample(value: Sequence[Any]) -> bool:
    return all(isinstance(item, int) and not isinstance(item, bool) for item in value)


def _result_metadata(raw_result: Any) -> dict[str, Any]:
    metadata = {
        "result_format": "xanadu_cloud_samples",
    }
    if isinstance(raw_result, Mapping):
        for key, value in raw_result.items():
            if key in {"counts", "output", "samples"}:
                continue
            metadata[str(key)] = value
    return metadata
