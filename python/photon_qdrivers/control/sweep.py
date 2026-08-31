"""Controller-executable parameter sweeps."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC, Sequence
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Mapping

from ..errors import ControlValidationError


class SweepTargetKind(str, Enum):
    """Kinds of objects that a control sweep may update."""

    EVENT = "event"
    CHANNEL = "channel"


@dataclass(frozen=True)
class ControlSweep:
    """A finite parameter sweep intended for controller-side execution."""

    sweep_id: str
    target_kind: SweepTargetKind
    target_id: str
    parameter: str
    values: tuple[float, ...]
    real_time: bool = True

    def __post_init__(self) -> None:
        for value, label in (
            (self.sweep_id, "Sweep id"),
            (self.target_id, "Sweep target id"),
            (self.parameter, "Sweep parameter"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ControlValidationError(f"{label} must be a non-empty string.")

        if not isinstance(self.target_kind, SweepTargetKind):
            try:
                object.__setattr__(self, "target_kind", SweepTargetKind(self.target_kind))
            except (TypeError, ValueError) as exc:
                raise ControlValidationError(
                    f"Unsupported sweep target kind '{self.target_kind}'."
                ) from exc

        if not isinstance(self.values, tuple):
            try:
                object.__setattr__(self, "values", tuple(self.values))
            except TypeError as exc:
                raise ControlValidationError("Sweep values must be a sequence.") from exc
        if not self.values:
            raise ControlValidationError("Sweep values must not be empty.")
        for value in self.values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ControlValidationError("Sweep values must be numeric.")
            if not isfinite(float(value)):
                raise ControlValidationError("Sweep values must be finite.")
        if not isinstance(self.real_time, bool):
            raise ControlValidationError("Sweep real_time must be a boolean.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sweep_id": self.sweep_id,
            "target_kind": self.target_kind.value,
            "target_id": self.target_id,
            "parameter": self.parameter,
            "values": list(self.values),
            "real_time": self.real_time,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ControlSweep":
        if not isinstance(data, MappingABC):
            raise ControlValidationError("Control sweep must be a mapping.")
        try:
            values = data["values"]
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise ControlValidationError("Sweep values must be a sequence.")
            return cls(
                sweep_id=data["sweep_id"],
                target_kind=SweepTargetKind(data["target_kind"]),
                target_id=data["target_id"],
                parameter=data["parameter"],
                values=tuple(values),
                real_time=data.get("real_time", True),
            )
        except KeyError as exc:
            raise ControlValidationError(
                f"Control sweep is missing required field '{exc.args[0]}'."
            ) from exc
        except ValueError as exc:
            if isinstance(exc, ControlValidationError):
                raise
            raise ControlValidationError(str(exc)) from exc
