"""Analytic photonic loopback model for deterministic control-plane experiments."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass, field
from itertools import combinations, product
from math import cos, isfinite, sin, sqrt
from typing import Any, Mapping

from ..errors import ControlValidationError
from .acquisition import AcquisitionKind, AcquisitionRecord
from .profile import HardwareProfile
from .program import ChannelRole, EventKind
from .sweep import SweepTargetKind
from .timing import CompiledControlEvent, CompiledControlProgram


ANALYTIC_LOOPBACK_SCHEMA_VERSION = "photon-qdrivers.control.loopback.v1"
ANALYTIC_LOOPBACK_MODEL_ID = "photon_qdrivers.control.analytic_loopback.v1"


@dataclass(frozen=True)
class LoopbackPath:
    """One coherent path from a source channel to a detector channel."""

    path_id: str
    source_channel: str
    detector_channel: str
    delay_ticks: int
    transmission: float = 1.0
    phase_offset_rad: float = 0.0

    def __post_init__(self) -> None:
        for value, label in (
            (self.path_id, "Loopback path id"),
            (self.source_channel, "Loopback source channel"),
            (self.detector_channel, "Loopback detector channel"),
        ):
            _require_identifier(value, label)
        _require_non_negative_int(self.delay_ticks, "Loopback path delay_ticks")
        _require_probability(self.transmission, "Loopback path transmission")
        _require_finite_number(
            self.phase_offset_rad, "Loopback path phase_offset_rad"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_id": self.path_id,
            "source_channel": self.source_channel,
            "detector_channel": self.detector_channel,
            "delay_ticks": self.delay_ticks,
            "transmission": self.transmission,
            "phase_offset_rad": self.phase_offset_rad,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LoopbackPath":
        _require_mapping(data, "Loopback path")
        try:
            return cls(
                path_id=data["path_id"],
                source_channel=data["source_channel"],
                detector_channel=data["detector_channel"],
                delay_ticks=data["delay_ticks"],
                transmission=data.get("transmission", 1.0),
                phase_offset_rad=data.get("phase_offset_rad", 0.0),
            )
        except KeyError as exc:
            raise _missing_field("Loopback path", exc) from exc


@dataclass(frozen=True)
class DetectorResponse:
    """Bounded analytic response for one detector channel."""

    detector_channel: str
    efficiency: float = 1.0
    dark_count_probability: float = 0.0
    dead_time_ticks: int = 0
    buffer_capacity: int = 65_536

    def __post_init__(self) -> None:
        _require_identifier(self.detector_channel, "Detector response channel")
        _require_probability(self.efficiency, "Detector efficiency")
        _require_probability(
            self.dark_count_probability, "Detector dark_count_probability"
        )
        _require_non_negative_int(
            self.dead_time_ticks, "Detector dead_time_ticks"
        )
        _require_positive_int(self.buffer_capacity, "Detector buffer_capacity")

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_channel": self.detector_channel,
            "efficiency": self.efficiency,
            "dark_count_probability": self.dark_count_probability,
            "dead_time_ticks": self.dead_time_ticks,
            "buffer_capacity": self.buffer_capacity,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "DetectorResponse":
        _require_mapping(data, "Detector response")
        try:
            return cls(
                detector_channel=data["detector_channel"],
                efficiency=data.get("efficiency", 1.0),
                dark_count_probability=data.get("dark_count_probability", 0.0),
                dead_time_ticks=data.get("dead_time_ticks", 0),
                buffer_capacity=data.get("buffer_capacity", 65_536),
            )
        except KeyError as exc:
            raise _missing_field("Detector response", exc) from exc


@dataclass(frozen=True)
class AnalyticLoopbackConfig:
    """Versioned optical paths, detector responses, and sampling controls."""

    paths: tuple[LoopbackPath, ...]
    detectors: tuple[DetectorResponse, ...]
    seed: int = 0
    coincidence_window_ticks: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ANALYTIC_LOOPBACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ANALYTIC_LOOPBACK_SCHEMA_VERSION:
            raise ControlValidationError(
                f"Unsupported analytic loopback schema '{self.schema_version}'. "
                f"Expected '{ANALYTIC_LOOPBACK_SCHEMA_VERSION}'."
            )
        paths = tuple(self.paths)
        detectors = tuple(self.detectors)
        object.__setattr__(self, "paths", paths)
        object.__setattr__(self, "detectors", detectors)
        if not paths:
            raise ControlValidationError(
                "Analytic loopback config must define at least one path."
            )
        if not detectors:
            raise ControlValidationError(
                "Analytic loopback config must define at least one detector response."
            )
        if any(not isinstance(path, LoopbackPath) for path in paths):
            raise ControlValidationError(
                "Analytic loopback paths must contain LoopbackPath objects."
            )
        if any(not isinstance(detector, DetectorResponse) for detector in detectors):
            raise ControlValidationError(
                "Analytic loopback detectors must contain DetectorResponse objects."
            )
        _require_unique(paths, "path_id", "loopback path")
        _require_unique(detectors, "detector_channel", "detector response")
        detector_channels = {
            detector.detector_channel for detector in detectors
        }
        for path in paths:
            if path.detector_channel not in detector_channels:
                raise ControlValidationError(
                    f"Loopback path '{path.path_id}' has no detector response for "
                    f"'{path.detector_channel}'."
                )
        route_delays: dict[tuple[str, str], set[int]] = {}
        for path in paths:
            route_delays.setdefault(
                (path.source_channel, path.detector_channel), set()
            ).add(path.delay_ticks)
        if any(len(delays) > 1 for delays in route_delays.values()):
            raise ControlValidationError(
                "Coherent paths between the same source and detector must have "
                "the same integer delay."
            )
        _require_non_negative_int(self.seed, "Analytic loopback seed")
        _require_non_negative_int(
            self.coincidence_window_ticks,
            "Analytic loopback coincidence_window_ticks",
        )
        _require_mapping(self.metadata, "Analytic loopback metadata")
        _canonical_json(self.to_dict(), "Analytic loopback config")

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict(), "Analytic loopback config")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "paths": [path.to_dict() for path in self.paths],
            "detectors": [detector.to_dict() for detector in self.detectors],
            "seed": self.seed,
            "coincidence_window_ticks": self.coincidence_window_ticks,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AnalyticLoopbackConfig":
        _require_mapping(data, "Analytic loopback config")
        try:
            raw_paths = _require_sequence(
                data["paths"], "Analytic loopback paths"
            )
            raw_detectors = _require_sequence(
                data["detectors"], "Analytic loopback detectors"
            )
            return cls(
                schema_version=data.get(
                    "schema_version", ANALYTIC_LOOPBACK_SCHEMA_VERSION
                ),
                paths=tuple(LoopbackPath.from_mapping(item) for item in raw_paths),
                detectors=tuple(
                    DetectorResponse.from_mapping(item) for item in raw_detectors
                ),
                seed=data.get("seed", 0),
                coincidence_window_ticks=data.get("coincidence_window_ticks", 0),
                metadata=data.get("metadata", {}),
            )
        except KeyError as exc:
            raise _missing_field("Analytic loopback config", exc) from exc


class AnalyticLoopbackPlant:
    """Produce analytic acquisitions from compiled schedules and optical paths.

    The model uses coherent path amplitudes followed by a deterministic,
    SHA-256-derived Bernoulli sampler. It is a reproducible reference plant,
    not an RTL model or a substitute for optical-bench validation.
    """

    def __init__(
        self, profile: HardwareProfile, config: AnalyticLoopbackConfig
    ) -> None:
        if not isinstance(profile, HardwareProfile):
            raise ControlValidationError(
                "Analytic loopback profile must be a HardwareProfile object."
            )
        if not isinstance(config, AnalyticLoopbackConfig):
            raise ControlValidationError(
                "Analytic loopback config must be an AnalyticLoopbackConfig object."
            )
        detector_map = {
            detector.detector_channel: detector for detector in config.detectors
        }
        for detector_channel in detector_map:
            _require_profile_role(profile, detector_channel, ChannelRole.DETECTOR)
        for path in config.paths:
            _require_profile_role(profile, path.source_channel, ChannelRole.SOURCE)
            _require_profile_role(
                profile, path.detector_channel, ChannelRole.DETECTOR
            )
        self._profile = profile
        self._config = config
        self._detectors = detector_map

    @property
    def profile(self) -> HardwareProfile:
        return self._profile

    @property
    def config(self) -> AnalyticLoopbackConfig:
        return self._config

    def acquire(
        self, event: CompiledControlEvent, program: CompiledControlProgram
    ) -> AcquisitionRecord:
        """Evaluate one repeated acquisition event across all shots and sweeps."""

        if event.kind is not EventKind.ACQUIRE:
            raise ControlValidationError(
                f"Event '{event.event_id}' is not a compiled acquisition event."
            )
        if event.acquisition_id is None or event.acquisition_kind is None:
            raise ControlValidationError(
                f"Acquire event '{event.event_id}' is missing acquisition metadata."
            )
        if (
            program.profile_id != self._profile.profile_id
            or program.profile_digest != self._profile.digest
        ):
            raise ControlValidationError(
                "Compiled program does not match the analytic loopback profile."
            )

        detector_channels = self._acquisition_detectors(event)
        iteration_records: list[dict[str, tuple[int, ...]]] = []
        window_starts: list[int] = []
        window_durations: list[int] = []
        dead_time_rejections = 0
        previous_detection: dict[str, int | None] = {
            detector_channel: None for detector_channel in detector_channels
        }
        for iteration_index, offset, overrides in _iterations(program):
            relative_start = int(
                _event_value(event, "start_tick", overrides, event.start_tick)
            )
            duration = int(
                _event_value(
                    event, "duration_ticks", overrides, event.duration_ticks
                )
            )
            window_start = offset + relative_start
            window_end = window_start + duration
            window_starts.append(window_start)
            window_durations.append(duration)

            detections: dict[str, tuple[int, ...]] = {}
            for detector_channel in detector_channels:
                candidates = self._detector_tags(
                    detector_channel=detector_channel,
                    acquisition=event,
                    program=program,
                    iteration_index=iteration_index,
                    offset=offset,
                    overrides=overrides,
                    window_start=window_start,
                    window_end=window_end,
                )
                detector = self._detectors[detector_channel]
                tags, rejected, last_detection = _apply_dead_time(
                    candidates,
                    detector.dead_time_ticks,
                    previous_detection[detector_channel],
                )
                previous_detection[detector_channel] = last_detection
                detections[detector_channel] = tags
                dead_time_rejections += rejected
            iteration_records.append(detections)

        return self._record(
            event=event,
            program=program,
            detector_channels=detector_channels,
            iteration_records=tuple(iteration_records),
            window_starts=tuple(window_starts),
            window_durations=tuple(window_durations),
            dead_time_rejections=dead_time_rejections,
        )

    def _acquisition_detectors(
        self, event: CompiledControlEvent
    ) -> tuple[str, ...]:
        if event.acquisition_kind is AcquisitionKind.COINCIDENCES:
            raw_detectors = event.parameters.get("detectors")
            if raw_detectors is None:
                detectors = tuple(sorted(self._detectors))
            else:
                values = _require_sequence(
                    raw_detectors, "Coincidence acquisition detectors"
                )
                detectors = tuple(values)
            if len(detectors) < 2 or len(set(detectors)) != len(detectors):
                raise ControlValidationError(
                    "Coincidence acquisition requires at least two unique detectors."
                )
        else:
            detectors = (event.channel,)
        for detector_channel in detectors:
            if detector_channel not in self._detectors:
                raise ControlValidationError(
                    f"Acquisition references unconfigured detector "
                    f"'{detector_channel}'."
                )
        return detectors

    def _detector_tags(
        self,
        *,
        detector_channel: str,
        acquisition: CompiledControlEvent,
        program: CompiledControlProgram,
        iteration_index: int,
        offset: int,
        overrides: Mapping[tuple[SweepTargetKind, str, str], float | int],
        window_start: int,
        window_end: int,
    ) -> tuple[int, ...]:
        detector = self._detectors[detector_channel]
        candidates: list[int] = []
        for source in program.events:
            if source.kind is not EventKind.SOURCE_TRIGGER:
                continue
            routes = tuple(
                path
                for path in self._config.paths
                if path.source_channel == source.channel
                and path.detector_channel == detector_channel
            )
            if not routes:
                continue
            relative_source_tick = int(
                _event_value(source, "start_tick", overrides, source.start_tick)
            )
            arrival_tick = offset + relative_source_tick + min(
                path.delay_ticks for path in routes
            )
            if not window_start <= arrival_tick < window_end:
                continue
            probability = self._detection_probability(
                source=source,
                routes=routes,
                detector=detector,
                overrides=overrides,
                source_tick=relative_source_tick,
                program=program,
            )
            if _bernoulli(
                probability,
                self._config.seed,
                program.digest,
                acquisition.acquisition_id,
                iteration_index,
                source.event_id,
                detector_channel,
                "signal",
            ):
                candidates.append(arrival_tick)

        if _bernoulli(
            detector.dark_count_probability,
            self._config.seed,
            program.digest,
            acquisition.acquisition_id,
            iteration_index,
            detector_channel,
            "dark",
        ):
            candidates.append(
                _dark_tag(
                    window_start,
                    window_end,
                    self._config.seed,
                    program.digest,
                    acquisition.acquisition_id,
                    iteration_index,
                    detector_channel,
                )
            )

        return tuple(sorted(candidates))

    def _detection_probability(
        self,
        *,
        source: CompiledControlEvent,
        routes: tuple[LoopbackPath, ...],
        detector: DetectorResponse,
        overrides: Mapping[tuple[SweepTargetKind, str, str], float | int],
        source_tick: int,
        program: CompiledControlProgram,
    ) -> float:
        emission_probability = _source_emission_probability(source, overrides)
        coherent_real = 0.0
        coherent_imaginary = 0.0
        for path in routes:
            transmission, phase = _path_state(
                path, program.events, overrides, source_tick
            )
            amplitude = sqrt(transmission)
            coherent_real += amplitude * cos(phase)
            coherent_imaginary += amplitude * sin(phase)
        coherent_intensity = coherent_real**2 + coherent_imaginary**2
        return _clamp_probability(
            emission_probability * detector.efficiency * coherent_intensity
        )

    def _record(
        self,
        *,
        event: CompiledControlEvent,
        program: CompiledControlProgram,
        detector_channels: tuple[str, ...],
        iteration_records: tuple[dict[str, tuple[int, ...]], ...],
        window_starts: tuple[int, ...],
        window_durations: tuple[int, ...],
        dead_time_rejections: int,
    ) -> AcquisitionRecord:
        kind = event.acquisition_kind
        if kind is None or event.acquisition_id is None:
            raise ControlValidationError("Compiled acquisition metadata is incomplete.")

        overflow = False
        dropped_events = 0
        metadata: dict[str, Any] = {
            "model": ANALYTIC_LOOPBACK_MODEL_ID,
            "model_scope": "analytic_loopback",
            "hardware_validated": False,
            "sampler": "sha256_bernoulli_v1",
            "seed": self._config.seed,
            "config_digest": self._config.digest,
            "program_digest": program.digest,
            "execution_iterations": program.execution_iterations,
            "shots": program.shots,
            "sweep_points": program.resource_usage.sweep_points,
            "detectors": list(detector_channels),
            "window_durations_ticks": list(window_durations),
            "dead_time_rejections": dead_time_rejections,
        }

        if kind is AcquisitionKind.WAVEFORM:
            detector_channel = detector_channels[0]
            max_duration = max(window_durations)
            rows: list[tuple[float, ...]] = []
            for detections, start, duration in zip(
                iteration_records, window_starts, window_durations
            ):
                row = [0.0] * max_duration
                for tag in detections[detector_channel]:
                    relative_tick = tag - start
                    if 0 <= relative_tick < duration:
                        row[relative_tick] += 1.0
                rows.append(tuple(row))
            payload: Any = tuple(rows)
            unit = "normalized"
            shape = (len(rows), max_duration)
            metadata["duration_sweep_padding"] = len(set(window_durations)) > 1
        elif kind is AcquisitionKind.TIME_TAGS:
            detector_channel = detector_channels[0]
            raw_tags = tuple(
                tag
                for detections in iteration_records
                for tag in detections[detector_channel]
            )
            capacity = self._detectors[detector_channel].buffer_capacity
            payload = raw_tags[:capacity]
            dropped_events = max(0, len(raw_tags) - capacity)
            overflow = dropped_events > 0
            unit = "ticks"
            shape = (len(payload),) if payload else ()
            metadata["buffer_capacity"] = capacity
            metadata["unsaturated_event_count"] = len(raw_tags)
        elif kind is AcquisitionKind.THRESHOLDED_EVENTS:
            detector_channel = detector_channels[0]
            raw_values = tuple(
                int(bool(detections[detector_channel]))
                for detections in iteration_records
            )
            capacity = self._detectors[detector_channel].buffer_capacity
            payload = raw_values[:capacity]
            dropped_events = max(0, len(raw_values) - capacity)
            overflow = dropped_events > 0
            unit = "binary"
            shape = (len(payload),)
            metadata["buffer_capacity"] = capacity
            metadata["unsaturated_event_count"] = len(raw_values)
        elif kind is AcquisitionKind.COUNTS:
            raw_counts = {
                detector_channel: sum(
                    len(detections[detector_channel])
                    for detections in iteration_records
                )
                for detector_channel in detector_channels
            }
            payload, counter_drops = self._saturate_counts(raw_counts)
            dropped_events = counter_drops
            overflow = counter_drops > 0
            unit = "counts"
            shape = ()
            metadata["unsaturated_counts"] = raw_counts
        else:
            raw_counts = self._coincidence_counts(
                event, detector_channels, iteration_records
            )
            payload, counter_drops = self._saturate_counts(raw_counts)
            dropped_events = counter_drops
            overflow = counter_drops > 0
            unit = "counts"
            shape = ()
            metadata["unsaturated_counts"] = raw_counts
            metadata["coincidence_window_ticks"] = self._coincidence_window(event)

        return AcquisitionRecord(
            acquisition_id=event.acquisition_id,
            kind=kind,
            payload=payload,
            unit=unit,
            shape=shape,
            start_tick=min(window_starts),
            end_tick=max(
                start + duration
                for start, duration in zip(window_starts, window_durations)
            ),
            overflow=overflow,
            dropped_events=dropped_events,
            metadata=metadata,
        )

    def _saturate_counts(
        self, raw_counts: Mapping[str, int]
    ) -> tuple[dict[str, int], int]:
        counter_max = (1 << self._profile.counter_bits) - 1
        saturated = {
            label: min(value, counter_max) for label, value in raw_counts.items()
        }
        dropped = sum(
            max(0, value - counter_max) for value in raw_counts.values()
        )
        return saturated, dropped

    def _coincidence_counts(
        self,
        event: CompiledControlEvent,
        detector_channels: tuple[str, ...],
        iteration_records: tuple[dict[str, tuple[int, ...]], ...],
    ) -> dict[str, int]:
        window = self._coincidence_window(event)
        counts: dict[str, int] = {}
        for left, right in combinations(detector_channels, 2):
            label = f"{left}&{right}"
            counts[label] = sum(
                _count_coincidences(detections[left], detections[right], window)
                for detections in iteration_records
            )
        return counts

    def _coincidence_window(self, event: CompiledControlEvent) -> int:
        value = event.parameters.get(
            "coincidence_window_ticks", self._config.coincidence_window_ticks
        )
        _require_non_negative_int(value, "Coincidence window")
        return value


def _iterations(program: CompiledControlProgram):
    value_domains = tuple(sweep.compiled_values for sweep in program.sweeps)
    combinations_iter = product(*value_domains) if value_domains else ((),)
    iteration_index = 0
    for values in combinations_iter:
        overrides = {
            (sweep.target_kind, sweep.target_id, sweep.compiled_parameter): value
            for sweep, value in zip(program.sweeps, values)
        }
        for _ in range(program.shots):
            yield iteration_index, iteration_index * program.repetition_ticks, overrides
            iteration_index += 1


def _event_value(
    event: CompiledControlEvent,
    parameter: str,
    overrides: Mapping[tuple[SweepTargetKind, str, str], float | int],
    default: Any,
) -> Any:
    event_key = (SweepTargetKind.EVENT, event.event_id, parameter)
    channel_key = (SweepTargetKind.CHANNEL, event.channel, parameter)
    if event_key in overrides:
        return overrides[event_key]
    if channel_key in overrides:
        return overrides[channel_key]
    return event.parameters.get(parameter, default)


def _source_emission_probability(
    source: CompiledControlEvent,
    overrides: Mapping[tuple[SweepTargetKind, str, str], float | int],
) -> float:
    if "emission_probability" in source.parameters:
        value = source.parameters["emission_probability"]
        _require_probability(value, "Source emission_probability")
        return float(value)
    else:
        amplitude = _event_value(source, "amplitude", overrides, 1.0)
        _require_finite_number(amplitude, "Source amplitude")
        value = float(amplitude) ** 2
    return _clamp_probability(value)


def _path_state(
    path: LoopbackPath,
    events: tuple[CompiledControlEvent, ...],
    overrides: Mapping[tuple[SweepTargetKind, str, str], float | int],
    source_tick: int,
) -> tuple[float, float]:
    transmission = path.transmission
    phase = path.phase_offset_rad
    for event in events:
        if event.parameters.get("path_id") != path.path_id:
            continue
        event_start = int(
            _event_value(event, "start_tick", overrides, event.start_tick)
        )
        event_duration = int(
            _event_value(event, "duration_ticks", overrides, event.duration_ticks)
        )
        if event.kind is EventKind.MODULATOR_PULSE:
            if not event_start <= source_tick < event_start + event_duration:
                continue
            if "transmission" in event.parameters:
                modulation = event.parameters["transmission"]
                _require_probability(modulation, "Modulator transmission")
                transmission *= float(modulation)
            amplitude = _event_value(event, "amplitude", overrides, 1.0)
            _require_finite_number(amplitude, "Modulator amplitude")
            transmission *= float(amplitude) ** 2
        elif event.kind is EventKind.PHASE_UPDATE and event_start <= source_tick:
            phase_value = _event_value(
                event,
                "phase",
                overrides,
                event.parameters.get("phase_rad", 0.0),
            )
            _require_finite_number(phase_value, "Path phase")
            phase += float(phase_value)
    return _clamp_probability(transmission), phase


def _bernoulli(probability: float, *parts: Any) -> bool:
    if probability <= 0.0:
        return False
    if probability >= 1.0:
        return True
    digest = _hash_parts(*parts)
    sample = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return sample < probability


def _dark_tag(window_start: int, window_end: int, *parts: Any) -> int:
    duration = window_end - window_start
    if duration <= 0:
        raise ControlValidationError("Acquisition window duration must be positive.")
    digest = _hash_parts(*parts, "dark-position")
    return window_start + int.from_bytes(digest[:8], "big") % duration


def _hash_parts(*parts: Any) -> bytes:
    encoded = json.dumps(
        list(parts), separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).digest()


def _count_coincidences(
    left: tuple[int, ...], right: tuple[int, ...], window: int
) -> int:
    left_index = 0
    right_index = 0
    count = 0
    while left_index < len(left) and right_index < len(right):
        delta = left[left_index] - right[right_index]
        if abs(delta) <= window:
            count += 1
            left_index += 1
            right_index += 1
        elif delta < 0:
            left_index += 1
        else:
            right_index += 1
    return count


def _apply_dead_time(
    tags: tuple[int, ...], dead_time_ticks: int, previous_tag: int | None
) -> tuple[tuple[int, ...], int, int | None]:
    accepted: list[int] = []
    rejected = 0
    last_tag = previous_tag
    for tag in tags:
        if last_tag is not None and tag - last_tag < dead_time_ticks:
            rejected += 1
            continue
        accepted.append(tag)
        last_tag = tag
    return tuple(accepted), rejected, last_tag


def _clamp_probability(value: Any) -> float:
    _require_finite_number(value, "Probability")
    numeric = float(value)
    if abs(numeric) < 1e-15:
        return 0.0
    return min(1.0, max(0.0, numeric))


def _require_profile_role(
    profile: HardwareProfile, channel: str, role: ChannelRole
) -> None:
    try:
        actual = profile.channel_roles[channel]
    except KeyError as exc:
        raise ControlValidationError(
            f"Analytic loopback channel '{channel}' is absent from profile "
            f"'{profile.profile_id}'."
        ) from exc
    if actual is not role:
        raise ControlValidationError(
            f"Analytic loopback channel '{channel}' must have role '{role.value}'."
        )


def _canonical_json(value: Any, label: str) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ControlValidationError(
            f"{label} must contain JSON-serializable finite values."
        ) from exc


def _require_mapping(value: Any, label: str) -> None:
    if not isinstance(value, MappingABC):
        raise ControlValidationError(f"{label} must be a mapping.")


def _require_sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise ControlValidationError(f"{label} must be a sequence.")
    return value


def _require_identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ControlValidationError(f"{label} must be a non-empty string.")


def _require_finite_number(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlValidationError(f"{label} must be numeric.")
    if not isfinite(float(value)):
        raise ControlValidationError(f"{label} must be finite.")


def _require_probability(value: Any, label: str) -> None:
    _require_finite_number(value, label)
    if not 0.0 <= float(value) <= 1.0:
        raise ControlValidationError(f"{label} must be between zero and one.")


def _require_non_negative_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControlValidationError(f"{label} must be a non-negative integer.")


def _require_positive_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ControlValidationError(f"{label} must be a positive integer.")


def _require_unique(values: tuple[Any, ...], attribute: str, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        identifier = getattr(value, attribute)
        if identifier in seen:
            raise ControlValidationError(f"Duplicate {label} '{identifier}'.")
        seen.add(identifier)


def _missing_field(label: str, exc: KeyError) -> ControlValidationError:
    return ControlValidationError(
        f"{label} is missing required field '{exc.args[0]}'."
    )
