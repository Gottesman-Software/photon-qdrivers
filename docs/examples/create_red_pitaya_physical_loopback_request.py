"""Create the integrity-checked P6.1 physical-loopback mailbox request."""

from __future__ import annotations

import argparse
from pathlib import Path

from photon_qdrivers import (
    BoardCapabilities,
    P6BoardBridge,
    RED_PITAYA_PHYSICAL_LOOPBACK_CHANNEL_MAP,
    encode_control_request_frame,
    red_pitaya_physical_loopback_envelope,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()

    envelope = red_pitaya_physical_loopback_envelope()
    capabilities = BoardCapabilities(max_instructions=16, count_width_bits=2)
    image = P6BoardBridge(
        capabilities,
        RED_PITAYA_PHYSICAL_LOOPBACK_CHANNEL_MAP,
    ).prepare(envelope)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        encode_control_request_frame(envelope), encoding="utf-8"
    )
    print(f"request={options.output}")
    print(f"control_envelope_digest={envelope.envelope_digest}")
    print(f"rtl_program_digest={image.rtl_program_digest}")
    print(f"board_image_digest={image.image_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
