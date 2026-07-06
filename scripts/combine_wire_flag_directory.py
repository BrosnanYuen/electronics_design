#!/usr/bin/env python3
"""Combine LTspice ASC files with matching txt files into complete ASC files for every pair in a directory."""

import argparse
from pathlib import Path
import sys


def _is_wire_or_flag_line(line: str) -> bool:
    stripped = line.lstrip()
    upper = stripped.upper()
    return upper.startswith("WIRE") or upper.startswith("FLAG")


def _read_latin1_lines(filepath: str) -> list[str]:
    with open(filepath, "rb") as f:
        data = f.read()
    return data.decode("latin-1").splitlines()


def _combine_asc_and_txt(asc_filepath: str, txt_filepath: str) -> bytes:
    """Combine an ASC file (no WIRE/FLAG) with a txt file (WIRE/FLAG) and return Latin-1 bytes."""
    asc_lines = _read_latin1_lines(asc_filepath)
    txt_lines = _read_latin1_lines(txt_filepath)

    header_lines: list[str] = []
    body_lines: list[str] = []
    header_done = False

    for line in asc_lines:
        if not header_done:
            header_lines.append(line)
            stripped = line.lstrip()
            if stripped.upper().startswith("SHEET"):
                header_done = True
        else:
            body_lines.append(line)

    wire_flag_lines = [line for line in txt_lines if _is_wire_or_flag_line(line)]

    output_lines = header_lines + wire_flag_lines + body_lines
    output_text = "\n".join(output_lines) + ("\n" if output_lines else "")
    return output_text.encode("latin-1")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Combine every LTspice .asc file with its matching .txt file into a complete ASC file.",
    )
    parser.add_argument(
        "directory",
        help="Directory containing LTspice .asc files and matching .txt files.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional output directory for the combined .asc files. Defaults to overwriting the input .asc files.",
    )
    parser.add_argument(
        "--txt-suffix",
        default="",
        help="Suffix added to the ASC stem to locate the matching .txt file. Default: '' (matches '<stem>.txt').",
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
    txt_suffix = arguments.txt_suffix
    exit_code = 0

    for asc_filepath in asc_files:
        txt_filepath = asc_filepath.with_name(f"{asc_filepath.stem}{txt_suffix}.txt")
        if not txt_filepath.is_file():
            print(f"{asc_filepath.name}: no matching .txt file found ({txt_filepath.name})", file=sys.stderr)
            exit_code = 1
            continue

        try:
            output_bytes = _combine_asc_and_txt(str(asc_filepath), str(txt_filepath))
        except OSError as error:
            print(f"{asc_filepath.name}: {error}", file=sys.stderr)
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
