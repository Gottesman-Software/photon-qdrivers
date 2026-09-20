#!/usr/bin/env python3
"""Prepare a pinned RedPitaya-FPGA logic project with the P6.1 overlay."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


PINNED_UPSTREAM_COMMIT = "728a4f37e9c0a9b5ba1d9b7a0d44c38bbd2dc674"
DEFAULT_PROJECT_NAME = "qdriverlab"
RTL_FILES = (
    "photon_qdriver_pkg.sv",
    "control_instruction_decoder.sv",
    "control_schedule_engine.sv",
    "red_pitaya_control_bridge.sv",
    "red_pitaya_sys_bus_adapter.sv",
)


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one {label} anchor in upstream top, found {count}."
        )
    return text.replace(old, new, 1)


def prepare_project(
    upstream: Path,
    source_root: Path,
    *,
    project_name: str = DEFAULT_PROJECT_NAME,
    force: bool = False,
    allow_unverified_upstream: bool = False,
) -> Path:
    upstream = upstream.resolve()
    source_root = source_root.resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=upstream,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != PINNED_UPSTREAM_COMMIT and not allow_unverified_upstream:
        raise RuntimeError(
            "RedPitaya-FPGA revision mismatch: "
            f"expected {PINNED_UPSTREAM_COMMIT}, found {revision}."
        )

    template = upstream / "prj" / "logic"
    target = upstream / "prj" / project_name
    if not template.is_dir():
        raise RuntimeError(f"Official logic project is missing: {template}")
    if target.exists():
        if not force:
            raise RuntimeError(
                f"Target project already exists: {target}; pass --force to replace it."
            )
        shutil.rmtree(target)
    shutil.copytree(template, target)

    target_rtl = target / "rtl"
    source_rtl = source_root / "fpga" / "systemverilog"
    for filename in RTL_FILES:
        shutil.copy2(source_rtl / filename, target_rtl / filename)

    top_path = target_rtl / "red_pitaya_top.sv"
    top = top_path.read_text(encoding="utf-8")
    top = _replace_once(
        top,
        "for (genvar i=13; i<16; i++) begin: for_sys\n"
        "  sys_bus_stub sys_bus_stub_13_16 (sys[i]);\n"
        "end: for_sys",
        "for (genvar i=14; i<16; i++) begin: for_sys\n"
        "  sys_bus_stub sys_bus_stub_14_16 (sys[i]);\n"
        "end: for_sys",
        "unused system-bus loop",
    )
    top = _replace_once(
        top,
        "sys_bus_stub sys_bus_stub_2 (sys[2]);",
        """sys_bus_stub sys_bus_stub_2 (sys[2]);

////////////////////////////////////////////////////////////////////////////////
// Photon-QDrivers P6.1 physical loopback (AXI-GP0 slot 13)
////////////////////////////////////////////////////////////////////////////////

logic [8-1:0] qdriver_detector_events;
logic [8-1:0] qdriver_pulse_active_mask;

assign qdriver_detector_events = exp_p_io;

red_pitaya_sys_bus_adapter #(
  .CHANNELS                (8),
  .MAX_INSTRUCTIONS        (16),
  .COUNT_WIDTH             (2),
  .FPGA_CLOCK_HZ           (125_000_000),
  .LOOPBACK_OUTPUT_CHANNEL (0),
  .LOOPBACK_INPUT_CHANNEL  (4)
) qdriver_p61 (
  .clk              (sys[13].clk),
  .reset_n          (sys[13].rstn),
  .bus_write_enable (sys[13].wen),
  .bus_read_enable  (sys[13].ren),
  .bus_address      (sys[13].addr),
  .bus_write_data   (sys[13].wdata),
  .bus_read_data    (sys[13].rdata),
  .bus_acknowledge  (sys[13].ack),
  .bus_error        (sys[13].err),
  .detector_events  (qdriver_detector_events),
  .pulse_active_mask(qdriver_pulse_active_mask)
);""",
        "system-bus slot insertion",
    )
    top = _replace_once(
        top,
        "assign exp_n_io = exp_exo.TDATA[0];",
        "assign exp_n_io = qdriver_pulse_active_mask;",
        "expansion-output assignment",
    )
    top_path.write_text(top, encoding="utf-8")

    marker = target / "QDRIVERLAB_OVERLAY.txt"
    marker.write_text(
        "\n".join(
            (
                "Photon-QDrivers P6.1 Red Pitaya overlay",
                f"upstream_commit={revision}",
                f"project_name={project_name}",
                "system_bus_slot=13",
                "physical_base_address=0x40340000",
                "loopback=DIO_N0-to-DIO_P4",
                "",
            )
        ),
        encoding="utf-8",
    )
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-unverified-upstream", action="store_true")
    return parser


def main() -> int:
    options = build_parser().parse_args()
    source_root = Path(__file__).resolve().parents[2]
    target = prepare_project(
        options.upstream,
        source_root,
        project_name=options.project_name,
        force=options.force,
        allow_unverified_upstream=options.allow_unverified_upstream,
    )
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
