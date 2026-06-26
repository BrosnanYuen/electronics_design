"""Render one LTspice ASC file to an image via the public package API."""  # Describe the script purpose.

from __future__ import annotations  # Keep annotations lazy and consistent with the package code.

import argparse  # Parse the command-line input and output path arguments.
from pathlib import Path  # Resolve the repository root so local package imports work.
import sys  # Exit with a non-zero status when plotting fails.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]  # Resolve the project root from the script location.
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"  # Resolve the source directory that contains the package.

if str(_SOURCE_DIRECTORY) not in sys.path:  # Ensure the local package is importable when the script runs directly.
    sys.path.insert(0, str(_SOURCE_DIRECTORY))  # Prepend the source directory so local imports resolve correctly.

from electronics_design import ltspice_asc_plot_schemdraw  # Import only the requested public plotting API.


def _build_argument_parser() -> argparse.ArgumentParser:  # Create the command-line parser for the ASC-to-image wrapper.
    parser = argparse.ArgumentParser(  # Construct the parser with a concise description of the script behavior.
        description="Convert an LTspice ASC schematic file into a schemdraw-based image.",  # Explain the script purpose to CLI users.
    )  # Finish the parser construction.
    parser.add_argument("asc_filepath", help="Path to the LTspice .asc file to render.")  # Accept the input ASC path.
    parser.add_argument("schemdraw_imagepath_out", help="Path where the output image file should be written (.png, .svg, .jpg).")  # Accept the output image path.
    parser.add_argument("--width", type=int, default=1920, help="Optional image width in pixels. Defaults to 1920.")  # Accept the optional output width.
    parser.add_argument("--height", type=int, default=1080, help="Optional image height in pixels. Defaults to 1080.")  # Accept the optional output height.
    return parser  # Return the configured parser to the caller.


def main() -> int:  # Parse CLI arguments, invoke the public plotting API, and map the result to a process exit code.
    parser = _build_argument_parser()  # Build the CLI parser before reading user arguments.
    arguments = parser.parse_args()  # Parse the command-line arguments supplied by the caller.
    plot_result = ltspice_asc_plot_schemdraw(arguments.asc_filepath, arguments.schemdraw_imagepath_out, arguments.width, arguments.height)  # Delegate all work to the public plotting API.
    if not plot_result[0]:  # Stop when the public plotting API reports a validation or output error.
        print(plot_result[1], file=sys.stderr)  # Print the stable public error message to standard error.
        return 1  # Return a non-zero status so shell callers can detect failure.
    return 0  # Return success when the image output is generated successfully.


if __name__ == "__main__":  # Execute the CLI entry point only when run as a script.
    raise SystemExit(main())  # Exit the process using the computed status code.
