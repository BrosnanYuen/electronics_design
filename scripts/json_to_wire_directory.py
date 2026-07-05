"""Convert every wire JSON file in a directory tree into LTspice ASC WIRE and FLAG directives."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from json_to_wire import _convert


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert every wire JSON file in a directory tree into LTspice ASC WIRE and FLAG directives.",
    )
    parser.add_argument(
        "directory",
        help="Directory to search recursively for wire JSON files.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional output directory for the generated .wire files. Defaults to the input directory.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    directory_path = Path(arguments.directory)
    if not directory_path.is_dir():
        print(f"{arguments.directory}: not a directory", file=sys.stderr)
        return 1
    json_files = sorted(directory_path.rglob("*.json"))
    if not json_files:
        print(f"{arguments.directory}: no .json files found", file=sys.stderr)
        return 0
    output_dir = Path(arguments.out_dir) if arguments.out_dir is not None else None
    exit_code = 0
    for json_filepath in json_files:
        output_path = (
            output_dir / json_filepath.with_suffix(".wire").name
            if output_dir is not None
            else str(json_filepath.with_suffix(".wire"))
        )
        try:
            _convert(str(json_filepath), str(output_path))
        except Exception as error:
            print(f"{json_filepath.name}: {error}", file=sys.stderr)
            exit_code = 1
            continue
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
