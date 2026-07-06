#!/usr/bin/env python3
"""Delete WIRE and FLAG lines from every LTspice ASC file in a directory, preserving Latin-1 encoding."""

import argparse
from pathlib import Path
import sys


def _is_wire_or_flag_line(line: str) -> bool:
    stripped = line.lstrip()
    upper = stripped.upper()
    return upper.startswith("WIRE") or upper.startswith("FLAG")


def _filter_asc_file(filepath: str) -> bytes:
    """Read an ASC file as Latin-1, strip WIRE/FLAG lines, return Latin-1 bytes."""
    with open(filepath, "rb") as f:
        data = f.read()
    text = data.decode("latin-1")
    lines = text.splitlines()
    filtered_lines = [line for line in lines if not _is_wire_or_flag_line(line)]
    output_text = "\n".join(filtered_lines) + ("\n" if filtered_lines else "")
    return output_text.encode("latin-1")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete all WIRE and FLAG lines from every LTspice ASC file in a directory. Output is Latin-1 encoded.",
    )
    parser.add_argument(
        "directory",
        help="Directory containing LTspice .asc files to process.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional output directory. Defaults to overwriting the input files.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    directory_path = Path(arguments.directory)
    if not directory_path.is_dir():
        print(f"{arguments.directory}: not a directory", file=sys.stderr)
        return 1

    asc_files = sorted(directory_path.rglob("*.asc"))
    if not asc_files:
        print(f"{arguments.directory}: no .asc files found", file=sys.stderr)
        return 0

    output_dir = Path(arguments.out_dir) if arguments.out_dir is not None else None
    exit_code = 0

    for asc_filepath in asc_files:
        try:
            output_bytes = _filter_asc_file(str(asc_filepath))
        except OSError:
            print(f"{asc_filepath.name}: unable to read file", file=sys.stderr)
            exit_code = 1
            continue

        output_path = output_dir / asc_filepath.name if output_dir is not None else asc_filepath
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(output_bytes)
        except OSError:
            print(f"{output_path}: unable to write file", file=sys.stderr)
            exit_code = 1
            continue

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
