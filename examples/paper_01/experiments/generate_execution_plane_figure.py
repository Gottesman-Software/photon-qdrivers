#!/usr/bin/env python3
"""Generate the execution-plane figure and refresh its inlined evidence tables."""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any, Iterable


DEFAULT_RTL = Path(__file__).with_name("rtl_reference_v1") / "rtl_parity.json"
DEFAULT_PROGRAM = Path(__file__).with_name("rtl_reference_v1") / "program.hex"
DEFAULT_BOARD = (
    Path(__file__).with_name("p6_board_reference_v1") / "bridge_summary.json"
)
DEFAULT_BOARD_PROGRAM = (
    Path(__file__).with_name("p6_board_reference_v1") / "board_program.frame"
)
DEFAULT_OUTPUT = (
    Path(__file__).parents[1]
    / "manuscript"
    / "figures"
    / "figure_05_execution_plane_parity.svg"
)
DEFAULT_MANUSCRIPT = (
    Path(__file__).parents[1] / "manuscript" / "qdriver_paper_01.tex"
)

TABLES_BEGIN = "% BEGIN GENERATED EXECUTION-PLANE TABLES"
TABLES_END = "% END GENERATED EXECUTION-PLANE TABLES"

WIDTH = 1600
HEIGHT = 700

NAVY = "#17324D"
INK = "#142331"
MUTED = "#5C6B78"
GRID = "#DCE4EA"
PALE = "#F5F8FA"
BLUE = "#2468A2"
TEAL = "#168A83"
ORANGE = "#D97706"
PURPLE = "#7654A8"
GREEN = "#238B57"
GREEN_PALE = "#EAF6EF"
WHITE = "#FFFFFF"

OPCODE_NAMES = {
    1: "SOURCE",
    2: "MODULATOR",
    3: "PHASE",
    4: "SYNC",
    5: "DELAY",
    6: "ACQUIRE",
}

OPCODE_COLORS = {
    1: BLUE,
    2: TEAL,
    3: PURPLE,
    4: "#66788A",
    5: ORANGE,
    6: GREEN,
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _text(
    x: float,
    y: float,
    value: object,
    css_class: str,
    *,
    anchor: str = "start",
    fill: str | None = None,
) -> str:
    fill_attr = f' fill="{fill}"' if fill else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'class="{css_class}"{fill_attr}>{escape(str(value))}</text>'
    )


def _rect(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str,
    stroke: str = "none",
    stroke_width: float = 1.0,
    radius: float = 0.0,
) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" '
        f'height="{height:.1f}" rx="{radius:.1f}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{stroke_width:.1f}"/>'
    )


def _line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str,
    width: float = 1.0,
    dash: str | None = None,
) -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
        f'y2="{y2:.1f}" stroke="{stroke}" stroke-width="{width:.1f}"{dash_attr}/>'
    )


def _badge(x: float, y: float, width: float, value: str, fill: str, color: str) -> list[str]:
    return [
        _rect(x, y, width, 28, fill=fill, stroke=color, stroke_width=0.9, radius=14),
        _text(x + width / 2, y + 19, value, "badge", anchor="middle", fill=color),
    ]


def _section_label(y: float, value: str) -> list[str]:
    return [
        _rect(46, y - 18, 10, 24, fill=BLUE, radius=5),
        _text(70, y, value, "section"),
        _line(360, y - 6, 1554, y - 6, stroke=GRID, width=1.2),
    ]


def _parse_board_words(path: Path) -> list[str]:
    return [
        line.split("=", 1)[1].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("instruction=")
    ]


def _decode_word(hex_word: str) -> dict[str, int]:
    word = int(hex_word, 16)
    return {
        "format_version": (word >> 124) & 0xF,
        "opcode": (word >> 120) & 0xF,
        "channel_index": (word >> 112) & 0xFF,
        "start_tick": (word >> 80) & 0xFFFFFFFF,
        "duration_ticks": (word >> 48) & 0xFFFFFFFF,
        "argument_word": (word >> 16) & 0xFFFFFFFF,
        "acquisition_code": (word >> 8) & 0xFF,
        "flags": word & 0xFF,
    }


def _validate_evidence(
    rtl: dict[str, Any],
    program_words: list[str],
    board: dict[str, Any],
    board_words: list[str],
) -> tuple[list[dict[str, int]], list[tuple[str, str, str]]]:
    if not rtl.get("exact_schedule_match"):
        raise ValueError("Instruction-level evidence does not report exact schedule parity.")
    expected = rtl["expected_observations"]
    observed = rtl["observed_observations"]
    if expected != observed or len(expected) != 6:
        raise ValueError("Expected and observed schedules are not the six-item fixture.")
    if program_words != board_words or len(program_words) != len(expected):
        raise ValueError("Schedule-engine words and board-image words differ.")

    decoded = [_decode_word(word) for word in program_words]
    core_fields = (
        "opcode",
        "channel_index",
        "start_tick",
        "duration_ticks",
        "argument_word",
        "acquisition_code",
    )
    for index, (instruction, observation) in enumerate(zip(decoded, expected)):
        for field in core_fields:
            if instruction[field] != observation[field]:
                raise ValueError(f"Instruction {index} differs at {field}.")

    if not board.get("exact_software_rtl_result_match"):
        raise ValueError("Board-reference evidence does not report exact software/RTL result parity.")
    software = board["software_result"]
    rtl_result = board["rtl_register_observations"]["result"]
    comparisons = [
        ("instructions", str(software["instruction_count"]), str(rtl_result["instruction_count"])),
        ("final tick", str(software["final_device_tick"]), str(rtl_result["final_device_tick"])),
        ("detector channel", str(software["acquisition_channel"]), str(rtl_result["acquisition_channel"])),
        (
            "acquisition window",
            f'[{software["acquisition_start_tick"]},{software["acquisition_end_tick"]})',
            f'[{rtl_result["acquisition_start_tick"]},{rtl_result["acquisition_end_tick"]})',
        ),
        ("recorded events", str(software["recorded_events"]), str(rtl_result["recorded_events"])),
        ("dropped events", str(software["dropped_events"]), str(rtl_result["dropped_events"])),
        (
            "overflow",
            "yes" if software["overflow"] else "no",
            "yes" if rtl_result["overflow"] else "no",
        ),
    ]
    if any(left != right for _, left, right in comparisons):
        raise ValueError("Board-reference software and RTL result values differ.")
    return decoded, comparisons


def _encoding_panel(body: list[str]) -> None:
    body.extend(_section_label(42, "128-BIT ENCODING"))
    body.extend(_badge(1284, 17, 270, "v1 · 32 hexadecimal digits", PALE, NAVY))

    fields = (
        (4, "v1", "127:124", "#345B78"),
        (4, "OP", "123:120", "#3E6D8F"),
        (8, "CHANNEL", "119:112", BLUE),
        (32, "START TICK", "111:80", "#2A7F9E"),
        (32, "DURATION", "79:48", TEAL),
        (32, "ARGUMENT", "47:16", PURPLE),
        (8, "ACQ", "15:8", ORANGE),
        (8, "FLAGS", "7:0", "#66788A"),
    )
    x0, y0, bar_width, bar_height = 70.0, 72.0, 1460.0, 92.0
    cursor = x0
    for bits, label, _bit_range, color in fields:
        width = bar_width * bits / 128.0
        body.append(_rect(cursor, y0, width, bar_height, fill=color, stroke=WHITE, stroke_width=1.5))
        label_class = "field-small" if bits <= 8 else "field"
        body.append(_text(cursor + width / 2, y0 + 40, label, label_class, anchor="middle", fill=WHITE))
        body.append(_text(cursor + width / 2, y0 + 68, f"{bits} b", "field-bits", anchor="middle", fill=WHITE))
        cursor += width

    for word_index in range(4):
        start = x0 + word_index * bar_width / 4
        end = start + bar_width / 4
        body.append(_line(start, 181, end, 181, stroke=NAVY, width=1.3))
        body.append(_line(start, 176, start, 186, stroke=NAVY, width=1.3))
        body.append(_line(end, 176, end, 186, stroke=NAVY, width=1.3))
        body.append(
            _text(
                (start + end) / 2,
                205,
                f"MMIO word {3 - word_index}",
                "small",
                anchor="middle",
            )
        )
    body.append(_text(70, 205, "MSB", "micro", fill=MUTED))
    body.append(_text(1530, 205, "LSB", "micro", anchor="end", fill=MUTED))


def _schedule_panel(body: list[str], instructions: list[dict[str, int]]) -> None:
    body.extend(_section_label(256, "REFERENCE SCHEDULE"))
    body.extend(_badge(1160, 231, 118, "6 instructions", PALE, NAVY))
    body.extend(_badge(1290, 231, 126, "12 ticks", PALE, NAVY))
    body.extend(_badge(1428, 231, 126, "ordered", GREEN_PALE, GREEN))

    x0, x1 = 330.0, 1530.0
    y0, row_height = 306.0, 48.0
    plot_bottom = y0 + row_height * len(instructions)

    def tick_x(tick: float) -> float:
        return x0 + (x1 - x0) * tick / 12.0

    for tick in range(13):
        x = tick_x(tick)
        body.append(_line(x, y0 - 16, x, plot_bottom, stroke=GRID, width=1.0))
        body.append(_text(x, plot_bottom + 24, tick, "tick", anchor="middle"))
    body.append(_text((x0 + x1) / 2, plot_bottom + 51, "Logical device tick", "axis", anchor="middle"))

    for index, instruction in enumerate(instructions):
        opcode = instruction["opcode"]
        color = OPCODE_COLORS[opcode]
        y = y0 + index * row_height
        body.append(_line(x0, y + row_height - 4, x1, y + row_height - 4, stroke="#EEF2F5", width=1.0))
        body.append(_rect(70, y + 8, 12, 12, fill=color, radius=6))
        body.append(_text(94, y + 19, f"I{index}  {OPCODE_NAMES[opcode]}", "row-label"))
        body.append(_text(300, y + 19, f'ch {instruction["channel_index"]}', "row-meta", anchor="end"))

        start = tick_x(instruction["start_tick"])
        duration = instruction["duration_ticks"]
        if duration == 0:
            cy = y + 20
            points = f"{start:.1f},{cy - 10:.1f} {start + 10:.1f},{cy:.1f} {start:.1f},{cy + 10:.1f} {start - 10:.1f},{cy:.1f}"
            body.append(f'<polygon points="{points}" fill="{color}" stroke="{WHITE}" stroke-width="1.5"/>')
        else:
            end = tick_x(instruction["start_tick"] + duration)
            body.append(_rect(start, y + 7, end - start, 27, fill=color, radius=5))
            body.append(_line(end, y + 7, end, y + 34, stroke=WHITE, width=2.0))
            if opcode == 6:
                body.append(_text((start + end) / 2, y + 26, "COUNTS · [7,11)", "bar-label", anchor="middle", fill=WHITE))

    final_x = tick_x(11)
    body.append(_line(final_x, y0 - 24, final_x, plot_bottom, stroke=GREEN, width=1.6, dash="6 5"))
    body.extend(_badge(final_x - 58, y0 - 47, 116, "final tick 11", GREEN_PALE, GREEN))
    legend_y = plot_bottom + 70
    body.append(_rect(70, legend_y - 11, 14, 14, fill=NAVY, radius=2))
    body.append(_text(96, legend_y + 2, "bar = half-open interval", "small"))
    body.append(f'<polygon points="336,{legend_y - 11} 344,{legend_y - 3} 336,{legend_y + 5} 328,{legend_y - 3}" fill="{PURPLE}"/>')
    body.append(_text(358, legend_y + 2, "diamond = instantaneous event", "small"))
    body.append(_text(1530, legend_y + 2, "same six words across software, RTL, and board fixture", "small", anchor="end", fill=GREEN))


def build_svg(instructions: list[dict[str, int]]) -> str:
    body: list[str] = []
    _encoding_panel(body)
    _schedule_panel(body, instructions)
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
            "<title id=\"title\">QDriver 128-bit instruction encoding and reference schedule</title>",
            "<desc id=\"desc\">The exact instruction encoding and six-instruction logical schedule shared by the software, RTL, and board-reference fixtures.</desc>",
            f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{WHITE}"/>',
            """<style>
text{font-family:Inter,"Helvetica Neue",Arial,sans-serif;fill:#142331}
.section{font-size:22px;font-weight:750;letter-spacing:2.2px;fill:#17324D}
.badge{font-size:16px;font-weight:700;letter-spacing:.2px}
.field{font-size:24px;font-weight:750;letter-spacing:.25px;fill:#FFFFFF}
.field-small{font-size:18px;font-weight:800;fill:#FFFFFF}
.field-bits{font-size:16px;font-weight:650;fill:#FFFFFF;opacity:.92}
.small{font-size:18px;font-weight:550}
.micro{font-size:14px;font-weight:700;letter-spacing:.7px}
.tick{font-size:17px;fill:#5C6B78}
.axis{font-size:19px;font-weight:650;fill:#33475B}
.row-label{font-size:19px;font-weight:750}
.row-meta{font-size:17px;font-weight:600;fill:#5C6B78}
.bar-label{font-size:17px;font-weight:750;letter-spacing:.15px;fill:#FFFFFF}
""" + "</style>",
            *body,
            "</svg>",
            "",
        ]
    )


def build_tables(
    instructions: list[dict[str, int]],
    comparisons: list[tuple[str, str, str]],
) -> str:
    operation_names = {
        1: "Source trigger",
        2: "Modulator pulse",
        3: "Phase update",
        4: "Synchronize",
        5: "Delay",
        6: "Acquire counts",
    }
    result_labels = {
        "instructions": "Instructions",
        "final tick": "Final tick",
        "detector channel": "Detector channel",
        "acquisition window": "Acquisition interval",
        "recorded events": "Recorded events",
        "dropped events": "Dropped events",
        "overflow": "Overflow",
    }
    lines = [
        "% Generated by generate_execution_plane_figure.py; do not edit by hand.",
        r"\begin{table*}[t]",
        r"\caption{Decoded instruction parity for the executable reference fixture. Each",
        r"row agrees exactly between the Python decode and the independent SystemVerilog",
        r"observation. Argument values are unsigned 32-bit hexadecimal words; acquisition",
        r"code 3 denotes counts.}",
        r"\label{tab:instruction-parity}",
        r"\begin{ruledtabular}",
        r"\begin{tabular}{clccccccc}",
        r"Instruction & Operation & Opcode & Channel & Start & Duration & Argument & Acquisition & Exact \\",
        r"\hline",
    ]
    for index, instruction in enumerate(instructions):
        lines.append(
            f'I{index} & {operation_names[instruction["opcode"]]} & '
            f'{instruction["opcode"]} & {instruction["channel_index"]} & '
            f'{instruction["start_tick"]} & {instruction["duration_ticks"]} & '
            f'\\code{{{instruction["argument_word"]:08x}}} & '
            f'{instruction["acquisition_code"]} & $\\checkmark$ \\\\'
        )
    lines.extend(
        [
            r"\end{tabular}",
            r"\end{ruledtabular}",
            r"\end{table*}",
            "",
            r"\begin{table}[t]",
            r"\caption{Board-result parity. The software board model and AXI-register RTL",
            r"agree exactly under Icarus simulation; these values are not measurements from a",
            r"synthesized or deployed board.}",
            r"\label{tab:board-result-parity}",
            r"\begin{ruledtabular}",
            r"\begin{tabular}{lccc}",
            r"Result field & Software & AXI RTL & Exact \\",
            r"\hline",
        ]
    )
    for label, left, right in comparisons:
        if label == "acquisition window":
            left = f"${left}$"
            right = f"${right}$"
        lines.append(
            f"{result_labels[label]} & {left} & {right} & $\\checkmark$ \\\\"
        )
    lines.extend(
        [
            r"\end{tabular}",
            r"\end{ruledtabular}",
            r"\end{table}",
            "",
        ]
    )
    return "\n".join(lines)


def update_manuscript_tables(path: Path, tables: str) -> None:
    manuscript = path.read_text(encoding="utf-8")
    prefix, begin, remainder = manuscript.partition(TABLES_BEGIN)
    if not begin:
        raise ValueError(f"Missing generated-table start marker in {path}.")
    _old_tables, end, suffix = remainder.partition(TABLES_END)
    if not end:
        raise ValueError(f"Missing generated-table end marker in {path}.")
    updated = (
        prefix
        + TABLES_BEGIN
        + "\n"
        + tables.rstrip()
        + "\n"
        + TABLES_END
        + suffix
    )
    path.write_text(updated, encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtl", type=Path, default=DEFAULT_RTL)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--board-program", type=Path, default=DEFAULT_BOARD_PROGRAM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--manuscript",
        type=Path,
        help=(
            "optional manuscript source containing the generated-table markers; "
            "the local Paper 01 source is used automatically when present"
        ),
    )
    args = parser.parse_args(argv)

    rtl = _read_json(args.rtl)
    program_words = [
        line.strip()
        for line in args.program.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    board = _read_json(args.board)
    board_words = _parse_board_words(args.board_program)
    instructions, comparisons = _validate_evidence(
        rtl, program_words, board, board_words
    )
    svg = build_svg(instructions)
    tables = build_tables(instructions, comparisons)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    manuscript = args.manuscript
    if manuscript is None and DEFAULT_MANUSCRIPT.exists():
        manuscript = DEFAULT_MANUSCRIPT
    if manuscript is not None:
        update_manuscript_tables(manuscript, tables)
    print(f"generated {args.output}")
    if manuscript is not None:
        print(f"updated tables in {manuscript}")
    else:
        print("manuscript source not present; skipped inline-table update")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
