#!/usr/bin/env python3
"""Combine an LTspice ASC file (no WIRE/FLAG) with a txt file (WIRE/FLAG only) into a complete ASC file."""

import argparse
from pathlib import Path
import sys

from combine_wire_flag_directory import _combine_asc_and_txt


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Combine an ASC file (no WIRE/FLAG) with a txt file (WIRE/FLAG only) into a complete ASC file.",
    )
    parser.add_argument(
        "asc_filepath",
        help="Path to the LTspice .asc file containing symbols, attributes, and directives (no WIRE/FLAG lines).",
    )
    parser.add_argument(
        "txt_filepath",
        help="Path to the .txt file containing WIRE and FLAG lines.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output .asc file path. Defaults to overwriting the input .asc file.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    try:
        output_bytes = _combine_asc_and_txt(arguments.asc_filepath, arguments.txt_filepath)
    except OSError as error:
        print(f"{error}", file=sys.stderr)
        return 1

    output_path = Path(arguments.out) if arguments.out is not None else Path(arguments.asc_filepath)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(output_bytes)
    except OSError:
        print(f"{output_path}: unable to write file", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
