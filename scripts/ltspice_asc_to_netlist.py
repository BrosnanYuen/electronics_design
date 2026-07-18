"""Convert LTspice ASC schematic files to netlists via the public package API."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import ltspice_asc_to_netlist


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert LTspice ASC schematic files into LTspice netlists.",
    )
    parser.add_argument(
        "asc_filepaths",
        nargs="+",
        help="One or more LTspice .asc files to convert.",
    )
    parser.add_argument(
        "--ltspice-windows-path",
        default="C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
        help="Windows-style LTspice root path used when writing .lib lines into the generated netlist.",
    )
    parser.add_argument(
        "--ltspice-wine-path",
        default="~/.wine/drive_c/users/brosnan/AppData/Local/LTspice/",
        help="Local LTspice root path used at runtime to browse .asy and library files.",
    )
    parser.add_argument(
        "--custom-search-paths",
        nargs="*",
        default=["./valid_asy/"],
        help="Optional additional search paths for LTspice .asy and library files.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional single output .net path. Only valid with exactly one input ASC file.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    convert_settings = {
        "custom_search_paths": arguments.custom_search_paths,
        "ltspice_windows_path": arguments.ltspice_windows_path,
        "ltspice_wine_path": arguments.ltspice_wine_path,
        "grid_size": 16,
        "voltage_must_have_dc": False,
    }
    if arguments.out is not None and len(arguments.asc_filepaths) != 1:
        print("--out can only be used with a single input ASC file.", file=sys.stderr)
        return 1
    exit_code = 0
    for asc_filepath in arguments.asc_filepaths:
        output_path = arguments.out if arguments.out is not None else str(Path(asc_filepath).with_suffix(".net"))
        result = ltspice_asc_to_netlist(asc_filepath, output_path, convert_settings)
        if not result[0]:
            print(f"{asc_filepath}: {result[1]}", file=sys.stderr)
            exit_code = 1
            continue
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
