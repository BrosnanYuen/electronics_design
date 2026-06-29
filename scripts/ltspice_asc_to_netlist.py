"""Convert one LTspice ASC file to a netlist via the public package API."""

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
        description="Convert an LTspice ASC schematic file into an LTspice netlist.",
    )
    parser.add_argument("asc_filepath", help="Path to the LTspice .asc file to convert.")
    parser.add_argument("net_filepath_out", help="Path where the output .net file should be written.")
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
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()
    convert_settings = {
        "ltspice_windows_path": arguments.ltspice_windows_path,
        "ltspice_wine_path": arguments.ltspice_wine_path,
    }
    result = ltspice_asc_to_netlist(
        arguments.asc_filepath,
        arguments.net_filepath_out,
        convert_settings,
    )
    if not result[0]:
        print(result[1], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
