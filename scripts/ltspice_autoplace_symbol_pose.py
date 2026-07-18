"""Automatically place LTspice symbol poses and route wires from a netlist."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import ltspice_autoplace_symbol_pose


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automatically place LTspice symbol poses and generate routed wiring from a netlist.",
    )
    parser.add_argument(
        "netlist_filepath",
        help="Path to the LTspice .net netlist file.",
    )
    parser.add_argument(
        "symbol_pose_filepath",
        help="Path where the autoplaced symbol-pose JSON should be written. "
        "If the file already exists, it is used as a seed for placement.",
    )
    parser.add_argument(
        "--wire-out",
        default=None,
        help="Optional output wire JSON path. Defaults to the netlist stem plus '_autoplace_wires.json'.",
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
        "--voltage-must-have-dc",
        action="store_true",
        help="Insert a zero DC value before AC-only voltage-source payloads.",
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
        "voltage_must_have_dc": arguments.voltage_must_have_dc,
    }
    netlist_input = Path(arguments.netlist_filepath)
    if not netlist_input.is_file():
        print(f"{netlist_input}: not a file", file=sys.stderr)
        return 1
    symbol_pose_output = Path(arguments.symbol_pose_filepath)
    wire_output_path = (
        arguments.wire_out
        if arguments.wire_out is not None
        else str(netlist_input.with_suffix("").with_suffix("") + "_autoplace_wires.json")
    )
    result = ltspice_autoplace_symbol_pose(
        str(netlist_input),
        str(symbol_pose_output),
        wire_output_path,
        convert_settings,
    )
    if not result[0]:
        print(f"{netlist_input.name}: {result[1]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
