"""Convert KiCad schematic files into LTspice netlists via the public package API."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import kicad_sch_to_ltspice_netlist


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert KiCad schematic (.kicad_sch) files into LTspice netlists.",
    )
    parser.add_argument(
        "kicad_sch_filepaths",
        nargs="+",
        help="One or more KiCad .kicad_sch files to convert.",
    )
    parser.add_argument(
        "--kicad-path",
        default="/usr/share/kicad/",
        help="Root path of the KiCad symbol libraries used for symbol lookup.",
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
        help="Optional single output .net path. Only valid with exactly one input schematic file.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    convert_settings = {
        "kicad_path": arguments.kicad_path,
        "custom_search_paths": arguments.custom_search_paths,
        "ltspice_windows_path": arguments.ltspice_windows_path,
        "ltspice_wine_path": arguments.ltspice_wine_path,
    }
    if arguments.out is not None and len(arguments.kicad_sch_filepaths) != 1:
        print("--out can only be used with a single input schematic file.", file=sys.stderr)
        return 1
    exit_code = 0
    for kicad_sch_filepath in arguments.kicad_sch_filepaths:
        output_path = arguments.out if arguments.out is not None else str(Path(kicad_sch_filepath).with_suffix(".net"))
        result = kicad_sch_to_ltspice_netlist(kicad_sch_filepath, output_path, convert_settings)
        if not result[0]:
            print(f"{kicad_sch_filepath}: {result[1]}", file=sys.stderr)
            exit_code = 1
            continue
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())