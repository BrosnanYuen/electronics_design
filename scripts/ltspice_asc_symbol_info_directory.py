"""Extract symbol info from all LTspice ASC files in a directory tree and save as JSON."""

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
        description="Extract symbol information from all LTspice ASC schematic files in a directory tree and save as JSON alongside each file.",
    )
    parser.add_argument(
        "directory",
        help="Directory to search recursively for LTspice .asc files.",
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
        "grid_size": 16,
        "voltage_must_have_dc": False,
    }
    directory_path = Path(arguments.directory)
    if not directory_path.is_dir():
        print(f"{arguments.directory}: not a directory", file=sys.stderr)
        return 1
    asc_files = sorted(directory_path.rglob("*.asc"))
    if not asc_files:
        print(f"{arguments.directory}: no .asc files found", file=sys.stderr)
        return 0
    exit_code = 0
    for asc_filepath in asc_files:
        output_path = asc_filepath.with_suffix(".json")
        try:
            symbol_info = get_ltspice_asc_symbol_info(str(asc_filepath), convert_settings)
        except ValueError as error:
            print(f"{asc_filepath}: {error}", file=sys.stderr)
            exit_code = 1
            continue
        try:
            output_path.write_text(
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
