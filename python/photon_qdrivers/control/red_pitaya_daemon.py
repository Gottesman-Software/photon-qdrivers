"""One-shot board-side bridge for a deployed P6.1 Red Pitaya image."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..errors import ControlValidationError
from .board import (
    P6BoardBridge,
    decode_control_request_frame,
    encode_control_result_frame,
)
from .red_pitaya import (
    RED_PITAYA_DEFAULT_BASE_ADDRESS,
    RED_PITAYA_DEFAULT_MAP_SIZE,
    DevMemRegisterIO,
    RedPitayaMMIOBoard,
    sha256_file,
)


def _parse_int(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from exc


def _load_channel_map(path: Path) -> Mapping[str, int]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlValidationError(
            f"Cannot read channel map '{path}': {exc}"
        ) from exc
    if not isinstance(value, dict) or not value:
        raise ControlValidationError("Channel map must be a non-empty JSON object.")
    if any(
        not isinstance(name, str)
        or not name
        or isinstance(index, bool)
        or not isinstance(index, int)
        or index < 0
        for name, index in value.items()
    ):
        raise ControlValidationError(
            "Channel map values must be non-negative integer indices."
        )
    return value


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute one integrity-checked P4 control frame through the "
            "P6.1 Red Pitaya MMIO image and capture physical evidence."
        )
    )
    parser.add_argument("--command", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--channel-map", type=Path, required=True)
    parser.add_argument("--bitstream", type=Path, required=True)
    parser.add_argument("--device", default="/dev/mem")
    parser.add_argument(
        "--base-address",
        type=_parse_int,
        default=RED_PITAYA_DEFAULT_BASE_ADDRESS,
    )
    parser.add_argument(
        "--map-size", type=_parse_int, default=RED_PITAYA_DEFAULT_MAP_SIZE
    )
    parser.add_argument("--timeout", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    frame = options.command.read_text(encoding="utf-8")
    envelope = decode_control_request_frame(frame)
    channel_map = _load_channel_map(options.channel_map)
    bitstream_digest = sha256_file(options.bitstream)
    captured_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with DevMemRegisterIO(
        options.base_address,
        options.map_size,
        device_path=options.device,
    ) as registers:
        board = RedPitayaMMIOBoard(
            registers,
            base_address=options.base_address,
            timeout_seconds=options.timeout,
        )
        capabilities = board.inspect_capabilities()
        image = P6BoardBridge(capabilities, channel_map).prepare(envelope)
        evidence = board.execute(
            image,
            bitstream_sha256=bitstream_digest,
            captured_at_utc=captured_at_utc,
        )

    result_frame = encode_control_result_frame(
        envelope,
        image,
        evidence.board_result,
        message="completed by P6.1 Red Pitaya MMIO bridge",
    )
    _atomic_write(options.result, result_frame)
    _atomic_write(
        options.evidence,
        json.dumps(evidence.to_dict(), sort_keys=True, indent=2) + "\n",
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "job_id": image.job_id,
                "image_digest": image.image_digest,
                "bitstream_sha256": bitstream_digest,
                "evidence_digest": evidence.evidence_digest,
                "host_round_trip_ns": evidence.host_round_trip_ns,
                "final_device_tick": evidence.board_result.final_device_tick,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
