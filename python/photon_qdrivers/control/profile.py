"""Finite hardware profiles for photonic control compilation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Any, Mapping

from ..errors import ControlResourceError, ControlValidationError
from .acquisition import AcquisitionKind
from .program import ChannelRole, ControlProgram, EventKind


class QuantizationRule(str, Enum):
    """Rule used to map requested nanoseconds to device clock ticks."""

    NEAREST = "nearest"
    FLOOR = "floor"
    CEIL = "ceil"


@dataclass(frozen=True)
class HardwareProfile:
    """Explicit timing, channel, numeric, and memory limits for a controller."""

    profile_id: str
    clock_period_ns: float
    channel_roles: Mapping[str, ChannelRole]
    quantization_rule: QuantizationRule = QuantizationRule.NEAREST
    max_instructions: int = 4_096
    max_waveform_samples: int = 65_536
    max_registers: int = 64
    max_acquisition_ticks: int = 65_536
    max_program_ticks: int = 1_000_000
    max_sweep_points: int = 65_536
    max_shots: int = 1_000_000
    amplitude_bits: int = 16
    phase_bits: int = 16
    counter_bits: int = 32
    timestamp_bits: int = 64
    supported_event_kinds: tuple[EventKind, ...] = field(
        default_factory=lambda: tuple(EventKind)
    )
    supported_acquisition_kinds: tuple[AcquisitionKind, ...] = field(
        default_factory=lambda: tuple(AcquisitionKind)
    )
    supported_sweep_parameters: tuple[str, ...] = (
        "amplitude",
        "phase",
        "duration_ns",
        "start_ns",
    )
    transport_protocol: str = "PQDR_CONTROL_V1"
    firmware_protocol: str = "PQDR_FPGA_V1"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.profile_id, "Hardware profile id")
        _require_positive_number(self.clock_period_ns, "Hardware clock_period_ns")
        if not isinstance(self.channel_roles, MappingABC) or not self.channel_roles:
            raise ControlValidationError(
                "Hardware profile channel_roles must be a non-empty mapping."
            )

        normalized_roles: dict[str, ChannelRole] = {}
        for channel, role in self.channel_roles.items():
            _require_identifier(channel, "Hardware channel name")
            try:
                normalized_roles[channel] = (
                    role if isinstance(role, ChannelRole) else ChannelRole(role)
                )
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported role '{role}' for hardware channel '{channel}'."
                ) from exc
        object.__setattr__(self, "channel_roles", normalized_roles)

        if not isinstance(self.quantization_rule, QuantizationRule):
            try:
                object.__setattr__(
                    self,
                    "quantization_rule",
                    QuantizationRule(self.quantization_rule),
                )
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported quantization rule '{self.quantization_rule}'."
                ) from exc

        positive_limits = (
            "max_instructions",
            "max_waveform_samples",
            "max_registers",
            "max_acquisition_ticks",
            "max_program_ticks",
            "max_sweep_points",
            "max_shots",
            "amplitude_bits",
            "phase_bits",
            "counter_bits",
            "timestamp_bits",
        )
        for name in positive_limits:
            _require_positive_int(getattr(self, name), f"Hardware {name}")

        event_kinds = _normalize_enum_tuple(
            self.supported_event_kinds, EventKind, "supported event kind"
        )
        acquisition_kinds = _normalize_enum_tuple(
            self.supported_acquisition_kinds,
            AcquisitionKind,
            "supported acquisition kind",
        )
        object.__setattr__(self, "supported_event_kinds", event_kinds)
        object.__setattr__(self, "supported_acquisition_kinds", acquisition_kinds)

        sweep_parameters = tuple(self.supported_sweep_parameters)
        if not sweep_parameters:
            raise ControlValidationError(
                "Hardware supported_sweep_parameters must not be empty."
            )
        for parameter in sweep_parameters:
            _require_identifier(parameter, "Supported sweep parameter")
        if len(set(sweep_parameters)) != len(sweep_parameters):
            raise ControlValidationError(
                "Hardware supported_sweep_parameters must be unique."
            )
        object.__setattr__(self, "supported_sweep_parameters", sweep_parameters)

        _require_identifier(self.transport_protocol, "Transport protocol")
        _require_identifier(self.firmware_protocol, "Firmware protocol")
        if not isinstance(self.metadata, MappingABC):
            raise ControlValidationError("Hardware profile metadata must be a mapping.")

    def validate_program(self, program: ControlProgram) -> None:
        """Check non-quantized capabilities before timing compilation."""

        if program.shots > self.max_shots:
            raise ControlResourceError(
                f"Control program requests {program.shots} shots; profile "
                f"'{self.profile_id}' supports at most {self.max_shots}."
            )
        if len(program.events) > self.max_instructions:
            raise ControlResourceError(
                f"Control program requires {len(program.events)} instructions; profile "
                f"'{self.profile_id}' supports at most {self.max_instructions}."
            )

        supported_events = set(self.supported_event_kinds)
        supported_acquisitions = set(self.supported_acquisition_kinds)
        for channel in program.channels:
            try:
                hardware_role = self.channel_roles[channel.name]
            except KeyError as exc:
                raise ControlValidationError(
                    f"Control channel '{channel.name}' is not present in hardware "
                    f"profile '{self.profile_id}'."
                ) from exc
            if hardware_role is not channel.role:
                raise ControlValidationError(
                    f"Control channel '{channel.name}' is '{channel.role.value}' in the "
                    f"program but '{hardware_role.value}' in profile '{self.profile_id}'."
                )

        for event in program.events:
            if event.kind not in supported_events:
                raise ControlValidationError(
                    f"Hardware profile '{self.profile_id}' does not support event kind "
                    f"'{event.kind.value}'."
                )
            if (
                event.acquisition_kind is not None
                and event.acquisition_kind not in supported_acquisitions
            ):
                raise ControlValidationError(
                    f"Hardware profile '{self.profile_id}' does not support acquisition "
                    f"kind '{event.acquisition_kind.value}'."
                )

        supported_parameters = set(self.supported_sweep_parameters)
        for sweep in program.sweeps:
            if sweep.parameter not in supported_parameters:
                raise ControlValidationError(
                    f"Hardware profile '{self.profile_id}' does not support sweep "
                    f"parameter '{sweep.parameter}'."
                )

    def validate_resource_usage(self, usage: Mapping[str, int]) -> None:
        """Check resource counts produced by the timing compiler."""

        limits = {
            "instructions": self.max_instructions,
            "waveform_samples": self.max_waveform_samples,
            "registers": self.max_registers,
            "acquisition_ticks": self.max_acquisition_ticks,
            "program_ticks": self.max_program_ticks,
            "sweep_points": self.max_sweep_points,
        }
        for resource, limit in limits.items():
            value = usage.get(resource, 0)
            if value > limit:
                raise ControlResourceError(
                    f"Control program requires {value} {resource}; profile "
                    f"'{self.profile_id}' supports at most {limit}."
                )

    @property
    def digest(self) -> str:
        """Stable SHA-256 digest used for execution provenance."""

        try:
            payload = json.dumps(
                self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ControlValidationError(
                "Hardware profile must contain JSON-serializable finite metadata."
            ) from exc
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "clock_period_ns": self.clock_period_ns,
            "channel_roles": {
                channel: role.value for channel, role in self.channel_roles.items()
            },
            "quantization_rule": self.quantization_rule.value,
            "max_instructions": self.max_instructions,
            "max_waveform_samples": self.max_waveform_samples,
            "max_registers": self.max_registers,
            "max_acquisition_ticks": self.max_acquisition_ticks,
            "max_program_ticks": self.max_program_ticks,
            "max_sweep_points": self.max_sweep_points,
            "max_shots": self.max_shots,
            "amplitude_bits": self.amplitude_bits,
            "phase_bits": self.phase_bits,
            "counter_bits": self.counter_bits,
            "timestamp_bits": self.timestamp_bits,
            "supported_event_kinds": [kind.value for kind in self.supported_event_kinds],
            "supported_acquisition_kinds": [
                kind.value for kind in self.supported_acquisition_kinds
            ],
            "supported_sweep_parameters": list(self.supported_sweep_parameters),
            "transport_protocol": self.transport_protocol,
            "firmware_protocol": self.firmware_protocol,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "HardwareProfile":
        if not isinstance(data, MappingABC):
            raise ControlValidationError("Hardware profile must be a mapping.")
        try:
            return cls(
                profile_id=data["profile_id"],
                clock_period_ns=data["clock_period_ns"],
                channel_roles=data["channel_roles"],
                quantization_rule=data.get("quantization_rule", "nearest"),
                max_instructions=data.get("max_instructions", 4_096),
                max_waveform_samples=data.get("max_waveform_samples", 65_536),
                max_registers=data.get("max_registers", 64),
                max_acquisition_ticks=data.get("max_acquisition_ticks", 65_536),
                max_program_ticks=data.get("max_program_ticks", 1_000_000),
                max_sweep_points=data.get("max_sweep_points", 65_536),
                max_shots=data.get("max_shots", 1_000_000),
                amplitude_bits=data.get("amplitude_bits", 16),
                phase_bits=data.get("phase_bits", 16),
                counter_bits=data.get("counter_bits", 32),
                timestamp_bits=data.get("timestamp_bits", 64),
                supported_event_kinds=tuple(
                    data.get("supported_event_kinds", tuple(kind.value for kind in EventKind))
                ),
                supported_acquisition_kinds=tuple(
                    data.get(
                        "supported_acquisition_kinds",
                        tuple(kind.value for kind in AcquisitionKind),
                    )
                ),
                supported_sweep_parameters=tuple(
                    data.get(
                        "supported_sweep_parameters",
                        ("amplitude", "phase", "duration_ns", "start_ns"),
                    )
                ),
                transport_protocol=data.get("transport_protocol", "PQDR_CONTROL_V1"),
                firmware_protocol=data.get("firmware_protocol", "PQDR_FPGA_V1"),
                metadata=data.get("metadata", {}),
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Hardware profile is missing required field '{exc.args[0]}'."
            ) from exc


def _normalize_enum_tuple(values: Sequence[Any], enum_type, label: str):
    try:
        normalized = tuple(
            value if isinstance(value, enum_type) else enum_type(value) for value in values
        )
    except (TypeError, ValueError) as exc:
        raise ControlValidationError(f"Unsupported {label}.") from exc
    if not normalized:
        raise ControlValidationError(f"Hardware {label}s must not be empty.")
    if len(set(normalized)) != len(normalized):
        raise ControlValidationError(f"Hardware {label}s must be unique.")
    return normalized


def _require_identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ControlValidationError(f"{label} must be a non-empty string.")


def _require_positive_number(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlValidationError(f"{label} must be numeric.")
    if not isfinite(float(value)) or value <= 0:
        raise ControlValidationError(f"{label} must be finite and positive.")


def _require_positive_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ControlValidationError(f"{label} must be a positive integer.")
