"""Convert wire JSON to LTspice ASC WIRE and FLAG directives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _find_ground_flag_point(segments):
    """Return (x, y) of the endpoint with the largest Y across ground net segments."""
    max_y = None
    best_point = None
    for x1, y1, x2, y2 in segments:
        if max_y is None or y1 > max_y:
            max_y = y1
            best_point = (x1, y1)
        if y2 > max_y:
            max_y = y2
            best_point = (x2, y2)
    return best_point


def _convert(json_filepath, asc_filepath):
    with open(json_filepath, "r") as input_file:
        data = json.load(input_file)

    lines = []
    ground_flags = []

    for net_name, segments in data.items():
        for x1, y1, x2, y2 in segments:
            lines.append(f"WIRE {int(x1)} {int(y1)} {int(x2)} {int(y2)}")

    for net_name, segments in data.items():
        if net_name.strip() == "0" or net_name.strip().upper() == "GND":
            point = _find_ground_flag_point(segments)
            if point is not None:
                ground_flags.append(f"FLAG {int(point[0])} {int(point[1])} 0")

    lines.extend(ground_flags)

    with open(asc_filepath, "w") as output_file:
        output_file.write("\n".join(lines))
        if lines:
            output_file.write("\n")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert wire JSON to LTspice ASC WIRE and FLAG directives.",
    )
    parser.add_argument(
        "wire_filepath",
        help="Path to the wire JSON file.",
    )
    parser.add_argument(
        "asc_filepath",
        nargs="?",
        default=None,
        help="Optional output ASC path. Defaults to the input stem plus .asc.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    wire_path = Path(arguments.wire_filepath)
    if not wire_path.is_file():
        print(f"{wire_path}: not a file", file=sys.stderr)
        return 1
    output_path = arguments.asc_filepath or str(wire_path.with_suffix(".wire"))
    _convert(str(wire_path), output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
