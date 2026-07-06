"""Convert an LTspice netlist into an ASC schematic file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import ltspice_netlist_to_asc


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert an LTspice netlist file into an LTspice ASC schematic file.",
    )
    parser.add_argument(
        "netlist_filepath",
        help="Path to the LTspice .net netlist file.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output .asc file path. Defaults to the netlist stem plus '.asc'.",
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
        "--custom-search-paths",
        nargs="*",
        default=["./valid_asy/"],
        help="Optional additional search paths for LTspice .asy and library files.",
    )
    parser.add_argument(
        "--minimum-dist",
        type=int,
        default=32,
        help="Minimum clearance distance around symbol rectangles. Default: 32.",
    )
    parser.add_argument(
        "--wire-pin-out-dist",
        type=int,
        default=16,
        help="Distance a wire exits a symbol pin before global routing. Default: 16.",
    )
    parser.add_argument(
        "--autoplace-iter",
        type=int,
        default=12,
        help="Number of autoplace optimization iterations. Default: 12.",
    )
    parser.add_argument(
        "--grid-size",
        type=int,
        default=16,
        help="Routing and placement grid spacing. Default: 16.",
    )
    parser.add_argument(
        "--ltspice-version",
        type=float,
        default=4.1,
        help="LTspice file format version used in the generated ASC. Default: 4.1.",
    )
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    convert_settings = {
        "custom_search_paths": arguments.custom_search_paths,
        "ltspice_windows_path": arguments.ltspice_windows_path,
        "ltspice_wine_path": arguments.ltspice_wine_path,
        "minimum_dist": arguments.minimum_dist,
        "wire_pin_out_dist": arguments.wire_pin_out_dist,
        "autoplace_iter": arguments.autoplace_iter,
        "grid_size": arguments.grid_size,
        "ltspice_version": arguments.ltspice_version,
    }
    netlist_input = Path(arguments.netlist_filepath)
    if not netlist_input.is_file():
        print(f"{netlist_input}: not a file", file=sys.stderr)
        return 1
    output_path = (
        arguments.out
        if arguments.out is not None
        else str(netlist_input.with_suffix(".asc"))
    )
    result = ltspice_netlist_to_asc(
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
