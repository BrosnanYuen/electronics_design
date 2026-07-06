#!/usr/bin/env python3
"""Delete WIRE and FLAG lines from an LTspice ASC file, preserving Latin-1 encoding."""

import argparse
import sys

from delete_wire_flag_directory import _filter_asc_file


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete all WIRE and FLAG lines from an LTspice ASC file. Output is Latin-1 encoded.",
    )
    parser.add_argument(
        "asc_filepath",
        help="Path to the LTspice .asc input file.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output file path. Defaults to overwriting the input file.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    try:
        output_bytes = _filter_asc_file(arguments.asc_filepath)
    except OSError:
        print(f"{arguments.asc_filepath}: unable to read file", file=sys.stderr)
        return 1

    output_path = arguments.out if arguments.out is not None else arguments.asc_filepath
    try:
        with open(output_path, "wb") as f:
            f.write(output_bytes)
    except OSError:
        print(f"{output_path}: unable to write file", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
