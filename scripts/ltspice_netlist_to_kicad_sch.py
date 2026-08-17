"""Convert an LTspice netlist into a KiCad schematic file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import ltspice_netlist_to_kicad_sch


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert an LTspice netlist file into a KiCad schematic (.kicad_sch) file.",
    )
    parser.add_argument(
        "netlist_filepath",
        help="Path to the LTspice .net netlist file.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output .kicad_sch file path. Defaults to the netlist stem plus '.kicad_sch'.",
    )
    parser.add_argument(
        "--kicad-path",
        default="/usr/share/kicad/",
        help="Root path of the KiCad symbol libraries used for symbol lookup.",
    )
    parser.add_argument(
        "--ltspice-windows-path",
        default="C:\\users\\brosnan\\AppData\\Local\\LTspice\\",
        help="Windows-style LTspice root path used for .asy fallback symbol lookup.",
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
        "--kicad-sch-version",
        default=None,
        help="Optional KiCad schematic format version in YYYYMMDD format. Defaults to today's date.",
    )
    parser.add_argument(
        "--kicad-sch-generator",
        default="electronics_design",
        help="Generator identifier written into the generated schematic. Default: 'electronics_design'.",
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
        "kicad_sch_generator": arguments.kicad_sch_generator,
    }
    if arguments.kicad_sch_version is not None:
        convert_settings["kicad_sch_version"] = arguments.kicad_sch_version
    netlist_input = Path(arguments.netlist_filepath)
    if not netlist_input.is_file():
        print(f"{netlist_input}: not a file", file=sys.stderr)
        return 1
    output_path = (
        arguments.out
        if arguments.out is not None
        else str(netlist_input.with_suffix(".kicad_sch"))
    )
    result = ltspice_netlist_to_kicad_sch(
        str(netlist_input),
        output_path,
        convert_settings,
    )
    if not result[0]:
        print(f"{netlist_input.name}: {result[1]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
