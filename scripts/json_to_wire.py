"""Convert one net-wire JSON file into ASC-style WIRE and FLAG lines."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from json_to_wire_directory import _convert_wire_json


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a net-wire JSON file into ASC-style WIRE and FLAG lines.",
    )
    parser.add_argument(
        "wire_filepath",
        help="Path to the net-wire JSON file.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output file path for the ASC lines. Defaults to printing to stdout.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    wire_path = Path(arguments.wire_filepath)
    try:
        asc_text = _convert_wire_json(wire_path)
    except (OSError, ValueError, KeyError) as error:
        print(f"{wire_path}: {error}", file=sys.stderr)
        return 1

    if arguments.out is not None:
        try:
            Path(arguments.out).write_text(asc_text, encoding="utf-8")
        except OSError:
            print(f"{arguments.out}: unable to write output file", file=sys.stderr)
            return 1
    else:
        print(asc_text, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
