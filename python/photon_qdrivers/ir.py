"""Versioned photonic circuit intermediate representation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import CircuitValidationError


IR_SCHEMA_VERSION = "photon-qdrivers.ir.v1"
PHOTONIC_CIRCUIT_TYPE = "photonic_circuit"


@dataclass(frozen=True)
class PhotonicOperation:
    """A normalized operation in a photonic circuit."""

    kind: str
    name: str
    modes: tuple[int, ...]
    parameters: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        operation: Mapping[str, Any],
        *,
        circuit_modes: int,
        index: int,
    ) -> "PhotonicOperation":
        if not isinstance(operation, Mapping):
            raise CircuitValidationError(f"Operation {index} must be a mapping.")

        if "gate" in operation:
            kind = "gate"
            name = operation["gate"]
            reserved_keys = {"gate", "mode", "modes"}
        elif "measure" in operation:
            kind = "measure"
            name = operation["measure"]
            reserved_keys = {"measure", "mode", "modes"}
        else:
            raise CircuitValidationError(
                f"Operation {index} must contain either 'gate' or 'measure'."
            )

        if not isinstance(name, str) or not name:
            raise CircuitValidationError(f"Operation {index} name must be a non-empty string.")

        modes = _parse_operation_modes(operation, circuit_modes=circuit_modes, index=index)
        parameters = {key: value for key, value in operation.items() if key not in reserved_keys}
        return cls(kind=kind, name=name, modes=modes, parameters=parameters)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.kind == "gate":
            data["gate"] = self.name
        elif self.kind == "measure":
            data["measure"] = self.name
        else:
            data["operation"] = self.name
            data["kind"] = self.kind

        data["modes"] = list(self.modes)
        data.update(dict(self.parameters))
        return data


@dataclass(frozen=True)
class PhotonicCircuit:
    """Validated circuit IR shared by simulators, emulators, and hardware."""

    modes: int
    operations: tuple[PhotonicOperation, ...]
    shots: int = 1024
    circuit_type: str = PHOTONIC_CIRCUIT_TYPE
    schema_version: str = IR_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, circuit: Mapping[str, Any] | "PhotonicCircuit") -> "PhotonicCircuit":
        if isinstance(circuit, PhotonicCircuit):
            return circuit
        if not isinstance(circuit, Mapping):
            raise CircuitValidationError("Circuit must be a mapping or PhotonicCircuit.")

        circuit_type = circuit.get("type", PHOTONIC_CIRCUIT_TYPE)
        if circuit_type != PHOTONIC_CIRCUIT_TYPE:
            raise CircuitValidationError(
                f"Unsupported circuit type '{circuit_type}'. Expected '{PHOTONIC_CIRCUIT_TYPE}'."
            )

        schema_version = circuit.get("schema_version", IR_SCHEMA_VERSION)
        if schema_version != IR_SCHEMA_VERSION:
            raise CircuitValidationError(
                f"Unsupported circuit schema '{schema_version}'. Expected '{IR_SCHEMA_VERSION}'."
            )

        modes = _parse_positive_int(circuit.get("modes"), field_name="modes")
        shots = _parse_positive_int(circuit.get("shots", 1024), field_name="shots")

        raw_operations = circuit.get("operations", [])
        if not isinstance(raw_operations, Sequence) or isinstance(raw_operations, (str, bytes)):
            raise CircuitValidationError("Circuit operations must be a sequence.")

        operations = tuple(
            PhotonicOperation.from_mapping(
                operation,
                circuit_modes=modes,
                index=index,
            )
            for index, operation in enumerate(raw_operations)
        )

        metadata = circuit.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise CircuitValidationError("Circuit metadata must be a mapping when provided.")

        return cls(
            modes=modes,
            operations=operations,
            shots=shots,
            circuit_type=circuit_type,
            schema_version=schema_version,
            metadata=dict(metadata),
        )

    def operation_names(self) -> set[str]:
        return {operation.name for operation in self.operations}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "type": self.circuit_type,
            "modes": self.modes,
            "shots": self.shots,
            "operations": [operation.to_dict() for operation in self.operations],
            "metadata": dict(self.metadata),
        }


def _parse_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CircuitValidationError(f"Circuit {field_name} must be a positive integer.")
    if value <= 0:
        raise CircuitValidationError(f"Circuit {field_name} must be a positive integer.")
    return value


def _parse_operation_modes(
    operation: Mapping[str, Any],
    *,
    circuit_modes: int,
    index: int,
) -> tuple[int, ...]:
    if "modes" in operation:
        raw_modes = operation["modes"]
    elif "mode" in operation:
        raw_modes = [operation["mode"]]
    else:
        raise CircuitValidationError(f"Operation {index} must specify 'mode' or 'modes'.")

    if not isinstance(raw_modes, Sequence) or isinstance(raw_modes, (str, bytes)) or not raw_modes:
        raise CircuitValidationError(f"Operation {index} modes must be a non-empty sequence.")

    modes: list[int] = []
    for raw_mode in raw_modes:
        if isinstance(raw_mode, bool) or not isinstance(raw_mode, int):
            raise CircuitValidationError(f"Operation {index} contains a non-integer mode.")
        if raw_mode < 0 or raw_mode >= circuit_modes:
            raise CircuitValidationError(
                f"Operation {index} references mode {raw_mode}, "
                f"outside circuit mode range 0..{circuit_modes - 1}."
            )
        modes.append(raw_mode)

    if len(set(modes)) != len(modes):
        raise CircuitValidationError(f"Operation {index} contains duplicate modes.")

    return tuple(modes)
