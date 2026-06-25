"""Render one LTspice netlist file to a PNG graph via the public package API."""  # Describe the script purpose.

from __future__ import annotations  # Keep annotations lazy and consistent with the package code.

import argparse  # Parse the command-line input and output path arguments.
from pathlib import Path  # Resolve the repository root so local package imports work.
import sys  # Exit with a non-zero status when plotting fails.

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]  # Resolve the project root from the script location.
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"  # Resolve the source directory that contains the package.

if str(_SOURCE_DIRECTORY) not in sys.path:  # Ensure the local package is importable when the script runs directly.
    sys.path.insert(0, str(_SOURCE_DIRECTORY))  # Prepend the source directory so local imports resolve correctly.

from electronics_design import ltspice_netlist_plot_networkx  # Import only the requested public plotting API.


def _build_argument_parser() -> argparse.ArgumentParser:  # Create the command-line parser for the netlist-to-PNG wrapper.
    parser = argparse.ArgumentParser(  # Construct the parser with a concise description of the script behavior.
        description="Convert an LTspice netlist file into a networkx-based PNG graph.",  # Explain the script purpose to CLI users.
    )  # Finish the parser construction.
    parser.add_argument("netlist_filepath", help="Path to the LTspice .net file to render.")  # Accept the input netlist path.
    parser.add_argument("networkx_png_filepath", help="Path where the output PNG file should be written.")  # Accept the output PNG path.
    return parser  # Return the configured parser to the caller.


def main() -> int:  # Parse CLI arguments, invoke the public plotting API, and map the result to a process exit code.
    parser = _build_argument_parser()  # Build the CLI parser before reading user arguments.
    arguments = parser.parse_args()  # Parse the command-line arguments supplied by the caller.
    plot_result = ltspice_netlist_plot_networkx(arguments.netlist_filepath, arguments.networkx_png_filepath)  # Delegate all work to the public plotting API.
    if not plot_result[0]:  # Stop when the public plotting API reports a validation or output error.
        print(plot_result[1], file=sys.stderr)  # Print the stable public error message to standard error.
        return 1  # Return a non-zero status so shell callers can detect failure.
    return 0  # Return success when the PNG output is generated successfully.


if __name__ == "__main__":  # Execute the CLI entry point only when run as a script.
    raise SystemExit(main())  # Exit the process using the computed status code.
