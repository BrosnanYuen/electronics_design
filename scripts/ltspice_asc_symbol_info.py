"""Extract symbol info from LTspice ASC files and save as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import get_ltspice_asc_symbol_info


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract symbol information from LTspice ASC schematic files and save as JSON.",
    )
    parser.add_argument(
        "asc_filepaths",
        nargs="+",
        help="One or more LTspice .asc files to read.",
    )
    parser.add_argument(
        "--ltspice-windows-path",
        default="C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
        help="Windows-style LTspice root path used for symbol lookup.",
    )
    parser.add_argument(
        "--ltspice-wine-path",
        default="~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
        help="Local LTspice root path used at runtime to browse .asy and library files.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional single output JSON path. Only valid with exactly one input ASC file.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    convert_settings = {
        "ltspice_windows_path": arguments.ltspice_windows_path,
        "ltspice_wine_path": arguments.ltspice_wine_path,
    }
    if arguments.out is not None and len(arguments.asc_filepaths) != 1:
        print("--out can only be used with a single input ASC file.", file=sys.stderr)
        return 1
    exit_code = 0
    for asc_filepath in arguments.asc_filepaths:
        output_path = arguments.out if arguments.out is not None else f"{asc_filepath}.json"
        try:
            symbol_info = get_ltspice_asc_symbol_info(asc_filepath, convert_settings)
        except ValueError as error:
            print(f"{asc_filepath}: {error}", file=sys.stderr)
            exit_code = 1
            continue
        try:
            Path(output_path).write_text(
                json.dumps(symbol_info, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            print(f"{output_path}: {error}", file=sys.stderr)
            exit_code = 1
            continue
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
