"""ORCA Computing hardware adapter.

ORCA does not currently expose a stable public Python package in this repo's
dependency set. This adapter therefore supports two production integration
paths:

- a private ORCA SDK module, selected with `options["sdk_module"]` or discovered
  from conservative module names; and
- an HTTPS endpoint selected with `BackendConfig.endpoint`.

Both paths are wrapped behind the shared `CloudHardwareBackend` contract.
"""

from __future__ import annotations

import importlib
import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from photon_qdrivers.cloud import CloudJobSnapshot, CloudJobState, redact_sensitive_mapping
from photon_qdrivers.config import BackendConfig
from photon_qdrivers.errors import (
    BackendExecutionError,
    BackendUnavailableError,
    CircuitValidationError,
)
from photon_qdrivers.hardware import CloudHardwareBackend
from photon_qdrivers.ir import PhotonicCircuit


_DEFAULT_SDK_MODULES = (
    "orca_quantum",
    "orca_computing",
    "orca_sdk",
)

_SUBMIT_METHODS = ("submit_job", "submit", "run_job", "run", "create_job")
_GET_METHODS = ("get_job", "retrieve_job", "job", "get")
_CANCEL_METHODS = ("cancel_job", "cancel")


class OrcaBackend(CloudHardwareBackend):
    """ORCA PT-series hardware adapter through a private SDK or REST endpoint."""

    name = "orca"
    target_name = "ORCA Computing"
    package_hint = "photon-qdrivers-orca"
    max_modes = 256
    max_shots = 1_000_000

    def _create_client(self) -> "OrcaSDKClient | OrcaRestClient":
        sdk_module_name = _configured_sdk_module(self.config)
        if sdk_module_name:
            return self._create_sdk_client(sdk_module_name)

        endpoint = _endpoint(self.config)
        if endpoint:
            return OrcaRestClient(config=self.config, endpoint=endpoint)

        for candidate in _DEFAULT_SDK_MODULES:
            try:
                return self._create_sdk_client(candidate)
            except BackendUnavailableError:
                continue

        raise BackendUnavailableError(
            "Backend 'orca' requires an ORCA SDK module or an HTTPS endpoint. "
            "Install the private ORCA adapter package if available "
            f"({self.package_hint}), pass BackendConfig(endpoint=...), or set "
            "PHOTON_QDRIVERS_ORCA_ENDPOINT."
        )

    def _validate_hardware_circuit(self, circuit: PhotonicCircuit) -> None:
        super()._validate_hardware_circuit(circuit)
        for index, operation in enumerate(circuit.operations):
            if operation.name == "BS" and len(operation.modes) != 2:
                raise CircuitValidationError(f"ORCA BS operation {index} must target two modes.")
            if operation.name == "PS" and len(operation.modes) != 1:
                raise CircuitValidationError(f"ORCA PS operation {index} must target one mode.")

    def _build_payload(self, job):
        payload = super()._build_payload(job)
        payload["orca"] = {
            "adapter": "orca_hardware",
            "device": _device_name(self.config),
            "profile": self.config.profile,
            "workload_type": str(self.config.options.get("workload_type", "photonic_circuit")),
        }
        application = self.config.options.get("application")
        if application:
            payload["orca"]["application"] = str(application)
        payload["metadata"]["adapter"] = "orca_hardware"
        return payload

    def _create_sdk_client(self, module_name: str) -> "OrcaSDKClient":
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise BackendUnavailableError(
                f"Backend 'orca' could not import ORCA SDK module '{module_name}'. "
                f"Expected adapter package: {self.package_hint}."
            ) from exc

        factory = _resolve_sdk_client_factory(module, self.config)
        client = _instantiate_sdk_client(factory, self.config)
        return OrcaSDKClient(client=client, config=self.config)


class OrcaSDKClient:
    """Compatibility wrapper around private ORCA Python SDK clients."""

    def __init__(self, *, client: Any, config: BackendConfig) -> None:
        self._client = client
        self._config = config
        self._provider_jobs: dict[str, Any] = {}

    def submit_job(self, payload: Mapping[str, Any]) -> CloudJobSnapshot:
        submit = _resolve_callable(
            self._client,
            _method_names(self._config, "submit_method", _SUBMIT_METHODS),
            purpose="submit ORCA jobs",
        )
        provider_job = _call_provider_method(submit, payload)
        snapshot = _snapshot_from_provider_value(
            provider_job,
            adapter="orca_sdk",
            default_shots=int(payload["shots"]),
            default_metadata=_provider_metadata(self._config, adapter="orca_sdk"),
        )
        self._provider_jobs[snapshot.provider_job_id] = provider_job
        return snapshot

    def get_job(self, provider_job_id: str) -> CloudJobSnapshot:
        get_job = _optional_callable(
            self._client,
            _method_names(self._config, "get_method", _GET_METHODS),
        )
        if get_job is not None:
            provider_job = get_job(provider_job_id)
            self._provider_jobs[provider_job_id] = provider_job
        else:
            provider_job = self._provider_jobs.get(provider_job_id)

        if provider_job is None:
            raise BackendExecutionError(f"Unknown ORCA provider job id '{provider_job_id}'.")

        refreshed = _refresh_provider_job(provider_job)
        if refreshed is not None:
            provider_job = refreshed
            self._provider_jobs[provider_job_id] = provider_job

        return _snapshot_from_provider_value(
            provider_job,
            adapter="orca_sdk",
            default_metadata=_provider_metadata(self._config, adapter="orca_sdk"),
        )

    def cancel_job(self, provider_job_id: str) -> bool:
        provider_job = self._provider_jobs.get(provider_job_id)
        if provider_job is not None:
            cancel = _optional_callable(provider_job, _CANCEL_METHODS)
            if cancel is not None:
                cancel()
                return True

        cancel_job = _optional_callable(
            self._client,
            _method_names(self._config, "cancel_method", _CANCEL_METHODS),
        )
        if cancel_job is None:
            return False
        cancel_job(provider_job_id)
        return True

    def close(self) -> None:
        close = _optional_callable(self._client, ("close", "shutdown", "disconnect"))
        if close is not None:
            close()
        self._provider_jobs.clear()


class OrcaRestClient:
    """Configurable JSON-over-HTTPS client for ORCA-compatible deployments."""

    def __init__(self, *, config: BackendConfig, endpoint: str) -> None:
        self._config = config
        self._endpoint = endpoint.rstrip("/")

    def submit_job(self, payload: Mapping[str, Any]) -> CloudJobSnapshot:
        response = self._request(
            "POST",
            str(self._config.options.get("submit_path", "/jobs")),
            payload,
        )
        return _snapshot_from_provider_value(
            response,
            adapter="orca_rest",
            default_shots=int(payload["shots"]),
            default_metadata=_provider_metadata(self._config, adapter="orca_rest"),
        )

    def get_job(self, provider_job_id: str) -> CloudJobSnapshot:
        template = str(self._config.options.get("job_path_template", "/jobs/{job_id}"))
        response = self._request("GET", _format_path(template, provider_job_id), None)
        return _snapshot_from_provider_value(
            response,
            adapter="orca_rest",
            default_metadata=_provider_metadata(self._config, adapter="orca_rest"),
        )

    def cancel_job(self, provider_job_id: str) -> bool:
        template = str(
            self._config.options.get("cancel_path_template", "/jobs/{job_id}/cancel")
        )
        try:
            self._request("POST", _format_path(template, provider_job_id), {})
        except BackendExecutionError:
            return False
        return True

    def close(self) -> None:
        return None

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        body = None
        if payload is not None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")

        request = urllib.request.Request(
            _join_url(self._endpoint, path),
            data=body,
            headers=_headers(self._config),
            method=method,
        )
        timeout = _http_timeout_seconds(self._config)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise BackendExecutionError(
                f"ORCA endpoint returned HTTP {exc.code}: {message}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BackendExecutionError(f"ORCA endpoint request failed: {exc.reason}") from exc

        if not raw_body.strip():
            return {"status": "completed"}
        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise BackendExecutionError("ORCA endpoint returned invalid JSON.") from exc
        if not isinstance(parsed, Mapping):
            raise BackendExecutionError("ORCA endpoint response must be a JSON object.")
        return parsed


def _configured_sdk_module(config: BackendConfig) -> str | None:
    value = config.options.get("sdk_module") or config.options.get("client_module")
    return str(value) if value else None


def _resolve_sdk_client_factory(module: Any, config: BackendConfig) -> Any:
    configured = config.options.get("client_class") or config.options.get("client_factory")
    candidate_names = (str(configured),) if configured else (
        "Client",
        "OrcaClient",
        "ORCAClient",
        "QuantumClient",
        "PTClient",
        "HardwareClient",
    )
    for name in candidate_names:
        value = getattr(module, name, None)
        if callable(value):
            return value
    raise BackendUnavailableError(
        "Backend 'orca' could not find a usable SDK client class. "
        "Set options['client_class'] to the private ORCA SDK client class name."
    )


def _instantiate_sdk_client(factory: Any, config: BackendConfig) -> Any:
    token = _credential(config, "token", "access_token")
    api_key = _credential(config, "api_key")
    endpoint = _endpoint(config)
    device = _device_name(config)
    client_options = config.options.get("sdk_client_options", {})
    if client_options is None:
        client_options = {}
    if not isinstance(client_options, Mapping):
        raise BackendUnavailableError("ORCA sdk_client_options must be a mapping.")

    kwargs = dict(client_options)
    if token:
        kwargs.setdefault("token", token)
    if api_key:
        kwargs.setdefault("api_key", api_key)
    if endpoint:
        kwargs.setdefault("endpoint", endpoint)
    if device:
        kwargs.setdefault("device", device)
    if config.profile:
        kwargs.setdefault("profile", config.profile)
    for key in ("project_id", "organization", "region"):
        value = config.options.get(key)
        if value:
            kwargs.setdefault(key, value)

    attempts: tuple[tuple[Any, ...] | Mapping[str, Any], ...] = (
        kwargs,
        {"token": token, "endpoint": endpoint, "device": device},
        {"api_key": api_key, "endpoint": endpoint, "device": device},
        (token,),
        (),
    )
    last_error: TypeError | None = None
    for attempt in attempts:
        try:
            if isinstance(attempt, Mapping):
                clean_kwargs = {key: value for key, value in attempt.items() if value}
                return factory(**clean_kwargs)
            return factory(*[value for value in attempt if value])
        except TypeError as exc:
            last_error = exc

    raise BackendUnavailableError(
        "Unable to construct the ORCA SDK client with the configured credentials."
    ) from last_error


def _method_names(
    config: BackendConfig,
    option_name: str,
    defaults: Sequence[str],
) -> tuple[str, ...]:
    configured = config.options.get(option_name)
    if configured:
        return (str(configured),)
    return tuple(defaults)


def _resolve_callable(obj: Any, names: Sequence[str], *, purpose: str) -> Any:
    method = _optional_callable(obj, names)
    if method is None:
        joined = ", ".join(names)
        raise BackendExecutionError(
            f"ORCA SDK client does not expose a method to {purpose}. "
            f"Tried: {joined}."
        )
    return method


def _optional_callable(obj: Any, names: Sequence[str]) -> Any | None:
    for name in names:
        method = getattr(obj, name, None)
        if callable(method):
            return method
    return None


def _call_provider_method(method: Any, payload: Mapping[str, Any]) -> Any:
    try:
        return method(payload)
    except TypeError:
        return method(**payload)


def _refresh_provider_job(provider_job: Any) -> Any | None:
    refresh = _optional_callable(provider_job, ("refresh", "reload", "update"))
    if refresh is None:
        return None
    refreshed = refresh()
    return refreshed if refreshed is not None else provider_job


def _snapshot_from_provider_value(
    value: Any,
    *,
    adapter: str,
    default_shots: int | None = None,
    default_metadata: Mapping[str, Any] | None = None,
) -> CloudJobSnapshot:
    if isinstance(value, CloudJobSnapshot):
        return value
    if isinstance(value, Mapping):
        return _snapshot_from_mapping(
            value,
            adapter=adapter,
            default_shots=default_shots,
            default_metadata=default_metadata,
        )
    return _snapshot_from_object(
        value,
        adapter=adapter,
        default_shots=default_shots,
        default_metadata=default_metadata,
    )


def _snapshot_from_mapping(
    data: Mapping[str, Any],
    *,
    adapter: str,
    default_shots: int | None,
    default_metadata: Mapping[str, Any] | None,
) -> CloudJobSnapshot:
    job_data = _job_mapping(data)
    provider_job_id = _first_present(
        job_data,
        ("provider_job_id", "remote_job_id", "job_id", "id", "uuid"),
    ) or _first_present(data, ("provider_job_id", "remote_job_id", "job_id", "id", "uuid"))
    if provider_job_id is None:
        provider_job_id = f"orca-{uuid4().hex}"

    raw_status = _first_present(job_data, ("state", "status", "job_status"))
    if raw_status is None:
        raw_status = _first_present(data, ("state", "status", "job_status"))
    state = _state_from_status(raw_status)

    counts = _extract_counts(job_data)
    if counts is None:
        counts = _extract_counts(data)

    shots = _first_present(job_data, ("shots", "num_shots", "samples"))
    if shots is None:
        shots = _first_present(data, ("shots", "num_shots", "samples"))
    if shots is None:
        shots = default_shots

    metadata = _metadata_from_mapping(
        data,
        job_data=job_data,
        adapter=adapter,
        default_metadata=default_metadata,
    )
    error = _first_present(job_data, ("error", "message", "failure_reason"))
    if error is None:
        error = _first_present(data, ("error", "message", "failure_reason"))

    return CloudJobSnapshot(
        provider_job_id=str(provider_job_id),
        state=state,
        counts=counts,
        shots=int(shots) if shots is not None else None,
        metadata=redact_sensitive_mapping(metadata),
        error=str(error) if error else None,
        raw_status=str(raw_status) if raw_status is not None else state.value,
    )


def _snapshot_from_object(
    provider_job: Any,
    *,
    adapter: str,
    default_shots: int | None,
    default_metadata: Mapping[str, Any] | None,
) -> CloudJobSnapshot:
    provider_job_id = _object_first_attr(
        provider_job,
        ("provider_job_id", "remote_job_id", "job_id", "id", "uuid"),
    ) or f"orca-{uuid4().hex}"
    raw_status = _object_first_attr(provider_job, ("state", "status", "job_status"))
    state = _state_from_status(raw_status)
    result = _object_result(provider_job)
    counts = _extract_counts(result) if result is not None else None
    shots = _object_first_attr(provider_job, ("shots", "num_shots", "samples")) or default_shots
    error = _object_first_attr(provider_job, ("error", "message", "failure_reason"))

    metadata = dict(default_metadata or {})
    metadata.update(
        {
            "adapter": adapter,
            "result_format": "orca_provider_job",
            "provider_type": type(provider_job).__name__,
        }
    )
    if isinstance(result, Mapping):
        metadata.update(_metadata_without_result_payload(result))

    return CloudJobSnapshot(
        provider_job_id=str(provider_job_id),
        state=state,
        counts=counts,
        shots=int(shots) if shots is not None else None,
        metadata=redact_sensitive_mapping(metadata),
        error=str(error) if error else None,
        raw_status=str(raw_status) if raw_status is not None else state.value,
    )


def _job_mapping(data: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("job", "data", "provider_job"):
        nested = data.get(key)
        if isinstance(nested, Mapping):
            return nested
    return data


def _extract_counts(data: Mapping[str, Any]) -> dict[str, int] | None:
    for key in ("counts", "histogram", "samples_count", "sample_counts"):
        value = data.get(key)
        if value is not None:
            return _normalize_counts(value)

    result = data.get("result") or data.get("results") or data.get("output")
    if isinstance(result, Mapping):
        return _extract_counts(result)
    if result is not None and not isinstance(result, (str, bytes, bytearray)):
        return _count_samples(result)

    samples = data.get("samples")
    if samples is not None and not isinstance(samples, (int, float, str, bytes, bytearray)):
        return _count_samples(samples)

    if _looks_like_counts(data):
        return _normalize_counts(data)
    return None


def _normalize_counts(value: Any) -> dict[str, int]:
    if isinstance(value, Mapping):
        counts: dict[str, int] = {}
        for state, count in value.items():
            if isinstance(count, bool):
                raise BackendExecutionError("ORCA count values must be integers.")
            counts[str(state)] = int(count)
        return counts
    return _count_samples(value)


def _count_samples(samples: Any) -> dict[str, int]:
    if isinstance(samples, (str, bytes, bytearray)):
        raise BackendExecutionError("ORCA samples must be a sequence, not a string.")
    if not isinstance(samples, Sequence):
        raise BackendExecutionError("ORCA samples must be a sequence.")

    counts: dict[str, int] = {}
    for sample in samples:
        state = _sample_state(sample)
        counts[state] = counts.get(state, 0) + 1
    return counts


def _sample_state(sample: Any) -> str:
    if isinstance(sample, Mapping):
        for key in ("state", "bitstring", "output", "sample"):
            value = sample.get(key)
            if value is not None:
                return str(value)
    if isinstance(sample, Sequence) and not isinstance(sample, (str, bytes, bytearray)):
        return "".join(str(value) for value in sample)
    return str(sample)


def _looks_like_counts(value: Mapping[Any, Any]) -> bool:
    if not value:
        return False
    reserved = {
        "api_key",
        "counts",
        "data",
        "error",
        "histogram",
        "id",
        "job",
        "job_id",
        "message",
        "metadata",
        "provider_job",
        "provider_job_id",
        "result",
        "results",
        "samples",
        "state",
        "status",
        "token",
    }
    if any(str(key) in reserved for key in value):
        return False
    return all(
        not isinstance(count, bool) and isinstance(count, int | float)
        for count in value.values()
    )


def _metadata_from_mapping(
    data: Mapping[str, Any],
    *,
    job_data: Mapping[str, Any],
    adapter: str,
    default_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metadata = dict(default_metadata or {})
    metadata.update(
        {
            "adapter": adapter,
            "result_format": "orca_provider_response",
        }
    )
    provider_metadata = data.get("metadata")
    if isinstance(provider_metadata, Mapping):
        metadata.update(provider_metadata)
    job_metadata = job_data.get("metadata")
    if isinstance(job_metadata, Mapping):
        metadata.update(job_metadata)
    metadata.update(_metadata_without_result_payload(data))
    return metadata


def _metadata_without_result_payload(data: Mapping[str, Any]) -> dict[str, Any]:
    omitted = {
        "counts",
        "data",
        "histogram",
        "job",
        "metadata",
        "output",
        "provider_job",
        "result",
        "results",
        "sample_counts",
        "samples",
        "samples_count",
    }
    metadata: dict[str, Any] = {}
    for key, value in data.items():
        if str(key) not in omitted:
            metadata[str(key)] = value
    return metadata


def _object_result(provider_job: Any) -> Mapping[str, Any] | None:
    for name in ("result", "results", "get_results", "get_result"):
        value = getattr(provider_job, name, None)
        if callable(value):
            value = value()
        if isinstance(value, Mapping):
            return value
    return None


def _state_from_status(status: Any) -> CloudJobState:
    if isinstance(status, CloudJobState):
        return status
    if status is None:
        return CloudJobState.CREATED
    nested_status = getattr(status, "status", None)
    if nested_status is not None and nested_status is not status:
        return _state_from_status(nested_status)
    enum_value = getattr(status, "value", None)
    enum_name = getattr(status, "name", None)
    text = str(enum_value if enum_value is not None else enum_name if enum_name else status)
    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "accepted": CloudJobState.QUEUED,
        "created": CloudJobState.CREATED,
        "new": CloudJobState.CREATED,
        "pending": CloudJobState.QUEUED,
        "queued": CloudJobState.QUEUED,
        "submitted": CloudJobState.QUEUED,
        "running": CloudJobState.RUNNING,
        "active": CloudJobState.RUNNING,
        "executing": CloudJobState.RUNNING,
        "processing": CloudJobState.RUNNING,
        "complete": CloudJobState.COMPLETED,
        "completed": CloudJobState.COMPLETED,
        "done": CloudJobState.COMPLETED,
        "success": CloudJobState.COMPLETED,
        "succeeded": CloudJobState.COMPLETED,
        "failed": CloudJobState.FAILED,
        "failure": CloudJobState.FAILED,
        "error": CloudJobState.FAILED,
        "errored": CloudJobState.FAILED,
        "cancelled": CloudJobState.CANCELLED,
        "canceled": CloudJobState.CANCELLED,
        "aborted": CloudJobState.CANCELLED,
    }
    return aliases.get(normalized, CloudJobState.CREATED)


def _object_first_attr(obj: Any, names: Sequence[str]) -> Any | None:
    for name in names:
        value = getattr(obj, name, None)
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
        if value:
            return value
    return None


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any | None:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _provider_metadata(config: BackendConfig, *, adapter: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "adapter": adapter,
        "target": "ORCA Computing",
        "device": _device_name(config),
    }
    if config.profile:
        metadata["profile"] = config.profile
    for key in ("project_id", "organization", "region", "application", "workload_type"):
        value = config.options.get(key)
        if value:
            metadata[key] = value
    return metadata


def _headers(config: BackendConfig) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "photon-qdrivers/0.1",
    }
    extra_headers = config.options.get("headers", {})
    if extra_headers is not None:
        if not isinstance(extra_headers, Mapping):
            raise BackendExecutionError("ORCA REST headers option must be a mapping.")
        headers.update({str(key): str(value) for key, value in extra_headers.items()})

    credential = _credential(config, "token", "access_token", "api_key")
    if not credential:
        return headers

    auth_header = str(config.options.get("auth_header", "")).strip()
    if auth_header:
        auth_prefix = str(config.options.get("auth_prefix", "")).strip()
        headers[auth_header] = f"{auth_prefix} {credential}".strip()
        return headers

    auth_scheme = str(config.options.get("auth_scheme", "bearer")).strip().lower()
    if auth_scheme in {"api_key", "apikey", "x-api-key"}:
        headers[str(config.options.get("api_key_header", "X-API-Key"))] = credential
    elif auth_scheme in {"token"}:
        headers["Authorization"] = f"Token {credential}"
    else:
        headers["Authorization"] = f"Bearer {credential}"
    return headers


def _endpoint(config: BackendConfig) -> str | None:
    endpoint = config.endpoint or config.options.get("endpoint")
    return str(endpoint) if endpoint else None


def _device_name(config: BackendConfig) -> str:
    for key in ("device", "device_id", "target", "processor_name", "qpu", "platform"):
        value = config.options.get(key)
        if value:
            return str(value)
    return "orca-pt-series"


def _credential(config: BackendConfig, *names: str) -> str:
    for name in names:
        value = config.credentials.get(name)
        if value:
            return str(value)
    return ""


def _format_path(template: str, provider_job_id: str) -> str:
    return template.format(job_id=provider_job_id, provider_job_id=provider_job_id)


def _join_url(endpoint: str, path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return endpoint.rstrip("/") + normalized_path


def _http_timeout_seconds(config: BackendConfig) -> float | None:
    value = config.options.get("http_timeout_seconds", config.timeout_seconds)
    return float(value) if value is not None else None
