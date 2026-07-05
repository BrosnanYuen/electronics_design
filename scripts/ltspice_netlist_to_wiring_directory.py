"""Convert LTspice netlists plus symbol-pose JSON into routed wiring JSON for every .net/.json pair in a directory."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import ltspice_netlist_to_wiring


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert every LTspice .net and matching .json symbol-pose pair in a directory into routed wiring JSON.",
    )
    parser.add_argument(
        "directory",
        help="Directory containing matching pairs of .net and .json symbol-pose files.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional output directory for the generated wiring JSON files. Defaults to the input directory.",
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
        "--grid-size",
        type=int,
        default=16,
        help="Routing grid spacing. Default: 16.",
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
        "grid_size": arguments.grid_size,
    }
    directory_path = Path(arguments.directory)
    if not directory_path.is_dir():
        print(f"{arguments.directory}: not a directory", file=sys.stderr)
        return 1
    netlist_files = sorted(directory_path.rglob("*.net"))
    if not netlist_files:
        print(f"{arguments.directory}: no .net files found", file=sys.stderr)
        return 0
    output_dir = Path(arguments.out_dir) if arguments.out_dir is not None else None
    exit_code = 0
    for netlist_filepath in netlist_files:
        json_filepath = netlist_filepath.with_suffix(".json")
        if not json_filepath.is_file():
            print(f"{netlist_filepath.name}: no matching .json symbol-pose file found ({json_filepath})", file=sys.stderr)
            exit_code = 1
            continue
        output_path = (
            output_dir / (netlist_filepath.with_suffix("").with_suffix("").name + "_wires.json")
            if output_dir is not None
            else str(netlist_filepath.with_suffix("").with_suffix("") + "_wires.json")
        )
        result = ltspice_netlist_to_wiring(
            str(netlist_filepath),
            str(json_filepath),
            str(output_path),
            convert_settings,
        )
        if not result[0]:
            print(f"{netlist_filepath.name}: {result[1]}", file=sys.stderr)
            exit_code = 1
            continue
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
