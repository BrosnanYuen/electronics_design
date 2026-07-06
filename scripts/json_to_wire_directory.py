"""Convert every net-wire JSON file in a directory into ASC-style WIRE and FLAG lines."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
import sys


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert every net-wire JSON file in a directory into ASC-style WIRE and FLAG lines.",
    )
    parser.add_argument(
        "directory",
        help="Directory containing net-wire JSON files to convert.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional output directory for the generated ASC files. Defaults to the input directory.",
    )
    parser.add_argument(
        "--suffix",
        default="_wires",
        help="Expected suffix of wire JSON files before the .json extension. Default: '_wires'.",
    )
    return parser


def _is_ground_net(net_name: str) -> bool:
    return net_name in {"0", "GND"}


def _is_auto_numbered_net(net_name: str) -> bool:
    return bool(re.fullmatch(r"N\d{3}", net_name))


def _collect_unique_points(wire_rows: list[list[int]]) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    points: list[tuple[int, int]] = []
    for x1, y1, x2, y2 in wire_rows:
        for point in ((x1, y1), (x2, y2)):
            if point not in seen:
                seen.add(point)
                points.append(point)
    return points


def _largest_y_point(points: list[tuple[int, int]]) -> tuple[int, int]:
    return max(points, key=lambda p: (p[1], p[0]))


def _smallest_y_point(points: list[tuple[int, int]]) -> tuple[int, int]:
    return min(points, key=lambda p: (p[1], p[0]))


def _convert_wire_json(wire_filepath: Path) -> str:
    import json

    net_wires = json.loads(wire_filepath.read_text(encoding="utf-8"))
    output_lines: list[str] = []

    for net_name in sorted(net_wires.keys()):
        wire_rows = net_wires[net_name]
        if not isinstance(wire_rows, list):
            continue

        for row in wire_rows:
            if len(row) != 4:
                continue
            x1, y1, x2, y2 = int(row[0]), int(row[1]), int(row[2]), int(row[3])
            output_lines.append(f"WIRE {x1} {y1} {x2} {y2}")

        if _is_auto_numbered_net(net_name):
            continue

        points = _collect_unique_points(wire_rows)
        if not points:
            continue

        if _is_ground_net(net_name):
            flag_x, flag_y = _largest_y_point(points)
        else:
            flag_x, flag_y = _smallest_y_point(points)

        output_lines.append(f"FLAG {flag_x} {flag_y} {net_name}")

    return "\n".join(output_lines) + ("\n" if output_lines else "")


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    directory_path = Path(arguments.directory)
    if not directory_path.is_dir():
        print(f"{arguments.directory}: not a directory", file=sys.stderr)
        return 1

    pattern = f"*{arguments.suffix}.json"
    wire_files = sorted(directory_path.rglob(pattern))
    if not wire_files:
        print(f"{arguments.directory}: no {arguments.suffix}.json files found", file=sys.stderr)
        return 0

    output_dir = Path(arguments.out_dir) if arguments.out_dir is not None else None
    exit_code = 0

    for wire_filepath in wire_files:
        try:
            asc_text = _convert_wire_json(wire_filepath)
        except (OSError, ValueError, KeyError) as error:
            print(f"{wire_filepath.name}: {error}", file=sys.stderr)
            exit_code = 1
            continue

        asc_filename = f"{wire_filepath.with_suffix('').with_suffix('').name}_asc.txt"
        output_path = output_dir / asc_filename if output_dir is not None else wire_filepath.with_name(asc_filename)

        try:
            output_path.write_text(asc_text, encoding="utf-8")
        except OSError as error:
            print(f"{output_path}: {error}", file=sys.stderr)
            exit_code = 1
            continue

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
