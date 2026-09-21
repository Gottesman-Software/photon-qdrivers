#!/usr/bin/env python3
"""Generate and verify the deterministic QDriverLab Paper 01 reference suite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import tempfile
from html import escape
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_PATH = Path(__file__).resolve()
REPOSITORY_ROOT = SCRIPT_PATH.parents[3]
SOURCE_ROOT = REPOSITORY_ROOT / "python"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from photon_qdrivers import (  # noqa: E402
    ANALYTIC_LOOPBACK_MODEL_ID,
    AcquisitionKind,
    AnalyticLoopbackConfig,
    AnalyticLoopbackPlant,
    ChannelRole,
    ControlChannel,
    ControlEvent,
    ControlProgram,
    DetectorResponse,
    EventKind,
    HardwareProfile,
    LoopbackPath,
    VirtualPhotonicController,
    compile_control_program,
)


EXPERIMENTS_DIR = SCRIPT_PATH.parent
DEFAULT_SPEC = EXPERIMENTS_DIR / "experiment_spec.json"
DEFAULT_OUTPUT = EXPERIMENTS_DIR / "reference_v1"

BLUE = "#235789"
ORANGE = "#d95f02"
GREEN = "#1b7f5a"
PURPLE = "#6f4e9c"
GRAY = "#5f6770"
LIGHT_GRAY = "#d9dde2"
TEXT = "#20262d"
WHITE = "#ffffff"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return f"{value:.10f}"
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row[key]) for key in fieldnames})


def _profile(
    profile_id: str,
    *,
    second_detector: bool = False,
    phase_channel: bool = False,
    counter_bits: int = 32,
) -> HardwareProfile:
    roles = {
        "source/0": ChannelRole.SOURCE,
        "detector/0": ChannelRole.DETECTOR,
    }
    if second_detector:
        roles["detector/1"] = ChannelRole.DETECTOR
    if phase_channel:
        roles["phase/0"] = ChannelRole.PHASE
    return HardwareProfile(
        profile_id=profile_id,
        clock_period_ns=1.0,
        channel_roles=roles,
        counter_bits=counter_bits,
    )


def _execute(
    profile: HardwareProfile,
    program: ControlProgram,
    plant_config: AnalyticLoopbackConfig,
    *,
    job_id: str,
):
    compiled = compile_control_program(program, profile)
    controller = VirtualPhotonicController(
        profile, AnalyticLoopbackPlant(profile, plant_config)
    )
    controller.initialize()
    return compiled, controller.execute(compiled, job_id=job_id)


def _count_program(
    *,
    program_id: str,
    shots: int,
    source_amplitude: float = 1.0,
    acquisition_kind: AcquisitionKind = AcquisitionKind.COUNTS,
    window_start: int = 0,
    window_duration: int = 12,
    repetition_ticks: int = 20,
    phase: float | None = None,
    coincidence_window: int | None = None,
) -> ControlProgram:
    channels = [
        ControlChannel("source/0", ChannelRole.SOURCE),
        ControlChannel("detector/0", ChannelRole.DETECTOR),
    ]
    events: list[ControlEvent] = []
    if phase is not None:
        channels.insert(1, ControlChannel("phase/0", ChannelRole.PHASE))
        events.append(
            ControlEvent(
                "phase-arm-b",
                EventKind.PHASE_UPDATE,
                "phase/0",
                start_ns=0,
                parameters={"path_id": "arm-b", "phase": phase},
            )
        )
    acquisition_parameters: dict[str, Any] = {}
    if coincidence_window is not None:
        channels.append(ControlChannel("detector/1", ChannelRole.DETECTOR))
        acquisition_parameters = {
            "detectors": ["detector/0", "detector/1"],
            "coincidence_window_ticks": coincidence_window,
        }
    events.extend(
        (
            ControlEvent(
                "source-pulse",
                EventKind.SOURCE_TRIGGER,
                "source/0",
                start_ns=0,
                duration_ns=1,
                parameters={"amplitude": source_amplitude},
            ),
            ControlEvent(
                "detector-window",
                EventKind.ACQUIRE,
                "detector/0",
                start_ns=window_start,
                duration_ns=window_duration,
                parameters=acquisition_parameters,
                acquisition_id="acq-0",
                acquisition_kind=acquisition_kind,
            ),
        )
    )
    return ControlProgram(
        program_id=program_id,
        channels=tuple(channels),
        events=tuple(events),
        shots=shots,
        repetition_period_ns=repetition_ticks,
        provenance={"paper_suite": "qdriverlab-reference-v1"},
    )


def _wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    if trials <= 0:
        raise ValueError("Wilson interval requires positive trials.")
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    half_width = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def _phase_fringe(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    settings = spec["phase_fringe"]
    profile = _profile("paper-phase-profile", phase_channel=True)
    rows: list[dict[str, Any]] = []
    for index, phase_over_pi in enumerate(settings["phase_over_pi"]):
        phase = float(phase_over_pi) * math.pi
        program = _count_program(
            program_id=f"paper-phase-{index:02d}",
            shots=settings["shots"],
            phase=phase,
        )
        plant = AnalyticLoopbackConfig(
            paths=(
                LoopbackPath(
                    "arm-a", "source/0", "detector/0", 5, transmission=0.25
                ),
                LoopbackPath(
                    "arm-b", "source/0", "detector/0", 5, transmission=0.25
                ),
            ),
            detectors=(DetectorResponse("detector/0"),),
            seed=settings["seed"],
        )
        _, result = _execute(
            profile, program, plant, job_id=f"paper-phase-job-{index:02d}"
        )
        clicks = result.acquisitions[0].payload["detector/0"]
        shots = settings["shots"]
        observed = clicks / shots
        expected = math.cos(phase / 2.0) ** 2
        lower, upper = _wilson_interval(clicks, shots)
        rows.append(
            {
                "phase_index": index,
                "phase_over_pi": float(phase_over_pi),
                "phase_rad": phase,
                "shots": shots,
                "clicks": clicks,
                "observed_probability": observed,
                "expected_probability": expected,
                "ci95_lower": lower,
                "ci95_upper": upper,
                "absolute_error": abs(observed - expected),
            }
        )
    return rows


def _loss_response(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    settings = spec["loss_response"]
    profile = _profile("paper-loss-profile")
    program = _count_program(
        program_id="paper-loss-program",
        shots=settings["shots_per_seed"],
        source_amplitude=settings["source_amplitude"],
    )
    rows: list[dict[str, Any]] = []
    for transmission in settings["transmissions"]:
        clicks = 0
        for seed in settings["seeds"]:
            plant = AnalyticLoopbackConfig(
                paths=(
                    LoopbackPath(
                        "loss-path",
                        "source/0",
                        "detector/0",
                        5,
                        transmission=transmission,
                    ),
                ),
                detectors=(
                    DetectorResponse(
                        "detector/0", efficiency=settings["detector_efficiency"]
                    ),
                ),
                seed=seed,
            )
            _, result = _execute(
                profile, program, plant, job_id=f"paper-loss-{transmission}-{seed}"
            )
            clicks += result.acquisitions[0].payload["detector/0"]
        trials = settings["shots_per_seed"] * len(settings["seeds"])
        observed = clicks / trials
        expected = (
            settings["source_amplitude"] ** 2
            * settings["detector_efficiency"]
            * transmission
        )
        lower, upper = _wilson_interval(clicks, trials)
        rows.append(
            {
                "transmission": transmission,
                "seeds": len(settings["seeds"]),
                "trials": trials,
                "clicks": clicks,
                "observed_probability": observed,
                "expected_probability": expected,
                "ci95_lower": lower,
                "ci95_upper": upper,
                "absolute_error": abs(observed - expected),
            }
        )
    return rows


def _timing_boundary(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    settings = spec["timing_boundary"]
    profile = _profile("paper-timing-profile")
    program = _count_program(
        program_id="paper-timing-program",
        shots=settings["shots"],
        window_start=settings["window_start_tick"],
        window_duration=settings["window_duration_ticks"],
    )
    window_end = settings["window_start_tick"] + settings["window_duration_ticks"]
    rows: list[dict[str, Any]] = []
    for delay in settings["delay_ticks"]:
        plant = AnalyticLoopbackConfig(
            paths=(LoopbackPath("timing-path", "source/0", "detector/0", delay),),
            detectors=(DetectorResponse("detector/0"),),
            seed=0,
        )
        _, result = _execute(
            profile, program, plant, job_id=f"paper-timing-{delay}"
        )
        clicks = result.acquisitions[0].payload["detector/0"]
        expected_inside = settings["window_start_tick"] <= delay < window_end
        rows.append(
            {
                "delay_ticks": delay,
                "window_start_tick": settings["window_start_tick"],
                "window_end_tick_exclusive": window_end,
                "shots": settings["shots"],
                "clicks": clicks,
                "observed_probability": clicks / settings["shots"],
                "expected_inside_window": expected_inside,
            }
        )
    return rows


def _coincidence_scan(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    settings = spec["coincidence_scan"]
    profile = _profile("paper-coincidence-profile", second_detector=True)
    plant = AnalyticLoopbackConfig(
        paths=(
            LoopbackPath(
                "coincidence-a",
                "source/0",
                "detector/0",
                settings["delay_a_ticks"],
            ),
            LoopbackPath(
                "coincidence-b",
                "source/0",
                "detector/1",
                settings["delay_b_ticks"],
            ),
        ),
        detectors=(
            DetectorResponse("detector/0"),
            DetectorResponse("detector/1"),
        ),
        seed=0,
    )
    separation = abs(settings["delay_a_ticks"] - settings["delay_b_ticks"])
    rows: list[dict[str, Any]] = []
    for window in settings["window_ticks"]:
        program = _count_program(
            program_id=f"paper-coincidence-{window}",
            shots=settings["shots"],
            acquisition_kind=AcquisitionKind.COINCIDENCES,
            coincidence_window=window,
        )
        _, result = _execute(
            profile, program, plant, job_id=f"paper-coincidence-{window}"
        )
        coincidences = result.acquisitions[0].payload[
            "detector/0&detector/1"
        ]
        rows.append(
            {
                "coincidence_window_ticks": window,
                "arrival_separation_ticks": separation,
                "shots": settings["shots"],
                "coincidences": coincidences,
                "observed_probability": coincidences / settings["shots"],
                "expected_match": window >= separation,
            }
        )
    return rows


def _saturation(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    settings = spec["saturation"]
    rows: list[dict[str, Any]] = []
    counter_capacity = (1 << settings["counter_bits"]) - 1
    for requested in settings["event_counts"]:
        counter_profile = _profile(
            "paper-counter-profile", counter_bits=settings["counter_bits"]
        )
        counter_program = _count_program(
            program_id=f"paper-counter-{requested}", shots=requested
        )
        counter_plant = AnalyticLoopbackConfig(
            paths=(LoopbackPath("counter-path", "source/0", "detector/0", 5),),
            detectors=(DetectorResponse("detector/0"),),
        )
        _, counter_result = _execute(
            counter_profile,
            counter_program,
            counter_plant,
            job_id=f"paper-counter-{requested}",
        )
        counter_record = counter_result.acquisitions[0]
        rows.append(
            {
                "resource": "counter",
                "capacity": counter_capacity,
                "requested_events": requested,
                "recorded_events": counter_record.payload["detector/0"],
                "dropped_events": counter_record.dropped_events,
                "overflow": counter_record.overflow,
            }
        )

        tag_profile = _profile("paper-tag-buffer-profile")
        tag_program = _count_program(
            program_id=f"paper-tag-buffer-{requested}",
            shots=requested,
            acquisition_kind=AcquisitionKind.TIME_TAGS,
        )
        tag_plant = AnalyticLoopbackConfig(
            paths=(LoopbackPath("tag-path", "source/0", "detector/0", 5),),
            detectors=(
                DetectorResponse(
                    "detector/0",
                    buffer_capacity=settings["time_tag_buffer_capacity"],
                ),
            ),
        )
        _, tag_result = _execute(
            tag_profile,
            tag_program,
            tag_plant,
            job_id=f"paper-tag-buffer-{requested}",
        )
        tag_record = tag_result.acquisitions[0]
        rows.append(
            {
                "resource": "time_tag_buffer",
                "capacity": settings["time_tag_buffer_capacity"],
                "requested_events": requested,
                "recorded_events": len(tag_record.payload),
                "dropped_events": tag_record.dropped_events,
                "overflow": tag_record.overflow,
            }
        )
    return rows


def _repeatability(spec: Mapping[str, Any]) -> dict[str, Any]:
    settings = spec["repeatability"]
    profile = _profile("paper-repeatability-profile")
    program = _count_program(
        program_id="paper-repeatability-program",
        shots=settings["shots"],
        source_amplitude=settings["source_amplitude"],
    )
    plant = AnalyticLoopbackConfig(
        paths=(LoopbackPath("repeat-path", "source/0", "detector/0", 5),),
        detectors=(DetectorResponse("detector/0"),),
        seed=settings["seed"],
    )
    compiled, first = _execute(
        profile, program, plant, job_id="paper-repeatability-job"
    )
    _, second = _execute(
        profile, program, plant, job_id="paper-repeatability-job"
    )
    first_payload = _canonical_json(first.to_dict()).encode("utf-8")
    return {
        "exact_result_match": first.to_dict() == second.to_dict(),
        "program_digest": compiled.digest,
        "trace_digest": first.trace.digest,
        "result_digest": _sha256_bytes(first_payload),
        "clicks": first.acquisitions[0].payload["detector/0"],
        "shots": settings["shots"],
        "seed": settings["seed"],
    }


def _chart_coordinates(
    value: float, domain: tuple[float, float], target: tuple[float, float]
) -> float:
    lower, upper = domain
    start, end = target
    if upper == lower:
        return (start + end) / 2.0
    return start + (value - lower) * (end - start) / (upper - lower)


def _svg_document(width: int, height: int, title: str, body: Iterable[str]) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f"<title>{escape(title)}</title>",
        f'<rect width="{width}" height="{height}" fill="{WHITE}"/>',
        '<style>text{font-family:"DejaVu Sans",Arial,sans-serif;fill:#20262d}.axis{stroke:#20262d;stroke-width:1.2}.grid{stroke:#d9dde2;stroke-width:1}.tick{font-size:13px}.label{font-size:15px;font-weight:600}.panel-title{font-size:18px;font-weight:700}.figure-title{font-size:22px;font-weight:700}.legend{font-size:13px}</style>',
        *body,
        "</svg>",
        "",
    ]
    return "\n".join(parts)


def _single_probability_figure(
    *,
    title: str,
    rows: Sequence[Mapping[str, Any]],
    x_key: str,
    x_domain: tuple[float, float],
    x_ticks: Sequence[tuple[float, str]],
    x_label: str,
) -> str:
    width, height = 920, 590
    left, right, top, bottom = 92, 34, 30, 78
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_range = (left, left + plot_width)
    y_range = (top + plot_height, top)
    y_domain = (0.0, 1.0)
    body: list[str] = []
    for value in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        y = _chart_coordinates(value, y_domain, y_range)
        body.append(
            f'<line x1="{left}" y1="{y:.3f}" x2="{left + plot_width}" y2="{y:.3f}" class="grid"/>'
        )
        body.append(
            f'<text x="{left - 12}" y="{y + 5:.3f}" text-anchor="end" class="tick">{value:.1f}</text>'
        )
    for value, label in x_ticks:
        x = _chart_coordinates(value, x_domain, x_range)
        body.append(
            f'<line x1="{x:.3f}" y1="{top + plot_height}" x2="{x:.3f}" y2="{top + plot_height + 6}" class="axis"/>'
        )
        body.append(
            f'<text x="{x:.3f}" y="{top + plot_height + 25}" text-anchor="middle" class="tick">{escape(label)}</text>'
        )
    body.extend(
        (
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" class="axis"/>',
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" class="axis"/>',
            f'<text x="{left + plot_width / 2}" y="{height - 20}" text-anchor="middle" class="label">{escape(x_label)}</text>',
            f'<text x="22" y="{top + plot_height / 2}" text-anchor="middle" transform="rotate(-90 22 {top + plot_height / 2})" class="label">Detection probability</text>',
        )
    )
    expected_points = []
    for row in rows:
        x = _chart_coordinates(float(row[x_key]), x_domain, x_range)
        y = _chart_coordinates(
            float(row["expected_probability"]), y_domain, y_range
        )
        expected_points.append(f"{x:.3f},{y:.3f}")
    body.append(
        f'<polyline points="{" ".join(expected_points)}" fill="none" stroke="{ORANGE}" stroke-width="3"/>'
    )
    for row in rows:
        x = _chart_coordinates(float(row[x_key]), x_domain, x_range)
        y = _chart_coordinates(
            float(row["observed_probability"]), y_domain, y_range
        )
        lower = _chart_coordinates(float(row["ci95_lower"]), y_domain, y_range)
        upper = _chart_coordinates(float(row["ci95_upper"]), y_domain, y_range)
        body.extend(
            (
                f'<line x1="{x:.3f}" y1="{lower:.3f}" x2="{x:.3f}" y2="{upper:.3f}" stroke="{BLUE}" stroke-width="1.2"/>',
                f'<line x1="{x - 4:.3f}" y1="{lower:.3f}" x2="{x + 4:.3f}" y2="{lower:.3f}" stroke="{BLUE}" stroke-width="1.2"/>',
                f'<line x1="{x - 4:.3f}" y1="{upper:.3f}" x2="{x + 4:.3f}" y2="{upper:.3f}" stroke="{BLUE}" stroke-width="1.2"/>',
                f'<circle cx="{x:.3f}" cy="{y:.3f}" r="4.2" fill="{BLUE}"/>',
            )
        )
    legend_y = top + 18
    body.extend(
        (
            f'<line x1="{left + 18}" y1="{legend_y}" x2="{left + 54}" y2="{legend_y}" stroke="{ORANGE}" stroke-width="3"/>',
            f'<text x="{left + 62}" y="{legend_y + 5}" class="legend">Analytic reference</text>',
            f'<circle cx="{left + 210}" cy="{legend_y}" r="4.2" fill="{BLUE}"/>',
            f'<text x="{left + 220}" y="{legend_y + 5}" class="legend">Deterministic samples with 95% Wilson interval</text>',
        )
    )
    return _svg_document(width, height, title, body)


def _panel(
    *,
    body: list[str],
    x: float,
    y: float,
    width: float,
    height: float,
    rows: Sequence[Mapping[str, Any]],
    x_key: str,
    series: Sequence[tuple[str, str, str]],
    x_label: str,
    y_label: str,
    x_domain: tuple[float, float],
    y_domain: tuple[float, float],
    x_ticks: Sequence[float],
    y_ticks: Sequence[float],
) -> None:
    left = x + 64
    top = y + 32
    plot_width = width - 82
    plot_height = height - 96
    x_range = (left, left + plot_width)
    y_range = (top + plot_height, top)
    for value in y_ticks:
        coordinate = _chart_coordinates(value, y_domain, y_range)
        body.append(
            f'<line x1="{left}" y1="{coordinate:.3f}" x2="{left + plot_width}" y2="{coordinate:.3f}" class="grid"/>'
        )
        body.append(
            f'<text x="{left - 10}" y="{coordinate + 4:.3f}" text-anchor="end" class="tick">{value:g}</text>'
        )
    for value in x_ticks:
        coordinate = _chart_coordinates(value, x_domain, x_range)
        body.append(
            f'<text x="{coordinate:.3f}" y="{top + plot_height + 23}" text-anchor="middle" class="tick">{value:g}</text>'
        )
    body.extend(
        (
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" class="axis"/>',
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" class="axis"/>',
            f'<text x="{left + plot_width / 2}" y="{y + height - 14}" text-anchor="middle" class="label">{escape(x_label)}</text>',
            f'<text x="{x + 17}" y="{top + plot_height / 2}" text-anchor="middle" transform="rotate(-90 {x + 17} {top + plot_height / 2})" class="label">{escape(y_label)}</text>',
        )
    )
    for key, label, color in series:
        points = []
        for row in rows:
            px = _chart_coordinates(float(row[x_key]), x_domain, x_range)
            py = _chart_coordinates(float(row[key]), y_domain, y_range)
            points.append(f"{px:.3f},{py:.3f}")
        line_width = 4.6 if label == "Expected" else 2.6
        body.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="{line_width}"/>'
        )
        for point in points:
            px, py = point.split(",")
            body.append(f'<circle cx="{px}" cy="{py}" r="3.8" fill="{color}"/>')


def _shared_legend(
    body: list[str],
    *,
    y: float,
    start_x: float,
    spacing: float,
    items: Sequence[tuple[str, str]],
) -> None:
    for index, (label, color) in enumerate(items):
        x = start_x + index * spacing
        body.append(
            f'<line x1="{x}" y1="{y}" x2="{x + 30}" y2="{y}" stroke="{color}" stroke-width="2.6"/>'
        )
        body.append(
            f'<text x="{x + 38}" y="{y + 5}" class="legend">{escape(label)}</text>'
        )


def _boundary_figure(
    timing_rows: Sequence[Mapping[str, Any]],
    coincidence_rows: Sequence[Mapping[str, Any]],
) -> str:
    width, height = 1080, 500
    body: list[str] = []
    _shared_legend(
        body,
        y=18,
        start_x=370,
        spacing=190,
        items=(("Observed", BLUE), ("Expected", ORANGE)),
    )
    timing_panel_rows = [
        {
            **row,
            "expected_probability": float(row["expected_inside_window"]),
        }
        for row in timing_rows
    ]
    coincidence_panel_rows = [
        {**row, "expected_probability": float(row["expected_match"])}
        for row in coincidence_rows
    ]
    _panel(
        body=body,
        x=10,
        y=18,
        width=520,
        height=468,
        rows=timing_panel_rows,
        x_key="delay_ticks",
        series=(
            ("expected_probability", "Expected", ORANGE),
            ("observed_probability", "Observed", BLUE),
        ),
        x_label="Path delay (ticks)",
        y_label="Detection probability",
        x_domain=(0.0, 14.0),
        y_domain=(0.0, 1.05),
        x_ticks=(0, 2, 4, 6, 8, 10, 12, 14),
        y_ticks=(0.0, 0.5, 1.0),
    )
    _panel(
        body=body,
        x=545,
        y=18,
        width=520,
        height=468,
        rows=coincidence_panel_rows,
        x_key="coincidence_window_ticks",
        series=(
            ("expected_probability", "Expected", ORANGE),
            ("observed_probability", "Observed", BLUE),
        ),
        x_label="Coincidence window (ticks)",
        y_label="Coincidence probability",
        x_domain=(0.0, 6.0),
        y_domain=(0.0, 1.05),
        x_ticks=(0, 1, 2, 3, 4, 5, 6),
        y_ticks=(0.0, 0.5, 1.0),
    )
    return _svg_document(width, height, "Device-tick boundary behavior", body)


def _saturation_figure(rows: Sequence[Mapping[str, Any]]) -> str:
    width, height = 1080, 500
    body: list[str] = []
    _shared_legend(
        body,
        y=18,
        start_x=265,
        spacing=195,
        items=(("Recorded", BLUE), ("Dropped", ORANGE), ("Capacity", GRAY)),
    )
    counter_rows = [row for row in rows if row["resource"] == "counter"]
    buffer_rows = [row for row in rows if row["resource"] == "time_tag_buffer"]
    for panel_x, panel_rows, capacity in (
        (10, counter_rows, 255),
        (545, buffer_rows, 128),
    ):
        augmented = [
            {**row, "capacity_reference": capacity} for row in panel_rows
        ]
        _panel(
            body=body,
            x=panel_x,
            y=18,
            width=520,
            height=468,
            rows=augmented,
            x_key="requested_events",
            series=(
                ("recorded_events", "Recorded", BLUE),
                ("dropped_events", "Dropped", ORANGE),
                ("capacity_reference", "Capacity", GRAY),
            ),
            x_label="Requested events",
            y_label="Events",
            x_domain=(64.0, 512.0),
            y_domain=(0.0, 520.0),
            x_ticks=(64, 128, 256, 384, 512),
            y_ticks=(0, 128, 256, 384, 512),
        )
    return _svg_document(width, height, "Finite-resource saturation behavior", body)


def _validate_results(
    spec: Mapping[str, Any],
    phase_rows: Sequence[Mapping[str, Any]],
    loss_rows: Sequence[Mapping[str, Any]],
    timing_rows: Sequence[Mapping[str, Any]],
    coincidence_rows: Sequence[Mapping[str, Any]],
    saturation_rows: Sequence[Mapping[str, Any]],
    repeatability: Mapping[str, Any],
) -> dict[str, Any]:
    phase_error = max(float(row["absolute_error"]) for row in phase_rows)
    loss_error = max(float(row["absolute_error"]) for row in loss_rows)
    timing_exact = all(
        (row["clicks"] == row["shots"]) == row["expected_inside_window"]
        for row in timing_rows
    )
    coincidence_exact = all(
        (row["coincidences"] == row["shots"]) == row["expected_match"]
        for row in coincidence_rows
    )
    saturation_exact = all(
        row["recorded_events"] == min(row["requested_events"], row["capacity"])
        and row["dropped_events"]
        == max(0, row["requested_events"] - row["capacity"])
        for row in saturation_rows
    )
    acceptance = spec["acceptance"]
    checks = {
        "phase_error_within_limit": phase_error
        <= acceptance["phase_max_absolute_error"],
        "loss_error_within_limit": loss_error
        <= acceptance["loss_max_absolute_error"],
        "timing_boundary_exact": timing_exact,
        "coincidence_boundary_exact": coincidence_exact,
        "saturation_exact": saturation_exact,
        "repeatability_exact": bool(repeatability["exact_result_match"]),
    }
    if not all(checks.values()):
        failed = ", ".join(key for key, value in checks.items() if not value)
        raise RuntimeError(f"Reference experiment acceptance failed: {failed}")
    return {
        "checks": checks,
        "phase_max_absolute_error": phase_error,
        "phase_error_limit": acceptance["phase_max_absolute_error"],
        "loss_max_absolute_error": loss_error,
        "loss_error_limit": acceptance["loss_max_absolute_error"],
    }


def generate_suite(spec_path: Path, output_dir: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    phase_rows = _phase_fringe(spec)
    loss_rows = _loss_response(spec)
    timing_rows = _timing_boundary(spec)
    coincidence_rows = _coincidence_scan(spec)
    saturation_rows = _saturation(spec)
    repeatability = _repeatability(spec)

    _write_csv(
        data_dir / "phase_fringe.csv",
        (
            "phase_index",
            "phase_over_pi",
            "phase_rad",
            "shots",
            "clicks",
            "observed_probability",
            "expected_probability",
            "ci95_lower",
            "ci95_upper",
            "absolute_error",
        ),
        phase_rows,
    )
    _write_csv(
        data_dir / "loss_response.csv",
        (
            "transmission",
            "seeds",
            "trials",
            "clicks",
            "observed_probability",
            "expected_probability",
            "ci95_lower",
            "ci95_upper",
            "absolute_error",
        ),
        loss_rows,
    )
    _write_csv(
        data_dir / "timing_boundary.csv",
        (
            "delay_ticks",
            "window_start_tick",
            "window_end_tick_exclusive",
            "shots",
            "clicks",
            "observed_probability",
            "expected_inside_window",
        ),
        timing_rows,
    )
    _write_csv(
        data_dir / "coincidence_window.csv",
        (
            "coincidence_window_ticks",
            "arrival_separation_ticks",
            "shots",
            "coincidences",
            "observed_probability",
            "expected_match",
        ),
        coincidence_rows,
    )
    _write_csv(
        data_dir / "saturation.csv",
        (
            "resource",
            "capacity",
            "requested_events",
            "recorded_events",
            "dropped_events",
            "overflow",
        ),
        saturation_rows,
    )
    _write_json(data_dir / "repeatability.json", repeatability)

    summary = _validate_results(
        spec,
        phase_rows,
        loss_rows,
        timing_rows,
        coincidence_rows,
        saturation_rows,
        repeatability,
    )
    _write_json(data_dir / "summary.json", summary)

    (figure_dir / "figure_01_phase_fringe.svg").write_text(
        _single_probability_figure(
            title="Analytic two-path phase fringe",
            rows=phase_rows,
            x_key="phase_over_pi",
            x_domain=(0.0, 2.0),
            x_ticks=((0.0, "0"), (0.5, "π/2"), (1.0, "π"), (1.5, "3π/2"), (2.0, "2π")),
            x_label="Relative phase",
        ),
        encoding="utf-8",
    )
    (figure_dir / "figure_02_loss_response.svg").write_text(
        _single_probability_figure(
            title="Loss and detector-efficiency response",
            rows=loss_rows,
            x_key="transmission",
            x_domain=(0.0, 1.0),
            x_ticks=((0.0, "0"), (0.2, "0.2"), (0.4, "0.4"), (0.6, "0.6"), (0.8, "0.8"), (1.0, "1.0")),
            x_label="Path transmission",
        ),
        encoding="utf-8",
    )
    (figure_dir / "figure_03_timing_and_coincidence.svg").write_text(
        _boundary_figure(timing_rows, coincidence_rows), encoding="utf-8"
    )
    (figure_dir / "figure_04_resource_saturation.svg").write_text(
        _saturation_figure(saturation_rows), encoding="utf-8"
    )

    generated = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    file_digests = {
        path.relative_to(output_dir).as_posix(): _sha256_file(path)
        for path in generated
    }
    manifest_core = {
        "schema_version": "qdriverlab.paper01.manifest.v1",
        "suite_id": spec["suite_id"],
        "model_id": ANALYTIC_LOOPBACK_MODEL_ID,
        "spec_digest": _sha256_file(spec_path),
        "generator_digest": _sha256_file(SCRIPT_PATH),
        "files": file_digests,
        "summary": summary,
    }
    manifest = {
        **manifest_core,
        "suite_digest": _sha256_bytes(
            _canonical_json(manifest_core).encode("utf-8")
        ),
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def _files_under(path: Path) -> dict[str, bytes]:
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def verify_suite(spec_path: Path, reference_dir: Path) -> dict[str, Any]:
    if not reference_dir.is_dir():
        raise FileNotFoundError(f"Reference directory does not exist: {reference_dir}")
    with tempfile.TemporaryDirectory(prefix="qdriverlab-paper01-") as temporary:
        generated_dir = Path(temporary) / "reference_v1"
        manifest = generate_suite(spec_path, generated_dir)
        expected = _files_under(reference_dir)
        generated = _files_under(generated_dir)
        if expected.keys() != generated.keys():
            missing = sorted(expected.keys() - generated.keys())
            unexpected = sorted(generated.keys() - expected.keys())
            raise RuntimeError(
                f"Reference file set differs; missing={missing}, unexpected={unexpected}"
            )
        changed = [name for name in expected if expected[name] != generated[name]]
        if changed:
            raise RuntimeError(
                "Reference content differs for: " + ", ".join(changed)
            )
        return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Regenerate in a temporary directory and compare exact bytes.",
    )
    arguments = parser.parse_args(argv)
    spec_path = arguments.spec.resolve()
    output_dir = arguments.output.resolve()
    if arguments.verify:
        manifest = verify_suite(spec_path, output_dir)
        print(
            f"verified {manifest['suite_id']} {manifest['suite_digest']}"
        )
        return 0
    if output_dir.exists() and any(
        item.is_file() for item in output_dir.rglob("*")
    ):
        parser.error(
            f"output directory is not empty: {output_dir}; use --verify or a new path"
        )
    manifest = generate_suite(spec_path, output_dir)
    print(f"generated {manifest['suite_id']} {manifest['suite_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
