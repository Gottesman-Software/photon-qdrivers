"""Quandela hardware adapter implemented through Perceval RemoteProcessor."""

from __future__ import annotations

import importlib
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

from .perceval_backend import (
    _build_input_state,
    _build_perceval_circuit,
    _validate_perceval_circuit,
)


class QuandelaBackend(CloudHardwareBackend):
    """Quandela cloud hardware backend using Perceval's remote runtime."""

    name = "quandela"
    target_name = "Quandela"
    package_hint = "perceval-quandela"
    max_modes = 24
    max_shots = 500_000

    def _create_client(self) -> "QuandelaPercevalClient":
        try:
            pcvl = importlib.import_module("perceval")
            algorithm = importlib.import_module("perceval.algorithm")
        except ImportError as exc:
            raise BackendUnavailableError(
                "Backend 'quandela' requires the optional Quandela SDK path "
                "'perceval-quandela'. Install with `pip install "
                "photon-qdrivers[quandela]` or `pip install perceval-quandela`."
            ) from exc

        remote_processor_cls = _resolve_remote_processor(pcvl)
        sampler_cls = getattr(algorithm, "Sampler", None)
        if sampler_cls is None:
            raise BackendUnavailableError(
                "Backend 'quandela' could not find perceval.algorithm.Sampler "
                "in the installed 'perceval-quandela' package."
            )

        return QuandelaPercevalClient(
            pcvl=pcvl,
            sampler_cls=sampler_cls,
            remote_processor_cls=remote_processor_cls,
            config=self.config,
        )

    def _validate_hardware_circuit(self, circuit: PhotonicCircuit) -> None:
        super()._validate_hardware_circuit(circuit)
        _validate_perceval_circuit(circuit)

    def _build_payload(self, job):
        payload = super()._build_payload(job)
        payload["quandela"] = {
            "adapter": "perceval_remote_processor",
            "processor_name": _processor_name(self.config),
            "min_detected_photons": _min_detected_photons(self.config),
            "max_shots_per_call": _max_shots_per_call(self.config, job.shots),
        }
        payload["metadata"]["adapter"] = "perceval_remote_processor"
        return payload


class QuandelaPercevalClient:
    """Small compatibility layer around Perceval's RemoteProcessor runtime."""

    def __init__(
        self,
        *,
        pcvl: Any,
        sampler_cls: Any,
        remote_processor_cls: Any,
        config: BackendConfig,
    ) -> None:
        self._pcvl = pcvl
        self._sampler_cls = sampler_cls
        self._remote_processor_cls = remote_processor_cls
        self._config = config
        self._provider_jobs: dict[str, Any] = {}
        self._completed_snapshots: dict[str, CloudJobSnapshot] = {}

    def submit_job(self, payload: Mapping[str, Any]) -> CloudJobSnapshot:
        circuit = PhotonicCircuit.from_mapping(payload["circuit"])
        processor = self._build_remote_processor(payload=payload, circuit=circuit)
        sampler = self._build_sampler(processor, payload=payload)
        sample_count = getattr(sampler, "sample_count", None)
        if sample_count is None:
            raise BackendExecutionError("Perceval Sampler does not expose sample_count.")

        shots = int(payload["shots"])
        if hasattr(sample_count, "execute_async"):
            provider_job = sample_count.execute_async(shots)
            return self._remember_provider_job(provider_job, shots=shots)

        if callable(sample_count):
            result = sample_count(shots)
            if _is_result_mapping(result):
                return self._completed_snapshot_from_result(result, shots=shots)
            if hasattr(result, "execute_async"):
                provider_job = result.execute_async(shots)
                return self._remember_provider_job(provider_job, shots=shots)
            return self._remember_provider_job(result, shots=shots)

        raise BackendExecutionError("Perceval Sampler.sample_count is not executable.")

    def get_job(self, provider_job_id: str) -> CloudJobSnapshot:
        if provider_job_id in self._completed_snapshots:
            return self._completed_snapshots[provider_job_id]

        provider_job = self._provider_jobs.get(provider_job_id)
        if provider_job is None:
            raise BackendExecutionError(
                f"Unknown Quandela provider job id '{provider_job_id}'."
            )
        return self._snapshot_from_provider_job(provider_job, provider_job_id=provider_job_id)

    def cancel_job(self, provider_job_id: str) -> bool:
        provider_job = self._provider_jobs.get(provider_job_id)
        if provider_job is None:
            return provider_job_id in self._completed_snapshots

        cancel = getattr(provider_job, "cancel", None)
        if not callable(cancel):
            return False
        cancel()
        return True

    def close(self) -> None:
        self._provider_jobs.clear()
        self._completed_snapshots.clear()

    def _build_remote_processor(
        self,
        *,
        payload: Mapping[str, Any],
        circuit: PhotonicCircuit,
    ) -> Any:
        processor_name = _processor_name(self._config)
        quandela_config = payload.get("quandela", {})
        if isinstance(quandela_config, Mapping):
            processor_name = str(quandela_config.get("processor_name", processor_name))

        processor = self._instantiate_remote_processor(
            processor_name=processor_name,
            modes=circuit.modes,
        )
        perceval_circuit = _build_perceval_circuit(self._pcvl, circuit)
        input_state = _build_input_state(self._pcvl, circuit)

        if callable(getattr(processor, "set_circuit", None)):
            processor.set_circuit(perceval_circuit)
        elif callable(getattr(processor, "add", None)):
            processor.add(0, perceval_circuit)
        else:
            raise BackendExecutionError(
                "Perceval RemoteProcessor does not support circuit assignment."
            )

        min_detected = _min_detected_photons(self._config)
        if callable(getattr(processor, "min_detected_photons_filter", None)):
            processor.min_detected_photons_filter(min_detected)

        if callable(getattr(processor, "with_input", None)):
            processor.with_input(input_state)
        else:
            raise BackendExecutionError("Perceval RemoteProcessor does not accept input states.")

        return processor

    def _instantiate_remote_processor(self, *, processor_name: str, modes: int) -> Any:
        token = _credential(self._config, "token", "api_key")
        endpoint = self._config.endpoint
        proxy_config = self._config.options.get("proxies")

        kwargs: dict[str, Any] = {"token": token, "m": modes}
        if endpoint:
            kwargs["url"] = endpoint
        if proxy_config is not None:
            kwargs["proxies"] = proxy_config

        attempts = (
            (processor_name, kwargs),
            (processor_name, {key: value for key, value in kwargs.items() if key != "proxies"}),
            (processor_name, {"token": token}),
            (processor_name, {}),
            (processor_name, token),
        )
        last_error: TypeError | None = None
        for args in attempts:
            try:
                if isinstance(args[1], Mapping):
                    return self._remote_processor_cls(args[0], **args[1])
                return self._remote_processor_cls(args[0], args[1])
            except TypeError as exc:
                last_error = exc

        raise BackendExecutionError(
            "Unable to construct Perceval RemoteProcessor with the installed SDK."
        ) from last_error

    def _build_sampler(self, processor: Any, *, payload: Mapping[str, Any]) -> Any:
        max_shots = _max_shots_per_call(self._config, int(payload["shots"]))
        try:
            return self._sampler_cls(processor, max_shots_per_call=max_shots)
        except TypeError:
            return self._sampler_cls(processor)

    def _remember_provider_job(self, provider_job: Any, *, shots: int) -> CloudJobSnapshot:
        provider_job_id = _provider_job_id(provider_job)
        self._provider_jobs[provider_job_id] = provider_job
        snapshot = self._snapshot_from_provider_job(
            provider_job,
            provider_job_id=provider_job_id,
            shots=shots,
        )
        if snapshot.terminal:
            self._completed_snapshots[provider_job_id] = snapshot
        return snapshot

    def _completed_snapshot_from_result(self, result: Mapping[str, Any], *, shots: int) -> CloudJobSnapshot:
        provider_job_id = f"quandela-sync-{uuid4().hex}"
        snapshot = CloudJobSnapshot(
            provider_job_id=provider_job_id,
            state=CloudJobState.COMPLETED,
            counts=_extract_counts(result),
            shots=shots,
            metadata=_result_metadata(result, adapter="perceval_remote_processor"),
            raw_status="completed",
        )
        self._completed_snapshots[provider_job_id] = snapshot
        return snapshot

    def _snapshot_from_provider_job(
        self,
        provider_job: Any,
        *,
        provider_job_id: str,
        shots: int | None = None,
    ) -> CloudJobSnapshot:
        state, raw_status, error = _provider_job_state(provider_job)
        counts = None
        metadata = {
            "adapter": "perceval_remote_processor",
            "processor_name": _processor_name(self._config),
        }

        if state == CloudJobState.COMPLETED:
            result = _provider_job_results(provider_job)
            counts = _extract_counts(result)
            metadata.update(_result_metadata(result, adapter="perceval_remote_processor"))

        snapshot = CloudJobSnapshot(
            provider_job_id=provider_job_id,
            state=state,
            counts=counts,
            shots=shots,
            metadata=redact_sensitive_mapping(metadata),
            error=error,
            raw_status=raw_status,
        )
        if snapshot.terminal:
            self._completed_snapshots[provider_job_id] = snapshot
        return snapshot


def _resolve_remote_processor(pcvl: Any) -> Any:
    remote_processor_cls = getattr(pcvl, "RemoteProcessor", None)
    if remote_processor_cls is not None:
        return remote_processor_cls

    for module_name in (
        "perceval.runtime",
        "perceval.runtime.remote_processor",
    ):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        remote_processor_cls = getattr(module, "RemoteProcessor", None)
        if remote_processor_cls is not None:
            return remote_processor_cls

    raise BackendUnavailableError(
        "Backend 'quandela' requires perceval.RemoteProcessor or "
        "perceval.runtime.RemoteProcessor from 'perceval-quandela'."
    )


def _processor_name(config: BackendConfig) -> str:
    for key in ("processor_name", "device", "device_id", "qpu", "platform"):
        value = config.options.get(key)
        if value:
            return str(value)
    return "qpu:belenos"


def _credential(config: BackendConfig, *names: str) -> str:
    for name in names:
        value = config.credentials.get(name)
        if value:
            return str(value)
    return ""


def _min_detected_photons(config: BackendConfig) -> int:
    value = config.options.get("min_detected_photons", 0)
    if isinstance(value, bool):
        raise CircuitValidationError("min_detected_photons must be an integer.")
    return int(value)


def _max_shots_per_call(config: BackendConfig, job_shots: int) -> int:
    value = config.options.get("max_shots_per_call", job_shots)
    if isinstance(value, bool):
        raise CircuitValidationError("max_shots_per_call must be an integer.")
    return int(value)


def _provider_job_id(provider_job: Any) -> str:
    for attr_name in ("id", "job_id", "provider_job_id"):
        value = getattr(provider_job, attr_name, None)
        if value:
            return str(value)
    if isinstance(provider_job, Mapping):
        for key in ("id", "job_id", "provider_job_id"):
            value = provider_job.get(key)
            if value:
                return str(value)
    return f"quandela-{uuid4().hex}"


def _provider_job_state(provider_job: Any) -> tuple[CloudJobState, str, str | None]:
    if isinstance(provider_job, Mapping):
        raw_status = str(
            provider_job.get("status")
            or provider_job.get("state")
            or provider_job.get("job_status")
            or "created"
        )
        error = provider_job.get("error") or provider_job.get("message")
        return _state_from_text(raw_status), raw_status, str(error) if error else None

    status = getattr(provider_job, "status", None)
    raw_status = _status_text(status)
    error = _status_error(status)

    if _truthy_attr(provider_job, "is_complete") or _truthy_attr(status, "success"):
        return CloudJobState.COMPLETED, raw_status, error
    if _truthy_attr(provider_job, "is_failed") or _truthy_attr(status, "failed"):
        return CloudJobState.FAILED, raw_status, error
    if _truthy_attr(provider_job, "is_cancelled") or _truthy_attr(provider_job, "is_canceled"):
        return CloudJobState.CANCELLED, raw_status, error
    if _truthy_attr(status, "canceled") or _truthy_attr(status, "cancelled"):
        return CloudJobState.CANCELLED, raw_status, error
    if _truthy_attr(status, "running"):
        return CloudJobState.RUNNING, raw_status, error

    return _state_from_text(raw_status), raw_status, error


def _status_text(status: Any) -> str:
    if status is None:
        return "created"

    nested_status = getattr(status, "status", None)
    if nested_status is not None and nested_status is not status:
        return _enum_text(nested_status)
    return _enum_text(status)


def _enum_text(value: Any) -> str:
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    enum_name = getattr(value, "name", None)
    if enum_name is not None:
        return str(enum_name)
    return str(value)


def _status_error(status: Any) -> str | None:
    if status is None:
        return None
    for attr_name in ("stop_message", "message", "error"):
        value = getattr(status, attr_name, None)
        if value:
            return str(value)
    return None


def _truthy_attr(obj: Any, attr_name: str) -> bool:
    if obj is None:
        return False
    value = getattr(obj, attr_name, None)
    if callable(value):
        try:
            value = value()
        except TypeError:
            return False
    return bool(value)


def _state_from_text(raw_status: str) -> CloudJobState:
    normalized = raw_status.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = normalized.removeprefix("runningstatus.")
    if normalized in {"success", "succeeded", "complete", "completed", "done"}:
        return CloudJobState.COMPLETED
    if normalized in {"error", "failed", "failure", "errored"}:
        return CloudJobState.FAILED
    if normalized in {"canceled", "cancelled", "cancel_request", "cancel_requested"}:
        return CloudJobState.CANCELLED
    if normalized in {"waiting", "pending", "queued", "submitted", "accepted"}:
        return CloudJobState.QUEUED
    if normalized in {"running", "active", "executing", "processing", "suspended"}:
        return CloudJobState.RUNNING
    return CloudJobState.CREATED


def _provider_job_results(provider_job: Any) -> Mapping[str, Any]:
    if isinstance(provider_job, Mapping):
        return provider_job

    get_results = getattr(provider_job, "get_results", None)
    if callable(get_results):
        result = get_results()
    elif callable(getattr(provider_job, "result", None)):
        result = provider_job.result()
    else:
        raise BackendExecutionError("Completed Perceval job does not expose results.")

    if not isinstance(result, Mapping):
        raise BackendExecutionError("Perceval job results must be a mapping.")
    return result


def _is_result_mapping(value: Any) -> bool:
    return isinstance(value, Mapping) and (
        "results" in value
        or "counts" in value
        or "results_list" in value
        or "samples" in value
        or _looks_like_counts(value)
    )


def _extract_counts(result: Mapping[str, Any]) -> dict[str, int]:
    if "results" in result:
        return _normalize_counts(result["results"])
    if "counts" in result:
        return _normalize_counts(result["counts"])
    if "samples" in result:
        return _count_samples(result["samples"])
    if "results_list" in result:
        counts: dict[str, int] = {}
        for entry in result["results_list"]:
            if not isinstance(entry, Mapping) or "results" not in entry:
                raise BackendExecutionError("Perceval results_list entries must contain results.")
            for state, count in _normalize_counts(entry["results"]).items():
                counts[state] = counts.get(state, 0) + count
        return counts
    if _looks_like_counts(result):
        return _normalize_counts(result)
    raise BackendExecutionError("Perceval result did not contain sample counts.")


def _normalize_counts(value: Any) -> dict[str, int]:
    if isinstance(value, Mapping):
        counts: dict[str, int] = {}
        for state, count in value.items():
            if isinstance(count, bool):
                raise BackendExecutionError("Perceval count values must be integers.")
            counts[str(state)] = int(count)
        return counts
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _count_samples(value)
    raise BackendExecutionError("Perceval counts must be a mapping or sample sequence.")


def _count_samples(samples: Any) -> dict[str, int]:
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes, bytearray)):
        raise BackendExecutionError("Perceval samples must be a sequence.")
    counts: dict[str, int] = {}
    for sample in samples:
        state = str(sample)
        counts[state] = counts.get(state, 0) + 1
    return counts


def _looks_like_counts(value: Mapping[Any, Any]) -> bool:
    if not value:
        return False
    reserved = {
        "counts",
        "error",
        "id",
        "job_id",
        "logical_perf",
        "message",
        "physical_perf",
        "provider_job_id",
        "results",
        "results_list",
        "samples",
        "state",
        "status",
    }
    if any(str(key) in reserved for key in value):
        return False
    return all(not isinstance(count, bool) and isinstance(count, int | float) for count in value.values())


def _result_metadata(result: Mapping[str, Any], *, adapter: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"adapter": adapter, "result_format": "perceval_sample_count"}
    for key, value in result.items():
        if key in {"results", "results_list", "samples"}:
            continue
        metadata[str(key)] = value
    return redact_sensitive_mapping(metadata)
