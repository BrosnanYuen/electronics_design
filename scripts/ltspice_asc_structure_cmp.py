"""Compare two LTspice ASC schematic files for structural equivalence via the public package API."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import ltspice_asc_structure_cmp


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two LTspice ASC schematic files for structural equivalence.",
    )
    parser.add_argument(
        "first_asc",
        help="Path to the first LTspice .asc file.",
    )
    parser.add_argument(
        "second_asc",
        help="Path to the second LTspice .asc file.",
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
    return parser


def main() -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args()

    convert_settings = {
        "custom_search_paths": arguments.custom_search_paths,
        "ltspice_windows_path": arguments.ltspice_windows_path,
        "ltspice_wine_path": arguments.ltspice_wine_path,
        "voltage_must_have_dc": False,
    }

    matches, message, line_number = ltspice_asc_structure_cmp(
        arguments.first_asc,
        arguments.second_asc,
        convert_settings,
    )

    if matches:
        print(f"SUCCESS: ASC structures are equivalent.")
        return 0
    print(f"MISMATCH: {message or 'ASC structures are different!'}")
    if line_number:
        print(f"  First differing line: {line_number}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
