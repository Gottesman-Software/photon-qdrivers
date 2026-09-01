"""Versioned envelope connecting compiled control programs to native runtimes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..errors import ControlValidationError
from .acquisition import AcquisitionRecord
from .timing import CompiledControlProgram


CONTROL_TRANSPORT_PROTOCOL = "PQDR_CONTROL_V1"
CONTROL_RESULT_PROTOCOL = "PQDR_CONTROL_RESULT_V1"


@dataclass(frozen=True)
class ControlEnvelope:
    """Integrity-checked native transport input for one compiled program."""

    job_id: str
    program: CompiledControlProgram
    protocol: str = CONTROL_TRANSPORT_PROTOCOL

    def __post_init__(self) -> None:
        if self.protocol != CONTROL_TRANSPORT_PROTOCOL:
            raise ControlValidationError(
                f"Unsupported native control protocol '{self.protocol}'."
            )
        if not isinstance(self.job_id, str) or not self.job_id.strip():
            raise ControlValidationError("Native control job_id must be non-empty.")
        if "\n" in self.job_id or "\r" in self.job_id:
            raise ControlValidationError(
                "Native control job_id must not contain line breaks."
            )
        if not isinstance(self.program, CompiledControlProgram):
            raise ControlValidationError(
                "Native control envelope requires a CompiledControlProgram."
            )

    @property
    def compiled_payload(self) -> str:
        return self.program.canonical_json

    @property
    def program_digest(self) -> str:
        return self.program.digest

    @property
    def envelope_digest(self) -> str:
        """Bind every native scalar field to the exact compiled payload."""

        preimage = "\n".join(
            (
                self.protocol,
                f"job_id={self.job_id}",
                f"program_id={self.program.program_id}",
                f"profile_id={self.program.profile_id}",
                f"profile_digest={self.program.profile_digest}",
                f"program_digest={self.program_digest}",
                f"shots={self.program.shots}",
                f"repetition_ticks={self.program.repetition_ticks}",
                f"sweep_points={self.program.resource_usage.sweep_points}",
                f"event_count={len(self.program.events)}",
                "compiled_payload_length="
                f"{len(self.compiled_payload.encode('utf-8'))}",
                f"compiled_payload={self.compiled_payload}",
                "END",
                "",
            )
        )
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Return the explicit scalar contract and canonical compiled payload."""

        return {
            "protocol": self.protocol,
            "job_id": self.job_id,
            "program_id": self.program.program_id,
            "profile_id": self.program.profile_id,
            "profile_digest": self.program.profile_digest,
            "program_digest": self.program_digest,
            "envelope_digest": self.envelope_digest,
            "compiled_payload": self.compiled_payload,
            "shots": self.program.shots,
            "repetition_ticks": self.program.repetition_ticks,
            "sweep_points": self.program.resource_usage.sweep_points,
            "event_count": len(self.program.events),
        }


def decode_acquisition_payload(payload: str) -> tuple[AcquisitionRecord, ...]:
    """Decode and validate acquisition records returned by a native runtime."""

    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ControlValidationError(
            "Native acquisition payload is not valid JSON."
        ) from exc
    if not isinstance(raw, list):
        raise ControlValidationError("Native acquisition payload must be a JSON array.")
    return tuple(AcquisitionRecord.from_mapping(item) for item in raw)
